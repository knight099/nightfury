// DEPRECATED: superseded by agent/internal/localui (onboarding plan Task 17). Remove after main.go cutover.
package local_ui

import (
	"embed"
	"encoding/json"
	"html/template"
	"net/http"
)

//go:embed templates/*.html
var fs embed.FS

type Server struct {
	Addr         string
	OnDiscovery  func() ([]map[string]string, error)
	OnSaveCamera func(brand, host, user, pass string) error
}

func (s *Server) Run() error {
	tpl := template.Must(template.ParseFS(fs, "templates/setup.html"))
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { _ = tpl.Execute(w, nil) })
	mux.HandleFunc("/api/discover", func(w http.ResponseWriter, r *http.Request) {
		out, err := s.OnDiscovery()
		if err != nil {
			http.Error(w, err.Error(), 500)
			return
		}
		_ = json.NewEncoder(w).Encode(out)
	})
	mux.HandleFunc("/api/camera", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			http.Error(w, "POST only", 405)
			return
		}
		var body struct{ Brand, Host, User, Pass string }
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		if err := s.OnSaveCamera(body.Brand, body.Host, body.User, body.Pass); err != nil {
			http.Error(w, err.Error(), 500)
			return
		}
		w.WriteHeader(204)
	})
	return http.ListenAndServe(s.Addr, mux)
}
