package devicepair

import (
	"fmt"
	"strings"

	qrcode "github.com/skip2/go-qrcode"
)

// Banner renders the pairing screen for a terminal or HDMI console.
//
// Both the QR and the digits are shown deliberately: the QR is the fast
// path, and the digits are the fallback for a customer whose phone camera
// will not focus on a CRT, a glare-lit monitor, or a serial console.
func Banner(code, claimURL string) string {
	qr, err := qrcode.New(claimURL, qrcode.Medium)
	var art string
	if err != nil {
		// A QR that will not render must not take the box down — the
		// six digits alone are still a complete pairing path.
		art = "(QR unavailable — use the code below)"
	} else {
		art = qr.ToSmallString(false)
	}

	spaced := code
	if len(code) == 6 {
		spaced = fmt.Sprintf("%s %s", code[:3], code[3:])
	}

	var b strings.Builder
	b.WriteString("\n  Nightwatch setup\n\n")
	b.WriteString(art)
	b.WriteString("\n  Scan this QR code or visit nightwatch.ai/connect\n")
	b.WriteString(fmt.Sprintf("\n  Code: %s\n\n", spaced))
	return b.String()
}
