// Package rtsp implements a thin RTSP pull client that reads H.264 from an
// NVR and hands decoded access units (Annex-B byte stream) to a callback.
package rtsp

import (
	"context"
	"fmt"
	"net"
	"sync"
	"time"

	"github.com/bluenviron/gortsplib/v5"
	"github.com/bluenviron/gortsplib/v5/pkg/base"
	"github.com/bluenviron/gortsplib/v5/pkg/format"
	"github.com/pion/rtp"
)

// FrameHandler is invoked for each decoded H.264 access unit. payload is the
// access unit serialized as Annex-B (each NALU prefixed with the 4-byte start
// code 0x00 0x00 0x00 0x01). keyframe is true when the access unit contains an
// IDR NALU (NAL type 5).
type FrameHandler func(payload []byte, keyframe bool)

// Client is an RTSP pull client.
type Client struct {
	URL     string
	OnFrame FrameHandler
}

// annexBStartCode is the 4-byte H.264 Annex-B start code.
var annexBStartCode = []byte{0x00, 0x00, 0x00, 0x01}

// auToAnnexB serializes an access unit (slice of NALUs) into the Annex-B byte
// stream used on the agent->relay tunnel.
func auToAnnexB(au [][]byte) []byte {
	total := 0
	for _, n := range au {
		total += 4 + len(n)
	}
	out := make([]byte, 0, total)
	for _, n := range au {
		out = append(out, annexBStartCode...)
		out = append(out, n...)
	}
	return out
}

// containsIDR returns true when any NALU in the access unit is an IDR slice
// (NAL type 5).
func containsIDR(au [][]byte) bool {
	for _, n := range au {
		if len(n) == 0 {
			continue
		}
		if n[0]&0x1F == 5 {
			return true
		}
	}
	return false
}

// Run dials the RTSP source, performs DESCRIBE/SETUP/PLAY, depacketizes
// H.264 RTP into access units, and invokes OnFrame for each. It returns an
// error if the URL is malformed or the server cannot be reached, and blocks
// until ctx is done otherwise.
func (c *Client) Run(ctx context.Context) error {
	if c.URL == "" {
		return fmt.Errorf("rtsp: empty URL")
	}

	u, err := base.ParseURL(c.URL)
	if err != nil {
		return fmt.Errorf("rtsp: parse url: %w", err)
	}
	if u.Host == "" {
		return fmt.Errorf("rtsp: url missing host: %q", c.URL)
	}

	// Bound TCP dial so unreachable hosts fail fast.
	dialer := &net.Dialer{Timeout: 300 * time.Millisecond}

	gc := &gortsplib.Client{
		Scheme:                u.Scheme,
		Host:                  u.Host,
		ReadTimeout:           5 * time.Second,
		WriteTimeout:          5 * time.Second,
		InitialUDPReadTimeout: 3 * time.Second,
		DialContext:           dialer.DialContext,
	}
	if err := gc.Start(); err != nil {
		return fmt.Errorf("rtsp: start: %w", err)
	}
	// gortsplib's Close is idempotent, so a single deferred Close covers
	// both early returns and the normal-exit path.
	defer gc.Close()

	// Run DESCRIBE/SETUP/PLAY in a goroutine so we can honor ctx while the
	// underlying TCP dial is in progress.
	type playReady struct {
		err error
	}
	readyCh := make(chan playReady, 1)

	go func() {
		desc, _, err := gc.Describe(u)
		if err != nil {
			readyCh <- playReady{fmt.Errorf("rtsp: describe: %w", err)}
			return
		}

		var forma *format.H264
		medi := desc.FindFormat(&forma)
		if medi == nil {
			readyCh <- playReady{fmt.Errorf("rtsp: no H264 media in stream")}
			return
		}

		dec, err := forma.CreateDecoder()
		if err != nil {
			readyCh <- playReady{fmt.Errorf("rtsp: create decoder: %w", err)}
			return
		}

		if _, err := gc.Setup(desc.BaseURL, medi, 0, 0); err != nil {
			readyCh <- playReady{fmt.Errorf("rtsp: setup: %w", err)}
			return
		}

		var primeOnce sync.Once
		primeNALUs := func() [][]byte {
			var out [][]byte
			if forma.SPS != nil {
				out = append(out, forma.SPS)
			}
			if forma.PPS != nil {
				out = append(out, forma.PPS)
			}
			return out
		}

		gc.OnPacketRTP(medi, forma, func(pkt *rtp.Packet) {
			au, derr := dec.Decode(pkt)
			if derr != nil {
				return
			}
			if len(au) == 0 || c.OnFrame == nil {
				return
			}
			primeOnce.Do(func() {
				prime := primeNALUs()
				if len(prime) > 0 {
					au = append(prime, au...)
				}
			})
			c.OnFrame(auToAnnexB(au), containsIDR(au))
		})

		if _, err := gc.Play(nil); err != nil {
			readyCh <- playReady{fmt.Errorf("rtsp: play: %w", err)}
			return
		}

		readyCh <- playReady{nil}
	}()

	select {
	case <-ctx.Done():
		// Ensure the setup goroutine has finished touching gc before we
		// return and the deferred gc.Close() runs. Closing the client
		// will unblock any in-flight DESCRIBE/SETUP/PLAY call.
		gc.Close()
		<-readyCh
		return nil
	case res := <-readyCh:
		if res.err != nil {
			return res.err
		}
	}

	// Wait for ctx cancel or session end.
	waitCh := make(chan error, 1)
	go func() { waitCh <- gc.Wait() }()

	select {
	case <-ctx.Done():
		return nil
	case err := <-waitCh:
		if err != nil && ctx.Err() == nil {
			return fmt.Errorf("rtsp: session ended: %w", err)
		}
		return nil
	}
}
