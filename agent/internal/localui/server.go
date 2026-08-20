package localui

import (
	"embed"
	"io/fs"
	"net/http"
)

//go:embed static
var staticFS embed.FS

// Serve runs the local pairing UI on addr until ListenAndServe returns.
//
// code and claimURL are set by the device-initiated pairing path so a
// customer on the LAN can reach http://nightwatch.local and see the same
// QR/digits banner shown on an attached display. The legacy dashboard-code
// flow (AGENT_PAIR_MODE=localui) has no code yet when the server starts —
// pass "" and "" and "/" continues to serve the static entry-code page.
func Serve(addr string, p Pairer, code, claimURL string) error {
	h := newHandlers(p)
	mux := http.NewServeMux()
	sub, _ := fs.Sub(staticFS, "static")
	mux.Handle("/", &bannerHandler{
		code:     code,
		claimURL: claimURL,
		fallback: http.FileServer(http.FS(sub)),
	})
	mux.HandleFunc("/api/pair", h.Pair)
	mux.HandleFunc("/api/status", h.Status)
	return http.ListenAndServe(addr, mux)
}
