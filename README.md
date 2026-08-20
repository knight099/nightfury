# Nightwatch

AI-powered CCTV event-intelligence SaaS. Instead of humans watching camera feeds, Nightwatch pulls RTSP/RTMP streams, runs motion-gated local object/pose detection plus Gemini Vision analysis to describe what's actually happening, and pushes structured events + real-time alerts (WhatsApp/email/webhook) to a multi-tenant dashboard.

It also has a consumer onboarding path: a small LAN agent lets non-technical users connect a home NVR (Hikvision/Dahua/CP Plus, etc.) without port-forwarding. The agent is a **self-contained edge box** — it runs the detection pipeline on the customer's own premises and talks directly to the backend.

## Architecture

**Default deployment — self-contained edge box, direct to backend:**

```
NVR (LAN) ──RTSP──▶ Agent (Go) ──spawns──▶ pipeline sidecar (Python)
                       │                        │
                       │        FFmpeg → motion gate → YOLO gate → Gemini Vision
                       │                        │
                       │                        ▼
                       │              Backend (FastAPI) ──▶ Postgres + GCS
                       │                        │
                       │                        ├─▶ Redis (sessions, rate limit, alert cooldown)
                       │                        ├─▶ Alert engine ─▶ WhatsApp / Email / Webhook
                       │                        └─▶ WebSocket ─▶ Frontend (Next.js)
                       │
                       └─ control WebSocket (heartbeat + WebRTC signaling) ──▶ Backend
```

Detection runs on the edge box. No continuous video tunnel to the cloud — only small event payloads and on-demand live view ever cross the network. The box holds no static secrets: it exchanges its device token for short-lived Vertex AI tokens and signed GCS upload URLs, brokered per-call by the backend.

**Cloud-VM fallback path (opt-in, legacy):** for direct-connect cameras or edge boxes that can't run the pipeline sidecar, `relay/` terminates an agent tunnel and republishes it as local RTSP for a centrally-hosted `worker/`. Not the default — don't reach for it without a specific reason.

| Service | Language | Role |
|---|---|---|
| [`backend/`](backend/) | Python / FastAPI | REST API, WebSocket, auth, alert engine, digest scheduler, credential broker |
| [`agent/`](agent/) | Go + Python | **Edge box (default path).** ONVIF discovery, pairing, control WebSocket, embedded WebRTC answerer, and a supervised copy of the detection pipeline in [`agent/pipeline/`](agent/pipeline/) |
| [`frontend/`](frontend/) | TypeScript / Next.js 16 (App Router) | Multi-tenant dashboard |
| [`worker/`](worker/) | Python | *Cloud-VM fallback only.* Same pipeline logic, run centrally |
| [`relay/`](relay/) | Go | *Cloud-VM fallback only.* gRPC/WebRTC tunnel terminator, RTSP republisher |

## Key design decisions

- **Auth:** username/password (not email or JWT) — Argon2id hashing, AES-256-GCM encrypted opaque session tokens in Redis, session binding to IP+User-Agent, brute-force lockout, idle (1hr) + absolute (24hr) expiry.
- **Multi-tenancy:** every table has `org_id`; every query filters by it *and* applies per-site scoping. `super_admin` bypasses the org filter **by role** — it has its own org (`nightwatch-hq`), so `org_id` is never null and must never be used as the super-admin test.
- **Video privacy:** raw video never leaves the premises — only WebP snapshots + 10s H.264 clips reach cloud storage. On the default path, motion-gated frames go straight from the edge box to Vertex/Gemini, never through backend, worker, or relay.
- **No standing secrets on customer hardware:** edge boxes get short-lived (≤30min) Vertex AI tokens and signed GCS upload URLs brokered against their device token — no service-account key, no static Gemini key. Revoking the device token kills AI access within one TTL window.
- **Cost engineering:** motion detection gates all Gemini calls; a local YOLOv8n ONNX pass further gates/short-circuits Gemini for simple person/vehicle/animal/intrusion detections; digest summaries use one Gemini text call over event metadata instead of per-event summarization.
- **Pose/sequence tracking:** an optional per-camera step-sequence engine (local YOLOv8-pose + IoU tracker + state machine) flags skipped or stalled steps in a defined procedure without any additional Gemini calls.
- **Live view fallback chain:** WebRTC (edge box answers directly over its control WebSocket; relay-proxied on the fallback path, with coturn TURN for symmetric NAT) → MJPEG worker stream (fallback deployments only) → snapshot polling. Never raw RTSP proxied to the browser, and never media through the backend.
- **Honest estimates:** footfall counting and cross-camera journeys are built on tracking *without* re-identification, and both surface their caveats in the API rather than rendering as certainties.

## Running locally

```bash
./start.sh
```

Starts backend → relay → worker → agent → frontend in order, using cloud Postgres (Neon) + cloud Redis (Upstash) — no Docker required for dependencies. See [`CLAUDE.md`](CLAUDE.md) for prerequisites, per-service run instructions, and production deployment notes.

## Documentation

- [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) — full agent/developer rules: running locally, production deployment, cross-service contracts, current build status. **These two are mirrors — edit both.**
- [`MASTER_PLAN.md`](MASTER_PLAN.md), [`MVP_PLAN.md`](MVP_PLAN.md) — original architecture and MVP scope planning. Historical: written before the edge-detection rearchitecture, so treat `CLAUDE.md` as authoritative where they disagree.
- [`docs/superpowers/specs/`](docs/superpowers/specs/) — design specs for individual features.
- [`docs/superpowers/plans/`](docs/superpowers/plans/) — implementation plans for individual features.
- [`nightwatch-layer3-implementation-plan.md`](nightwatch-layer3-implementation-plan.md) — future workstream (alert verification, embedding/search, agent-summarize). Not started.
- Per-service rules: `backend/CLAUDE.md`, `worker/CLAUDE.md`, `frontend/CLAUDE.md`, `agent/pipeline/CLAUDE.md`.
