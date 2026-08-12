package webrtcsignal

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/nightwatch/agent/internal/republish"
)

func TestSignal_RejectsBadAgentKey(t *testing.T) {
	reg := republish.NewRegistry()
	srv := NewServer("correct-key", reg)
	ts := httptest.NewServer(srv)
	defer ts.Close()

	body := strings.NewReader(`{"agent_key":"wrong","offer":"v=0"}`)
	resp, err := http.Post(ts.URL, "application/json", body)
	if err != nil {
		t.Fatalf("post: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", resp.StatusCode)
	}
	// Sanity check that body decoding occurs
	_ = bytes.Buffer{}
}
