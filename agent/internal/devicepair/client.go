// Package devicepair implements device-initiated provisioning.
//
// The device:
//  1. Generates a persistent device_id (UUID) and a cryptographically secure
//     6-digit code.
//  2. Calls POST /api/devices/provision to register with the backend.
//  3. Prints "NW-XXXXXX — enter at nightwatch.ai to link this device" and a
//     QR code encoding a claim URL for the same box.
//  4. Polls GET /api/devices/{device_id}/status every 5 s for up to 10 min.
//  5. On "claimed", saves the returned token to disk and returns.
package devicepair

import (
	"bytes"
	"context"
	cryptorand "crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"time"
)

const (
	pollInterval = 5 * time.Second
	pollTimeout  = 10 * time.Minute
)

// Token is the credential returned by the backend when the device is claimed.
type Token struct {
	DeviceToken string `json:"device_token"`
	RelayURL    string `json:"relay_url"`
	OrgID       string `json:"org_id"`
	AgentID     string `json:"agent_id"`
}

// Client talks to /api/devices on the Nightwatch backend.
type Client struct {
	backendURL string
	http       *http.Client
}

func NewClient(backendURL string) *Client {
	return &Client{
		backendURL: backendURL,
		http:       &http.Client{Timeout: 15 * time.Second},
	}
}

type provisionReq struct {
	DeviceID  string `json:"device_id"`
	Code      string `json:"code"`
	Pubkey    string `json:"pubkey"`
	MachineID string `json:"machine_id"`
	Version   string `json:"version,omitempty"`
}

type provisionResp struct {
	DeviceID  string `json:"device_id"`
	Code      string `json:"code"` // "NW-XXXXXX"
	Status    string `json:"status"`
	ExpiresAt string `json:"expires_at"`
	ClaimURL  string `json:"claim_url"`
}

type statusResp struct {
	Status      string `json:"status"`
	DeviceToken string `json:"device_token"`
	RelayURL    string `json:"relay_url"`
	OrgID       string `json:"org_id"`
	AgentID     string `json:"agent_id"`
}

// GenerateCode returns a cryptographically secure 6-digit string.
//
// math/rand was wrong here twice over: it is not cryptographically secure,
// and 4 digits is a 10,000-value space that a claim endpoint can be walked
// through. Six digits from crypto/rand widens it 100x and removes the
// predictability; the backend's rate limit covers the rest.
func GenerateCode() (string, error) {
	n, err := cryptorand.Int(cryptorand.Reader, big.NewInt(1_000_000))
	if err != nil {
		return "", fmt.Errorf("generate pairing code: %w", err)
	}
	return fmt.Sprintf("%06d", n.Int64()), nil
}

// Provision registers the device with the backend and returns the display
// code (in "NW-XXXXXX" format) and the claim URL for the QR banner.
func (c *Client) Provision(ctx context.Context, deviceID, code, pubkey, machineID, version string) (string, string, error) {
	body, _ := json.Marshal(provisionReq{
		DeviceID:  deviceID,
		Code:      code,
		Pubkey:    pubkey,
		MachineID: machineID,
		Version:   version,
	})
	req, err := http.NewRequestWithContext(ctx, "POST", c.backendURL+"/api/devices/provision", bytes.NewReader(body))
	if err != nil {
		return "", "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.http.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("provision request failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 201 {
		return "", "", fmt.Errorf("provision failed: HTTP %d", resp.StatusCode)
	}
	var out provisionResp
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", "", err
	}
	return out.Code, out.ClaimURL, nil
}

// PollUntilClaimed polls the backend until the device is claimed or the
// context is cancelled.  Returns the device token on success.
func (c *Client) PollUntilClaimed(ctx context.Context, deviceID string) (Token, error) {
	deadline := time.Now().Add(pollTimeout)
	for {
		select {
		case <-ctx.Done():
			return Token{}, ctx.Err()
		default:
		}
		if time.Now().After(deadline) {
			return Token{}, errors.New("provisioning timed out — code expired; restart device to generate a new code")
		}

		tok, status, err := c.checkStatus(ctx, deviceID)
		if err == nil {
			switch status {
			case "claimed":
				return tok, nil
			case "expired":
				return Token{}, errors.New("code expired before it was claimed; restart device to generate a new code")
			}
		}

		select {
		case <-ctx.Done():
			return Token{}, ctx.Err()
		case <-time.After(pollInterval):
		}
	}
}

func (c *Client) checkStatus(ctx context.Context, deviceID string) (Token, string, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", c.backendURL+"/api/devices/"+deviceID+"/status", nil)
	if err != nil {
		return Token{}, "", err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return Token{}, "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 404 {
		return Token{}, "", fmt.Errorf("device not found")
	}
	if resp.StatusCode != 200 {
		return Token{}, "", fmt.Errorf("status HTTP %d", resp.StatusCode)
	}
	var s statusResp
	if err := json.NewDecoder(resp.Body).Decode(&s); err != nil {
		return Token{}, "", err
	}
	return Token{
		DeviceToken: s.DeviceToken,
		RelayURL:    s.RelayURL,
		OrgID:       s.OrgID,
		AgentID:     s.AgentID,
	}, s.Status, nil
}
