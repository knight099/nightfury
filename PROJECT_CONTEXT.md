# Nightwatch — Project Context (Interview Prep)

## 30-Second Pitch
Nightwatch is an AI-powered CCTV event-intelligence SaaS. Instead of humans watching camera feeds, it pulls RTSP streams, runs motion-gated Gemini Vision analysis to describe what's happening (not just "motion detected"), and pushes structured events + real-time alerts (WhatsApp/email/webhook) to a multi-tenant dashboard. It also has a consumer onboarding path — a small LAN agent that lets non-technical users connect a home NVR (Hikvision/Dahua/CP Plus) without port-forwarding, by tunneling the stream through a cloud relay.

## Architecture — 5 Services, One Monorepo
```
Camera (RTSP/RTMP) ──▶ Worker (Python) ──▶ Backend (FastAPI) ──▶ Postgres + GCS
                                                  │
                                                  ├─▶ Redis (sessions, rate limit, alert cooldown)
                                                  ├─▶ Alert engine ─▶ WhatsApp / Email / Webhook
                                                  └─▶ WebSocket ─▶ Frontend (Next.js)

Home camera path:
NVR (LAN) ──▶ Agent (Go, on user's device) ──gRPC/WebRTC tunnel──▶ Relay (Go, cloud)
                                                                        │
                                                          republished as RTSP ──▶ Worker (same pipeline)
```

| Service | Language | Role | Approx size |
|---|---|---|---|
| `backend/` | Python / FastAPI | REST API, WebSocket, auth, alert engine, digest scheduler | ~7.3k LOC, 90 routes, 38 test files |
| `worker/` | Python | RTSP/RTMP ingest → motion detection → Gemini Vision → event packaging → GCS upload | ~3.4k LOC, 8 test files |
| `frontend/` | TypeScript / Next.js 14 (App Router) | Multi-tenant dashboard | ~9.6k LOC, 12 pages |
| `agent/` | Go | LAN agent for home users — ONVIF discovery, pairing, tunnel client | part of ~4.2k LOC (agent+relay) |
| `relay/` | Go | Cloud tunnel terminator — gRPC/WebRTC in, RTSP out, WebRTC viewer signaling | part of ~4.2k LOC (agent+relay) |

## Tech Stack Highlights
- **Auth:** username/password (deliberately not email or JWT) — Argon2id hashing, AES-256-GCM encrypted opaque session tokens stored server-side in Redis, session binding to IP+User-Agent, brute-force lockout, idle (1hr) + absolute (24hr) expiry.
- **Multi-tenancy:** every table has `org_id`; every query filters by it except `super_admin` (which has `org_id = null`). Enforced at the query layer, not RLS.
- **DB:** PostgreSQL 15 via SQLAlchemy 2.0 async, Alembic migrations (no `create_all` in prod).
- **AI:** Gemini 2.0 Flash for vision, gated behind a motion-detection pre-filter (~80% API cost reduction), circuit breaker + confidence filtering on responses. Digest summaries run a single Gemini *text* call over event metadata only — no raw video ever reaches Gemini or leaves the worker.
- **Video privacy constraint:** raw video never leaves the worker/edge. Only WebP snapshots + 10s H.264 clips go to GCS. Live view is MJPEG (worker-local) or WebRTC-via-relay — never raw RTSP proxied to the browser.
- **Live view fallback chain:** WebRTC (via relay, for tunneled home cameras) → MJPEG signed-URL stream (worker-local) → snapshot polling (GCS, 1–2s). Each step degrades gracefully if the previous is unavailable.

## Consumer Onboarding (Home Camera Plugin)
The hardest product problem: non-technical users have an NVR behind NAT with no port-forwarding skill. Solved with:
- A small Docker agent on user's NAS/router/Pi, ONVIF auto-discovery + manual RTSP fallback per brand.
- Outbound-only TLS gRPC tunnel to the relay (WebRTC/STUN/TURN fallback after 3 non-auth connect failures — transport is sticky per session, no flapping).
- 6-digit pairing code (10-min TTL, single-use) → long-lived device token bound to the agent's pubkey, scoped to one org.
- Relay republishes each tunneled camera as local RTSP, so the existing worker pipeline needs zero changes downstream.

## Notable Engineering Decision: the delete-orphan Incident (good "tell me about a bug" story)
**Symptom:** an org delete wiped far more than the org — cascaded through users, sites, cameras, and (via FK) every event.
**Root cause:** `DELETE /api/admin/orgs/{id}` called `db.delete(org)`, and the ORM relationships (`Organization.users/sites/cameras`) were declared `cascade="all, delete-orphan"`. One call triggered SQLAlchemy to cascade-delete every child row, and FK cascades took it the rest of the way to events.
**Fix:** replaced hard deletes with a `SoftDeleteService` — `deleted_at` columns on the 5 deletable entities, explicit cascaded soft-delete/restore logic that mirrors the old cascade shape but reversibly, and removed the `delete-orphan` relationships entirely so a future accidental `db.delete()` can't cascade-destroy data again. Every list/auth/ingestion query updated to exclude soft-deleted rows; admin UI got a "show deleted" + restore flow.
**Process note worth mentioning in an interview:** the fix was built and committed correctly the first time — but on an isolated worktree branch that never got merged into `main`, so the vulnerable code kept running in "production" for a while after the fix existed. Good illustration of why branch hygiene / merge discipline matters as much as the fix itself.

## Current Status
**Done:** backend (auth, CRUD, alert engine, WebSocket, admin, digests, soft delete), worker (full pipeline + offline SQLite queue), frontend (6+ pages, onboarding tour, help widget, chat panel), agent + relay (device-initiated pairing, WebRTC live view), Terraform + GitHub Actions CI/CD, full test suites on backend/worker.

**Not yet done:** end-to-end test with a real physical camera (P0), loading skeletons/error boundaries, analytics/charts page, cross-entity search, TURN server for production NAT traversal (WebRTC currently LAN-reliable only).

## Likely Interview Angles This Project Supports
- **Distributed systems / real-time:** WebSocket fan-out per org, Redis-backed alert cooldown, adaptive frame sampling (1fps idle → 5fps active) with dedup.
- **Security:** session design (why not JWT), multi-tenant isolation strategy, brute-force/lockout, HMAC-signed short-TTL stream URLs.
- **Cost engineering:** motion-gate before Gemini calls, per-org daily Gemini spend cap, single text call for digests instead of per-event summarization.
- **Systems/networking:** NAT traversal problem (gRPC-first, WebRTC/STUN/TURN fallback, sticky transport), RTSP↔WebRTC bridging at the relay.
- **Incident/postmortem:** the delete-orphan cascade bug above — root cause, fix design, and the branch-merge process gap that let it linger.
