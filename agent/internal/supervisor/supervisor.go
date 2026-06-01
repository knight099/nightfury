// Package supervisor wires the RTSP client(s) to a Transport, handling
// reconnect with exponential backoff and primary/fallback transport selection.
package supervisor

import (
	"context"
	"log"
	"time"

	"github.com/nightwatch/agent/internal/rtsp"
	"github.com/nightwatch/agent/internal/transport"
)

// CameraSpec identifies a camera to stream from a local RTSP URL.
type CameraSpec struct {
	ID  string
	URL string
}

// Supervisor connects a Transport, opens each configured camera, and pumps
// RTSP frames into the transport. It re-establishes the transport on failure
// using exponential backoff and switches to Fallback when the Decider says so.
type Supervisor struct {
	Cameras  []CameraSpec
	Primary  transport.Transport
	Fallback transport.Transport
	Decider  *transport.Decider
}

const (
	initialBackoff = 1 * time.Second
	maxBackoff     = 30 * time.Second
)

// Run blocks until ctx is cancelled, returning ctx.Err().
func (s *Supervisor) Run(ctx context.Context) error {
	backoff := initialBackoff

	for ctx.Err() == nil {
		tp := s.Primary
		if s.Decider != nil && s.Decider.ShouldFallback() && s.Fallback != nil {
			tp = s.Fallback
		}
		if tp == nil {
			if !sleepCtx(ctx, backoff) {
				return ctx.Err()
			}
			backoff = nextBackoff(backoff)
			continue
		}

		if err := tp.Connect(ctx); err != nil {
			if s.Decider != nil {
				s.Decider.Record(err)
			}
			log.Printf("supervisor: transport %s connect failed: %v (retry in %s)", tp.Name(), err, backoff)
			if !sleepCtx(ctx, backoff) {
				return ctx.Err()
			}
			backoff = nextBackoff(backoff)
			continue
		}

		if s.Decider != nil {
			s.Decider.RecordSuccess()
		}
		backoff = initialBackoff

		sessionCtx, cancel := context.WithCancel(ctx)
		for _, cam := range s.Cameras {
			if err := tp.OpenCamera(cam.ID); err != nil {
				log.Printf("supervisor: open camera %s failed: %v", cam.ID, err)
				continue
			}
			cam := cam
			go func() {
				client := &rtsp.Client{
					URL: cam.URL,
					OnFrame: func(payload []byte, keyframe bool) {
						if err := tp.SendFrame(cam.ID, payload, keyframe); err != nil {
							log.Printf("supervisor: send frame %s failed: %v", cam.ID, err)
						}
					},
				}
				if err := client.Run(sessionCtx); err != nil && sessionCtx.Err() == nil {
					log.Printf("supervisor: rtsp client %s exited: %v", cam.ID, err)
				}
			}()
		}

		<-ctx.Done()
		cancel()
		if err := tp.Close(); err != nil {
			log.Printf("supervisor: transport close: %v", err)
		}
		return ctx.Err()
	}

	return ctx.Err()
}

// nextBackoff doubles the current backoff duration, capping at maxBackoff.
func nextBackoff(cur time.Duration) time.Duration {
	next := cur * 2
	if next > maxBackoff {
		return maxBackoff
	}
	if next <= 0 {
		return initialBackoff
	}
	return next
}

// sleepCtx sleeps for d or until ctx is cancelled. Returns true if it slept the
// full duration, false if ctx was cancelled.
func sleepCtx(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}
