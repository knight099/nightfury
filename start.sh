#!/bin/bash
# Start Nightwatch services for local development/testing
# Backend uses cloud DB (Neon) + cloud Redis (Upstash) — no Docker needed.
# Cameras are added via the frontend UI; worker picks them up automatically.

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
WORKER_DIR="$ROOT_DIR/worker"
FRONTEND_DIR="$ROOT_DIR/frontend"
AGENT_DIR="$ROOT_DIR/agent"
RELAY_DIR="$ROOT_DIR/relay"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

BACKEND_PID=""
RELAY_PID=""
WORKER_PID=""
AGENT_PID=""
FRONTEND_PID=""

cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
    [ -n "$AGENT_PID"    ] && kill "$AGENT_PID"    2>/dev/null
    [ -n "$WORKER_PID"   ] && kill "$WORKER_PID"   2>/dev/null
    [ -n "$RELAY_PID"    ] && kill "$RELAY_PID"    2>/dev/null
    [ -n "$BACKEND_PID"  ] && kill "$BACKEND_PID"  2>/dev/null
    echo -e "${GREEN}All services stopped.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║      NIGHTWATCH — Local Dev          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"

# ── Pre-flight checks ─────────────────────────────────────────────────────────

if ! command -v uv &>/dev/null; then
    echo -e "${RED}Error: 'uv' not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
    exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo -e "${RED}Error: backend/.env missing. Copy backend/.env.example and fill in secrets.${NC}"
    exit 1
fi

if [ ! -f "$WORKER_DIR/.env" ]; then
    echo -e "${RED}Error: worker/.env missing. Copy worker/.env.example and fill in secrets.${NC}"
    exit 1
fi

WORKER_PYTHON="$WORKER_DIR/.venv/bin/python3"
if [ ! -f "$WORKER_PYTHON" ]; then
    echo -e "${YELLOW}Worker .venv not found — installing dependencies...${NC}"
    cd "$WORKER_DIR"
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
    echo -e "${GREEN}Worker dependencies installed.${NC}"
fi

# ── Backend ───────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}[1/5] Starting Backend (port 8080)...${NC}"
cd "$BACKEND_DIR"
echo -e "       Running DB migrations..."
if ! PYTHONPATH=. uv run alembic upgrade head >> /tmp/nightwatch-backend.log 2>&1; then
    echo -e "${RED}       Migrations failed. Check /tmp/nightwatch-backend.log${NC}"
    exit 1
fi
echo -e "${GREEN}       Migrations OK${NC}"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload \
    >> /tmp/nightwatch-backend.log 2>&1 &
BACKEND_PID=$!

echo -n "       Waiting for backend"
for i in $(seq 1 20); do
    sleep 1
    if curl -sf http://localhost:8080/healthz &>/dev/null; then
        echo -e " ${GREEN}ready${NC}"
        break
    fi
    echo -n "."
    if [ "$i" -eq 20 ]; then
        echo -e "\n${RED}Backend failed to start. Check /tmp/nightwatch-backend.log${NC}"
        cleanup
    fi
done

# ── Relay ─────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[2/5] Starting Relay (gRPC :9443, RTSP :8554, WebRTC :9080)...${NC}"
RELAY_BIN="$RELAY_DIR/nightwatch-relay"
if [ ! -f "$RELAY_BIN" ]; then
    echo -e "       Building relay..."
    cd "$RELAY_DIR" && go build -o nightwatch-relay ./cmd/relay/ >> /tmp/nightwatch-relay.log 2>&1
fi
cd "$RELAY_DIR"
# Load relay .env into the relay process environment
set -a; [ -f .env ] && source .env; set +a
"$RELAY_BIN" >> /tmp/nightwatch-relay.log 2>&1 &
RELAY_PID=$!
sleep 1
if kill -0 "$RELAY_PID" 2>/dev/null; then
    echo -e "${GREEN}       Relay running (PID $RELAY_PID)${NC}"
else
    echo -e "${YELLOW}       Relay failed (not required for direct RTSP cameras)${NC}"
    RELAY_PID=""
fi

