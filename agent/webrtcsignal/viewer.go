package webrtcsignal

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/pion/webrtc/v4"
	"github.com/pion/webrtc/v4/pkg/media"

	"github.com/nightwatch/agent/internal/republish"
)

// ViewerServer handles browser-facing WebRTC signaling.
// POST /view {camera_id, view_token, offer} → {answer}
//
// Frames are pulled from the shared Registry (same H.264 Annex-B ring
// populated by the gRPC / agent-WebRTC paths) and sent to the browser
// as a standard H.264 video track.
type ViewerServer struct {
	secret   string // STREAM_TOKEN_SECRET shared with backend
	registry *republish.Registry
}

func NewViewerServer(secret string, reg *republish.Registry) *ViewerServer {
	return &ViewerServer{secret: secret, registry: reg}
}

type viewRequest struct {
	CameraID  string `json:"camera_id"`
	ViewToken string `json:"view_token"`
	Offer     string `json:"offer"`
}

type viewResponse struct {
	Answer string `json:"answer"`
}

// verifyToken validates the HMAC token produced by the backend's
// sign_stream_token() helper: "<expires_at_unix>.<hex_hmac_sha256>".
func (s *ViewerServer) verifyToken(cameraID, token string) bool {
	parts := strings.SplitN(token, ".", 2)
	if len(parts) != 2 {
		return false
	}
	expiresAt, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return false
	}
	if time.Now().Unix() > expiresAt {
		return false
	}
	msg := fmt.Sprintf("%s:%d", cameraID, expiresAt)
	mac := hmac.New(sha256.New, []byte(s.secret))
	_, _ = mac.Write([]byte(msg))
	expected := fmt.Sprintf("%x", mac.Sum(nil))
	return hmac.Equal([]byte(expected), []byte(parts[1]))
}

func (s *ViewerServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req viewRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad json", http.StatusBadRequest)
		return
	}

	answer, err := s.HandleOffer(req.CameraID, req.ViewToken, webrtc.SessionDescription{
		Type: webrtc.SDPTypeOffer,
		SDP:  req.Offer,
	})
	if err != nil {
		switch {
		case errors.Is(err, ErrInvalidToken):
			http.Error(w, "unauthorized", http.StatusUnauthorized)
		case errors.Is(err, ErrCameraNotFound):
			http.Error(w, "camera not on relay", http.StatusNotFound)
		default:
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
		return
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(viewResponse{Answer: answer.SDP})
}

// viewerPump drains Annex-B H.264 frames from the publisher ring and writes
// them to the browser video track until the PeerConnection closes.
//
// Paced at 25fps via ticker. On each tick we drain the entire ring and send
// only the most recent frame, discarding accumulated backlog. This prevents
// the burst-then-stall pattern that occurs when the ring fills faster than
// the viewer consumes it.
func viewerPump(pc *webrtc.PeerConnection, track *webrtc.TrackLocalStaticSample, pub *republish.Publisher) {
	defer pc.Close()

	const fps = 25
	frameDur := time.Second / fps
	ticker := time.NewTicker(frameDur)
	defer ticker.Stop()

	for {
		switch pc.ConnectionState() {
		case webrtc.PeerConnectionStateFailed,
			webrtc.PeerConnectionStateClosed,
			webrtc.PeerConnectionStateDisconnected:
			return
		}

		<-ticker.C

		// Drain the ring to get the latest frame, skipping stale backlog.
		var frame []byte
		var ok bool
		for {
			f, has := pub.Frames.Pop()
			if !has {
				break
			}
			frame = f
			ok = true
		}
		if !ok {
			continue
		}

		if err := track.WriteSample(media.Sample{
			Data:     frame,
			Duration: frameDur,
		}); err != nil {
			return
		}
	}
}
