#!/bin/bash
# Start all Nightwatch services (Postgres, Redis, Backend, Worker, Frontend)

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
WORKER_DIR="$ROOT_DIR/worker"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

cleanup() {
    echo -e "\n${YELLOW}Shutting down all services...${NC}"
    kill $BACKEND_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    docker compose -f "$BACKEND_DIR/docker-compose.yml" stop db redis 2>/dev/null
    echo -e "${GREEN}All services stopped.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║      NIGHTWATCH — Starting All       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"

# 1. Start Postgres + Redis
echo -e "\n${YELLOW}[1/4] Starting Postgres & Redis...${NC}"
docker compose -f "$BACKEND_DIR/docker-compose.yml" up -d db redis
sleep 2
echo -e "${GREEN}       Postgres (5432) + Redis (6379) running${NC}"

# 2. Start Backend
echo -e "${YELLOW}[2/4] Starting Backend (port 8080)...${NC}"
cd "$BACKEND_DIR"
BACKEND_PYTHON="$BACKEND_DIR/venv/bin/python3"
if [ ! -f "$BACKEND_PYTHON" ]; then
    echo -e "${RED}       Backend venv not found. Run: cd backend && python3 -m venv venv && venv/bin/pip install -r requirements.txt${NC}"
    exit 1
fi
PYTHONPATH="$BACKEND_DIR" "$BACKEND_DIR/venv/bin/alembic" upgrade head >> /tmp/nightwatch-backend.log 2>&1
PYTHONPATH="$BACKEND_DIR" "$BACKEND_PYTHON" -m uvicorn app.main:app --reload --port 8080 --host 0.0.0.0 >> /tmp/nightwatch-backend.log 2>&1 &
BACKEND_PID=$!
sleep 2
if kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${GREEN}       Backend running (PID $BACKEND_PID)${NC}"
else
    echo -e "${RED}       Backend failed to start. Check /tmp/nightwatch-backend.log${NC}"
    exit 1
fi

# 3. Start Worker
echo -e "${YELLOW}[3/4] Starting Worker...${NC}"
cd "$WORKER_DIR"
if [ -f "cameras.json" ]; then
    python3 main.py > /tmp/nightwatch-worker.log 2>&1 &
    WORKER_PID=$!
    sleep 1
    echo -e "${GREEN}       Worker running (PID $WORKER_PID)${NC}"
else
    echo -e "${YELLOW}       Worker skipped — no cameras.json found${NC}"
    echo -e "${YELLOW}       Copy cameras.json.example → cameras.json to enable${NC}"
    WORKER_PID=""
fi

# 4. Start Frontend
echo -e "${YELLOW}[4/4] Starting Frontend (port 3000)...${NC}"
cd "$FRONTEND_DIR"
npm run dev > /tmp/nightwatch-frontend.log 2>&1 &
FRONTEND_PID=$!
sleep 3
if kill -0 $FRONTEND_PID 2>/dev/null; then
    echo -e "${GREEN}       Frontend running (PID $FRONTEND_PID)${NC}"
else
    echo -e "${RED}       Frontend failed to start. Check /tmp/nightwatch-frontend.log${NC}"
    exit 1
fi

echo -e "\n${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        All services running!         ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Frontend:  http://localhost:3000    ║${NC}"
echo -e "${GREEN}║  Backend:   http://localhost:8080    ║${NC}"
echo -e "${GREEN}║  Postgres:  localhost:5432           ║${NC}"
echo -e "${GREEN}║  Redis:     localhost:6379           ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Super Admin: super_nightvision     ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Logs:                              ║${NC}"
echo -e "${GREEN}║    /tmp/nightwatch-backend.log      ║${NC}"
echo -e "${GREEN}║    /tmp/nightwatch-worker.log       ║${NC}"
echo -e "${GREEN}║    /tmp/nightwatch-frontend.log     ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo -e "\n${YELLOW}Press Ctrl+C to stop all services${NC}\n"

# Wait for any child to exit
wait
