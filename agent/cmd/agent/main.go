package main

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"encoding/base64"
	"encoding/hex"
	"fmt"
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

	"github.com/google/uuid"

	"github.com/nightwatch/agent/internal/config"
	"github.com/nightwatch/agent/internal/control"
	"github.com/nightwatch/agent/internal/devicepair"
	"github.com/nightwatch/agent/internal/discovery"
	"github.com/nightwatch/agent/internal/localui"
	"github.com/nightwatch/agent/internal/pairing"
	"github.com/nightwatch/agent/internal/pipeline"
	"github.com/nightwatch/agent/internal/republish"
	"github.com/nightwatch/agent/internal/store"
	"github.com/nightwatch/agent/internal/supervisor"
	"github.com/nightwatch/agent/internal/transport"
	"github.com/nightwatch/agent/webrtcsignal"
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
	// config.Load() auto-loads .env from cwd before reading env vars.
	cfg := config.Load()
	slog.Info("agent starting", "relay", cfg.RelayAddr, "insecure", cfg.RelayInsecure)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// BACKEND_URL is now set by config.Load()'s dotenv loader if it wasn't
	// already in the environment.
	backend := os.Getenv("BACKEND_URL")
	if backend == "" {
		backend = "https://nightfury-backend.vercel.app"
	}

	if err := os.MkdirAll(cfg.StateDir, 0700); err != nil {
		slog.Warn("could not create state dir", "dir", cfg.StateDir, "err", err)
	}
	tokenPath := filepath.Join(cfg.StateDir, "token.json")
	s := store.New(tokenPath)

	if !s.Exists() {
		if cfg.DeviceToken != "" {
			relayURL := os.Getenv("AGENT_RELAY_URL")
			if relayURL == "" {
				relayURL = cfg.RelayAddr
			}
			if err := s.Save(store.Token{
				DeviceToken: cfg.DeviceToken,
				RelayURL:    relayURL,
				OrgID:       cfg.OrgID,
				AgentID:     cfg.AgentID,
			}); err != nil {
				slog.Error("failed to save preconfigured device token", "err", err)
				return
			}
			slog.Info("using preconfigured agent token; skipping pairing")
		} else if cfg.PairCode != "" {
			// The account-bound installer supplies a short-lived, one-time pair
			// code. The agent still creates its own keypair and receives a device
			// token only after redeeming the code, so no long-lived credential is
			// embedded in a downloaded file.
			mid := machineID()
			pub := ensurePubkey(cfg.StateDir)
			adapter := &pairAdapter{
				backend: backend, store: s, machineID: mid, pubkey: pub, version: agentVersion,
			}
			if err := adapter.Pair(ctx, cfg.PairCode); err != nil {
				slog.Error("automatic installer pairing failed", "err", err)
				return
			}
			slog.Info("installer pairing complete; starting tunnel")
		} else {
			pairMode := os.Getenv("AGENT_PAIR_MODE")
			mid := machineID()
			pub := ensurePubkey(cfg.StateDir)

			if pairMode == "localui" {
				// Legacy: user opens a local web page and enters a code from the dashboard.
				slog.Info("pairing via local UI", "ui_addr", cfg.LocalUIAddr)
				adapter := &pairAdapter{
					backend:   backend,
					store:     s,
					machineID: mid,
					pubkey:    pub,
					version:   agentVersion,
				}
				go func() {
					if err := localui.Serve(cfg.LocalUIAddr, adapter); err != nil {
						log.Printf("local UI server exited: %v", err)
					}
				}()
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
			} else {
				// Default: device-initiated provisioning.
				// Device generates NW-XXXX, registers with cloud, waits for customer to claim it.
				deviceID := loadOrCreateDeviceID(cfg.StateDir)
				code, err := devicepair.GenerateCode()
				if err != nil {
					// A box that cannot generate a secure code must fail
					// loudly, not fall back to a weaker generator.
					slog.Error("failed to generate pairing code", "err", err)
					return
				}
				dc := devicepair.NewClient(backend)

				displayCode, claimURL, err := dc.Provision(ctx, deviceID, code, pub, mid, agentVersion)
				if err != nil {
					slog.Error("device provision failed", "err", err)
					return
				}
				fmt.Print(devicepair.Banner(displayCode, claimURL))
				slog.Info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
				slog.Info("DEVICE PAIRING CODE: "+displayCode, "action", "enter at nightwatch.ai → Cameras → Connect Device")
				slog.Info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

				// Keep the banner visible on an HDMI console (which has no
				// scrollback to refer back to) until the box is claimed, and
				// serve the same banner on the LAN for a customer with no
				// display attached. Both are cancelled together once
				// PollUntilClaimed returns — the LAN listener in particular
				// must not outlive the pairing window: unlike Serve (legacy
				// AGENT_PAIR_MODE=localui), ServeBanner has no auth check on
				// anything (it serves only a read-only page), so leaving it
				// up indefinitely would just be needless attack surface,
				// not a takeover path — but there is no reason to keep it
				// running after the box is claimed either.
				bannerCtx, stopBanner := context.WithCancel(ctx)
				go func() {
					ticker := time.NewTicker(30 * time.Second)
					defer ticker.Stop()
					for {
						select {
						case <-bannerCtx.Done():
							return
						case <-ticker.C:
							fmt.Print(devicepair.Banner(displayCode, claimURL))
						}
					}
				}()
				go func() {
					if err := localui.ServeBanner(bannerCtx, cfg.LocalUIAddr, displayCode, claimURL); err != nil {
						log.Printf("local UI banner server exited: %v", err)
					}
				}()

				tok, err := dc.PollUntilClaimed(ctx, deviceID)
				stopBanner()
				if err != nil {
					slog.Error("provisioning failed", "err", err)
					return
				}
				if err := s.Save(store.Token{
					DeviceToken: tok.DeviceToken,
					RelayURL:    tok.RelayURL,
					OrgID:       tok.OrgID,
					AgentID:     tok.AgentID,
				}); err != nil {
					slog.Error("failed to save device token", "err", err)
					return
				}
				slog.Info("device claimed — starting tunnel", "agent_id", tok.AgentID)
			}
		}
	}

	tok, err := s.Load()
	if err != nil {
		slog.Error("failed to load token after pairing", "err", err)
		return
	}

	if err := validateConfiguredIdentity(tok, cfg); err != nil {
		slog.Error("agent identity mismatch", "err", err)
		return
	}

	relayAddr := stripRelayScheme(tok.RelayURL)
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
	signalURL := signalScheme + "://" + relayAddr + "/signal"
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

	// registry holds a short in-memory buffer of recent frames per camera so
	// a live-view WebRTC viewer can be served directly from this process
	// (see supervisor.Supervisor.Registry / webrtcsignal.HandleOffer).
	registry := republish.NewRegistry()

	sup := &supervisor.Supervisor{
		Cameras:  cams,
		Primary:  primary,
		Fallback: fallback,
		Decider:  &transport.Decider{},
		Registry: registry,
	}

	pipelineEnv := append(os.Environ(),
		"NIGHTWATCH_DEVICE_TOKEN="+tok.DeviceToken,
		"NIGHTWATCH_BACKEND_URL="+backend,
	)
	// Only supervise the Python pipeline sidecar when it is actually
	// installed. Existing agent deployments (and any agent running purely as
	// a relay tunnel) have no pipeline directory, and unconditionally
	// spawning a nonexistent interpreter would crash-loop forever.
	pipelinePython := filepath.Join(cfg.PipelineDir, ".venv", "bin", "python3")
	if pipelineInstalled(cfg.PipelineDir, pipelinePython) {
		pipelineSup := pipeline.NewSupervisor(pipelinePython, cfg.PipelineDir, pipelineEnv)
		go func() {
			if err := pipelineSup.Run(ctx); err != nil && ctx.Err() == nil {
				log.Printf("pipeline supervisor stopped: %v", err)
			}
		}()
	} else {
		slog.Info("pipeline sidecar not installed, skipping supervision",
			"pipeline_dir", cfg.PipelineDir, "python", pipelinePython)
	}

	// registry is populated by sup.Run (each camera's RTSP frames are pushed
	// into its Publisher alongside the existing remote-transport send) —
	// see supervisor.Supervisor.Registry. If a camera is never opened
	// (transport down, RTSP unreachable), HandleOffer still fails cleanly
	// and fast for it: control.Client.handleOffer replies immediately with
	// an explicit {"error": ...} signal_answer, so the backend's
	// request_signal raises straight away (no 10s timeout wait) and
	// camera_webrtc_offer falls through to the relay-VM proxy path.
	viewer := webrtcsignal.NewViewerServer(cfg.StreamTokenSecret, registry)
	controlClient := control.NewClient(backend, tok.DeviceToken, viewer)
	go func() {
		if err := controlClient.Run(ctx); err != nil && ctx.Err() == nil {
			log.Printf("control client stopped: %v", err)
		}
	}()

	if err := sup.Run(ctx); err != nil && err != context.Canceled {
		slog.Error("supervisor exited", "err", err)
	}
	slog.Info("agent shutting down")
}

