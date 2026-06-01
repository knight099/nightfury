package pairing

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// Request is the JSON body posted to /api/agents/pair.
type Request struct {
	Code      string `json:"code"`
	MachineID string `json:"machine_id"`
	Pubkey    string `json:"pubkey"`
	Version   string `json:"version,omitempty"`
}

// Response is the JSON body returned by the backend on success.
type Response struct {
	DeviceToken string `json:"device_token"`
	RelayURL    string `json:"relay_url"`
	OrgID       string `json:"org_id"`
	AgentID     string `json:"agent_id"`
}

// Client posts pairing codes to the backend in exchange for a long-lived
// device token.
type Client struct {
	backendURL string
	http       *http.Client
}

// NewClient builds a pairing client targeting the given backend base URL.
func NewClient(backendURL string) *Client {
	return &Client{backendURL: backendURL, http: &http.Client{Timeout: 10 * time.Second}}
}

// Pair exchanges a pairing code for a device token.
func (c *Client) Pair(ctx context.Context, req Request) (Response, error) {
	body, _ := json.Marshal(req)
	httpReq, err := http.NewRequestWithContext(ctx, "POST", c.backendURL+"/api/agents/pair", bytes.NewReader(body))
	if err != nil {
		return Response{}, err
	}
	httpReq.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(httpReq)
	if err != nil {
		return Response{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return Response{}, fmt.Errorf("pair failed: %d", resp.StatusCode)
	}
	var out Response
	return out, json.NewDecoder(resp.Body).Decode(&out)
}
