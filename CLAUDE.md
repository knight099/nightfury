# Nightwatch — Agent Rules (Root)

## Project Overview
AI-powered CCTV event intelligence SaaS platform. Five services:
- **backend/** — FastAPI REST API + WebSocket + Digest service (Python)
- **worker/** — Stream processing + Gemini Vision AI (Python) — runs the cloud-VM fallback deployment path only; the default edge-box deployment runs an identical copy of this pipeline locally as `agent/pipeline/`
- **frontend/** — Next.js dashboard (TypeScript)
- **agent/** — self-contained edge box for home/site users (Go) — runs on customer premises, pulls RTSP from NVR, and (default deployment) supervises its own detection pipeline + WebRTC live-view stack in-process, talking directly to backend. No relay dependency in the default path.
- **relay/** — Cloud tunnel terminator (Go) — **fallback-only**, for the legacy cloud-VM deployment path (direct-connect cameras, or edge boxes that can't run the pipeline sidecar); accepts agent gRPC/WebRTC tunnels, republishes streams as local RTSP for the worker. Not used by the default edge-box agent.

## Home-camera plugin (consumer onboarding)
Lets non-technical users connect home NVRs (CP Plus, Hikvision, Dahua, etc.) without port-forwarding or a PC.

**Default deployment: self-contained edge box, direct to backend, nothing in between.** See `docs/superpowers/specs/2026-08-12-edge-detection-architecture-design.md` for the full design.
- **Capture:** small Docker LAN agent (edge box: Pi / NAS / on-prem server) auto-discovers NVR via ONVIF, falls back to manual RTSP URL entry per brand.
- **Detection runs on the edge box, not the cloud.** The Go agent supervises a Python pipeline sidecar (`agent/pipeline/` — a self-contained copy of `worker/`'s logic: FFmpeg → motion gate → Gemini Vision → event packaging) as a restarting child process. No continuous video tunnel to the cloud; only small event payloads and on-demand live view ever cross the network.
- **Control plane:** one persistent, device-token-authenticated control WebSocket (`WS /api/agents/me/control`) direct from agent to backend — carries merged agent+pipeline heartbeat and WebRTC signaling (SDP/ICE) for live view. No relay hop.
- **Pairing:** 6-digit code (10-min TTL, single-use) issued by backend; agent exchanges for long-lived device token bound to its pubkey. The same device token also authenticates the pipeline sidecar's own calls to backend (`/internal/*` accepts this Bearer token alongside the legacy static `X-Worker-Key`).
- **Live view (on demand only):** frontend requests → backend mints a short-lived signed view request, forwards it down the control WebSocket → agent's embedded WebRTC stack (`agent/webrtcsignal/`, pion/webrtc) answers directly → media negotiates browser ⇄ edge box (STUN first, coturn TURN fallback for symmetric NAT/CGNAT, see `deploy/coturn/`). Backend and TURN never see media, only signaling.
- **Uploads:** pipeline sidecar requests a signed GCS upload URL from backend (`POST /api/edge/upload-url`, org-scoped) and PUTs snapshot/clip directly — no GCS service-account key on customer-owned hardware.
- **Gemini credentials:** pipeline sidecar exchanges its device token for a short-lived (≤30min) Vertex AI token via backend's broker (`POST /api/edge/gemini-token`) — no static Gemini key on the device; revoking the device token kills Gemini access within one TTL window.
- **Cloud-VM fallback (non-default, opt-in):** `relay/` + `worker/` remain untouched and independently deployable for direct-connect cameras or edge boxes that can't run the pipeline sidecar — relay republishes tunneled cameras as `rtsp://relay-internal:8554/<camera_id>` and worker runs the same pipeline logic centrally. New deployments default to the self-contained edge box above; don't reach for this path without a specific reason.
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
| Backend  | Vercel (serverless) or Cloud Run | `POSTGRES_URL`, `REDIS_URL` from Supabase/Upstash; also brokers GCS upload URLs + short-lived Vertex AI tokens for edge boxes |
| Agent (edge box) | Customer's LAN device — **default deployment** | Outbound-only (control WebSocket + HTTPS), no inbound ports needed. Runs `agent/pipeline/` (detection) + `agent/webrtcsignal/` (live view) in-process — self-contained, no dependency on `worker/`/`relay/` |
| coturn   | Small VM, public IP          | TURN fallback for live view when direct WebRTC P2P fails (symmetric NAT/CGNAT); see `deploy/coturn/` |
| Worker   | GCE VM or dedicated server — **cloud-VM fallback path only** | Needs FFmpeg + GCS access + direct NVR LAN |
| Relay    | GCE VM with public IP — **cloud-VM fallback path only** | Ports 9443 (gRPC), 8554 (RTSP), 9080 (WebRTC) open |
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

### Backend (97 API paths, 19 models, 19 migrations)
- FastAPI + SQLAlchemy 2.0 async + PostgreSQL + Redis
- Auth: username/password, Argon2id hashing, AES-256-GCM encrypted Redis sessions, brute-force lockout, session binding (IP+UA), idle/absolute expiry
- Multi-tenant isolation on every query: `org_id` filter **plus** `scope_to_sites(...)` for per-site restriction (`users.sites_access`). Both halves are required — see Cross-Service Rules
- Super admin: bypasses org filters, CRUD all orgs/users, change passwords, force-logout, view sessions
- Alert engine with per-site scoping and an escalation ladder (unacknowledged events climb to the next rung)
- WebSocket: per-org real-time event broadcast, filtered per subscriber by site scope
- Internal edge endpoints: event ingestion, batched heartbeat, agent-scoped camera assignments, setup jobs
- Scheduled work: digests, escalation sweep (1min), fleet-health/failover sweep (1min), retention purge (nightly)

### Worker / agent pipeline (cloud-VM fallback and edge box run the same logic)
- Full stream-to-event pipeline: FFmpeg → motion detect → YOLO gate → Gemini Vision → event package → upload
- Motion detection + YOLO gating cut Gemini calls sharply; adaptive sampling (1fps idle, 5fps active) with deduplication
- Pose detection + step-sequence tracking for procedure monitoring
- Footfall line-crossing counting (estimates — see Footfall below)
- Self-sizing capacity, graceful degradation, batched heartbeat, setup-job polling
- Supervisor manages multiple cameras, health reporting, auto-restart

### Frontend (30 routes, builds clean)
- Next.js App Router + TypeScript + Tailwind + shadcn/ui, dark theme only
- Core: login, dashboard, events (+ detail, feedback, incident status), cameras (+ per-camera view, zones, sequences), alerts, digests, settings, usage, admin
- Estate: `/fleet` (appliance capacity + coverage), `/wall` (video wall), `/map` (camera adjacency), `/setup` (agentic camera setup)
- 11-step onboarding tour, help widget, persistent chat side panel (Ctrl/Cmd+K)
- Typed API client + Zustand auth store + TanStack Query

### Mall / estate scale (COMPLETE)
Design + gap analysis: `docs/superpowers/plans/2026-08-18-mall-scale-architecture.md`
- **Camera placement**: backend is the assignment authority. `GET /internal/assignments` is scoped to the calling agent (it previously returned every camera in the database — a cross-tenant leak). A deterministic, sticky, pin-respecting bin-packer distributes cameras across the appliances at a site
- **Self-sizing appliances**: capacity is measured from CPU/RAM then revised from observed load with hysteresis. `max_cameras` is an operator ceiling, not the number. Over capacity degrades sampling across all cameras rather than silently dropping some
- **Fleet visibility**: `/fleet` shows coverage (analysed/configured), per-appliance capacity, staleness, and `unassigned` cameras with the remedy stated as a number
- **Failover**: a silent appliance is marked offline; the reconciler relocates its cameras or exposes them as unassigned, and the org is notified. A recovered box is returned to service on its next heartbeat
- **Incident workflow**: `events.status` (new/acknowledged/resolved/dismissed) kept strictly orthogonal to the detection-quality `feedback` fields, plus a shift-handover filter
- **Retention**: per-org `retention_days` in `organizations.settings`; absent or zero means keep forever (opt-in by design)
- **Per-site AI budgets**: one busy site can no longer exhaust the whole org's daily spend
- **Verified to scale**: placement holds from 4 to 800 cameras (planner <10ms, reconcile <40ms, idempotent at every size); event queries run 2–6ms at 360k events / 400 cameras

### Cross-camera journeys (COMPLETE)
- Operator-drawn adjacency (`camera_connections`) plus event timing correlates activity across cameras into a path
- **Not** person re-identification: no embeddings, no biometrics, no visual matching. The summary sentence is templated, never model-generated, so the "may or may not be the same person" caveat cannot drift into a certainty
- Design: `docs/superpowers/specs/2026-08-13-camera-map-journeys-design.md`

### Footfall counting (COMPLETE — estimates only)
- Operator draws a counting line; directional crossings are counted off the YOLO person detections the gate already produces (no extra inference)
- Built on tracking **without** re-identification, so it over-counts on occlusion and under-counts in crowds. Honest as relative trend, dishonest as absolute counts — the API returns `estimate: true` plus a caveat string so a client cannot render it as a turnstile figure by omission
- Stored as raw per-heartbeat buckets, never a running total

### Edge Detection Architecture (COMPLETE — now the default deployment model)
- Agent (`agent/`) is self-contained: supervises its own copy of the detection pipeline (`agent/pipeline/`, copied from `worker/`) as a restarting child process, and embeds its own WebRTC answer stack (`agent/webrtcsignal/`, copied from `relay/webrtcsignal/`) for live view — no runtime dependency on `relay/`/`worker/` for new deployments
- Persistent control WebSocket (`WS /api/agents/me/control`, device-token auth) carries merged agent+pipeline heartbeat and WebRTC signaling direct from agent to backend
- `backend/app/api/edge_uploads.py` — org-scoped signed GCS upload URLs for the pipeline sidecar (no service-account key on customer hardware)
- `backend/app/services/gemini_broker.py` + `backend/app/api/edge_credentials.py` — short-lived (≤30min) Vertex AI token broker, lazy + fail-safe
- `backend/app/core/dependencies.py::verify_worker_key` — dual-mode: accepts the legacy static `X-Worker-Key` OR a device-token Bearer, additive, no regression to the cloud-VM fallback path
- `deploy/coturn/` — TURN fallback for live view when direct WebRTC P2P fails; TURN credentials wired into the browser's `RTCPeerConnection`
- `relay/` and `worker/` are untouched and remain deployable as an opt-in cloud-VM fallback path (direct-connect cameras, or edge boxes that can't run the pipeline sidecar)
- Full design: `docs/superpowers/specs/2026-08-12-edge-detection-architecture-design.md`; implementation plan: `docs/superpowers/plans/2026-08-12-edge-detection-architecture.md`

### Agentic Camera Setup (COMPLETE)
- Operator selects a batch of cameras (max 50); backend enqueues one setup job
  per camera onto that camera's own agent's Redis list
- The **Python pipeline** (not the Go agent) drains the jobs: samples 10 frames
  over 3 minutes, makes one structured Gemini Vision call, posts back a proposal
- Backend validates the proposal and clusters the batch by a closed `scene_type`
  enum; low-confidence, invalid, or `other` proposals go to "Needs your input"
  and can never be bulk-approved
- Approval is the ONLY path that writes camera config. `suggested_alert` is
  stored in the proposal and shown in the UI, but approval never writes an
  alert rule — alert rules remain a separate, per-camera confirmation step
- Camera adjacency is deliberately NOT proposed — it is not visible in frames.
  The flow prompts the operator to draw it on `/map` after a batch is approved
- Design: `docs/superpowers/specs/2026-08-18-agentic-camera-setup-design.md`

## What's Left

Everything below is genuinely not built. Completed work is in the status
section above and is not repeated here.

### Known gaps in shipped features
- **Setup runs are not metered against the per-site AI budget.** The agentic-setup spec promised they would be; no task implemented it. Exposure is bounded by the 50-camera batch cap (one Gemini call per camera, once). Metering must happen at dispatch in `start_setup_run`, because the edge box makes the call, not the backend
- **Alert rules are proposed but never applied.** `suggested_alert` is stored and displayed; approval never writes an alert rule. The per-camera confirm-and-write flow is unbuilt
- **Scheduled digests are still org-wide.** On-demand digests are site-scoped, so a site-restricted account sees those but never the morning/evening runs. Needs per-site scheduled generation
- **No end-to-end test against a real camera** (CP Plus RTSP → pipeline → backend → frontend). Still the highest-value pre-pilot check

### Not built
- **Fall / person-down detection.** Pose labels exist (`standing`, `bending`, `crouching`, `sitting`, `reaching`) but there is no validated fallen state. Do not promise this to customers
- **Crowd density / occupancy counting.** Distinct from footfall line-crossing, and not implemented
- **Cross-camera person re-identification.** Deliberately out of scope — see `docs/superpowers/specs/2026-08-01-remind-reid-integration-design.md` for why (GPU-dependent, more privacy-sensitive, and journeys deliberately avoid identity claims)
- Analytics / charts page; full-text search across events
- Loading skeletons and error boundaries on the older pages

### Operational follow-ups
- After migrating a production database, confirm no camera is left with `agent_id IS NULL` — assignments are agent-scoped, so an unplaced camera is analysed by nobody
- Tune the journey correlation window (10 min) and max chain length (5) against real site data; both are starting guesses
- Tune the setup observation window (10 frames over 3 minutes) against real footage

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
- Worker authenticates via static `X-Worker-Key` header (cloud-VM fallback path only)
- Agent authenticates via long-lived device token bound to its pubkey, scoped to one `org_id`. `/internal/*` routes accept this device-token Bearer in addition to the legacy `X-Worker-Key` (dual-mode, additive — see `backend/app/core/dependencies.py::verify_worker_key`)
- The agent's pipeline sidecar (`agent/pipeline/`) reuses the same device token for its own backend calls (events, GCS upload URLs, Gemini token broker) — no separate secret
- Backend brokers short-lived (≤30min) Vertex AI tokens to device-token-authenticated edge boxes instead of shipping a static Gemini key to customer hardware (`POST /api/edge/gemini-token`)
- Relay (cloud-VM fallback path only) rejects any stream tagged with a `camera_id` that doesn't belong to the agent's `org_id`
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
# Home-user camera — DEFAULT: self-contained edge box, direct to backend, nothing in between
NVR ──RTSP (LAN)──► Agent (Go) ──spawns──► pipeline sidecar (agent/pipeline/, Python)
                        │                       │
                        │            FFmpeg → motion gate → Gemini Vision → event packaging
                        │              (Gemini/GCS creds brokered from Backend, per-call,
                        │               device-token authenticated — no static secrets on device)
                        │                       │
                        │                       ▼
                        │                  Backend (events, uploads, heartbeat) → DB/GCS → Alerts/WS → Frontend
                        │
                        └─ control WebSocket (heartbeat + WebRTC signaling), direct ──► Backend

# Live view (on demand only, default deployment)
Frontend requests view → Backend (verifies org/session, mints signed view request)
  → forwards over agent's control WebSocket → agent's embedded WebRTC stack answers directly
  → media negotiates browser ⇄ agent (STUN first, coturn TURN fallback). Backend/TURN never see media.

# Cloud-VM fallback path (legacy, opt-in — relay/worker untouched, NOT the default)
Camera → Worker → Backend → DB/GCS → Alerts/WS → Frontend
NVR ──RTSP (LAN)──► Agent ──gRPC/WebRTC tunnel──► Relay ──RTSP republish (relay-internal:8554)──► Worker → Backend → ...

# Digest (new)
Scheduler tick (per org, per slot, in org timezone)
  OR  POST /api/digests {start,end,...}
      → query events in window → compact (sample if >200) → Gemini text summary
      → persist digests row → render WhatsApp message + dashboard view

# Live view fallback chain (frontend, unchanged priority order)
WebRTC (edge box answers directly for default deployments; relay-VM proxy for cloud-VM fallback
  deployments) → MJPEG (cloud-VM fallback deployments only — pure edge-box deployments have no
  MJPEG server, so this leg is skipped) → snapshot polling.
NEVER stream raw video through Backend or over the control WebSocket — media is either
edge-box↔browser P2P/TURN (default) or worker-VM-local MJPEG (fallback only); only event
snapshots + 10s clips and small signaling messages ever reach cloud infra.
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
- Video NEVER leaves customer premises to cloud compute — only event snapshots + 10s clips go to cloud storage. Default (edge-box) deployments: motion-gated frames go straight from the agent's pipeline sidecar to Gemini's/Vertex's API, never through Backend/Worker/Relay. Cloud-VM fallback deployments: video stays on the Worker only.
- No standing static secrets on customer-owned hardware — edge boxes get short-lived, device-token-brokered credentials (Vertex AI tokens, signed GCS upload URLs) instead of a service-account key or static Gemini key
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
- Live view priority order: (1) WebRTC — for the default edge-box deployment, the agent answers directly over its control WebSocket (no relay hop); for cloud-VM fallback deployments, `POST /api/cameras/{id}/webrtc-offer` proxies to relay `/view` as before; (2) MJPEG worker stream (signed URL, cloud-VM fallback deployments only — pure edge-box deployments have no MJPEG server); (3) snapshot polling. coturn (`deploy/coturn/`) is deployed as an already-approved, explicit exception for edge-box NAT traversal — don't stand up additional TURN infra beyond that without explicit instruction.
- Don't add WebRTC direct-to-browser from the cloud Worker — for the cloud-VM fallback path, WebRTC still goes through the relay only. (The edge box's own embedded WebRTC stack answering directly is a separate, already-approved default path — see `docs/superpowers/specs/2026-08-12-edge-detection-architecture-design.md`.)
- Don't route the default edge-box deployment's control-plane, detection, uploads, or live-view signaling through `relay/`/`worker/` — those exist solely for the opt-in cloud-VM fallback path. New camera/agent features default to the direct-to-backend model unless there's a specific reason to target the fallback path.
