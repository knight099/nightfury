package webrtcsignal

import (
	"errors"
	"fmt"

	"github.com/pion/webrtc/v4"
)

// ErrInvalidToken is returned by HandleOffer when the view token fails
// verification (expired, malformed, or bad HMAC).
var ErrInvalidToken = errors.New("invalid view token")

// ErrCameraNotFound is returned by HandleOffer when no publisher is
// registered for the requested camera ID.
var ErrCameraNotFound = errors.New("camera not on relay")

// Per-stage sentinel errors. HandleOffer wraps the underlying pion error
// with one of these via %w so callers (e.g. ServeHTTP) can distinguish
// failure stages with errors.Is and reproduce the original ServeHTTP's
// per-stage HTTP status/message behavior instead of collapsing everything
// into a single generic response.
var (
	ErrCodecRegistration  = errors.New("codec registration failed")
	ErrPeerConnectionInit = errors.New("peer connection failed")
	ErrTrackCreate        = errors.New("track create failed")
	ErrAddTrack           = errors.New("add track failed")
	// ErrBadOffer indicates the remote SDP offer was rejected by
	// SetRemoteDescription; this is a client error (malformed/incompatible
	// offer), not a server fault, so it maps to 400 in ServeHTTP.
	ErrBadOffer     = errors.New("set remote")
	ErrCreateAnswer = errors.New("create answer failed")
	ErrSetLocal     = errors.New("set local failed")
)

// HandleOffer builds a PeerConnection for cameraID, wires it to the
// camera's republished H.264 stream, and negotiates an SDP answer for the
// given offer. It contains the same peer-connection-building logic that
// ServeHTTP used to run inline; ServeHTTP is now a thin HTTP wrapper around
// this function so it can also be called directly (e.g. from an outbound
// WebSocket signaling path with no HTTP round trip involved).
func (s *ViewerServer) HandleOffer(cameraID, viewToken string, offer webrtc.SessionDescription) (webrtc.SessionDescription, error) {
	if s.secret != "" && !s.verifyToken(cameraID, viewToken) {
		return webrtc.SessionDescription{}, ErrInvalidToken
	}

	pub, ok := s.registry.Get(cameraID)
	if !ok {
		return webrtc.SessionDescription{}, ErrCameraNotFound
	}

	m := &webrtc.MediaEngine{}
	if err := m.RegisterCodec(webrtc.RTPCodecParameters{
		RTPCodecCapability: webrtc.RTPCodecCapability{
			MimeType:    webrtc.MimeTypeH264,
			ClockRate:   90000,
			SDPFmtpLine: "level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f",
		},
		PayloadType: 96,
	}, webrtc.RTPCodecTypeVideo); err != nil {
		return webrtc.SessionDescription{}, fmt.Errorf("%w: %v", ErrCodecRegistration, err)
	}

	api := webrtc.NewAPI(webrtc.WithMediaEngine(m))
	pc, err := api.NewPeerConnection(webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{{URLs: []string{"stun:stun.l.google.com:19302"}}},
	})
	if err != nil {
		return webrtc.SessionDescription{}, fmt.Errorf("%w: %v", ErrPeerConnectionInit, err)
	}

	videoTrack, err := webrtc.NewTrackLocalStaticSample(
		webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264, ClockRate: 90000},
		"video", "nightwatch-"+cameraID,
	)
	if err != nil {
		_ = pc.Close()
		return webrtc.SessionDescription{}, fmt.Errorf("%w: %v", ErrTrackCreate, err)
	}

	if _, err = pc.AddTrack(videoTrack); err != nil {
		_ = pc.Close()
		return webrtc.SessionDescription{}, fmt.Errorf("%w: %v", ErrAddTrack, err)
	}

	if err = pc.SetRemoteDescription(offer); err != nil {
		_ = pc.Close()
		return webrtc.SessionDescription{}, fmt.Errorf("%w: %v", ErrBadOffer, err)
	}

	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		_ = pc.Close()
		return webrtc.SessionDescription{}, fmt.Errorf("%w: %v", ErrCreateAnswer, err)
	}

	gatherDone := webrtc.GatheringCompletePromise(pc)
	if err = pc.SetLocalDescription(answer); err != nil {
		_ = pc.Close()
		return webrtc.SessionDescription{}, fmt.Errorf("%w: %v", ErrSetLocal, err)
	}
	<-gatherDone

	go viewerPump(pc, videoTrack, pub)

	return *pc.LocalDescription(), nil
}
