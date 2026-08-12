package webrtcsignal

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"

	"github.com/pion/webrtc/v4"

	"github.com/nightwatch/agent/internal/auth"
	"github.com/nightwatch/agent/internal/republish"
)

const defaultBufCap = 256

// Server is an HTTP signaling endpoint that accepts a WebRTC offer from
// an agent and returns an answer. Each negotiated PeerConnection accepts
// data channels named "cam:<camera_id>". The first message on a channel
// is a text payload identifying the camera; subsequent messages are
// framed bytes pushed into the registered Publisher's ring buffer.
type Server struct {
	agentKey string
	verifier *auth.Verifier
	registry *republish.Registry
	api      *webrtc.API
}

func NewServer(agentKey string, reg *republish.Registry) *Server {
	m := &webrtc.MediaEngine{}
	api := webrtc.NewAPI(webrtc.WithMediaEngine(m))
	return &Server{agentKey: agentKey, registry: reg, api: api}
}

// NewServerWithVerifier constructs a Server that authenticates incoming
// signaling requests by treating the agent_key field as a device token
// and resolving it via the supplied Verifier.
func NewServerWithVerifier(v *auth.Verifier, reg *republish.Registry) *Server {
	m := &webrtc.MediaEngine{}
	api := webrtc.NewAPI(webrtc.WithMediaEngine(m))
	return &Server{verifier: v, registry: reg, api: api}
}

// NewServerWithRegistry constructs a Server with a freshly-allocated
// internal Publisher registry. Suitable for tests and standalone use.
func NewServerWithRegistry(agentKey string) *Server {
	return NewServer(agentKey, republish.NewRegistry())
}

// FrameCount returns the number of buffered frames currently in the ring
// for the given camera id, or -1 if the camera is not registered. Exposed
// for cross-module tests that cannot import the internal republish package.
func (s *Server) FrameCount(cameraID string) int {
	if pub, ok := s.registry.Get(cameraID); ok {
		return pub.Frames.Len()
	}
	return -1
}

// HasCamera reports whether a camera publisher is currently registered.
func (s *Server) HasCamera(cameraID string) bool {
	_, ok := s.registry.Get(cameraID)
	return ok
}

type signalRequest struct {
	AgentKey string `json:"agent_key"`
	Offer    string `json:"offer"`
}

type signalResponse struct {
	Answer string `json:"answer"`
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req signalRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad json", http.StatusBadRequest)
		return
	}
	if s.verifier != nil {
		if req.AgentKey == "" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		if _, err := s.verifier.Verify(r.Context(), req.AgentKey); err != nil {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
	} else if s.agentKey == "" || req.AgentKey != s.agentKey {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	pc, err := s.api.NewPeerConnection(webrtc.Configuration{})
	if err != nil {
		http.Error(w, "pc create failed", http.StatusInternalServerError)
		return
	}

	var (
		mu       sync.Mutex
		regCam   = map[string]string{} // dc label -> camera id (registered)
	)

	pc.OnDataChannel(func(dc *webrtc.DataChannel) {
		label := dc.Label()
		var cameraID string
		var pub *republish.Publisher
		var first sync.Once

		dc.OnMessage(func(msg webrtc.DataChannelMessage) {
			if msg.IsString {
				// First text message is camera id
				first.Do(func() {
					cameraID = string(msg.Data)
					if cameraID == "" && strings.HasPrefix(label, "cam:") {
						cameraID = strings.TrimPrefix(label, "cam:")
					}
					if cameraID == "" {
						return
					}
					p := republish.NewPublisher(cameraID, defaultBufCap)
					if err := s.registry.RegisterErr(cameraID, p); err != nil {
						// Already registered; reuse existing.
						if existing, ok := s.registry.Get(cameraID); ok {
							pub = existing
						}
						return
					}
					pub = p
					mu.Lock()
					regCam[label] = cameraID
					mu.Unlock()
				})
				return
			}
			// Binary frame
			if pub == nil {
				// Allow case where caller never sent text first but label encodes id
				if cameraID == "" && strings.HasPrefix(label, "cam:") {
					cameraID = strings.TrimPrefix(label, "cam:")
					p := republish.NewPublisher(cameraID, defaultBufCap)
					if err := s.registry.RegisterErr(cameraID, p); err == nil {
						pub = p
						mu.Lock()
						regCam[label] = cameraID
						mu.Unlock()
					} else if existing, ok := s.registry.Get(cameraID); ok {
						pub = existing
					}
				}
				if pub == nil {
					return
				}
			}
			buf := make([]byte, len(msg.Data))
			copy(buf, msg.Data)
			pub.Frames.Push(buf)
		})

		dc.OnClose(func() {
			mu.Lock()
			id, ok := regCam[label]
			if ok {
				delete(regCam, label)
			}
			mu.Unlock()
			if ok {
				s.registry.Unregister(id)
			}
		})
	})

	pc.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		if state == webrtc.PeerConnectionStateClosed || state == webrtc.PeerConnectionStateFailed {
			mu.Lock()
			ids := make([]string, 0, len(regCam))
			for _, id := range regCam {
				ids = append(ids, id)
			}
			regCam = map[string]string{}
			mu.Unlock()
			for _, id := range ids {
				s.registry.Unregister(id)
			}
		}
	})

	offer := webrtc.SessionDescription{Type: webrtc.SDPTypeOffer, SDP: req.Offer}
	if err := pc.SetRemoteDescription(offer); err != nil {
		http.Error(w, "set remote: "+err.Error(), http.StatusBadRequest)
		_ = pc.Close()
		return
	}

	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		http.Error(w, "answer: "+err.Error(), http.StatusInternalServerError)
		_ = pc.Close()
		return
	}
	gatherComplete := webrtc.GatheringCompletePromise(pc)
	if err := pc.SetLocalDescription(answer); err != nil {
		http.Error(w, "set local: "+err.Error(), http.StatusInternalServerError)
		_ = pc.Close()
		return
	}
	<-gatherComplete

	resp := signalResponse{Answer: pc.LocalDescription().SDP}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}
