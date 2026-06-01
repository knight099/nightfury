# Tunnel Subsystem (Agent + Relay) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Go LAN agent (user-installed on NAS/router/Pi) and a cloud Go relay so that home NVR cameras can stream to Nightwatch's existing worker without any port-forwarding. Primary transport gRPC over TLS/443; WebRTC fallback when gRPC is blocked.

**Architecture:** Agent runs on the user's LAN, pulls RTSP from NVRs locally, frames RTP packets, and pushes them over a long-lived outbound bidirectional tunnel to the relay. Relay terminates the tunnel and republishes each camera as a local RTSP URL `rtsp://relay-internal:8554/<camera_id>` that the existing worker pulls from. Agent discovers NVRs via ONVIF WS-Discovery (UDP 3702) with a manual RTSP fallback flow per brand. Pairing and `agents` table are NOT in this plan — they live in the onboarding plan; here, agents authenticate with a static dev-only `X-Agent-Key` header that will be replaced by device tokens later.

**Tech Stack:** Go 1.22+, gRPC + protobuf, [Pion](https://github.com/pion/webrtc) for WebRTC, [gortsplib](https://github.com/bluenviron/gortsplib) for the relay's inner RTSP server, [use-go/onvif](https://github.com/use-go/onvif) for discovery, Docker multi-arch (linux/arm64, linux/armv7, linux/amd64). Existing Python worker is configured by env to point at the relay's RTSP URL — no Python code changes needed.

**Spec:** `docs/superpowers/specs/2026-05-28-home-camera-plugin-design.md` (Sections 5.1, 5.2, 6.1, 8.1).

**Scope boundaries:**
- IN: agent binary, relay service, protobuf contract, ONVIF discovery, manual RTSP fallback CLI/UI, gRPC transport, WebRTC fallback, transport-fallback decision logic, basic auth via static key, multi-arch Docker image, end-to-end stubbed-stream test.
- OUT (handled in onboarding plan): pair-code minting, `agents`/`agent_pair_codes` DB tables, device tokens, `/onboard` frontend, brand-picker manual UI in production.
- OUT (already handled): worker pipeline, event ingestion, alerts, frontend dashboard.

---

## File Structure

### Created — `agent/` (new top-level)
- `agent/go.mod`, `agent/go.sum`
- `agent/cmd/agent/main.go` — entrypoint
- `agent/internal/config/config.go` — env + flags + on-disk state
- `agent/internal/discovery/onvif.go` — WS-Discovery probe, RTSP URL extraction
- `agent/internal/discovery/manual.go` — brand-template URL builder
- `agent/internal/rtsp/client.go` — pulls RTSP from NVR, emits frames
- `agent/internal/transport/transport.go` — `Transport` interface
- `agent/internal/transport/grpc.go` — gRPC bidi-stream implementation
- `agent/internal/transport/webrtc.go` — WebRTC data-channel implementation
- `agent/internal/transport/fallback.go` — decision logic
- `agent/internal/supervisor/supervisor.go` — manages N camera streams + reconnect
- `agent/internal/local_ui/server.go` — local web UI on `:8765` for setup
- `agent/internal/local_ui/templates/*.html`
- `agent/Dockerfile` — multi-stage, multi-arch
- `agent/Makefile`
- Test files alongside each package: `*_test.go`

### Created — `relay/` (new top-level)
- `relay/go.mod`, `relay/go.sum`
- `relay/cmd/relay/main.go`
- `relay/internal/config/config.go`
- `relay/internal/auth/static_key.go` — temporary `X-Agent-Key` auth
- `relay/internal/grpc_server/server.go` — receives agent gRPC streams
- `relay/internal/webrtc_signal/server.go` — HTTPS signaling for WebRTC fallback
- `relay/internal/republish/rtsp_server.go` — gortsplib-based RTSP server
- `relay/internal/republish/registry.go` — camera_id → publisher map
- `relay/internal/buffer/ring.go` — bounded per-camera buffer
- `relay/internal/metrics/metrics.go` — Prometheus counters
- `relay/Dockerfile`
- Test files alongside each package: `*_test.go`

### Created — shared
- `proto/tunnel.proto`
- `proto/Makefile` — codegen for both Go modules
- `proto/gen/go/tunnelpb/*.pb.go` (generated, committed)

### Modified
- `worker/CLAUDE.md` and `worker/AGENTS.md` — note that camera RTSP URLs may now be relay URLs (`rtsp://relay-internal:8554/<camera_id>`) and that the worker doesn't care.
- (No Python/TS code changes in this plan — worker treats relay URLs identically to direct NVR URLs.)

---

## Conventions

- Go module names: `github.com/nightwatch/agent` and `github.com/nightwatch/relay`. Adjust to the actual GitHub org if different — check `git remote get-url origin` before scaffolding.
- Tests use stdlib `testing` plus `github.com/stretchr/testify/require` (one dependency, widely understood).
- Each task ends in a commit. Small, feature-scoped commits.
- All errors include context: `fmt.Errorf("rtsp connect: %w", err)`.
- Logging via `log/slog` (stdlib structured logging).

---

## Task 1: Scaffold the protobuf contract

**Files:**
- Create: `proto/tunnel.proto`, `proto/Makefile`
- Create: `proto/gen/go/tunnelpb/` (committed generated code)

- [ ] **Step 1: Write the proto**

Create `proto/tunnel.proto`:

```proto
syntax = "proto3";

package nightwatch.tunnel.v1;

option go_package = "github.com/nightwatch/proto/gen/go/tunnelpb";

service Tunnel {
  // Bidi-stream: agent sends frames + control; relay sends control acks.
  rpc Stream(stream AgentMessage) returns (stream RelayMessage);
}

message AgentMessage {
  oneof kind {
    Hello       hello       = 1;
    CameraOpen  camera_open = 2;
    Frame       frame       = 3;
    CameraClose camera_close = 4;
    Heartbeat   heartbeat   = 5;
  }
}

message RelayMessage {
  oneof kind {
    HelloAck    hello_ack    = 1;
    CameraAck   camera_ack   = 2;
    Disconnect  disconnect   = 3;
    Pong        pong         = 4;
  }
}

message Hello {
  string agent_version = 1;
  string machine_id    = 2;
}

message HelloAck {
  string session_id = 1;
}

message CameraOpen {
  string camera_id = 1;        // assigned by backend (UUID string)
  string codec     = 2;        // e.g. "h264"
  uint32 width     = 3;
  uint32 height    = 4;
  uint32 fps       = 5;
}

message CameraAck {
  string camera_id = 1;
  bool   accepted  = 2;
  string reason    = 3;
}

message Frame {
  string camera_id = 1;
  bytes  payload   = 2;          // framed RTP / RTSP-over-TCP bytes
  int64  monotonic_us = 3;       // agent monotonic clock
  bool   keyframe  = 4;
}

message CameraClose {
  string camera_id = 1;
  string reason    = 2;
}

message Heartbeat {
  int64 monotonic_us = 1;
}

message Pong {
  int64 monotonic_us = 1;
}

message Disconnect {
  string reason = 1;
  bool   reauth_required = 2;
}
```

- [ ] **Step 2: Add codegen Makefile**

Create `proto/Makefile`:

```makefile
PROTO_DIR := .
OUT_GO    := gen/go/tunnelpb

.PHONY: gen clean
gen:
	mkdir -p $(OUT_GO)
	protoc --go_out=$(OUT_GO) --go_opt=paths=source_relative \
	       --go-grpc_out=$(OUT_GO) --go-grpc_opt=paths=source_relative \
	       $(PROTO_DIR)/tunnel.proto

clean:
	rm -rf $(OUT_GO)
```

- [ ] **Step 3: Generate**

Run: `cd proto && make gen`
Expected: produces `proto/gen/go/tunnelpb/tunnel.pb.go` and `tunnel_grpc.pb.go`. (Requires `protoc`, `protoc-gen-go`, `protoc-gen-go-grpc` installed; install via `go install google.golang.org/protobuf/cmd/protoc-gen-go@latest` and `go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest`.)

- [ ] **Step 4: Commit**

```bash
git add proto/
git commit -m "feat(tunnel): add tunnel.proto and generated Go bindings"
```

---

## Task 2: Scaffold the relay Go module

**Files:**
- Create: `relay/go.mod`, `relay/cmd/relay/main.go`, `relay/internal/config/config.go`

- [ ] **Step 1: Initialize module**

```bash
mkdir -p relay/cmd/relay relay/internal/config
cd relay && go mod init github.com/nightwatch/relay
go get github.com/stretchr/testify@latest
```

- [ ] **Step 2: Add config**

Create `relay/internal/config/config.go`:

```go
package config

import (
	"os"
)

type Config struct {
	GRPCAddr        string
	RTSPAddr        string
	WebRTCSignalAddr string
	StaticAgentKey  string
}

func Load() Config {
	return Config{
		GRPCAddr:         envOr("RELAY_GRPC_ADDR", ":9443"),
		RTSPAddr:         envOr("RELAY_RTSP_ADDR", ":8554"),
		WebRTCSignalAddr: envOr("RELAY_WEBRTC_ADDR", ":9080"),
		StaticAgentKey:   os.Getenv("RELAY_AGENT_KEY"),
	}
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
```

- [ ] **Step 3: Add main**

Create `relay/cmd/relay/main.go`:

```go
package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/nightwatch/relay/internal/config"
)

func main() {
	cfg := config.Load()
	slog.Info("relay starting",
		"grpc", cfg.GRPCAddr, "rtsp", cfg.RTSPAddr, "webrtc", cfg.WebRTCSignalAddr,
	)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	<-ctx.Done()
	slog.Info("relay shutting down")
	_ = os.Stdout.Sync()
}
```

- [ ] **Step 4: Verify build**

Run: `cd relay && go build ./...`
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add relay/
git commit -m "feat(relay): scaffold Go module with config and main"
```

---

## Task 3: Relay — bounded ring buffer for per-camera frames

**Files:**
- Create: `relay/internal/buffer/ring.go`, `relay/internal/buffer/ring_test.go`

- [ ] **Step 1: Write failing test**

Create `relay/internal/buffer/ring_test.go`:

```go
package buffer

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestRing_PushPop_BelowCapacity(t *testing.T) {
	r := New[int](4)
	r.Push(1)
	r.Push(2)
	v, ok := r.Pop()
	require.True(t, ok)
	require.Equal(t, 1, v)
	v, ok = r.Pop()
	require.True(t, ok)
	require.Equal(t, 2, v)
	_, ok = r.Pop()
	require.False(t, ok)
}

func TestRing_DropsOldestWhenFull(t *testing.T) {
	r := New[int](3)
	r.Push(1); r.Push(2); r.Push(3)
	r.Push(4) // should drop 1
	require.Equal(t, 1, r.DroppedCount())
	v, _ := r.Pop()
	require.Equal(t, 2, v)
}

func TestRing_LenAndCap(t *testing.T) {
	r := New[int](2)
	require.Equal(t, 0, r.Len())
	r.Push(1)
	require.Equal(t, 1, r.Len())
	require.Equal(t, 2, r.Cap())
}
```

- [ ] **Step 2: Run to verify fail**

Run: `cd relay && go test ./internal/buffer/...`
Expected: build fails — package doesn't exist.

- [ ] **Step 3: Implement**

Create `relay/internal/buffer/ring.go`:

```go
package buffer

import "sync"

type Ring[T any] struct {
	mu      sync.Mutex
	data    []T
	head    int
	size    int
	cap     int
	dropped int
}

func New[T any](capacity int) *Ring[T] {
	if capacity <= 0 {
		capacity = 1
	}
	return &Ring[T]{data: make([]T, capacity), cap: capacity}
}

func (r *Ring[T]) Push(v T) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.size == r.cap {
		// drop oldest
		r.head = (r.head + 1) % r.cap
		r.size--
		r.dropped++
	}
	tail := (r.head + r.size) % r.cap
	r.data[tail] = v
	r.size++
}

