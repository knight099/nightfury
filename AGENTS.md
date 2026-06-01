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

**P1 — Must do before production:**
- Alembic migration files (currently using create_all)
- Rate limiting middleware (Redis sliding window)
- GCS signed URLs (currently returning gs:// paths — frontend can't load them)
- Event detail page (/events/[id]) with snapshot viewer + clip player
- Production deployment: Terraform, Cloud Run (backend+frontend), GCE (worker)

**P2 — Should do for good MVP:**
- Zone drawing editor (canvas polygon tool on camera frame)
- WebSocket real-time feed (replace 10s polling in frontend)
- Nginx-RTMP server config (for cloud-hosted push mode)
- Admin UI page (super_admin: orgs/users management)
- SQLite offline queue in worker (for when backend is unreachable)
- Full test suites (backend integration, worker e2e)
- Live camera view: snapshot polling (current approach) — worker uploads `latest/{camera_id}.webp` every 2s, frontend polls via `GET /api/cameras/{id}/latest-frame`.
- Per-camera event view at `/cameras/[id]` with snapshot + filtered events.
- Persistent chat side panel: live event stream + ask-Gemini per camera/event.

**P3 — Nice to have:**
- Mobile responsive layout
- Loading skeletons + error boundaries
- Analytics/charts page
- Settings/team management page
- Search across events

**Future (not in MVP):**
- Live video feed via WebRTC: relay republishes camera streams as WebRTC. Lowest latency (~1s). Requires WebRTC signaling + TURN. Out of scope for MVP; revisit when snapshot polling proves insufficient.

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

# Live snapshot view (polling)
Worker → encode latest BGR frame as WebP every 2s → GCS latest/{camera_id}.webp
Frontend → GET /api/cameras/{id}/latest-frame → signed URL → <img> tag, refresh every 1-2s
NEVER stream raw video to cloud; only the most recent annotated/decoded frame at low fps.
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
- Don't add HLS or raw RTSP republishing for the live view in the MVP — use snapshot polling. WebRTC live video is a planned future feature, do not implement it without explicit instruction.
