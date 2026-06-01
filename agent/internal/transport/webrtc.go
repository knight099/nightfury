package transport

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"

	"github.com/pion/webrtc/v4"
)

// WebRTC is a Transport implementation that opens a Pion PeerConnection
// against a relay HTTP signaling endpoint. Each camera gets its own
// DataChannel named "cam:<id>". The first message sent over the channel
// is a text payload identifying the camera; subsequent messages are
// binary frames.
type WebRTC struct {
	signalURL string
	agentKey  string
	api       *webrtc.API

	mu       sync.Mutex
	pc       *webrtc.PeerConnection
	channels map[string]*webrtc.DataChannel
	opened   map[string]chan struct{}
}

// NewWebRTC constructs a WebRTC transport pointing at the given signaling URL.
func NewWebRTC(signalURL, agentKey string) *WebRTC {
	m := &webrtc.MediaEngine{}
	api := webrtc.NewAPI(webrtc.WithMediaEngine(m))
	return &WebRTC{
		signalURL: signalURL,
		agentKey:  agentKey,
		api:       api,
		channels:  make(map[string]*webrtc.DataChannel),
		opened:    make(map[string]chan struct{}),
	}
}

func (w *WebRTC) Name() string { return "webrtc" }

type signalRequest struct {
	AgentKey string `json:"agent_key"`
	Offer    string `json:"offer"`
}

type signalResponse struct {
	Answer string `json:"answer"`
}

// Connect creates the PeerConnection, generates an offer, exchanges with
// the relay over HTTP, and waits for the connection to enter "connected".
func (w *WebRTC) Connect(ctx context.Context) error {
	pc, err := w.api.NewPeerConnection(webrtc.Configuration{})
	if err != nil {
		return fmt.Errorf("new pc: %w", err)
	}

	connected := make(chan struct{})
	failed := make(chan error, 1)
	var once sync.Once
	pc.OnConnectionStateChange(func(state webrtc.PeerConnectionState) {
		switch state {
		case webrtc.PeerConnectionStateConnected:
			once.Do(func() { close(connected) })
		case webrtc.PeerConnectionStateFailed, webrtc.PeerConnectionStateClosed:
			select {
			case failed <- fmt.Errorf("pc state %s", state.String()):
			default:
			}
		}
	})

	// Open at least one data channel before creating the offer so that
	// the SDP carries an SCTP m-section. We use a placeholder channel
	// that we never use; per-camera channels are added in OpenCamera
	// (with negotiation triggered by renegotiation OR — to keep things
	// simple — we just create channels lazily after Connect using the
	// already-established SCTP transport, which Pion supports).
	if _, err := pc.CreateDataChannel("control", nil); err != nil {
		_ = pc.Close()
		return fmt.Errorf("create control dc: %w", err)
	}

	offer, err := pc.CreateOffer(nil)
	if err != nil {
		_ = pc.Close()
		return fmt.Errorf("create offer: %w", err)
	}
	gatherComplete := webrtc.GatheringCompletePromise(pc)
	if err := pc.SetLocalDescription(offer); err != nil {
		_ = pc.Close()
		return fmt.Errorf("set local: %w", err)
	}
	select {
	case <-gatherComplete:
	case <-ctx.Done():
		_ = pc.Close()
		return ctx.Err()
	}

	body, _ := json.Marshal(signalRequest{
		AgentKey: w.agentKey,
		Offer:    pc.LocalDescription().SDP,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, w.signalURL, bytes.NewReader(body))
	if err != nil {
		_ = pc.Close()
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		_ = pc.Close()
		return fmt.Errorf("signal post: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		buf, _ := io.ReadAll(resp.Body)
		_ = pc.Close()
		return fmt.Errorf("signal status %d: %s", resp.StatusCode, string(buf))
	}
	var sr signalResponse
	if err := json.NewDecoder(resp.Body).Decode(&sr); err != nil {
		_ = pc.Close()
		return fmt.Errorf("decode answer: %w", err)
	}
	if err := pc.SetRemoteDescription(webrtc.SessionDescription{
		Type: webrtc.SDPTypeAnswer,
		SDP:  sr.Answer,
	}); err != nil {
		_ = pc.Close()
		return fmt.Errorf("set remote: %w", err)
	}

	select {
	case <-connected:
	case err := <-failed:
		_ = pc.Close()
		return err
	case <-ctx.Done():
		_ = pc.Close()
		return ctx.Err()
	case <-time.After(10 * time.Second):
		_ = pc.Close()
		return errors.New("webrtc connect timeout")
	}

	w.mu.Lock()
	w.pc = pc
	w.mu.Unlock()
	return nil
}

// OpenCamera creates a per-camera DataChannel and waits for it to open.
// The first message sent is a text payload containing the camera id, so
// the relay can register a Publisher.
func (w *WebRTC) OpenCamera(id string) error {
	w.mu.Lock()
	pc := w.pc
	if pc == nil {
		w.mu.Unlock()
		return errors.New("not connected")
	}
	if _, ok := w.channels[id]; ok {
		w.mu.Unlock()
		return nil
	}
	w.mu.Unlock()

	dc, err := pc.CreateDataChannel("cam:"+id, nil)
	if err != nil {
		return fmt.Errorf("create dc: %w", err)
	}
	openedCh := make(chan struct{})
	var once sync.Once
	dc.OnOpen(func() {
		// First message is the camera id (text)
		_ = dc.SendText(id)
		once.Do(func() { close(openedCh) })
	})

	select {
	case <-openedCh:
	case <-time.After(5 * time.Second):
		return fmt.Errorf("data channel open timeout for camera %s", id)
	}

	w.mu.Lock()
	w.channels[id] = dc
	w.opened[id] = openedCh
	w.mu.Unlock()
	return nil
}

// SendFrame writes a binary frame on the camera's DataChannel.
func (w *WebRTC) SendFrame(id string, payload []byte, keyframe bool) error {
	w.mu.Lock()
	dc, ok := w.channels[id]
	w.mu.Unlock()
	if !ok {
		return fmt.Errorf("camera %s not open", id)
	}
	return dc.Send(payload)
}

// Close tears down all data channels and the PeerConnection.
func (w *WebRTC) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	for _, dc := range w.channels {
		_ = dc.Close()
	}
	w.channels = map[string]*webrtc.DataChannel{}
	if w.pc != nil {
		err := w.pc.Close()
		w.pc = nil
		return err
	}
	return nil
}