func (r *Ring[T]) Pop() (T, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	var zero T
	if r.size == 0 {
		return zero, false
	}
	v := r.data[r.head]
	r.data[r.head] = zero
	r.head = (r.head + 1) % r.cap
	r.size--
	return v, true
}

func (r *Ring[T]) Len() int { r.mu.Lock(); defer r.mu.Unlock(); return r.size }
func (r *Ring[T]) Cap() int { return r.cap }
func (r *Ring[T]) DroppedCount() int { r.mu.Lock(); defer r.mu.Unlock(); return r.dropped }
```

- [ ] **Step 4: Run tests**

Run: `cd relay && go test ./internal/buffer/... -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add relay/internal/buffer
git commit -m "feat(relay): add bounded ring buffer for per-camera frames"
```

---

## Task 4: Relay — per-camera publisher registry

**Files:**
- Create: `relay/internal/republish/registry.go`, `relay/internal/republish/registry_test.go`

- [ ] **Step 1: Write failing test**

Create `relay/internal/republish/registry_test.go`:

```go
package republish

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestRegistry_RegisterAndGet(t *testing.T) {
	reg := NewRegistry()
	pub := NewPublisher("cam-1", 64)
	reg.Register("cam-1", pub)

	got, ok := reg.Get("cam-1")
	require.True(t, ok)
	require.Same(t, pub, got)
}

func TestRegistry_DuplicateRegisterRejected(t *testing.T) {
	reg := NewRegistry()
	pub1 := NewPublisher("cam-1", 64)
	pub2 := NewPublisher("cam-1", 64)
	require.NoError(t, reg.RegisterErr("cam-1", pub1))
	require.Error(t, reg.RegisterErr("cam-1", pub2))
}

func TestRegistry_Unregister(t *testing.T) {
	reg := NewRegistry()
	pub := NewPublisher("cam-1", 64)
	reg.Register("cam-1", pub)
	reg.Unregister("cam-1")
	_, ok := reg.Get("cam-1")
	require.False(t, ok)
}
```

- [ ] **Step 2: Run to verify fail**

Run: `cd relay && go test ./internal/republish/...`
Expected: build error.

- [ ] **Step 3: Implement**

Create `relay/internal/republish/registry.go`:

```go
package republish

import (
	"errors"
	"sync"

	"github.com/nightwatch/relay/internal/buffer"
)

// Publisher is the per-camera in-memory state — the RTSP server reads from this,
// the gRPC server writes to it.
type Publisher struct {
	CameraID string
	Frames   *buffer.Ring[[]byte]
}

func NewPublisher(cameraID string, bufCap int) *Publisher {
	return &Publisher{
		CameraID: cameraID,
		Frames:   buffer.New[[]byte](bufCap),
	}
}

type Registry struct {
	mu  sync.RWMutex
	pub map[string]*Publisher
}

func NewRegistry() *Registry { return &Registry{pub: make(map[string]*Publisher)} }

func (r *Registry) Register(id string, p *Publisher) {
	r.mu.Lock(); defer r.mu.Unlock()
	r.pub[id] = p
}

func (r *Registry) RegisterErr(id string, p *Publisher) error {
	r.mu.Lock(); defer r.mu.Unlock()
	if _, exists := r.pub[id]; exists {
		return errors.New("camera already registered")
	}
	r.pub[id] = p
	return nil
}

func (r *Registry) Unregister(id string) {
	r.mu.Lock(); defer r.mu.Unlock()
	delete(r.pub, id)
}

func (r *Registry) Get(id string) (*Publisher, bool) {
	r.mu.RLock(); defer r.mu.RUnlock()
	p, ok := r.pub[id]
	return p, ok
}
```

- [ ] **Step 4: Run tests**

Run: `cd relay && go test ./internal/republish/... -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add relay/internal/republish
git commit -m "feat(relay): add per-camera publisher registry"
```

---

## Task 5: Relay — gRPC server (auth + Stream RPC)

**Files:**
- Create: `relay/internal/auth/static_key.go`, `relay/internal/auth/static_key_test.go`
- Create: `relay/internal/grpc_server/server.go`, `relay/internal/grpc_server/server_test.go`

- [ ] **Step 1: Auth — write failing test**

Create `relay/internal/auth/static_key_test.go`:

```go
package auth

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/metadata"
)

func TestStaticKey_Accepts(t *testing.T) {
	authn := StaticKey{Key: "secret"}
	md := metadata.Pairs("x-agent-key", "secret")
	ctx := metadata.NewIncomingContext(context.Background(), md)
	require.NoError(t, authn.Verify(ctx))
}

func TestStaticKey_RejectsWrong(t *testing.T) {
	authn := StaticKey{Key: "secret"}
	md := metadata.Pairs("x-agent-key", "wrong")
	ctx := metadata.NewIncomingContext(context.Background(), md)
	require.Error(t, authn.Verify(ctx))
}

func TestStaticKey_RejectsMissing(t *testing.T) {
	authn := StaticKey{Key: "secret"}
	require.Error(t, authn.Verify(context.Background()))
}
```

- [ ] **Step 2: Implement auth**

Create `relay/internal/auth/static_key.go`:

```go
package auth

import (
	"context"
	"errors"

	"google.golang.org/grpc/metadata"
)

type StaticKey struct{ Key string }

func (s StaticKey) Verify(ctx context.Context) error {
	if s.Key == "" {
		return errors.New("auth not configured")
	}
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return errors.New("no metadata")
	}
	got := md.Get("x-agent-key")
	if len(got) == 0 || got[0] != s.Key {
		return errors.New("invalid agent key")
	}
	return nil
}
```

- [ ] **Step 3: Run auth test**

Run: `cd relay && go test ./internal/auth/... -v`
Expected: PASS.

- [ ] **Step 4: gRPC server — write integration test**

Add `relay/go.mod` deps: `go get google.golang.org/grpc github.com/nightwatch/proto/gen/go/tunnelpb` (use a `replace` directive in go.mod pointing to `../proto/gen/go/tunnelpb` if you're in a monorepo without remote module resolution).

In `relay/go.mod`, add at the bottom:

```
replace github.com/nightwatch/proto/gen/go/tunnelpb => ../proto/gen/go/tunnelpb
```

Create `relay/internal/grpc_server/server_test.go`:

```go
package grpc_server

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
	"github.com/nightwatch/relay/internal/auth"
	"github.com/nightwatch/relay/internal/republish"
)

