# Nightwatch

AI-powered CCTV event-intelligence SaaS. Instead of humans watching camera feeds, Nightwatch pulls RTSP/RTMP streams, runs motion-gated local object/pose detection plus Gemini Vision analysis to describe what's actually happening, and pushes structured events + real-time alerts (WhatsApp/email/webhook) to a multi-tenant dashboard.

It also has a consumer onboarding path: a small LAN agent lets non-technical users connect a home NVR (Hikvision/Dahua/CP Plus, etc.) without port-forwarding, by tunneling the stream through a cloud relay.

## Architecture

```
Camera (RTSP/RTMP) ──▶ Worker (Python) ──▶ Backend (FastAPI) ──▶ Postgres + GCS
                                                 │
                                                 ├─▶ Redis (sessions, rate limit, alert cooldown)
                                                 ├─▶ Alert engine ─▶ WhatsApp / Email / Webhook
                                                 └─▶ WebSocket ─▶ Frontend (Next.js)

Home camera path:
NVR (LAN) ──▶ Agent (Go, user's device) ──gRPC/WebRTC tunnel──▶ Relay (Go, cloud)
                                                                     │
                                                       republished as RTSP ──▶ Worker (same pipeline)
```

| Service | Language | Role |
|---|---|---|
| [`backend/`](backend/) | Python / FastAPI | REST API, WebSocket, auth, alert engine, digest scheduler |
| [`worker/`](worker/) | Python | RTSP/RTMP ingest → motion detection → local YOLO gate → pose/sequence tracking → Gemini Vision → event packaging → GCS upload |
| [`frontend/`](frontend/) | TypeScript / Next.js 14 (App Router) | Multi-tenant dashboard |
| [`agent/`](agent/) | Go | LAN agent for home users — ONVIF discovery, pairing, tunnel client |
| [`relay/`](relay/) | Go | Cloud tunnel terminator — gRPC/WebRTC in, RTSP out, WebRTC viewer signaling |

## Key design decisions

- **Auth:** username/password (not email or JWT) — Argon2id hashing, AES-256-GCM encrypted opaque session tokens in Redis, session binding to IP+User-Agent, brute-force lockout, idle (1hr) + absolute (24hr) expiry.
- **Multi-tenancy:** every table has `org_id`; every query filters by it except `super_admin` (`org_id = null`).
- **Video privacy:** raw video never leaves the worker/edge — only WebP snapshots + 10s H.264 clips reach cloud storage. Live view is MJPEG (worker-local) or WebRTC-via-relay, never raw RTSP proxied to the browser.
- **Cost engineering:** motion detection gates all Gemini calls; a local YOLOv8n ONNX pass further gates/short-circuits Gemini for simple person/vehicle/animal/intrusion detections; digest summaries use one Gemini text call over event metadata instead of per-event summarization.
- **Pose/sequence tracking:** an optional per-camera step-sequence engine (local YOLOv8-pose + IoU tracker + state machine) flags skipped or stalled steps in a defined procedure (e.g. retail checkout compliance) without any additional Gemini calls.

## Running locally

```bash
./start.sh
```

Starts backend → relay → worker → agent → frontend in order, using cloud Postgres (Neon) + cloud Redis (Upstash) — no Docker required for dependencies. See [`CLAUDE.md`](CLAUDE.md) for prerequisites, per-service run instructions, and production deployment notes.

## Documentation

- [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) — full agent/developer rules: running locally, production deployment, cross-service contracts, current build status.
- [`MASTER_PLAN.md`](MASTER_PLAN.md), [`MVP_PLAN.md`](MVP_PLAN.md) — architecture and MVP scope planning.
- [`docs/superpowers/specs/`](docs/superpowers/specs/) — design specs for individual features.
- [`docs/superpowers/plans/`](docs/superpowers/plans/) — implementation plans for individual features.
- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) — condensed project overview and notable engineering decisions.
- Per-service rules: `backend/CLAUDE.md`, `worker/CLAUDE.md`, `frontend/CLAUDE.md`.
