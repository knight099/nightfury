package localui

import (
	"embed"
	"io/fs"
	"net/http"
)

//go:embed static
var staticFS embed.FS

// Serve runs the local pairing UI on addr until ListenAndServe returns.
func Serve(addr string, p Pairer) error {
	h := newHandlers(p)
	mux := http.NewServeMux()
	sub, _ := fs.Sub(staticFS, "static")
	mux.Handle("/", http.FileServer(http.FS(sub)))
	mux.HandleFunc("/api/pair", h.Pair)
	mux.HandleFunc("/api/status", h.Status)
	return http.ListenAndServe(addr, mux)
}
