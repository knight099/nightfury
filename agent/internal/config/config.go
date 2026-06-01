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
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
