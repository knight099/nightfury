// Package republish exposes per-camera frames received from agents as a real
// RTSP server so that the worker (and any other consumer) can pull them with
// a stock RTSP client.
//
// Frame format on the wire (Publisher.Frames): each ring entry is a single
// H.264 access unit serialized as Annex-B (NALUs separated by 0x00 0x00 0x00
// 0x01 start codes). The relay splits the access unit back into NALUs,
// captures SPS/PPS lazily from the in-band stream, and packetizes them as
// RTP/H.264 for delivery to connected RTSP readers.
package republish

import (
	"context"
	"fmt"
	"log"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"github.com/bluenviron/gortsplib/v5"
	"github.com/bluenviron/gortsplib/v5/pkg/base"
	"github.com/bluenviron/gortsplib/v5/pkg/description"
	"github.com/bluenviron/gortsplib/v5/pkg/format"
	"github.com/bluenviron/gortsplib/v5/pkg/format/rtph264"
)

// RTSPServer republishes per-camera frames as an RTSP server. Each camera
// registered with the Registry is exposed at rtsp://<addr>/<camera_id>.
type RTSPServer struct {
	reg  *Registry
	addr string

	mu      sync.Mutex
	server  *gortsplib.Server
	listAddr string

	// streams is the lazy per-camera state. A camera's ServerStream is
	// created on demand the first time SPS+PPS are observed in the frame
	// stream (most NVRs send them in-band ahead of every IDR).
	streamMu sync.Mutex
	streams  map[string]*camStream
}

type camStream struct {
	stream  *gortsplib.ServerStream
	media   *description.Media
	forma   *format.H264
	encoder *rtph264.Encoder
	startTS uint32

	// pump goroutine state
	stopped atomic.Bool
}

func NewRTSPServer(reg *Registry, addr string) *RTSPServer {
	return &RTSPServer{
		reg:     reg,
		addr:    addr,
		streams: make(map[string]*camStream),
	}
}

// Addr returns the listener address. Empty until Run has bound the socket.
func (s *RTSPServer) Addr() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.listAddr
}

// Run starts the RTSP server and blocks until ctx is done. Returns an error
// if the listener cannot be bound.
func (s *RTSPServer) Run(ctx context.Context) error {
	// Pre-bind the TCP listener so Addr() is observable even when the
	// configured address is ":0".
	ln, err := net.Listen("tcp", s.addr)
	if err != nil {
		return fmt.Errorf("rtsp: listen: %w", err)
	}
	resolved := ln.Addr().String()
	// gortsplib's Server doesn't accept a pre-bound listener; close ours and
	// hand the resolved address off so it rebinds on the same port. This is
	// a small race window but acceptable for our deployment (single-process
	// owner).
	_ = ln.Close()

	s.mu.Lock()
	srv := &gortsplib.Server{
		Handler:     s,
		RTSPAddress: resolved,
		ReadTimeout: 10 * time.Second,
		WriteTimeout: 10 * time.Second,
	}
	s.server = srv
	s.listAddr = resolved
	s.mu.Unlock()

	if err := srv.Start(); err != nil {
		return fmt.Errorf("rtsp: server start: %w", err)
	}

	doneCh := make(chan error, 1)
	go func() { doneCh <- srv.Wait() }()

	select {
	case <-ctx.Done():
		srv.Close()
		s.closeAllStreams()
		return nil
	case err := <-doneCh:
		s.closeAllStreams()
		if err != nil && ctx.Err() == nil {
			return fmt.Errorf("rtsp: server: %w", err)
		}
		return nil
	}
}

func (s *RTSPServer) closeAllStreams() {
	s.streamMu.Lock()
	defer s.streamMu.Unlock()
	for id, cs := range s.streams {
		cs.stopped.Store(true)
		if cs.stream != nil {
			cs.stream.Close()
		}
		delete(s.streams, id)
	}
}

// pathToCameraID strips a leading slash from the RTSP request path.
func pathToCameraID(p string) string {
	for len(p) > 0 && p[0] == '/' {
		p = p[1:]
	}
	return p
}

