package auth

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"

	"google.golang.org/grpc/metadata"
)

// AgentInfo identifies the org and agent associated with a verified device token.
type AgentInfo struct {
	OrgID   string `json:"org_id"`
	AgentID string `json:"agent_id"`
}

// AgentAuthenticator is implemented by anything that can authenticate an
// incoming agent gRPC stream from its context metadata.
type AgentAuthenticator interface {
	Verify(ctx context.Context) error
}

// Verifier verifies an agent device token by calling the backend's
// internal /agents/verify-token endpoint, with a short in-memory cache.
type Verifier struct {
	backendURL string
	workerKey  string
	ttl        time.Duration
	httpClient *http.Client

	mu    sync.Mutex
	cache map[string]cacheEntry
}

type cacheEntry struct {
	info      AgentInfo
	expiresAt time.Time
}

// NewVerifier returns a Verifier that calls backendURL with the given worker
// key and caches positive results for ttl.
func NewVerifier(backendURL, workerKey string, ttl time.Duration) *Verifier {
	return &Verifier{
		backendURL: backendURL,
		workerKey:  workerKey,
		ttl:        ttl,
		httpClient: &http.Client{Timeout: 5 * time.Second},
		cache:      make(map[string]cacheEntry),
	}
}

// Verify resolves the given device token to an AgentInfo. Cache hits skip the
// HTTP call.
func (v *Verifier) Verify(ctx context.Context, token string) (AgentInfo, error) {
	if token == "" {
		return AgentInfo{}, errors.New("empty token")
	}

	v.mu.Lock()
	if entry, ok := v.cache[token]; ok && time.Now().Before(entry.expiresAt) {
		info := entry.info
		v.mu.Unlock()
		return info, nil
	}
	v.mu.Unlock()

	body, err := json.Marshal(map[string]string{"token": token})
	if err != nil {
		return AgentInfo{}, err
	}
	req, err := http.NewRequestWithContext(
		ctx, http.MethodPost,
		v.backendURL+"/internal/agents/verify-token",
		bytes.NewReader(body),
	)
	if err != nil {
		return AgentInfo{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Worker-Key", v.workerKey)

	resp, err := v.httpClient.Do(req)
	if err != nil {
		return AgentInfo{}, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return AgentInfo{}, fmt.Errorf("verify-token rejected: status %d", resp.StatusCode)
	}

	var info AgentInfo
	if err := json.NewDecoder(resp.Body).Decode(&info); err != nil {
		return AgentInfo{}, err
	}

	v.mu.Lock()
	v.cache[token] = cacheEntry{info: info, expiresAt: time.Now().Add(v.ttl)}
	v.mu.Unlock()

	return info, nil
}

// DeviceTokenAuthenticator implements AgentAuthenticator by reading an
// "x-agent-token" metadata header and resolving it via Verifier.
//
// NOTE: this uses metadata key "x-agent-token" (distinct from StaticKey's
// "x-agent-key") to keep the two auth modes cleanly separated.
type DeviceTokenAuthenticator struct {
	V *Verifier
}

func (d DeviceTokenAuthenticator) Verify(ctx context.Context) error {
	if d.V == nil {
		return errors.New("auth not configured")
	}
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return errors.New("no metadata")
	}
	got := md.Get("x-agent-token")
	if len(got) == 0 || got[0] == "" {
		return errors.New("missing agent token")
	}
	if _, err := d.V.Verify(ctx, got[0]); err != nil {
		return err
	}
	return nil
}