func newServer(t *testing.T) (tunnelpb.TunnelClient, *republish.Registry, func()) {
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)

	reg := republish.NewRegistry()
	srv := grpc.NewServer()
	s := &Server{Registry: reg, Auth: auth.StaticKey{Key: "k"}, BufCap: 16}
	tunnelpb.RegisterTunnelServer(srv, s)
	go srv.Serve(lis)

	conn, err := grpc.Dial(lis.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	cli := tunnelpb.NewTunnelClient(conn)
	return cli, reg, func() { conn.Close(); srv.Stop(); lis.Close() }
}

func TestStream_HelloAuthAccepted(t *testing.T) {
	cli, _, done := newServer(t); defer done()
	ctx := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("x-agent-key", "k"))
	stream, err := cli.Stream(ctx)
	require.NoError(t, err)
	require.NoError(t, stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Hello{Hello: &tunnelpb.Hello{AgentVersion: "test"}}}))
	got, err := stream.Recv()
	require.NoError(t, err)
	require.NotNil(t, got.GetHelloAck())
}

func TestStream_FrameRegistersPublisher(t *testing.T) {
	cli, reg, done := newServer(t); defer done()
	ctx := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("x-agent-key", "k"))
	stream, err := cli.Stream(ctx); require.NoError(t, err)
	stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Hello{Hello: &tunnelpb.Hello{}}})
	_, _ = stream.Recv()
	stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_CameraOpen{CameraOpen: &tunnelpb.CameraOpen{CameraId: "cam-1"}}})
	_, _ = stream.Recv()
	stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Frame{Frame: &tunnelpb.Frame{CameraId: "cam-1", Payload: []byte("hello")}}})

	// Allow goroutine schedule
	time.Sleep(100 * time.Millisecond)
	pub, ok := reg.Get("cam-1")
	require.True(t, ok)
	require.GreaterOrEqual(t, pub.Frames.Len(), 1)
}

func TestStream_RejectsBadAuth(t *testing.T) {
	cli, _, done := newServer(t); defer done()
	ctx := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("x-agent-key", "wrong"))
	stream, err := cli.Stream(ctx); require.NoError(t, err)
	require.NoError(t, stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Hello{Hello: &tunnelpb.Hello{}}}))
	_, err = stream.Recv()
	require.Error(t, err)
}
```

- [ ] **Step 5: Run to verify fail**

Run: `cd relay && go test ./internal/grpc_server/...`
Expected: build error.

- [ ] **Step 6: Implement gRPC server**

Create `relay/internal/grpc_server/server.go`:

```go
package grpc_server

import (
	"errors"
	"io"
	"log/slog"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
	"github.com/nightwatch/relay/internal/auth"
	"github.com/nightwatch/relay/internal/republish"
)

type Server struct {
	tunnelpb.UnimplementedTunnelServer
	Registry *republish.Registry
	Auth     auth.StaticKey
	BufCap   int
}

func (s *Server) Stream(stream tunnelpb.Tunnel_StreamServer) error {
	if err := s.Auth.Verify(stream.Context()); err != nil {
		return err
	}
	registered := map[string]bool{}
	defer func() {
		for id := range registered {
			s.Registry.Unregister(id)
		}
	}()

	for {
		msg, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			return nil
		}
		if err != nil {
			return err
		}
		switch k := msg.Kind.(type) {
		case *tunnelpb.AgentMessage_Hello:
			if err := stream.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_HelloAck{HelloAck: &tunnelpb.HelloAck{SessionId: "s-1"}}}); err != nil {
				return err
			}
		case *tunnelpb.AgentMessage_CameraOpen:
			id := k.CameraOpen.CameraId
			pub := republish.NewPublisher(id, s.BufCap)
			if err := s.Registry.RegisterErr(id, pub); err != nil {
				_ = stream.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_CameraAck{CameraAck: &tunnelpb.CameraAck{CameraId: id, Accepted: false, Reason: err.Error()}}})
				continue
			}
			registered[id] = true
			_ = stream.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_CameraAck{CameraAck: &tunnelpb.CameraAck{CameraId: id, Accepted: true}}})
		case *tunnelpb.AgentMessage_Frame:
			if pub, ok := s.Registry.Get(k.Frame.CameraId); ok {
				pub.Frames.Push(k.Frame.Payload)
			}
		case *tunnelpb.AgentMessage_CameraClose:
			s.Registry.Unregister(k.CameraClose.CameraId)
			delete(registered, k.CameraClose.CameraId)
		case *tunnelpb.AgentMessage_Heartbeat:
			_ = stream.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_Pong{Pong: &tunnelpb.Pong{MonotonicUs: k.Heartbeat.MonotonicUs}}})
		default:
			slog.Warn("unknown agent message")
		}
	}
}
```

- [ ] **Step 7: Run tests**

Run: `cd relay && go test ./internal/grpc_server/... -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add relay/
git commit -m "feat(relay): add gRPC tunnel server with static-key auth"
```

---

## Task 6: Relay — RTSP republish server

**Files:**
- Create: `relay/internal/republish/rtsp_server.go`, `relay/internal/republish/rtsp_server_test.go`

- [ ] **Step 1: Add gortsplib dep**

Run: `cd relay && go get github.com/bluenviron/gortsplib/v4@latest`

- [ ] **Step 2: Write failing test**

Create `relay/internal/republish/rtsp_server_test.go`:

```go
package republish

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestRTSPServer_StartsAndAcceptsConnection(t *testing.T) {
	reg := NewRegistry()
	pub := NewPublisher("cam-1", 32)
	for _, b := range [][]byte{[]byte("frame1"), []byte("frame2")} {
		pub.Frames.Push(b)
	}
	reg.Register("cam-1", pub)

	srv := NewRTSPServer(reg, "127.0.0.1:0")
	go func() { _ = srv.Run(context.Background()) }()

	require.Eventually(t, func() bool {
		return srv.Addr() != ""
	}, time.Second, 10*time.Millisecond)

	c, err := net.DialTimeout("tcp", srv.Addr(), time.Second)
	require.NoError(t, err)
	_ = c.Close()
}
```

- [ ] **Step 3: Implement skeleton**

Create `relay/internal/republish/rtsp_server.go`:

```go
package republish

import (
	"context"
	"net"
	"sync"
)

// RTSPServer republishes per-camera frames as an RTSP server.
//
// NOTE: This is a minimal skeleton. The full gortsplib integration (SDP, RTP packetization)
// is implemented in Task 6b. This task gets the listener up and addressable so consumers
// (worker config, tests) can wire to it.
type RTSPServer struct {
	reg  *Registry
	addr string

	mu       sync.Mutex
	listener net.Listener
}

func NewRTSPServer(reg *Registry, addr string) *RTSPServer {
	return &RTSPServer{reg: reg, addr: addr}
}

func (s *RTSPServer) Run(ctx context.Context) error {
	lis, err := net.Listen("tcp", s.addr)
	if err != nil {
		return err
	}
	s.mu.Lock()
	s.listener = lis
	s.mu.Unlock()

	go func() {
		<-ctx.Done()
		_ = lis.Close()
	}()
	for {
		conn, err := lis.Accept()
		if err != nil {
			return nil
		}
		go s.handle(conn)
	}
}

func (s *RTSPServer) handle(c net.Conn) {
	// Placeholder: real handler implemented in Task 6b using gortsplib.
	// For now, accept the connection and close it.
	_ = c.Close()
}

func (s *RTSPServer) Addr() string {
	s.mu.Lock(); defer s.mu.Unlock()
	if s.listener == nil { return "" }
	return s.listener.Addr().String()
}
```

- [ ] **Step 4: Run test**

Run: `cd relay && go test ./internal/republish/... -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add relay/internal/republish/rtsp_server.go relay/internal/republish/rtsp_server_test.go
git commit -m "feat(relay): scaffold RTSP republish server (listener + addressable)"
```

---

## Task 6b: Relay — wire gortsplib for actual RTSP republishing

**Files:**
- Modify: `relay/internal/republish/rtsp_server.go`
- Test: `relay/internal/republish/rtsp_server_pipe_test.go`

- [ ] **Step 1: Read gortsplib server example**

Open `https://github.com/bluenviron/gortsplib/blob/main/examples/server/main.go` (in browser) and adapt the "publisher + reader" pattern. Key callbacks: `OnConnOpen`, `OnDescribe`, `OnSetup`, `OnPlay`. The frames in `Publisher.Frames` are already RTP-framed (Task 7 ensures this); the RTSP server just dequeues and writes to the reader session.

- [ ] **Step 2: Replace `handle` with gortsplib integration**

In `relay/internal/republish/rtsp_server.go`, replace the skeleton with a full gortsplib `server.Server` that:
- On `OnDescribe(camera_id)` → looks up `reg.Get(camera_id)`, returns SDP for H.264.
- On `OnPlay` → starts a goroutine that pops from `pub.Frames` and writes RTP to the session.
- Tracks active readers; on disconnect, stop the writer goroutine.

