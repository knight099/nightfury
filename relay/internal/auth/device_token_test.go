package auth

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/metadata"
)

func TestVerifyTokenSuccess(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		require.Equal(t, "/internal/agents/verify-token", r.URL.Path)
		require.Equal(t, "wkey", r.Header.Get("X-Worker-Key"))
		var body map[string]string
		require.NoError(t, json.NewDecoder(r.Body).Decode(&body))
		require.Equal(t, "tok-1", body["token"])
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(AgentInfo{OrgID: "org-1", AgentID: "agent-1"})
	}))
	defer srv.Close()

	v := NewVerifier(srv.URL, "wkey", time.Minute)
	info, err := v.Verify(context.Background(), "tok-1")
	require.NoError(t, err)
	require.Equal(t, "org-1", info.OrgID)
	require.Equal(t, "agent-1", info.AgentID)
}

func TestVerifyTokenCached(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&calls, 1)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(AgentInfo{OrgID: "org-1", AgentID: "agent-1"})
	}))
	defer srv.Close()

	v := NewVerifier(srv.URL, "wkey", time.Minute)
	for i := 0; i < 3; i++ {
		_, err := v.Verify(context.Background(), "tok-1")
		require.NoError(t, err)
	}
	require.Equal(t, int32(1), atomic.LoadInt32(&calls))
}

func TestVerifyTokenRejected(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "no", http.StatusUnauthorized)
	}))
	defer srv.Close()

	v := NewVerifier(srv.URL, "wkey", time.Minute)
	_, err := v.Verify(context.Background(), "bad")
	require.Error(t, err)
}

func TestDeviceTokenAuthenticator_ReadsMetadata(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(AgentInfo{OrgID: "o", AgentID: "a"})
	}))
	defer srv.Close()

	v := NewVerifier(srv.URL, "wkey", time.Minute)
	authn := DeviceTokenAuthenticator{V: v}

	md := metadata.Pairs("x-agent-token", "tok")
	ctx := metadata.NewIncomingContext(context.Background(), md)
	require.NoError(t, authn.Verify(ctx))

	require.Error(t, authn.Verify(context.Background()))

	mdEmpty := metadata.Pairs("x-agent-token", "")
	ctxEmpty := metadata.NewIncomingContext(context.Background(), mdEmpty)
	require.Error(t, authn.Verify(ctxEmpty))
}