# ── Worker ────────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[3/5] Starting Worker (MJPEG :8090)...${NC}"
cd "$WORKER_DIR"
"$WORKER_PYTHON" main.py >> /tmp/nightwatch-worker.log 2>&1 &
WORKER_PID=$!
sleep 2
if kill -0 "$WORKER_PID" 2>/dev/null; then
    echo -e "${GREEN}       Worker running (PID $WORKER_PID)${NC}"
else
    echo -e "${YELLOW}       Worker failed (continuing). Check /tmp/nightwatch-worker.log${NC}"
    WORKER_PID=""
fi

# ── Agent ─────────────────────────────────────────────────────────────────────
AGENT_BIN="$AGENT_DIR/nightwatch-agent"
if [ -f "$AGENT_DIR/.env" ]; then
    echo -e "${YELLOW}[4/5] Starting LAN Agent (pairing UI :8765)...${NC}"
    if [ ! -f "$AGENT_BIN" ]; then
        echo -e "       Building agent..."
        cd "$AGENT_DIR" && go build -o nightwatch-agent ./cmd/agent/ >> /tmp/nightwatch-agent.log 2>&1
    fi
    cd "$AGENT_DIR"
    set -a; source .env; set +a
    "$AGENT_BIN" >> /tmp/nightwatch-agent.log 2>&1 &
    AGENT_PID=$!
    sleep 1
    if kill -0 "$AGENT_PID" 2>/dev/null; then
        echo -e "${GREEN}       Agent running (PID $AGENT_PID)${NC}"
        if [ -f "$AGENT_DIR/state/token.json" ]; then
            echo -e "${CYAN}       Already paired — tunneling cameras${NC}"
        else
            echo -e "${CYAN}       Not yet paired — open http://localhost:8765 to pair${NC}"
        fi
    else
        echo -e "${YELLOW}       Agent failed. Check /tmp/nightwatch-agent.log${NC}"
        AGENT_PID=""
    fi
else
    echo -e "${CYAN}[4/5] Agent skipped (no agent/.env)${NC}"
fi

# ── Frontend ──────────────────────────────────────────────────────────────────
echo -e "${YELLOW}[5/5] Starting Frontend (port 3000)...${NC}"
cd "$FRONTEND_DIR"
npm run dev >> /tmp/nightwatch-frontend.log 2>&1 &
FRONTEND_PID=$!
sleep 3
if kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo -e "${GREEN}       Frontend running (PID $FRONTEND_PID)${NC}"
else
    echo -e "${RED}       Frontend failed to start. Check /tmp/nightwatch-frontend.log${NC}"
    cleanup
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          All services running!            ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Dashboard:   http://localhost:3000       ║${NC}"
echo -e "${GREEN}║  Backend:     http://localhost:8080       ║${NC}"
echo -e "${GREEN}║  Relay gRPC:  localhost:9443              ║${NC}"
echo -e "${GREEN}║  Relay RTSP:  rtsp://localhost:8554       ║${NC}"
echo -e "${GREEN}║  Worker MJPEG:http://localhost:8090       ║${NC}"
echo -e "${GREEN}║  Agent UI:    http://localhost:8765       ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Logs (tail -f to follow):                ║${NC}"
echo -e "${GREEN}║    /tmp/nightwatch-backend.log            ║${NC}"
echo -e "${GREEN}║    /tmp/nightwatch-relay.log              ║${NC}"
echo -e "${GREEN}║    /tmp/nightwatch-worker.log             ║${NC}"
echo -e "${GREEN}║    /tmp/nightwatch-agent.log              ║${NC}"
echo -e "${GREEN}║    /tmp/nightwatch-frontend.log           ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Agent path (NVR cameras):                ║${NC}"
echo -e "${GREEN}║    1. Open http://localhost:8765          ║${NC}"
echo -e "${GREEN}║    2. Get pair code from /cameras/connect ║${NC}"
echo -e "${GREEN}║    3. Agent tunnels NVR → relay → worker  ║${NC}"
echo -e "${GREEN}║  Direct RTSP cameras:                     ║${NC}"
echo -e "${GREEN}║    Add at /cameras (mode: rtsp_pull)      ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo -e "\n${YELLOW}Press Ctrl+C to stop all services${NC}\n"

wait
