package localui

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
)

var errCodeFmt = errors.New("bad code format")
var codeRE = regexp.MustCompile(`^\d{6}$`)

// Pairer abstracts the pairing flow used by the local web UI.
type Pairer interface {
	Pair(ctx context.Context, code string) error
	IsPaired() bool
}

type handlers struct{ pairer Pairer }

func newHandlers(p Pairer) *handlers { return &handlers{pairer: p} }

// Pair handles POST /api/pair {code}.
func (h *handlers) Pair(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Code string `json:"code"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "bad json", 400)
		return
	}
	if !codeRE.MatchString(body.Code) {
		http.Error(w, "code must be 6 digits", 400)
		return
	}
	if err := h.pairer.Pair(r.Context(), body.Code); err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	_, _ = w.Write([]byte(`{"ok":true}`))
}

// Status handles GET /api/status, returning {"paired": bool}.
func (h *handlers) Status(w http.ResponseWriter, r *http.Request) {
	_ = json.NewEncoder(w).Encode(map[string]any{"paired": h.pairer.IsPaired()})
}