// pipelineInstalled reports whether the Python detection pipeline sidecar is
// actually present and runnable at the configured location: the pipeline
// directory must exist, contain main.py, and have an executable interpreter
// at the venv path the supervisor would spawn.
func pipelineInstalled(pipelineDir, pythonPath string) bool {
	if fi, err := os.Stat(pipelineDir); err != nil || !fi.IsDir() {
		return false
	}
	if _, err := os.Stat(filepath.Join(pipelineDir, "main.py")); err != nil {
		return false
	}
	fi, err := os.Stat(pythonPath)
	if err != nil || fi.IsDir() || fi.Mode()&0111 == 0 {
		return false
	}
	return true
}

func validateConfiguredIdentity(tok store.Token, cfg config.Config) error {
	if cfg.OrgID != "" && tok.OrgID != "" && cfg.OrgID != tok.OrgID {
		return fmt.Errorf("token org_id %s does not match configured AGENT_ORG_ID %s", tok.OrgID, cfg.OrgID)
	}
	if cfg.AgentID != "" && tok.AgentID != "" && cfg.AgentID != tok.AgentID {
		return fmt.Errorf("token agent_id %s does not match configured AGENT_ID %s", tok.AgentID, cfg.AgentID)
	}
	return nil
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

// stripRelayScheme removes grpc:// or grpcs:// scheme prefixes from a relay
// URL so the result is a plain host:port suitable for gRPC dialing.
func stripRelayScheme(addr string) string {
	for _, prefix := range []string{"grpcs://", "grpc://"} {
		if strings.HasPrefix(addr, prefix) {
			return addr[len(prefix):]
		}
	}
	return addr
}

// loadOrCreateDeviceID reads a persistent device UUID from dataDir/device_id,
// generating and saving a new one on first run.
func loadOrCreateDeviceID(dataDir string) string {
	path := filepath.Join(dataDir, "device_id")
	if b, err := os.ReadFile(path); err == nil {
		id := strings.TrimSpace(string(b))
		if id != "" {
			return id
		}
	}
	id := uuid.New().String()
	_ = os.WriteFile(path, []byte(id), 0600)
	return id
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