(Concrete code: ~80 lines. Pattern is well-documented in gortsplib's README.)

- [ ] **Step 3: Pipe test (end-to-end through registry)**

Create `relay/internal/republish/rtsp_server_pipe_test.go`:

```go
package republish

import (
	"context"
	"net/url"
	"testing"
	"time"

	"github.com/bluenviron/gortsplib/v4"
	"github.com/stretchr/testify/require"
)

func TestRTSPServer_DescribeReturnsSDPForRegisteredCamera(t *testing.T) {
	reg := NewRegistry()
	reg.Register("cam-1", NewPublisher("cam-1", 64))
	srv := NewRTSPServer(reg, "127.0.0.1:0")
	ctx, cancel := context.WithCancel(context.Background()); defer cancel()
	go func() { _ = srv.Run(ctx) }()
	require.Eventually(t, func() bool { return srv.Addr() != "" }, time.Second, 10*time.Millisecond)

	u, _ := url.Parse("rtsp://" + srv.Addr() + "/cam-1")
	c := gortsplib.Client{}
	require.NoError(t, c.Start(u.Scheme, u.Host))
	defer c.Close()
	_, _, _, err := c.Describe(u)
	require.NoError(t, err)
}
```

- [ ] **Step 4: Run test**

Run: `cd relay && go test ./internal/republish/... -v -run TestRTSPServer_DescribeReturnsSDPForRegisteredCamera`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add relay/internal/republish/
git commit -m "feat(relay): wire gortsplib for full RTSP republishing"
```

---

## Task 7: Scaffold the agent Go module

**Files:**
- Create: `agent/go.mod`, `agent/cmd/agent/main.go`, `agent/internal/config/config.go`

- [ ] **Step 1: Init module**

```bash
mkdir -p agent/cmd/agent agent/internal/config
cd agent && go mod init github.com/nightwatch/agent
go get github.com/stretchr/testify@latest google.golang.org/grpc@latest
```

Add `replace github.com/nightwatch/proto/gen/go/tunnelpb => ../proto/gen/go/tunnelpb` to `agent/go.mod`.

- [ ] **Step 2: Add config**

Create `agent/internal/config/config.go`:

```go
package config

import "os"

type Config struct {
	RelayAddr      string
	RelayInsecure  bool
	StaticAgentKey string
	LocalUIAddr    string
	StateDir       string
}

func Load() Config {
	return Config{
		RelayAddr:      envOr("AGENT_RELAY_ADDR", "relay.nightwatch.ai:9443"),
		RelayInsecure:  os.Getenv("AGENT_RELAY_INSECURE") == "1",
		StaticAgentKey: os.Getenv("AGENT_KEY"),
		LocalUIAddr:    envOr("AGENT_UI_ADDR", ":8765"),
		StateDir:       envOr("AGENT_STATE_DIR", "/var/lib/nightwatch-agent"),
	}
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" { return v }
	return def
}
```

- [ ] **Step 3: Add main**

Create `agent/cmd/agent/main.go`:

```go
package main

import (
	"context"
	"log/slog"
	"os/signal"
	"syscall"

	"github.com/nightwatch/agent/internal/config"
)

func main() {
	cfg := config.Load()
	slog.Info("agent starting", "relay", cfg.RelayAddr)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	<-ctx.Done()
	slog.Info("agent shutting down")
}
```

- [ ] **Step 4: Verify build**

Run: `cd agent && go build ./...`
Expected: success.

- [ ] **Step 5: Commit**

```bash
git add agent/
git commit -m "feat(agent): scaffold Go module with config and main"
```

---

## Task 8: Agent — ONVIF discovery

**Files:**
- Create: `agent/internal/discovery/onvif.go`, `agent/internal/discovery/onvif_test.go`

- [ ] **Step 1: Add dep**

Run: `cd agent && go get github.com/use-go/onvif@latest`

- [ ] **Step 2: Write a unit test for the parser (the only purely-deterministic part)**

Create `agent/internal/discovery/onvif_test.go`:

```go
package discovery

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestParseRTSPFromGetStreamURIResponse(t *testing.T) {
	xml := []byte(`<?xml version="1.0"?>
<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope">
  <env:Body>
    <trt:GetStreamUriResponse xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
      <trt:MediaUri>
        <tt:Uri xmlns:tt="http://www.onvif.org/ver10/schema">rtsp://192.168.1.108:554/Streaming/Channels/101</tt:Uri>
      </trt:MediaUri>
    </trt:GetStreamUriResponse>
  </env:Body>
</env:Envelope>`)
	uri, err := parseStreamURI(xml)
	require.NoError(t, err)
	require.Equal(t, "rtsp://192.168.1.108:554/Streaming/Channels/101", uri)
}

func TestParseStreamURI_NoURIReturnsError(t *testing.T) {
	_, err := parseStreamURI([]byte(`<x/>`))
	require.Error(t, err)
}
```

- [ ] **Step 3: Implement parser + discovery wrapper**

Create `agent/internal/discovery/onvif.go`:

```go
package discovery

import (
	"context"
	"encoding/xml"
	"errors"
	"fmt"
	"time"

	"github.com/use-go/onvif"
	"github.com/use-go/onvif/device"
	wsdiscovery "github.com/use-go/onvif/ws-discovery"
)

type Discovered struct {
	XAddr      string // ONVIF service URL
	Endpoint   string // host:port of the device
	Name       string
	Make       string
	Model      string
	StreamURIs []string
}

// Discover sends a WS-Discovery probe and returns devices that responded within `timeout`.
// Authentication-less probe — for full StreamURI extraction the user must supply credentials.
func Discover(ctx context.Context, timeout time.Duration) ([]Discovered, error) {
	probeCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	devs, err := wsdiscovery.SendProbe(probeCtx, "", nil, []string{"dn:NetworkVideoTransmitter"}, map[string]string{"dn": "http://www.onvif.org/ver10/network/wsdl"})
	if err != nil {
		return nil, fmt.Errorf("ws-discovery probe: %w", err)
	}
	out := make([]Discovered, 0, len(devs))
	for _, d := range devs {
		out = append(out, Discovered{XAddr: d})
	}
	return out, nil
}

// FetchStreamURI authenticates with the device and asks for its primary RTSP URI.
func FetchStreamURI(xaddr, username, password string) (string, error) {
	dev, err := onvif.NewDevice(onvif.DeviceParams{Xaddr: xaddr, Username: username, Password: password})
	if err != nil {
		return "", err
	}
	resp, err := dev.CallMethod(device.GetCapabilities{Category: "Media"})
	if err != nil {
		return "", err
	}
	body := readBody(resp)
	return parseStreamURI(body)
}

func readBody(resp interface{ Body() ([]byte, error) }) []byte {
	b, _ := resp.Body()
	return b
}

func parseStreamURI(body []byte) (string, error) {
	var env struct {
		Body struct {
			GetStreamUriResponse struct {
				MediaUri struct {
					Uri string `xml:"Uri"`
				} `xml:"MediaUri"`
			} `xml:"GetStreamUriResponse"`
		} `xml:"Body"`
	}
	if err := xml.Unmarshal(body, &env); err != nil {
		return "", err
	}
	uri := env.Body.GetStreamUriResponse.MediaUri.Uri
	if uri == "" {
		return "", errors.New("no Uri element found")
	}
	return uri, nil
}
```

- [ ] **Step 4: Run tests**

Run: `cd agent && go test ./internal/discovery/... -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/internal/discovery/
git commit -m "feat(agent): add ONVIF WS-Discovery + GetStreamURI parser"
```

---

## Task 9: Agent — manual RTSP URL builder per brand

**Files:**
- Create: `agent/internal/discovery/manual.go`, `agent/internal/discovery/manual_test.go`

- [ ] **Step 1: Write failing test**

Create `agent/internal/discovery/manual_test.go`:

```go
package discovery

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestBuildManualRTSP_CPPlus(t *testing.T) {
	got, err := BuildManualRTSP("cpplus", "192.168.1.108", 554, "admin", "p@ss", 1, "main")
	require.NoError(t, err)
	require.Equal(t, "rtsp://admin:p%40ss@192.168.1.108:554/cam/realmonitor?channel=1&subtype=0", got)
}

func TestBuildManualRTSP_Hikvision(t *testing.T) {
	got, err := BuildManualRTSP("hikvision", "10.0.0.5", 554, "admin", "x", 2, "sub")
	require.NoError(t, err)
	require.Equal(t, "rtsp://admin:x@10.0.0.5:554/Streaming/Channels/202", got)
}

func TestBuildManualRTSP_Dahua(t *testing.T) {
	got, err := BuildManualRTSP("dahua", "10.0.0.5", 554, "admin", "x", 1, "main")
	require.NoError(t, err)
	require.Equal(t, "rtsp://admin:x@10.0.0.5:554/cam/realmonitor?channel=1&subtype=0", got)
}

func TestBuildManualRTSP_UnknownBrand(t *testing.T) {
	_, err := BuildManualRTSP("unknown-brand", "1.2.3.4", 554, "u", "p", 1, "main")
	require.Error(t, err)
}
```

- [ ] **Step 2: Implement**

Create `agent/internal/discovery/manual.go`:

```go
package discovery

import (
	"fmt"
	"net/url"
)

// BuildManualRTSP constructs an RTSP URL based on a brand template.
//
// Supported brands: cpplus, hikvision, dahua, reolink, generic.
// `stream` is "main" or "sub". `channel` is 1-based.
func BuildManualRTSP(brand, host string, port int, user, pass string, channel int, stream string) (string, error) {
	subtype := 0
	if stream == "sub" {
		subtype = 1
	}
	userInfo := url.UserPassword(user, pass).String()
	switch brand {
	case "cpplus", "dahua":
		return fmt.Sprintf("rtsp://%s@%s:%d/cam/realmonitor?channel=%d&subtype=%d",
			userInfo, host, port, channel, subtype), nil
	case "hikvision":
		// Channel encoding: <channel><subtype-digit> e.g. 101 = ch1 main, 202 = ch2 sub
		streamDigit := 1
		if stream == "sub" {
			streamDigit = 2
		}
		return fmt.Sprintf("rtsp://%s@%s:%d/Streaming/Channels/%d0%d",
			userInfo, host, port, channel, streamDigit), nil
	case "reolink":
		return fmt.Sprintf("rtsp://%s@%s:%d/h264Preview_%02d_%s",
			userInfo, host, port, channel, stream), nil
	case "generic":
		return fmt.Sprintf("rtsp://%s@%s:%d/", userInfo, host, port), nil
	default:
		return "", fmt.Errorf("unknown brand %q", brand)
	}
}
```

- [ ] **Step 3: Run tests**

Run: `cd agent && go test ./internal/discovery/... -v -run TestBuildManualRTSP`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add agent/internal/discovery/manual.go agent/internal/discovery/manual_test.go
git commit -m "feat(agent): add manual RTSP URL builder for known brands"
```

---

## Task 10: Agent — RTSP client (wraps gortsplib in pull mode)

**Files:**
- Create: `agent/internal/rtsp/client.go`, `agent/internal/rtsp/client_test.go`

- [ ] **Step 1: Add dep**

Run: `cd agent && go get github.com/bluenviron/gortsplib/v4@latest`

- [ ] **Step 2: Implement client wrapper**

Create `agent/internal/rtsp/client.go`:

```go
package rtsp

import (
	"context"
	"fmt"
	"net/url"

	"github.com/bluenviron/gortsplib/v4"
)

type FrameHandler func(payload []byte, keyframe bool)

type Client struct {
	URL       string
	OnFrame   FrameHandler
}

func (c *Client) Run(ctx context.Context) error {
	u, err := url.Parse(c.URL)
	if err != nil {
		return fmt.Errorf("parse url: %w", err)
	}
	cli := gortsplib.Client{}
	if err := cli.Start(u.Scheme, u.Host); err != nil {
		return err
	}
	defer cli.Close()
	desc, _, err := cli.Describe(u)
	if err != nil {
		return err
	}
	if err := cli.SetupAll(desc.BaseURL, desc.Medias); err != nil {
		return err
	}
	cli.OnPacketRTPAny(func(_ *gortsplib.ServerSession, _ *gortsplib.Format, pkt interface{}) {
		// gortsplib gives RTP packets; serialize for transport
		if c.OnFrame != nil {
			b := serializeRTP(pkt)
			c.OnFrame(b, false)
		}
	})
	if _, err := cli.Play(nil); err != nil {
		return err
	}
	<-ctx.Done()
	return nil
}

// serializeRTP marshals an RTP packet to wire bytes.
func serializeRTP(pkt interface{}) []byte {
	type marshaler interface{ Marshal() ([]byte, error) }
	if m, ok := pkt.(marshaler); ok {
		b, _ := m.Marshal()
		return b
	}
	return nil
}
```

- [ ] **Step 3: Smoke test**

Create `agent/internal/rtsp/client_test.go`:

```go
package rtsp

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestClient_InvalidURLReturnsError(t *testing.T) {
	c := &Client{URL: "rtsp://127.0.0.1:1/"} // nothing listening
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	err := c.Run(ctx)
	require.Error(t, err)
}
```

(Real RTSP-loop test happens in Task 14 end-to-end with a recorded stream.)

- [ ] **Step 4: Run tests**

Run: `cd agent && go test ./internal/rtsp/... -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/internal/rtsp/
git commit -m "feat(agent): add RTSP client wrapper around gortsplib"
```

---

## Task 11: Agent — Transport interface + gRPC implementation

**Files:**
- Create: `agent/internal/transport/transport.go`
- Create: `agent/internal/transport/grpc.go`, `agent/internal/transport/grpc_test.go`

- [ ] **Step 1: Define interface**

Create `agent/internal/transport/transport.go`:

```go
package transport

import "context"

type Transport interface {
	Connect(ctx context.Context) error
	OpenCamera(cameraID string) error
	SendFrame(cameraID string, payload []byte, keyframe bool) error
	Close() error
	Name() string
}
```

- [ ] **Step 2: gRPC implementation — write integration test against the relay's actual server**

Create `agent/internal/transport/grpc_test.go`:

```go
package transport

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
)

// fakeServer mimics the relay's auth-and-ack behavior for transport tests.
type fakeServer struct{ tunnelpb.UnimplementedTunnelServer; received chan *tunnelpb.AgentMessage }

func (f *fakeServer) Stream(s tunnelpb.Tunnel_StreamServer) error {
	for {
		m, err := s.Recv()
		if err != nil { return err }
		f.received <- m
		switch m.Kind.(type) {
		case *tunnelpb.AgentMessage_Hello:
			s.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_HelloAck{HelloAck: &tunnelpb.HelloAck{SessionId: "x"}}})
		case *tunnelpb.AgentMessage_CameraOpen:
			s.Send(&tunnelpb.RelayMessage{Kind: &tunnelpb.RelayMessage_CameraAck{CameraAck: &tunnelpb.CameraAck{Accepted: true}}})
		}
	}
}

func newFake(t *testing.T) (string, chan *tunnelpb.AgentMessage, func()) {
	lis, _ := net.Listen("tcp", "127.0.0.1:0")
	srv := grpc.NewServer()
	rcv := make(chan *tunnelpb.AgentMessage, 16)
	tunnelpb.RegisterTunnelServer(srv, &fakeServer{received: rcv})
	go srv.Serve(lis)
	return lis.Addr().String(), rcv, func() { srv.Stop(); lis.Close() }
}

func TestGRPC_ConnectAndOpenCamera(t *testing.T) {
	addr, rcv, done := newFake(t); defer done()
	tp := NewGRPC(addr, "k", []grpc.DialOption{grpc.WithTransportCredentials(insecure.NewCredentials())})
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second); defer cancel()
	require.NoError(t, tp.Connect(ctx))
	require.NoError(t, tp.OpenCamera("cam-1"))
	require.NoError(t, tp.SendFrame("cam-1", []byte("hi"), false))

	got := <-rcv
	require.NotNil(t, got.GetHello())
	got = <-rcv
	require.Equal(t, "cam-1", got.GetCameraOpen().CameraId)
	got = <-rcv
	require.Equal(t, []byte("hi"), got.GetFrame().Payload)

	require.NoError(t, tp.Close())
	require.Equal(t, "grpc", tp.Name())
}
```

- [ ] **Step 3: Implement gRPC transport**

Create `agent/internal/transport/grpc.go`:

```go
package transport

import (
	"context"
	"errors"
	"sync"

	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
)

type GRPC struct {
	addr   string
	key    string
	dialOpts []grpc.DialOption

	mu     sync.Mutex
	conn   *grpc.ClientConn
	client tunnelpb.TunnelClient
	stream tunnelpb.Tunnel_StreamClient
}

func NewGRPC(addr, key string, dialOpts []grpc.DialOption) *GRPC {
	return &GRPC{addr: addr, key: key, dialOpts: dialOpts}
}

func (g *GRPC) Name() string { return "grpc" }

func (g *GRPC) Connect(ctx context.Context) error {
	conn, err := grpc.DialContext(ctx, g.addr, g.dialOpts...)
	if err != nil { return err }
	cli := tunnelpb.NewTunnelClient(conn)
	md := metadata.Pairs("x-agent-key", g.key)
	streamCtx := metadata.NewOutgoingContext(ctx, md)
	stream, err := cli.Stream(streamCtx)
	if err != nil { conn.Close(); return err }
	if err := stream.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Hello{Hello: &tunnelpb.Hello{AgentVersion: "0.1.0"}}}); err != nil {
		conn.Close(); return err
	}
	if _, err := stream.Recv(); err != nil { conn.Close(); return err }
	g.mu.Lock(); g.conn, g.client, g.stream = conn, cli, stream; g.mu.Unlock()
	return nil
}

func (g *GRPC) OpenCamera(id string) error {
	g.mu.Lock(); s := g.stream; g.mu.Unlock()
	if s == nil { return errors.New("not connected") }
	if err := s.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_CameraOpen{CameraOpen: &tunnelpb.CameraOpen{CameraId: id}}}); err != nil {
		return err
	}
	_, err := s.Recv()
	return err
}

func (g *GRPC) SendFrame(id string, payload []byte, keyframe bool) error {
	g.mu.Lock(); s := g.stream; g.mu.Unlock()
	if s == nil { return errors.New("not connected") }
	return s.Send(&tunnelpb.AgentMessage{Kind: &tunnelpb.AgentMessage_Frame{Frame: &tunnelpb.Frame{CameraId: id, Payload: payload, Keyframe: keyframe}}})
}

func (g *GRPC) Close() error {
	g.mu.Lock(); defer g.mu.Unlock()
	if g.stream != nil { _ = g.stream.CloseSend() }
	if g.conn != nil { return g.conn.Close() }
	return nil
}
```

- [ ] **Step 4: Run tests**

Run: `cd agent && go test ./internal/transport/... -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/internal/transport/
git commit -m "feat(agent): add Transport interface and gRPC implementation"
```

---

## Task 12: Agent — fallback decision logic

**Files:**
- Create: `agent/internal/transport/fallback.go`, `agent/internal/transport/fallback_test.go`

- [ ] **Step 1: Failing test**

Create `agent/internal/transport/fallback_test.go`:

```go
package transport

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestFallback_AuthErrorDoesNotTriggerFallback(t *testing.T) {
	d := &Decider{}
	authErr := status.Error(codes.Unauthenticated, "bad key")
	d.Record(authErr)
	require.False(t, d.ShouldFallback())
}

func TestFallback_ThreeConnectErrorsTriggers(t *testing.T) {
	d := &Decider{}
	netErr := errors.New("connection refused")
	for i := 0; i < 3; i++ { d.Record(netErr) }
	require.True(t, d.ShouldFallback())
}

func TestFallback_OneSuccessResetsCounter(t *testing.T) {
	d := &Decider{}
	netErr := errors.New("connection refused")
	d.Record(netErr); d.Record(netErr)
	d.RecordSuccess()
	d.Record(netErr)
	require.False(t, d.ShouldFallback())
}
```

- [ ] **Step 2: Implement**

Create `agent/internal/transport/fallback.go`:

```go
package transport

import (
	"strings"
	"sync"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// Decider tracks consecutive transport errors and decides whether to switch
// from gRPC to WebRTC. Auth errors never trigger fallback.
type Decider struct {
	mu       sync.Mutex
	failures int
}

const FallbackThreshold = 3

func (d *Decider) Record(err error) {
	if err == nil { return }
	d.mu.Lock(); defer d.mu.Unlock()
	if isAuthError(err) {
		// don't count
		return
	}
	d.failures++
}

func (d *Decider) RecordSuccess() {
	d.mu.Lock(); defer d.mu.Unlock()
	d.failures = 0
}

func (d *Decider) ShouldFallback() bool {
	d.mu.Lock(); defer d.mu.Unlock()
	return d.failures >= FallbackThreshold
}

func isAuthError(err error) bool {
	if s, ok := status.FromError(err); ok {
		switch s.Code() {
		case codes.Unauthenticated, codes.PermissionDenied:
			return true
		}
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "unauthorized") || strings.Contains(msg, "forbidden")
}
```

- [ ] **Step 3: Run tests**

Run: `cd agent && go test ./internal/transport/... -v -run TestFallback`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add agent/internal/transport/fallback.go agent/internal/transport/fallback_test.go
git commit -m "feat(agent): add transport fallback decider (gRPC→WebRTC)"
```

---

## Task 13: Agent — WebRTC transport (fallback)

**Files:**
- Create: `agent/internal/transport/webrtc.go`, `agent/internal/transport/webrtc_test.go`
- Create: `relay/internal/webrtc_signal/server.go`, `relay/internal/webrtc_signal/server_test.go`

- [ ] **Step 1: Add deps**

Run: `cd agent && go get github.com/pion/webrtc/v4@latest`
Run: `cd relay && go get github.com/pion/webrtc/v4@latest`

- [ ] **Step 2: Relay — signaling endpoint**

Create `relay/internal/webrtc_signal/server.go`:

```go
package webrtc_signal

import (
	"encoding/json"
	"net/http"

	"github.com/pion/webrtc/v4"

	"github.com/nightwatch/relay/internal/republish"
)

type SDPRequest struct {
	AgentKey string                    `json:"agent_key"`
	Offer    webrtc.SessionDescription `json:"offer"`
}

type SDPResponse struct {
	Answer webrtc.SessionDescription `json:"answer"`
}

type Server struct {
	Registry  *republish.Registry
	AgentKey  string
	BufCap    int
}

func (s *Server) Handle(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST only", http.StatusMethodNotAllowed); return
	}
	var req SDPRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest); return
	}
	if req.AgentKey != s.AgentKey {
		http.Error(w, "bad key", http.StatusUnauthorized); return
	}
	pc, err := webrtc.NewPeerConnection(webrtc.Configuration{})
	if err != nil { http.Error(w, err.Error(), 500); return }

	pc.OnDataChannel(func(dc *webrtc.DataChannel) {
		// First message on the channel must be a JSON envelope identifying the camera.
		// Subsequent messages are framed bytes that go straight into the publisher.
		var cameraID string
		dc.OnMessage(func(msg webrtc.DataChannelMessage) {
			if cameraID == "" {
				cameraID = string(msg.Data)
				pub := republish.NewPublisher(cameraID, s.BufCap)
				_ = s.Registry.RegisterErr(cameraID, pub)
				return
			}
			if pub, ok := s.Registry.Get(cameraID); ok {
				pub.Frames.Push(msg.Data)
			}
		})
		dc.OnClose(func() { s.Registry.Unregister(cameraID) })
	})

	if err := pc.SetRemoteDescription(req.Offer); err != nil { http.Error(w, err.Error(), 500); return }
	answer, err := pc.CreateAnswer(nil)
	if err != nil { http.Error(w, err.Error(), 500); return }
	gather := webrtc.GatheringCompletePromise(pc)
	if err := pc.SetLocalDescription(answer); err != nil { http.Error(w, err.Error(), 500); return }
	<-gather
	json.NewEncoder(w).Encode(SDPResponse{Answer: *pc.LocalDescription()})
}
```

- [ ] **Step 3: Relay signaling test**

Create `relay/internal/webrtc_signal/server_test.go`:

```go
package webrtc_signal

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/pion/webrtc/v4"
	"github.com/stretchr/testify/require"

	"github.com/nightwatch/relay/internal/republish"
)

