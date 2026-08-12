// Package control implements the agent's outbound control WebSocket client.
//
// The agent dials the backend's POST /api/agents/me/control WebSocket
// endpoint (authenticated via the agent's device token), and answers
// signal_offer messages pushed by the backend on behalf of dashboard
// viewers requesting a WebRTC feed. Each offer is handled by calling
// webrtcsignal.ViewerServer.HandleOffer directly (no HTTP round trip),
// and the resulting SDP answer is written back as a signal_answer message.
package control

import (
	"context"
	"encoding/json"
	"log"
	"net/url"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/pion/webrtc/v4"

	"github.com/nightwatch/agent/webrtcsignal"
)

// Client maintains a reconnecting WebSocket connection to the backend's
// agent control channel and dispatches incoming WebRTC signaling offers to
// a local ViewerServer.
type Client struct {
	backendURL  string
	deviceToken string
	viewer      *webrtcsignal.ViewerServer
}

// NewClient builds a control Client. backendURL is the plain http(s)
// backend base URL (e.g. "https://api.example.com"); it is translated to
// ws(s):// internally. deviceToken authenticates the agent to the backend.
// viewer answers WebRTC offers for cameras published on this agent.
func NewClient(backendURL, deviceToken string, viewer *webrtcsignal.ViewerServer) *Client {
	return &Client{backendURL: backendURL, deviceToken: deviceToken, viewer: viewer}
}

// Run connects to the control channel and processes messages until ctx is
// canceled, reconnecting with exponential backoff (capped at 30s) on any
// disconnect or dial error. It returns ctx.Err() when ctx is canceled.
func (c *Client) Run(ctx context.Context) error {
	backoff := time.Second
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err := c.runOnce(ctx); err != nil {
			log.Printf("control channel disconnected: %v, retrying in %s", err, backoff)
		}
		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return ctx.Err()
		}
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
}

// runOnce dials the control WebSocket once and reads messages until the
// connection errors or closes. Each signal_offer is dispatched to its own
// goroutine (handleOffer) so a slow ICE gathering step on one offer doesn't
// block other concurrently arriving offers (e.g. two dashboard tabs
// requesting a view at once).
func (c *Client) runOnce(ctx context.Context) error {
	u, err := url.Parse(c.backendURL)
	if err != nil {
		return err
	}
	switch u.Scheme {
	case "https":
		u.Scheme = "wss"
	case "http":
		u.Scheme = "ws"
	default:
		u.Scheme = "wss"
	}
	u.Path = "/api/agents/me/control"
	q := u.Query()
	q.Set("token", c.deviceToken)
	u.RawQuery = q.Encode()

	conn, _, err := websocket.DefaultDialer.DialContext(ctx, u.String(), nil)
	if err != nil {
		return err
	}
	defer conn.Close()

	// gorilla/websocket connections are not safe for concurrent writes
	// (or concurrent reads) from multiple goroutines. handleOffer runs in
	// its own goroutine per offer and writes the signal_answer reply, so
	// all writes to conn — from any goroutine spawned for this connection
	// — must go through this single mutex, held for the duration of each
	// write. runOnce itself never writes to conn, only reads, so there is
	// no separate write path to protect here.
	var writeMu sync.Mutex

	for {
		var msg map[string]any
		if err := conn.ReadJSON(&msg); err != nil {
			return err
		}
		if msg["type"] != "signal_offer" {
			continue
		}
		go c.handleOffer(conn, &writeMu, msg)
	}
}

// handleOffer decodes a signal_offer message, resolves it via
// viewer.HandleOffer, and writes back a signal_answer reply. writeMu must
// be the same mutex shared by every goroutine writing to conn.
func (c *Client) handleOffer(conn *websocket.Conn, writeMu *sync.Mutex, msg map[string]any) {
	cameraID, _ := msg["camera_id"].(string)
	viewToken, _ := msg["view_token"].(string)
	requestID, _ := msg["request_id"].(string)
	offerRaw, err := json.Marshal(msg["offer"])
	if err != nil {
		log.Printf("bad offer payload: %v", err)
		return
	}
	var offer webrtc.SessionDescription
	if err := json.Unmarshal(offerRaw, &offer); err != nil {
		log.Printf("bad offer payload: %v", err)
		return
	}

	answer, err := c.viewer.HandleOffer(cameraID, viewToken, offer)
	if err != nil {
		log.Printf("HandleOffer failed for camera %s: %v", cameraID, err)
		return
	}

	writeMu.Lock()
	defer writeMu.Unlock()
	if err := conn.WriteJSON(map[string]any{
		"type":       "signal_answer",
		"request_id": requestID,
		"answer":     answer,
	}); err != nil {
		log.Printf("failed to send signal_answer for camera %s: %v", cameraID, err)
	}
}
