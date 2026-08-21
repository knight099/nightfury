package localui

import (
	"encoding/base64"
	"fmt"
	"html/template"
	"net/http"

	qrcode "github.com/skip2/go-qrcode"
)

// bannerHandler serves the pairing banner (QR + spaced digits) at "/" for a
// customer browsing to the box on the LAN when there is no display
// attached. Used by ServeBanner (device-initiated pairing path only) with
// code and claimURL already known; fallback is invoked for any other path
// or when code is empty (defense in depth — ServeBanner's mux only ever
// registers "/").
type bannerHandler struct {
	code     string
	claimURL string
	fallback http.Handler
}

var bannerTmpl = template.Must(template.New("banner").Parse(`<!doctype html>
<html><head><meta charset="utf-8"><title>Nightwatch setup</title>
<style>
  body { background:#111; color:#eee; font-family: system-ui, sans-serif; text-align:center; padding:2rem; }
  img { background:#fff; padding:1rem; border-radius:8px; }
  .code { font-size:2rem; letter-spacing:0.3rem; margin-top:1.5rem; }
</style></head>
<body>
  <h1>Nightwatch setup</h1>
  <p>Scan this QR code, or visit nightwatch.ai/connect and enter the code below.</p>
  <img src="data:image/png;base64,{{.PNG}}" alt="Pairing QR code" width="256" height="256">
  <div class="code">{{.SpacedCode}}</div>
</body></html>
`))

func (h *bannerHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" || h.code == "" {
		h.fallback.ServeHTTP(w, r)
		return
	}

	png, err := qrcode.Encode(h.claimURL, qrcode.Medium, 256)
	if err != nil {
		// A QR that will not render must not take the page down — the
		// digits alone are still a complete pairing path.
		png = nil
	}

	spaced := h.code
	if len(h.code) == 6 {
		spaced = fmt.Sprintf("%s %s", h.code[:3], h.code[3:])
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_ = bannerTmpl.Execute(w, struct {
		PNG        string
		SpacedCode string
	}{
		PNG:        base64.StdEncoding.EncodeToString(png),
		SpacedCode: spaced,
	})
}