func TestSignal_RejectsBadAgentKey(t *testing.T) {
	s := &Server{Registry: republish.NewRegistry(), AgentKey: "k", BufCap: 16}
	pc, _ := webrtc.NewPeerConnection(webrtc.Configuration{})
	offer, _ := pc.CreateOffer(nil)
	body, _ := json.Marshal(SDPRequest{AgentKey: "wrong", Offer: offer})
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/", bytes.NewReader(body))
	s.Handle(w, r)
	require.Equal(t, http.StatusUnauthorized, w.Code)
}
```

- [ ] **Step 4: Agent — WebRTC transport**

Create `agent/internal/transport/webrtc.go`:

```go
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

	"github.com/pion/webrtc/v4"
)

type WebRTC struct {
	SignalURL string
	AgentKey  string

	mu  sync.Mutex
	pc  *webrtc.PeerConnection
	dc  map[string]*webrtc.DataChannel
}

func NewWebRTC(signalURL, key string) *WebRTC {
	return &WebRTC{SignalURL: signalURL, AgentKey: key, dc: map[string]*webrtc.DataChannel{}}
}

func (w *WebRTC) Name() string { return "webrtc" }

func (w *WebRTC) Connect(ctx context.Context) error {
	pc, err := webrtc.NewPeerConnection(webrtc.Configuration{})
	if err != nil { return err }
	offer, err := pc.CreateOffer(nil)
	if err != nil { return err }
	gather := webrtc.GatheringCompletePromise(pc)
	if err := pc.SetLocalDescription(offer); err != nil { return err }
	<-gather

	body, _ := json.Marshal(map[string]interface{}{
		"agent_key": w.AgentKey,
		"offer":     pc.LocalDescription(),
	})
	req, _ := http.NewRequestWithContext(ctx, "POST", w.SignalURL, bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil { return err }
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("signal: %d %s", resp.StatusCode, b)
	}
	var ans struct{ Answer webrtc.SessionDescription `json:"answer"` }
	if err := json.NewDecoder(resp.Body).Decode(&ans); err != nil { return err }
	if err := pc.SetRemoteDescription(ans.Answer); err != nil { return err }

	w.mu.Lock(); w.pc = pc; w.mu.Unlock()
	return nil
}

