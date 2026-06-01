package transport

import (
	"strings"
	"sync"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// Decider tracks consecutive non-auth connect errors and decides when to fall
// back to an alternate transport (e.g. gRPC -> WebRTC).
type Decider struct {
	mu       sync.Mutex
	failures int
}

// FallbackThreshold is the number of consecutive non-auth errors before
// ShouldFallback returns true.
const FallbackThreshold = 3

func (d *Decider) Record(err error) {
	if err == nil {
		return
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if isAuthError(err) {
		return
	}
	d.failures++
}

func (d *Decider) RecordSuccess() {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.failures = 0
}

func (d *Decider) ShouldFallback() bool {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.failures >= FallbackThreshold
}

func isAuthError(err error) bool {
	if s, ok := status.FromError(err); ok {
		switch s.Code() {
		case codes.Unauthenticated, codes.PermissionDenied:
			return true
		}
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "unauthorized") || strings.Contains(msg, "forbidden")
}