// getOrInitStream returns the camStream for the given camera_id, lazily
// building it once SPS+PPS are available from the in-band frame stream.
// Returns (nil, nil) when the publisher exists but parameter sets have not
// yet arrived; returns (nil, error) when the camera is unknown.
func (s *RTSPServer) getOrInitStream(cameraID string) (*camStream, error) {
	pub, ok := s.reg.Get(cameraID)
	if !ok {
		return nil, fmt.Errorf("camera %q not registered", cameraID)
	}

	s.streamMu.Lock()
	cs, ok := s.streams[cameraID]
	s.streamMu.Unlock()
	if ok && cs.stream != nil {
		return cs, nil
	}

	// Try to pull frames until we observe SPS and PPS. We bound the wait so
	// DESCRIBE returns reasonably quickly even if the publisher has not sent
	// any frames yet.
	deadline := time.Now().Add(2 * time.Second)
	var sps, pps []byte
	var pending [][]byte // frames consumed during init; replay after stream is up.

	for time.Now().Before(deadline) {
		f, ok := pub.Frames.Pop()
		if !ok {
			time.Sleep(50 * time.Millisecond)
			continue
		}
		pending = append(pending, f)
		for _, nalu := range splitAnnexB(f) {
			if len(nalu) == 0 {
				continue
			}
			switch nalu[0] & 0x1F {
			case 7:
				if sps == nil {
					sps = append([]byte(nil), nalu...)
				}
			case 8:
				if pps == nil {
					pps = append([]byte(nil), nalu...)
				}
			}
		}
		if sps != nil && pps != nil {
			break
		}
	}
	if sps == nil || pps == nil {
		// Push pending frames back so we don't lose them.
		for _, f := range pending {
			pub.Frames.Push(f)
		}
		return nil, fmt.Errorf("camera %q: SPS/PPS not yet observed", cameraID)
	}

	forma := &format.H264{
		PayloadTyp:        96,
		SPS:               sps,
		PPS:               pps,
		PacketizationMode: 1,
	}
	media := &description.Media{
		Type:    description.MediaTypeVideo,
		Formats: []format.Format{forma},
	}
	desc := &description.Session{Medias: []*description.Media{media}}

	s.mu.Lock()
	srv := s.server
	s.mu.Unlock()
	if srv == nil {
		return nil, fmt.Errorf("server not running")
	}

	stream := &gortsplib.ServerStream{Server: srv, Desc: desc}
	if err := stream.Initialize(); err != nil {
		return nil, fmt.Errorf("rtsp: init server stream: %w", err)
	}

	enc, err := forma.CreateEncoder()
	if err != nil {
		stream.Close()
		return nil, fmt.Errorf("rtsp: create encoder: %w", err)
	}

	cs = &camStream{
		stream:  stream,
		media:   media,
		forma:   forma,
		encoder: enc,
	}

	s.streamMu.Lock()
	if existing, ok := s.streams[cameraID]; ok && existing.stream != nil {
		// Lost a race; clean up ours.
		s.streamMu.Unlock()
		stream.Close()
		return existing, nil
	}
	s.streams[cameraID] = cs
	s.streamMu.Unlock()

	go s.pump(cameraID, pub, cs, pending)

	return cs, nil
}

// pump drains the publisher's frame ring, packetizes each access unit, and
// writes the resulting RTP packets to all connected readers of the stream.
func (s *RTSPServer) pump(cameraID string, pub *Publisher, cs *camStream, replay [][]byte) {
	const clockRate uint32 = 90000
	tsStep := uint32(clockRate / 30) // assume ~30fps; actual cadence comes from the source.
	var ts uint32

	writeAU := func(au [][]byte) {
		if len(au) == 0 {
			return
		}
		pkts, err := cs.encoder.Encode(au)
		if err != nil {
			log.Printf("relay rtsp: encode %s: %v", cameraID, err)
			return
		}
		for _, p := range pkts {
			p.Timestamp = ts
			if err := cs.stream.WritePacketRTP(cs.media, p); err != nil {
				// Reader gone or stream closed; not fatal.
				return
			}
		}
		ts += tsStep
	}

	for _, frame := range replay {
		if cs.stopped.Load() {
			return
		}
		writeAU(splitAnnexB(frame))
	}

	for !cs.stopped.Load() {
		f, ok := pub.Frames.Pop()
		if !ok {
			time.Sleep(20 * time.Millisecond)
		} else {
			writeAU(splitAnnexB(f))
		}
		// If the publisher has been removed from the registry (camera
		// unregistered), exit the pump and drop our cached stream so a
		// future re-register can rebuild cleanly.
		if _, ok := s.reg.Get(cameraID); !ok {
			cs.stopped.Store(true)
			s.streamMu.Lock()
			if existing, ok := s.streams[cameraID]; ok && existing == cs {
				delete(s.streams, cameraID)
			}
			s.streamMu.Unlock()
			if cs.stream != nil {
				cs.stream.Close()
			}
			return
		}
	}
}