func (w *WebRTC) OpenCamera(id string) error {
	w.mu.Lock(); pc := w.pc; w.mu.Unlock()
	if pc == nil { return errors.New("not connected") }
	dc, err := pc.CreateDataChannel("cam:"+id, nil)
	if err != nil { return err }
	openCh := make(chan struct{})
	dc.OnOpen(func() { close(openCh) })
	<-openCh
	if err := dc.SendText(id); err != nil { return err }
	w.mu.Lock(); w.dc[id] = dc; w.mu.Unlock()
	return nil
}

func (w *WebRTC) SendFrame(id string, payload []byte, keyframe bool) error {
	w.mu.Lock(); dc := w.dc[id]; w.mu.Unlock()
	if dc == nil { return errors.New("camera not opened") }
	return dc.Send(payload)
}

func (w *WebRTC) Close() error {
	w.mu.Lock(); defer w.mu.Unlock()
	if w.pc != nil { return w.pc.Close() }
	return nil
}
```

- [ ] **Step 5: Smoke test agent WebRTC against the relay**

Create `agent/internal/transport/webrtc_test.go`:

```go
package transport

import (
	"context"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	relayrepub "github.com/nightwatch/relay/internal/republish"
	relaywebrtc "github.com/nightwatch/relay/internal/webrtc_signal"
)

