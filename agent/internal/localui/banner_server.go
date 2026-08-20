package localui

import (
	"context"
	"net/http"
	"time"
)

const shutdownTimeout = 5 * time.Second

// ServeBanner runs a minimal, read-only HTTP server that serves only the
// QR/digits pairing banner at "/" — no /api/pair, no /api/status, no other
// route. It exists so the default device-initiated pairing path (which has
// no operator-entered code to check against — anyone who can reach the box
// on the LAN would otherwise be able to pair it) never exposes an
// authentication-bypassing endpoint. The legacy dashboard-code flow
// (AGENT_PAIR_MODE=localui) continues to use Serve, unchanged.
//
// ServeBanner blocks until ctx is cancelled, at which point it shuts the
// listener down and returns nil (or the shutdown error, if any). Callers
// should run it in a goroutine and cancel ctx once pairing completes so the
// LAN-reachable banner does not outlive the pairing window.
func ServeBanner(ctx context.Context, addr, code, claimURL string) error {
	mux := http.NewServeMux()
	mux.Handle("/", &bannerHandler{
		code:     code,
		claimURL: claimURL,
		// No static-file fallback: this mux serves nothing but the banner.
		fallback: http.NotFoundHandler(),
	})

	srv := &http.Server{Addr: addr, Handler: mux}

	errCh := make(chan error, 1)
	go func() {
		errCh <- srv.ListenAndServe()
	}()

	select {
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
		defer cancel()
		return srv.Shutdown(shutdownCtx)
	case err := <-errCh:
		if err == http.ErrServerClosed {
			return nil
		}
		return err
	}
}