// splitAnnexB splits an Annex-B encoded byte stream into individual NALUs.
// Recognizes both 3-byte and 4-byte start codes.
func splitAnnexB(buf []byte) [][]byte {
	var nalus [][]byte
	i := 0
	n := len(buf)
	for i < n {
		// Find next start code.
		idx := nextStartCode(buf, i)
		if idx < 0 {
			break
		}
		// Skip the start code itself.
		scLen := 3
		if idx+3 < n && buf[idx] == 0 && buf[idx+1] == 0 && buf[idx+2] == 0 && buf[idx+3] == 1 {
			scLen = 4
		}
		start := idx + scLen
		// Find following start code.
		next := nextStartCode(buf, start)
		if next < 0 {
			next = n
		}
		if next > start {
			nalus = append(nalus, buf[start:next])
		}
		i = next
	}
	return nalus
}

func nextStartCode(buf []byte, from int) int {
	if from < 0 {
		from = 0
	}
	// Search for 0x000001 or 0x00000001.
	for i := from; i+2 < len(buf); i++ {
		if buf[i] == 0 && buf[i+1] == 0 {
			if buf[i+2] == 1 {
				return i
			}
			if buf[i+2] == 0 && i+3 < len(buf) && buf[i+3] == 1 {
				return i
			}
		}
	}
	return -1
}

// --- gortsplib server handler implementation ---

// OnDescribe is called when a client issues DESCRIBE rtsp://addr/<camera_id>.
func (s *RTSPServer) OnDescribe(ctx *gortsplib.ServerHandlerOnDescribeCtx) (*base.Response, *gortsplib.ServerStream, error) {
	cameraID := pathToCameraID(ctx.Path)
	if cameraID == "" {
		return &base.Response{StatusCode: base.StatusNotFound}, nil, nil
	}
	cs, err := s.getOrInitStream(cameraID)
	if err != nil {
		log.Printf("relay rtsp: describe %s: %v", cameraID, err)
		return &base.Response{StatusCode: base.StatusNotFound}, nil, nil
	}
	return &base.Response{StatusCode: base.StatusOK}, cs.stream, nil
}

// OnSetup is called for each SETUP. Returns the existing stream for the path.
func (s *RTSPServer) OnSetup(ctx *gortsplib.ServerHandlerOnSetupCtx) (*base.Response, *gortsplib.ServerStream, error) {
	cameraID := pathToCameraID(ctx.Path)
	if cameraID == "" {
		return &base.Response{StatusCode: base.StatusNotFound}, nil, nil
	}
	cs, err := s.getOrInitStream(cameraID)
	if err != nil {
		log.Printf("relay rtsp: setup %s: %v", cameraID, err)
		return &base.Response{StatusCode: base.StatusNotFound}, nil, nil
	}
	return &base.Response{StatusCode: base.StatusOK}, cs.stream, nil
}

// OnPlay is called when the client transitions to PLAY state.
func (s *RTSPServer) OnPlay(_ *gortsplib.ServerHandlerOnPlayCtx) (*base.Response, error) {
	return &base.Response{StatusCode: base.StatusOK}, nil
}

// OnConnOpen / OnConnClose / OnSessionOpen / OnSessionClose are required by
// the ServerHandler contract for connection-lifecycle hooks; we no-op.
func (s *RTSPServer) OnConnOpen(_ *gortsplib.ServerHandlerOnConnOpenCtx)       {}
func (s *RTSPServer) OnConnClose(_ *gortsplib.ServerHandlerOnConnCloseCtx)     {}
func (s *RTSPServer) OnSessionOpen(_ *gortsplib.ServerHandlerOnSessionOpenCtx) {}
func (s *RTSPServer) OnSessionClose(_ *gortsplib.ServerHandlerOnSessionCloseCtx) {
}

// Compile-time interface checks.
var (
	_ gortsplib.ServerHandlerOnDescribe = (*RTSPServer)(nil)
	_ gortsplib.ServerHandlerOnSetup    = (*RTSPServer)(nil)
	_ gortsplib.ServerHandlerOnPlay     = (*RTSPServer)(nil)
)

