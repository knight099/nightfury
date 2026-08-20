package control

import (
	"context"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/nightwatch/agent/internal/discovery"
)

// scanCooldown bounds how often scan_now may trigger a real probe. A
// customer mashing "Scan again" in the onboarding wizard must not flood
// the LAN with WS-Discovery multicast.
const scanCooldown = 10 * time.Second

// scanState guards on-demand discovery scans with both a mutex (so two
// rapid scan_now commands never run concurrent ONVIF probes) and a cooldown
// (so a burst of requests within scanCooldown only runs the first one).
type scanState struct {
	mu       sync.Mutex
	lastScan time.Time
}

// handleScanNow runs the same discovery-and-report cycle the interval
// reporter (discovery.RunReporter) already runs, on demand. Results are not
// returned synchronously here — they land via the existing
// POST /api/agents/me/discovered, same as the periodic reporter — so this
// is fire-and-forget from the caller's perspective.
//
// Guarded by scanState's mutex, held for the whole probe, and a cooldown
// checked before acquiring it: a request that arrives while a probe is in
// flight, or within scanCooldown of the last one, is dropped and logged
// rather than queued or errored. Dropping is correct behaviour, not a
// failure — the control socket has nothing to report back for a command
// message.
func (s *scanState) handleScanNow(ctx context.Context, backendURL, deviceToken string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if !s.lastScan.IsZero() {
		if elapsed := time.Since(s.lastScan); elapsed < scanCooldown {
			log.Printf("scan_now dropped: last scan %s ago, cooldown is %s", elapsed, scanCooldown)
			return
		}
	}
	s.lastScan = time.Now()

	devs, err := discovery.Discover(ctx, 5*time.Second)
	if err != nil {
		log.Printf("scan_now: onvif discovery failed: %v", err)
		return
	}
	log.Printf("scan_now: discovery complete, %d device(s) found", len(devs))

	client := &http.Client{Timeout: 15 * time.Second}
	if err := discovery.Report(ctx, client, backendURL, deviceToken, devs); err != nil {
		log.Printf("scan_now: discovery report failed: %v", err)
	}
}
