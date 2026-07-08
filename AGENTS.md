# Nightwatch — Agent Rules (Root)

## Project Overview
AI-powered CCTV event intelligence SaaS platform. Five services:
- **backend/** — FastAPI REST API + WebSocket + Digest service (Python)
- **worker/** — Stream processing + Gemini Vision AI (Python)
- **frontend/** — Next.js dashboard (TypeScript)
- **agent/** — LAN agent for home users (Go) — runs in user's LAN, pulls RTSP from NVR, tunnels to relay
- **relay/** — Cloud tunnel terminator (Go) — accepts agent gRPC/WebRTC tunnels, republishes streams as local RTSP for the worker

## Home-camera plugin (consumer onboarding)
Lets non-technical users connect home NVRs (CP Plus, Hikvision, Dahua, etc.) without port-forwarding or a PC.
- **Capture:** small Docker LAN agent on user's NAS / OpenWRT router / Pi auto-discovers NVR via ONVIF, falls back to manual RTSP URL entry per brand.
- **Transport:** outbound TLS gRPC tunnel to cloud relay; falls back to WebRTC (STUN/TURN) if gRPC connect fails 3× with non-auth errors. Transport is sticky per session.
- **Pairing:** 6-digit code (10-min TTL, single-use) issued by backend; agent exchanges for long-lived device token bound to its pubkey.
- **Cloud:** relay republishes each tunneled camera as `rtsp://relay-internal:8554/<camera_id>` so the existing worker pipeline is unchanged.
- **Summaries:** Digest service runs scheduled morning (covers prior night) + evening (covers day) recaps per org timezone, plus on-demand `POST /api/digests` with custom range. Operates on event metadata only (no raw video to Gemini), one Gemini text call per digest. Delivered via existing WhatsApp/email alert engine + new `/digests` dashboard page. Per-org daily Gemini spend cap.
- **Empty windows:** templated "all quiet" digest, no Gemini call.
- **Gemini failure:** one retry, then fallback degraded digest from event metadata so users always receive something.

## Running Locally

### One-command start (recommended)
```bash
./start.sh
```
Starts all five services in order: backend → relay → worker → agent → frontend.
Uses cloud DB (Neon) + cloud Redis (Upstash) — no Docker needed for deps.
All logs go to `/tmp/nightwatch-*.log`. Press Ctrl+C to stop everything.

**Prerequisites:**
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `go` 1.21+ installed
- `node` 20+ + `npm` installed
- `ffmpeg` installed (for worker)
- `backend/.env` filled in (copy `backend/.env.example`)
- `worker/.env` filled in (copy `worker/.env.example`)

### Run each service independently

**Backend (port 8080):**
```bash
cd backend
cp .env.example .env   # fill in POSTGRES_URL, REDIS_URL, secrets
uv run alembic upgrade head   # run once to apply DB migrations
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

**Worker (MJPEG port 8090):**
```bash
cd worker
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in BACKEND_URL, GEMINI_API_KEY, GCS_BUCKET
.venv/bin/python3 main.py
```

**Relay (gRPC :9443, RTSP :8554, WebRTC :9080):**
```bash
cd relay
cp .env.example .env   # fill in STREAM_TOKEN_SECRET, RELAY_BACKEND_URL
go build -o nightwatch-relay ./cmd/relay/
./nightwatch-relay
```

**Agent (device-initiated pairing, default):**
```bash
cd agent
go build -o nightwatch-agent ./cmd/agent/
rm -f state/token.json state/device_id   # force re-pair if already paired
BACKEND_URL=http://localhost:8080 RELAY_INSECURE=true RELAY_ADDR=localhost:9443 ./nightwatch-agent
# Agent logs: DEVICE PAIRING CODE: NW-XXXX
# Go to http://localhost:3000/cameras/connect → "Nightwatch Device" → enter code
```

Set `AGENT_PAIR_MODE=localui` to use the legacy dashboard-code → local web-UI flow instead.

**Frontend (port 3000):**
```bash
cd frontend
npm install
npm run dev
```

### Testing device-initiated pairing locally (no Pi needed)
```bash
# 1. Start backend + frontend (./start.sh or independently above)
# 2. Delete old agent state to force re-pair
rm -f agent/state/token.json agent/state/device_id
# 3. Run agent pointing at local backend
cd agent && BACKEND_URL=http://localhost:8080 RELAY_INSECURE=true ./nightwatch-agent
# 4. Copy the NW-XXXX code from agent logs
# 5. Open http://localhost:3000/cameras/connect → Nightwatch Device → enter code
```

---

## Running in Production

### Infrastructure overview
| Service  | Host                          | Notes                                      |
|----------|-------------------------------|--------------------------------------------|
| Backend  | Vercel (serverless) or Cloud Run | `POSTGRES_URL`, `REDIS_URL` from Supabase/Upstash |
| Worker   | GCE VM or dedicated server   | Needs FFmpeg + GCS access + direct NVR LAN |
| Relay    | GCE VM with public IP        | Ports 9443 (gRPC), 8554 (RTSP), 9080 (WebRTC) open |
| Agent    | Customer's LAN device        | Outbound-only, no inbound ports needed     |
| Frontend | Vercel                       | Static Next.js build                       |

### Backend — Cloud Run or Vercel
```bash
# Env vars to set (Secret Manager / Vercel dashboard):
POSTGRES_URL=postgresql+asyncpg://...
REDIS_URL=rediss://...
SECRET_KEY=<32-byte random hex>
WORKER_API_KEY=<shared with worker>
STREAM_TOKEN_SECRET=<shared with relay + worker>
RELAY_PUBLIC_URL=grpcs://relay.yourdomain.com:9443
RELAY_WEBRTC_URL=http://<relay-internal-ip>:9080
SUPER_ADMIN_USERNAME=super_nightvision
SUPER_ADMIN_PASSWORD=<strong password>
GCS_BUCKET=nightwatch-prod
GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcs-sa.json

# Apply migrations once (run from local or CI):
cd backend && uv run alembic upgrade head
```

### Worker — GCE VM
```bash
# On the VM:
git clone ... && cd vision/worker
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Fill .env:
BACKEND_URL=https://api.yourdomain.com
WORKER_API_KEY=<same as backend WORKER_API_KEY>
GEMINI_API_KEY=...
GCS_BUCKET=nightwatch-prod
STREAM_TOKEN_SECRET=<same as backend>
MJPEG_SERVER_HOST=0.0.0.0
MJPEG_SERVER_PORT=8090

# Run as a systemd service:
sudo tee /etc/systemd/system/nightwatch-worker.service > /dev/null <<EOF
[Unit]
Description=Nightwatch Worker
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/vision/worker
EnvironmentFile=/home/ubuntu/vision/worker/.env
ExecStart=/home/ubuntu/vision/worker/.venv/bin/python3 main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now nightwatch-worker
```

### Relay — GCE VM
```bash
# On the VM:
cd vision/relay
go build -o nightwatch-relay ./cmd/relay/
# Fill .env:
RELAY_GRPC_ADDR=:9443
RELAY_RTSP_ADDR=:8554
RELAY_WEBRTC_ADDR=:9080
RELAY_BACKEND_URL=https://api.yourdomain.com
RELAY_WORKER_KEY=<same as WORKER_API_KEY>
STREAM_TOKEN_SECRET=<same as backend>

# TLS for gRPC (agents connect over the public internet):
# Use a reverse proxy (nginx/caddy) to terminate TLS on port 9443,
# or set RELAY_TLS_CERT / RELAY_TLS_KEY env vars if relay supports it.

# Systemd service:
sudo tee /etc/systemd/system/nightwatch-relay.service > /dev/null <<EOF
[Unit]
Description=Nightwatch Relay
After=network.target

[Service]
WorkingDirectory=/home/ubuntu/vision/relay
EnvironmentFile=/home/ubuntu/vision/relay/.env
ExecStart=/home/ubuntu/vision/relay/nightwatch-relay
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now nightwatch-relay
```

**Firewall rules to open on the relay VM:**
```
TCP 9443   # gRPC (agent tunnel)
TCP 8554   # RTSP (worker pulls from relay)
TCP 9080   # WebRTC signaling (browser → backend → relay)
```

### Agent — Customer device (Pi / NAS / OpenWRT)
```bash
# Download pre-built binary or build from source:
curl -L https://releases.yourdomain.com/agent/latest/nightwatch-agent-linux-arm64 -o nightwatch-agent
chmod +x nightwatch-agent

# Run — device-initiated pairing (default):
BACKEND_URL=https://api.yourdomain.com ./nightwatch-agent
# Agent prints NW-XXXX — customer enters it at yourdomain.com/cameras/connect

# Or via Docker:
docker run -d --name nightwatch-agent \
  --network host \
  --restart unless-stopped \
  -e BACKEND_URL=https://api.yourdomain.com \
  -v /var/lib/nightwatch:/data \
  nightwatchhq/agent:latest
```

### Frontend — Vercel
```bash
cd frontend
# Set in Vercel dashboard:
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
NEXT_PUBLIC_RELAY_URL=grpcs://relay.yourdomain.com:9443

# Deploy:
vercel --prod
# Or via GitHub Actions (see .github/workflows/deploy.yml)
```

### CI/CD
GitHub Actions workflow at `.github/workflows/deploy.yml` handles:
- Backend: builds Docker image → pushes to Artifact Registry → deploys to Cloud Run
- Frontend: `npm run build` → deploys to Vercel
- Migrations: `alembic upgrade head` runs as a Cloud Run job before backend deploy

---

## Current Project Status (What's Done)

### Backend (COMPLETE — 45 routes, verified loading)
- FastAPI + SQLAlchemy 2.0 async + PostgreSQL + Redis
- Auth: username/password, Argon2id hashing, AES-256-GCM encrypted Redis sessions, brute-force lockout, session binding (IP+UA), idle/absolute expiry
- 7 DB models: organizations, users, sites, cameras, events, alert_rules, alert_history
- Full CRUD for all entities with multi-tenant isolation (org_id filtering)
- Super admin: bypasses all filters, CRUD all orgs/users, change passwords, force-logout, view sessions
- Alert engine: evaluates rules on event ingestion, sends WhatsApp/email/webhook
- WebSocket: per-org real-time event broadcast
- Internal worker endpoints: event ingestion + heartbeat
- Docker compose for local dev (Postgres + Redis)

### Worker (COMPLETE — 12 source files, 10 tests passing)
- Full stream-to-event pipeline: FFmpeg → motion detect → Gemini Vision → event package → upload
- Supports RTSP pull + RTMP push camera modes
- Motion detection gates Gemini calls (saves ~80% API cost)
- Adaptive frame sampling (1fps idle, 5fps active) with deduplication
- Gemini 2.0 Flash with circuit breaker, structured JSON parsing, confidence filtering
- Event packaging: annotated WebP snapshots + 10s H.264 clips + GCS upload
- Supervisor manages multiple cameras, health reporting, auto-restart

### Frontend (COMPLETE — 6 pages, builds clean)
- Next.js 14 App Router + TypeScript + Tailwind + shadcn/ui
- Dark theme only (#0D0D0D bg, #1E90FF accent, Comic Relief font)
- Pages: login, dashboard, events (with feedback), cameras (add/delete), alerts (CRUD)
- 11-step onboarding tour (driver.js, auto on first login)
- Help widget (floating chat, 6 troubleshooting topics, keyword matching)
- Typed API client + Zustand auth store + TanStack Query data fetching

### What's NOT Built Yet (Priority Order)

**P0 — Must do before first real test:**
- End-to-end test with real camera (CP Plus RTSP → worker → backend → frontend)

**P1 — COMPLETE:**
- ✅ Alembic migration files (3 migration files covering all 13 tables; alembic/env.py wired)
- ✅ Rate limiting middleware (Redis sliding window in app/core/rate_limit.py, enabled by default)
- ✅ GCS signed URLs (V4 signing in app/services/gcs.py; data-URI fallback for local dev)
- ✅ Production deployment: terraform/ (Cloud Run + GCE + Secret Manager + GCS IAM), .github/workflows/deploy.yml (GCP + Vercel CI/CD), /healthz endpoint added

**P2 — COMPLETE:**
- ✅ Zone drawing editor (canvas polygon tool on camera frame — ZonesEditor.tsx wired into /cameras/[id])
- ✅ WebSocket real-time feed (useEventsSocket hook used on dashboard + events pages + chat panel)
- ✅ Nginx-RTMP server config (nginx/nginx.conf + nginx/Dockerfile for push-mode cameras)
- ✅ Admin UI page (/admin page with orgs + users CRUD, super_admin gated)
- ✅ SQLite offline queue in worker (offline_queue.py + drain-on-heartbeat in api_client.py)
- ✅ Full test suites (backend: 50+ tests across events/cameras/alerts/admin/digests/agents/chat; worker: 15+ tests across motion/ring/prompt/frame_sampler/offline_queue)
- ✅ Live camera view (MJPEG primary + signed stream-token + GCS snapshot fallback)
- ✅ Per-camera event view (/cameras/[id] with live stream + filtered events)
- ✅ Persistent chat side panel (Events tab WebSocket feed + Ask tab Gemini Q&A, Ctrl+K toggle)

**P3 — Nice to have:**
- Loading skeletons + error boundaries
- Analytics/charts page
- ✅ Settings/team management page (backend /api/settings/ + frontend /settings)
- Search across events

**Future (partially done):**
- ✅ Live video via WebRTC (relay path): relay/webrtcsignal/viewer.go serves H.264 video track to browser; backend POST /api/cameras/{id}/webrtc-offer proxies offer to relay with HMAC-signed view_token; frontend WebRTCPlayer component tries WebRTC first, falls back to MJPEG, then snapshot polling. STREAM_TOKEN_SECRET shared between backend and relay. TURN server not yet configured (works on LAN / same-network; may need TURN for NAT traversal in production).

## Monorepo Structure
```
Vision/
├── AGENTS.md            ← you are here
├── CLAUDE.md            # mirror of AGENTS.md for Claude Code
├── MASTER_PLAN.md       # Full architecture plan
├── MVP_PLAN.md          # Cloud SaaS MVP spec
├── plans/               # Detailed plans per service
├── docs/superpowers/specs/  # Design specs (brainstorm output)
├── backend/             # FastAPI API server (+ digest service)
├── worker/              # Stream processing workers
├── frontend/            # Next.js web dashboard
├── agent/               # Go LAN agent (user-installed)
└── relay/               # Go cloud tunnel terminator
```

## Cross-Service Rules

### Auth Contract
- Auth is username + password (NOT email)
- Backend issues AES-256-GCM encrypted opaque tokens (NOT JWT)
- Frontend stores token in localStorage, sends as `Authorization: Bearer <token>`
- Worker authenticates via static `X-Worker-Key` header (not user sessions)
- Agent authenticates via long-lived device token bound to its pubkey, scoped to one `org_id`
- Relay rejects any stream tagged with a `camera_id` that doesn't belong to the agent's `org_id`
- super_admin role has `org_id = null` and sees all data across all orgs

### API Contract
- Backend runs on port 8080
- Frontend calls backend at `NEXT_PUBLIC_API_URL` (default: `http://localhost:8080`)
- Worker calls backend at `BACKEND_URL` (default: `http://localhost:8080`)
- Worker uses `/internal/events` (POST) and `/internal/heartbeat` (POST)
- All client-facing routes under `/api/`
- All responses are JSON

### Data Flow
```
# Direct camera (existing)
Camera → Worker → Backend → DB/GCS → Alerts/WS → Frontend

# Home-user camera (new, via agent)
NVR ──RTSP (LAN)──► Agent ──gRPC/WebRTC tunnel──► Relay
                                                    │
                                  republished as RTSP on relay-internal:8554
                                                    ▼
                                                 Worker (unchanged pipeline)
                                                    │
                                                    ▼
                                                 Backend → DB/GCS → Alerts/WS → Frontend

# Digest (new)
Scheduler tick (per org, per slot, in org timezone)
  OR  POST /api/digests {start,end,...}
      → query events in window → compact (sample if >200) → Gemini text summary
      → persist digests row → render WhatsApp message + dashboard view

# Live view (MJPEG stream, primary; snapshot polling, fallback)
Worker hosts a local MJPEG server (multipart/x-mixed-replace) on MJPEG_SERVER_PORT (default 8090),
serving GET /stream/{camera_id}?token=... from each camera's latest decoded frame.
Backend GET /api/cameras/{id}/stream-url (org-scoped, auth required) returns a signed,
short-lived stream-token URL (HMAC, STREAM_TOKEN_SECRET shared between backend + worker,
default TTL 15min). Frontend <img> tag points at this URL, refetching the signed URL
periodically to stay ahead of expiry.
Fallback: if the MJPEG <img> errors (worker unreachable / stream not started), frontend
falls back to snapshot polling — worker encodes latest BGR frame as WebP every 2s →
GCS latest/{camera_id}.webp; frontend polls GET /api/cameras/{id}/latest-frame → signed
URL → <img>, refresh every 1-2s.
NEVER stream raw video to cloud/relay; the MJPEG server runs on the worker (LAN-local or
worker VM) and is reached directly by the frontend — only event snapshots + 10s clips are
uploaded to cloud storage.
```

### Naming Conventions
- Database tables: snake_case plural (`alert_rules`, `events`)
- API endpoints: kebab-style paths (`/api/auth/login`, `/api/alerts/rules`)
- Python: snake_case functions/variables, PascalCase classes
- TypeScript: camelCase functions/variables, PascalCase components/interfaces
- Env vars: UPPER_SNAKE_CASE

### Security Principles
- Zero plaintext secrets in code — always environment variables
- All camera credentials in config files, never in database directly
- Video NEVER leaves the worker — only event snapshots + 10s clips go to cloud
- Multi-tenant isolation: every query filters by org_id (except super_admin)
- Rate limiting on all public endpoints (Redis-backed)
- Session-bound tokens (IP + User-Agent) — stolen tokens don't work from other devices

### Development Workflow
- Each service runs independently (docker compose for deps only)
- Backend needs: PostgreSQL + Redis (docker compose up db redis)
- Worker needs: FFmpeg + Gemini API key + cameras.json
- Frontend needs: Node.js 20+ (npm run dev)
- Always run `npm run build` for frontend before considering work done
- Always verify backend imports with `python3 -c "from app.main import app"`

### What NOT To Do
- Don't add email-based auth — we use username only
- Don't use JWT anywhere — sessions are server-side Redis
- Don't stream video to cloud — only events leave the edge/worker
- Don't use light mode — UI is dark-only
- Don't add ORM raw queries — SQLAlchemy models only
- Don't hardcode IPs, ports, or credentials
- Don't add features not in MVP_PLAN.md without explicit instruction
- Don't add HLS or raw RTSP republishing to the live view.
- Live view priority order: (1) WebRTC via relay (`POST /api/cameras/{id}/webrtc-offer` → relay `/view`), (2) MJPEG worker stream (signed URL), (3) snapshot polling. WebRTC falls back automatically when the camera is not on the relay (returns 404/503). Do not add TURN servers without explicit instruction.
- Don't add WebRTC direct-to-browser from the worker — WebRTC goes through the relay only.
