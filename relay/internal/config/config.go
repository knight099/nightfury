package config

import (
	"os"
)

type Config struct {
	GRPCAddr         string
	RTSPAddr         string
	WebRTCSignalAddr string
	StaticAgentKey   string
	BackendURL       string
	WorkerKey        string
}

func Load() Config {
	return Config{
		GRPCAddr:         envOr("RELAY_GRPC_ADDR", ":9443"),
		RTSPAddr:         envOr("RELAY_RTSP_ADDR", ":8554"),
		WebRTCSignalAddr: envOr("RELAY_WEBRTC_ADDR", ":9080"),
		StaticAgentKey:   os.Getenv("RELAY_AGENT_KEY"),
		BackendURL:       envOr("RELAY_BACKEND_URL", "http://backend:8080"),
		WorkerKey:        os.Getenv("RELAY_WORKER_KEY"),
	}
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