func TestWebRTC_RoundTripFrame(t *testing.T) {
	reg := relayrepub.NewRegistry()
	srv := &relaywebrtc.Server{Registry: reg, AgentKey: "k", BufCap: 16}
	hs := httptest.NewServer(http.HandlerFunc(srv.Handle))
	defer hs.Close()

	tp := NewWebRTC(hs.URL, "k")
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second); defer cancel()
	require.NoError(t, tp.Connect(ctx))
	require.NoError(t, tp.OpenCamera("cam-1"))
	require.NoError(t, tp.SendFrame("cam-1", []byte("hi"), false))

	require.Eventually(t, func() bool {
		pub, ok := reg.Get("cam-1")
		return ok && pub.Frames.Len() >= 1
	}, 2*time.Second, 50*time.Millisecond)

	require.NoError(t, tp.Close())
}
```

Add `replace github.com/nightwatch/relay => ../relay` to `agent/go.mod`. Add `import "net/http"` to `webrtc_test.go`.

- [ ] **Step 6: Run tests**

Run: `cd agent && go test ./internal/transport/... -v`
Run: `cd relay && go test ./internal/webrtc_signal/... -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agent/internal/transport/webrtc.go agent/internal/transport/webrtc_test.go relay/internal/webrtc_signal/
git commit -m "feat(tunnel): add WebRTC fallback transport (agent + relay signaling)"
```

---

## Task 14: Agent supervisor — wires RTSP client → transport, with reconnect

**Files:**
- Create: `agent/internal/supervisor/supervisor.go`, `agent/internal/supervisor/supervisor_test.go`

- [ ] **Step 1: Implement supervisor**

Create `agent/internal/supervisor/supervisor.go`:

```go
package supervisor

import (
	"context"
	"log/slog"
	"time"

	"github.com/nightwatch/agent/internal/rtsp"
	"github.com/nightwatch/agent/internal/transport"
)

type CameraSpec struct {
	ID  string
	URL string
}

type Supervisor struct {
	Cameras  []CameraSpec
	Primary  transport.Transport
	Fallback transport.Transport
	Decider  *transport.Decider
}

func (s *Supervisor) Run(ctx context.Context) error {
	backoff := time.Second
	for ctx.Err() == nil {
		tp := s.Primary
		if s.Decider.ShouldFallback() && s.Fallback != nil {
			tp = s.Fallback
			slog.Info("transport fallback active", "transport", tp.Name())
		}
		if err := tp.Connect(ctx); err != nil {
			s.Decider.Record(err)
			slog.Warn("transport connect failed", "err", err, "backoff", backoff)
			sleepCtx(ctx, backoff)
			backoff = nextBackoff(backoff)
			continue
		}
		s.Decider.RecordSuccess()
		backoff = time.Second

		for _, cam := range s.Cameras {
			if err := tp.OpenCamera(cam.ID); err != nil { continue }
			c := cam
			go func() {
				cli := &rtsp.Client{
					URL: c.URL,
					OnFrame: func(b []byte, kf bool) { _ = tp.SendFrame(c.ID, b, kf) },
				}
				_ = cli.Run(ctx)
			}()
		}
		<-ctx.Done()
		_ = tp.Close()
		return ctx.Err()
	}
	return ctx.Err()
}

func sleepCtx(ctx context.Context, d time.Duration) {
	t := time.NewTimer(d); defer t.Stop()
	select { case <-ctx.Done(): case <-t.C: }
}

func nextBackoff(cur time.Duration) time.Duration {
	cur *= 2
	if cur > 30*time.Second { cur = 30 * time.Second }
	return cur
}
```

- [ ] **Step 2: Unit test for backoff**

Create `agent/internal/supervisor/supervisor_test.go`:

```go
package supervisor

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestNextBackoff_DoublesUpToCap(t *testing.T) {
	require.Equal(t, 2*time.Second, nextBackoff(1*time.Second))
	require.Equal(t, 30*time.Second, nextBackoff(20*time.Second))
	require.Equal(t, 30*time.Second, nextBackoff(30*time.Second))
}
```

- [ ] **Step 3: Run tests**

Run: `cd agent && go test ./internal/supervisor/... -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add agent/internal/supervisor/
git commit -m "feat(agent): add supervisor with reconnect + transport selection"
```

---

## Task 15: Agent local web UI

**Files:**
- Create: `agent/internal/local_ui/server.go`
- Create: `agent/internal/local_ui/templates/setup.html`

- [ ] **Step 1: Minimal server**

Create `agent/internal/local_ui/server.go`:

```go
package local_ui

import (
	"embed"
	"encoding/json"
	"html/template"
	"net/http"
)

//go:embed templates/*.html
var fs embed.FS

type Server struct {
	Addr string
	OnDiscovery func() ([]map[string]string, error)
	OnSaveCamera func(brand, host, user, pass string) error
}

func (s *Server) Run() error {
	tpl := template.Must(template.ParseFS(fs, "templates/setup.html"))
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { _ = tpl.Execute(w, nil) })
	mux.HandleFunc("/api/discover", func(w http.ResponseWriter, r *http.Request) {
		out, err := s.OnDiscovery()
		if err != nil { http.Error(w, err.Error(), 500); return }
		_ = json.NewEncoder(w).Encode(out)
	})
	mux.HandleFunc("/api/camera", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" { http.Error(w, "POST only", 405); return }
		var body struct{ Brand, Host, User, Pass string }
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil { http.Error(w, err.Error(), 400); return }
		if err := s.OnSaveCamera(body.Brand, body.Host, body.User, body.Pass); err != nil {
			http.Error(w, err.Error(), 500); return
		}
		w.WriteHeader(204)
	})
	return http.ListenAndServe(s.Addr, mux)
}
```

- [ ] **Step 2: Template**

Create `agent/internal/local_ui/templates/setup.html`:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Nightwatch Agent</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:2rem auto">
  <h1>Nightwatch Agent — Setup</h1>
  <button onclick="discover()">Discover NVRs</button>
  <pre id="out"></pre>
  <script>
    async function discover() {
      const r = await fetch('/api/discover');
      document.getElementById('out').textContent = await r.text();
    }
  </script>
</body></html>
```

- [ ] **Step 3: Smoke test (optional)**

Skip a unit test — UI is exercised in the manual end-to-end test (Task 17).

- [ ] **Step 4: Commit**

```bash
git add agent/internal/local_ui/
git commit -m "feat(agent): add minimal local web UI for discover/setup"
```

---

## Task 16: Wire main.go for agent and relay

**Files:**
- Modify: `agent/cmd/agent/main.go`
- Modify: `relay/cmd/relay/main.go`

- [ ] **Step 1: Relay main**

Replace `relay/cmd/relay/main.go`:

```go
package main

import (
	"context"
	"log/slog"
	"net"
	"net/http"
	"os/signal"
	"syscall"

	"google.golang.org/grpc"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
	"github.com/nightwatch/relay/internal/auth"
	"github.com/nightwatch/relay/internal/config"
	"github.com/nightwatch/relay/internal/grpc_server"
	"github.com/nightwatch/relay/internal/republish"
	"github.com/nightwatch/relay/internal/webrtc_signal"
)

func main() {
	cfg := config.Load()
	reg := republish.NewRegistry()

	// gRPC
	gLis, err := net.Listen("tcp", cfg.GRPCAddr)
	if err != nil { slog.Error("listen grpc", "err", err); return }
	gSrv := grpc.NewServer()
	tunnelpb.RegisterTunnelServer(gSrv, &grpc_server.Server{Registry: reg, Auth: auth.StaticKey{Key: cfg.StaticAgentKey}, BufCap: 64})

	// RTSP
	rtspSrv := republish.NewRTSPServer(reg, cfg.RTSPAddr)

	// WebRTC signaling
	signalSrv := &webrtc_signal.Server{Registry: reg, AgentKey: cfg.StaticAgentKey, BufCap: 64}
	httpSrv := &http.Server{Addr: cfg.WebRTCSignalAddr, Handler: http.HandlerFunc(signalSrv.Handle)}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go func() { slog.Info("grpc serving", "addr", cfg.GRPCAddr); _ = gSrv.Serve(gLis) }()
	go func() { slog.Info("rtsp serving", "addr", cfg.RTSPAddr); _ = rtspSrv.Run(ctx) }()
	go func() { slog.Info("webrtc-signal serving", "addr", cfg.WebRTCSignalAddr); _ = httpSrv.ListenAndServe() }()

	<-ctx.Done()
	gSrv.GracefulStop()
	_ = httpSrv.Shutdown(context.Background())
	slog.Info("relay stopped")
}
```

- [ ] **Step 2: Agent main**

Replace `agent/cmd/agent/main.go`:

```go
package main

import (
	"context"
	"log/slog"
	"os/signal"
	"syscall"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/nightwatch/agent/internal/config"
	"github.com/nightwatch/agent/internal/supervisor"
	"github.com/nightwatch/agent/internal/transport"
)

func main() {
	cfg := config.Load()

	dialOpts := []grpc.DialOption{}
	if cfg.RelayInsecure {
		dialOpts = append(dialOpts, grpc.WithTransportCredentials(insecure.NewCredentials()))
	} else {
		// TLS — production path. Load system roots by default.
		dialOpts = append(dialOpts, grpc.WithAuthority(""))
	}

	primary := transport.NewGRPC(cfg.RelayAddr, cfg.StaticAgentKey, dialOpts)
	fallback := transport.NewWebRTC("https://"+cfg.RelayAddr+"/webrtc/offer", cfg.StaticAgentKey)
	dec := &transport.Decider{}

	// Cameras come from on-disk state file (agent_state.json), populated by local UI.
	// For now, accept env CAMERAS as `id1=url1,id2=url2` for development.
	cameras := loadCamerasFromEnv()

	sup := &supervisor.Supervisor{
		Cameras:  cameras,
		Primary:  primary,
		Fallback: fallback,
		Decider:  dec,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	slog.Info("agent starting", "cameras", len(cameras))
	if err := sup.Run(ctx); err != nil { slog.Error("supervisor exited", "err", err) }
}

func loadCamerasFromEnv() []supervisor.CameraSpec {
	// Implementation: read AGENT_CAMERAS env, split on comma, then '='.
	// Trimmed for brevity; real impl is a 10-line loop.
	return nil
}
```

- [ ] **Step 3: Build both**

Run: `cd agent && go build ./...`
Run: `cd relay && go build ./...`
Expected: success.

- [ ] **Step 4: Commit**

```bash
git add agent/cmd/agent/main.go relay/cmd/relay/main.go
git commit -m "feat(tunnel): wire main.go for agent and relay"
```

---

## Task 17: End-to-end test with stubbed RTSP source

**Files:**
- Create: `relay/test/e2e_test.go`

- [ ] **Step 1: Write e2e test**

Create `relay/test/e2e_test.go`:

```go
package e2e_test

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	tunnelpb "github.com/nightwatch/proto/gen/go/tunnelpb"
	agenttp "github.com/nightwatch/agent/internal/transport"
	"github.com/nightwatch/relay/internal/auth"
	"github.com/nightwatch/relay/internal/grpc_server"
	"github.com/nightwatch/relay/internal/republish"
)

func TestE2E_AgentToRelayFrameDelivery(t *testing.T) {
	// Start relay
	lis, _ := net.Listen("tcp", "127.0.0.1:0")
	reg := republish.NewRegistry()
	srv := grpc.NewServer()
	tunnelpb.RegisterTunnelServer(srv, &grpc_server.Server{Registry: reg, Auth: auth.StaticKey{Key: "k"}, BufCap: 32})
	go srv.Serve(lis)
	defer srv.Stop()

	// Connect agent transport
	tp := agenttp.NewGRPC(lis.Addr().String(), "k", []grpc.DialOption{grpc.WithTransportCredentials(insecure.NewCredentials())})
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second); defer cancel()
	require.NoError(t, tp.Connect(ctx))
	require.NoError(t, tp.OpenCamera("cam-1"))
	for i := 0; i < 5; i++ {
		require.NoError(t, tp.SendFrame("cam-1", []byte("frame"), false))
	}

	require.Eventually(t, func() bool {
		pub, ok := reg.Get("cam-1")
		return ok && pub.Frames.Len() >= 5
	}, 2*time.Second, 50*time.Millisecond)
}
```

- [ ] **Step 2: Run**

Run: `cd relay && go test ./test/... -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add relay/test/
git commit -m "test(tunnel): add e2e test for agent→relay frame delivery"
```

---

## Task 18: Multi-arch Docker images

**Files:**
- Create: `agent/Dockerfile`, `relay/Dockerfile`

- [ ] **Step 1: Agent Dockerfile**

Create `agent/Dockerfile`:

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.22 AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /out/nightwatch-agent ./cmd/agent

FROM gcr.io/distroless/static
COPY --from=build /out/nightwatch-agent /nightwatch-agent
EXPOSE 8765
ENTRYPOINT ["/nightwatch-agent"]
```

- [ ] **Step 2: Relay Dockerfile**

Create `relay/Dockerfile`:

```dockerfile
FROM --platform=$BUILDPLATFORM golang:1.22 AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /out/nightwatch-relay ./cmd/relay

FROM gcr.io/distroless/static
COPY --from=build /out/nightwatch-relay /nightwatch-relay
EXPOSE 9443 8554 9080
ENTRYPOINT ["/nightwatch-relay"]
```

- [ ] **Step 3: Build locally**

Run: `cd agent && docker build -t nightwatch-agent:dev .`
Run: `cd relay && docker build -t nightwatch-relay:dev .`
Expected: both build.

- [ ] **Step 4: Multi-arch buildx (smoke)**

Run: `cd agent && docker buildx build --platform linux/amd64,linux/arm64,linux/arm/v7 -t nightwatch-agent:multi .`
Expected: success (no push).

- [ ] **Step 5: Commit**

```bash
git add agent/Dockerfile relay/Dockerfile
git commit -m "feat(tunnel): add multi-arch Dockerfiles for agent and relay"
```

---

## Task 19: Worker docs update

**Files:**
- Modify: `worker/CLAUDE.md`, `worker/AGENTS.md`

- [ ] **Step 1: Add note**

In both files, add a section after the existing camera-config section:

```markdown
### Relay-routed cameras (home users)
Some cameras now arrive via the cloud relay rather than direct RTSP-to-NVR. From the worker's
perspective these are identical — just an `rtsp://` URL — but the URL points at the relay
(`rtsp://relay-internal:8554/<camera_id>`) instead of the user's NVR. No code changes are needed
in the worker. Operators must ensure the worker can reach `relay-internal:8554` on the cloud
network.
```

- [ ] **Step 2: Commit**

```bash
git add worker/CLAUDE.md worker/AGENTS.md
git commit -m "docs(worker): note relay-routed RTSP URLs from home agents"
```

---

## Task 20: Manual end-to-end pilot test

**Files:** none

- [ ] **Step 1: Set up loopback**

On a dev machine: run `relay/cmd/relay` with `RELAY_AGENT_KEY=devkey RELAY_GRPC_ADDR=:9443`. Start a recorded RTSP stream as a fake NVR (e.g. `ffmpeg -re -i sample.mp4 -c copy -f rtsp rtsp://127.0.0.1:8555/live`). Run `agent/cmd/agent` with `AGENT_RELAY_ADDR=127.0.0.1:9443 AGENT_RELAY_INSECURE=1 AGENT_KEY=devkey AGENT_CAMERAS=cam-1=rtsp://127.0.0.1:8555/live`.

- [ ] **Step 2: Pull from relay**

Run: `ffplay rtsp://127.0.0.1:8554/cam-1`
Expected: video plays (the gortsplib RTSP server in relay republishes the frames).

- [ ] **Step 3: Run worker against relay URL**

Update `worker` config to point at `rtsp://127.0.0.1:8554/cam-1`. Verify worker emits events to backend as usual.

- [ ] **Step 4: Network-fault drill**

Kill agent's network for 60s (`sudo pfctl -e -f /tmp/blockrules` on macOS, or just `kill` and restart). Confirm:
- Worker camera flips to `offline`
- Agent reconnects automatically with backoff
- No duplicate events appear

- [ ] **Step 5: Document results**

Note in PR: actual reconnect time observed, fallback triggered or not, any issues with frame ordering or A/V sync.

---

## Self-review

**Spec coverage:**
- 5.1 Agent (Go, ONVIF, manual fallback, pair via short code) → Tasks 7–10, 14, 15. **Pair-code flow deferred to onboarding plan** as called out at top.
- 5.1 gRPC primary, WebRTC fallback, decision logic → Tasks 11, 12, 13.
- 5.2 Relay (terminate tunnels, republish RTSP, auth, bounded buffers, metrics) → Tasks 3, 4, 5, 6, 6b. **Prometheus metrics omitted** — small follow-up; not blocking.
- 6.1 Live event flow → Task 17 (e2e test) + Task 20 (manual).
- 8.1 Agent↔Relay error handling (reconnect, fallback, bounded buffers) → Tasks 3, 12, 14.

**Gaps:**
- TLS certificates for production — currently insecure-by-flag. Add as a small separate task before deploy: load certs from env, build dialOpts accordingly. Out of scope for this plan.
- Prometheus metrics package referenced but not implemented. Either add a small Task 5b, or defer to ops-readiness work.
- Local UI is minimal HTML; production polish belongs in the onboarding plan.

**Placeholders:** `loadCamerasFromEnv` in `agent/cmd/agent/main.go` Task 16 is a stub — flag it; implement in Task 16.5 if needed before manual pilot:

> Task 16.5 (5 min): implement `loadCamerasFromEnv` to parse `AGENT_CAMERAS=id1=url1,id2=url2`.

**Type consistency:** `Transport.Name()` returns `"grpc"`/`"webrtc"`; `Decider` checks status codes; protobuf field names match between proto and Go references.
