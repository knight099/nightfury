package main

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"encoding/base64"
	"encoding/hex"
	"log"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/nightwatch/agent/internal/config"
	"github.com/nightwatch/agent/internal/discovery"
	"github.com/nightwatch/agent/internal/localui"
	"github.com/nightwatch/agent/internal/pairing"
	"github.com/nightwatch/agent/internal/store"
	"github.com/nightwatch/agent/internal/supervisor"
	"github.com/nightwatch/agent/internal/transport"
)

// discoveryInterval is how often the agent rescans the LAN for ONVIF
// cameras and reports results to the backend (override via env).
const defaultDiscoveryInterval = time.Minute

const agentVersion = "0.1.0"

type pairAdapter struct {
	backend   string
	store     *store.Store
	machineID string
	pubkey    string
	version   string
}

func (p *pairAdapter) IsPaired() bool { return p.store.Exists() }

func (p *pairAdapter) Pair(ctx context.Context, code string) error {
	c := pairing.NewClient(p.backend)
	resp, err := c.Pair(ctx, pairing.Request{
		Code: code, MachineID: p.machineID, Pubkey: p.pubkey, Version: p.version,
	})
	if err != nil {
		return err
	}
	return p.store.Save(store.Token{
		DeviceToken: resp.DeviceToken, RelayURL: resp.RelayURL,
		OrgID: resp.OrgID, AgentID: resp.AgentID,
	})
}

func main() {
	cfg := config.Load()
	slog.Info("agent starting", "relay", cfg.RelayAddr, "insecure", cfg.RelayInsecure)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	backend := os.Getenv("BACKEND_URL")
	if backend == "" {
		backend = "https://api.nightwatch.local"
	}

	if err := os.MkdirAll(cfg.StateDir, 0700); err != nil {
		slog.Warn("could not create state dir", "dir", cfg.StateDir, "err", err)
	}
	tokenPath := filepath.Join(cfg.StateDir, "token.json")
	s := store.New(tokenPath)

	if !s.Exists() {
		slog.Info("not paired yet — open http://localhost:8765 and enter code", "ui_addr", cfg.LocalUIAddr)
		adapter := &pairAdapter{
			backend:   backend,
			store:     s,
			machineID: machineID(),
			pubkey:    ensurePubkey(cfg.StateDir),
			version:   agentVersion,
		}
		go func() {
			if err := localui.Serve(cfg.LocalUIAddr, adapter); err != nil {
				log.Printf("local UI server exited: %v", err)
			}
		}()
		// Block until paired or signal received.
		ticker := time.NewTicker(2 * time.Second)
		defer ticker.Stop()
		for !s.Exists() {
			select {
			case <-ctx.Done():
				slog.Info("agent shutting down before pairing completed")
				return
			case <-ticker.C:
			}
		}
		slog.Info("paired — starting tunnel")
	}

	tok, err := s.Load()
	if err != nil {
		slog.Error("failed to load token after pairing", "err", err)
		return
	}

	relayAddr := tok.RelayURL
	if relayAddr == "" {
		relayAddr = cfg.RelayAddr
	}

	var dialOpts []grpc.DialOption
	if cfg.RelayInsecure {
		dialOpts = append(dialOpts, grpc.WithTransportCredentials(insecure.NewCredentials()))
	} else {
		dialOpts = append(dialOpts, grpc.WithTransportCredentials(credentials.NewTLS(&tls.Config{})))
	}

	primary := transport.NewGRPC(relayAddr, tok.DeviceToken, dialOpts)

	signalScheme := "https"
	if cfg.RelayInsecure {
		signalScheme = "http"
	}
	signalURL := signalScheme + "://" + relayHost(relayAddr) + "/signal"
	fallback := transport.NewWebRTC(signalURL, tok.DeviceToken)

	interval := defaultDiscoveryInterval
	if raw := os.Getenv("AGENT_DISCOVERY_INTERVAL"); raw != "" {
		if d, derr := time.ParseDuration(raw); derr == nil && d > 0 {
			interval = d
		}
	}
	go discovery.RunReporter(ctx, backend, tok.DeviceToken, interval)
	go discovery.RunResolver(ctx, backend, tok.DeviceToken, 10*time.Second)

	cams := loadCamerasFromEnv()
	if len(cams) == 0 {
		slog.Warn("no cameras configured (AGENT_CAMERAS env var empty)")
	}

	sup := &supervisor.Supervisor{
		Cameras:  cams,
		Primary:  primary,
		Fallback: fallback,
		Decider:  &transport.Decider{},
	}

	if err := sup.Run(ctx); err != nil && err != context.Canceled {
		slog.Error("supervisor exited", "err", err)
	}
	slog.Info("agent shutting down")
}

// machineID returns /etc/machine-id if readable, otherwise a hex digest of
// hostname plus the first non-loopback MAC address.
func machineID() string {
	if b, err := os.ReadFile("/etc/machine-id"); err == nil {
		id := strings.TrimSpace(string(b))
		if id != "" {
			return id
		}
	}
	host, _ := os.Hostname()
	mac := ""
	if ifaces, err := net.Interfaces(); err == nil {
		for _, ifa := range ifaces {
			if ifa.Flags&net.FlagLoopback != 0 {
				continue
			}
			if len(ifa.HardwareAddr) > 0 {
				mac = ifa.HardwareAddr.String()
				break
			}
		}
	}
	sum := sha256.Sum256([]byte(host + "|" + mac))
	return hex.EncodeToString(sum[:])[:32]
}

// ensurePubkey returns the agent's base64-encoded ed25519 public key,
// generating a fresh keypair on first run and persisting it under dataDir.
func ensurePubkey(dataDir string) string {
	pubPath := filepath.Join(dataDir, "agent.key.pub")
	if b, err := os.ReadFile(pubPath); err == nil {
		return strings.TrimSpace(string(b))
	}
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		slog.Error("ed25519 keygen failed", "err", err)
		return ""
	}
	pubB64 := base64.StdEncoding.EncodeToString(pub)
	_ = os.WriteFile(filepath.Join(dataDir, "agent.key"), priv, 0600)
	_ = os.WriteFile(pubPath, []byte(pubB64), 0644)
	return pubB64
}

// relayHost strips an optional port from a host:port string for use
// when constructing the WebRTC signaling URL on a different port.
// If no port is present, the input is returned unchanged.
func relayHost(addr string) string {
	if i := strings.LastIndex(addr, ":"); i > 0 && !strings.Contains(addr[i:], "]") {
		return addr[:i]
	}
	return addr
}

// loadCamerasFromEnv parses AGENT_CAMERAS of the form
// "id1=url1,id2=url2,..." into supervisor.CameraSpec entries. Empty
// or unset env returns nil. Malformed entries (missing '=' or empty
// id/url) are skipped.
func loadCamerasFromEnv() []supervisor.CameraSpec {
	raw := os.Getenv("AGENT_CAMERAS")
	if raw == "" {
		return nil
	}
	var out []supervisor.CameraSpec
	for _, entry := range strings.Split(raw, ",") {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		eq := strings.Index(entry, "=")
		if eq <= 0 || eq == len(entry)-1 {
			continue
		}
		id := strings.TrimSpace(entry[:eq])
		url := strings.TrimSpace(entry[eq+1:])
		if id == "" || url == "" {
			continue
		}
		out = append(out, supervisor.CameraSpec{ID: id, URL: url})
	}
	return out
}
