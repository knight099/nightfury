package config

import (
	"bufio"
	"os"
	"path/filepath"
	"strings"
)

type Config struct {
	RelayAddr      string
	RelayInsecure  bool
	StaticAgentKey string
	DeviceToken    string
	PairCode       string
	OrgID          string
	AgentID        string
	LocalUIAddr    string
	StateDir       string
	PipelineDir    string
}

// Load reads config from environment variables.
// It first loads a .env file from the current working directory (if present)
// so the agent can be run directly without manually sourcing the file.
func Load() Config {
	loadDotenv(".env")
	return Config{
		RelayAddr:      envOr("AGENT_RELAY_ADDR", "relay.nightwatch.ai:9443"),
		RelayInsecure:  os.Getenv("AGENT_RELAY_INSECURE") == "1",
		StaticAgentKey: os.Getenv("AGENT_KEY"),
		DeviceToken:    os.Getenv("AGENT_DEVICE_TOKEN"),
		// PairCode is a short-lived, single-use code written by the downloaded
		// installer. It lets first start happen without asking the customer to
		// copy a pairing code into a local UI.
		PairCode:    os.Getenv("AGENT_PAIR_CODE"),
		OrgID:       os.Getenv("AGENT_ORG_ID"),
		AgentID:     os.Getenv("AGENT_ID"),
		LocalUIAddr: envOr("AGENT_UI_ADDR", ":8765"),
		StateDir:    envOr("AGENT_STATE_DIR", "/var/lib/nightwatch-agent"),
		PipelineDir: envOr("AGENT_PIPELINE_DIR", "/opt/nightwatch/agent/pipeline"),
	}
}

// loadDotenv reads key=value pairs from path and sets them in the process
// environment. Existing env vars are NOT overwritten (dotenv convention).
// Lines starting with # and blank lines are ignored.
func loadDotenv(path string) {
	if !filepath.IsAbs(path) {
		if cwd, err := os.Getwd(); err == nil {
			path = filepath.Join(cwd, path)
		}
	}
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		idx := strings.Index(line, "=")
		if idx <= 0 {
			continue
		}
		key := strings.TrimSpace(line[:idx])
		val := strings.TrimSpace(line[idx+1:])
		// Strip inline comments (e.g. VALUE=foo # comment)
		if ci := strings.Index(val, " #"); ci >= 0 {
			val = strings.TrimSpace(val[:ci])
		}
		// Strip surrounding quotes
		if len(val) >= 2 && ((val[0] == '"' && val[len(val)-1] == '"') ||
			(val[0] == '\'' && val[len(val)-1] == '\'')) {
			val = val[1 : len(val)-1]
		}
		// Don't overwrite already-set env vars (real env takes precedence)
		if os.Getenv(key) == "" {
			_ = os.Setenv(key, val)
		}
	}
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
