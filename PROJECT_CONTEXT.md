# Nightwatch — Project Context (Interview Prep)

> Narrative/talking-points doc. `CLAUDE.md` is authoritative on what is actually
> built; if the two disagree, `CLAUDE.md` wins.

## 30-Second Pitch
Nightwatch is an AI-powered CCTV event-intelligence SaaS. Instead of humans watching camera feeds, it pulls RTSP streams, runs motion-gated local detection plus Gemini Vision analysis to describe what's happening (not just "motion detected"), and pushes structured events + real-time alerts (WhatsApp/email/webhook) to a multi-tenant dashboard. It also has a consumer onboarding path — a small LAN agent that lets non-technical users connect a home NVR (Hikvision/Dahua/CP Plus) without port-forwarding, by running the whole detection pipeline on a self-contained edge box on the customer's premises.

## Architecture — Default Path: Self-Contained Edge Box
```
NVR (LAN) ──RTSP──▶ Agent (Go) ──spawns──▶ pipeline sidecar (Python, agent/pipeline/)
                       │                        │
                       │        FFmpeg → motion gate → YOLO gate → Gemini Vision
                       │                        │
                       │                        ▼
                       │              Backend (FastAPI) ──▶ Postgres + GCS
                       │                        ├─▶ Redis (sessions, rate limit, alert cooldown)
                       │                        ├─▶ Alert engine ─▶ WhatsApp / Email / Webhook
                       │                        └─▶ WebSocket ─▶ Frontend (Next.js)
                       │
                       └─ control WebSocket (heartbeat + WebRTC signaling) ──▶ Backend
```

Detection happens on the customer's hardware. Only event payloads and on-demand
live view cross the network — there is no continuous video tunnel to the cloud.

**Cloud-VM fallback (opt-in, legacy):** `relay/` terminates an agent tunnel and
republishes it as local RTSP for a centrally-hosted `worker/`. Kept deployable
for direct-connect cameras and boxes too weak to run the sidecar.

| Service | Language | Role |
|---|---|---|
| `backend/` | Python / FastAPI | REST API, WebSocket, auth, alert engine, digest scheduler, credential broker |
| `agent/` | Go + Python | Edge box: ONVIF discovery, pairing, control WebSocket, embedded WebRTC answerer, supervised detection pipeline |
| `frontend/` | TypeScript / Next.js 16 (App Router) | Multi-tenant dashboard |
| `worker/` | Python | Cloud-VM fallback only — same pipeline logic, run centrally |
| `relay/` | Go | Cloud-VM fallback only — gRPC/WebRTC in, RTSP out |

## Tech Stack Highlights
- **Auth:** username/password (deliberately not email or JWT) — Argon2id hashing, AES-256-GCM encrypted opaque session tokens stored server-side in Redis, session binding to IP+User-Agent, brute-force lockout, idle (1hr) + absolute (24hr) expiry.
- **Multi-tenancy:** every query filters by `org_id` *and* applies per-site scoping (`users.sites_access`) — both halves are required. `super_admin` bypasses the org filter **by role**; it has its own org (`nightwatch-hq`) so it has somewhere to keep its own test hardware. `org_id IS NULL` is explicitly *not* the super-admin test. Enforced at the query layer, not RLS.
- **DB:** PostgreSQL via SQLAlchemy 2.0 async, Alembic migrations (no `create_all` in prod).
- **AI:** Gemini 2.5 Flash for vision, gated behind motion detection *and* a local YOLO26n ONNX pass (end-to-end/NMS-free export), with circuit breaker + confidence filtering on responses. Digest summaries run a single Gemini *text* call over event metadata only — no raw video ever reaches Gemini beyond individual motion-gated frames.
- **Credential brokering:** edge boxes hold no static secrets. They exchange a device token for short-lived (≤30min) Vertex AI tokens and signed GCS upload URLs, brokered per-call by the backend. Revoking the device token kills AI and storage access within one TTL window. On an edge box the static-API-key fallback is *deliberately disabled* — a transient broker outage must not silently re-introduce a long-lived key onto physically-accessible hardware.
- **Video privacy constraint:** raw video never leaves the premises. Only WebP snapshots + 10s H.264 clips go to GCS.
- **Live view fallback chain:** WebRTC (edge box answers directly; relay-proxied on the fallback path; coturn TURN for symmetric NAT/CGNAT) → MJPEG signed-URL stream (fallback deployments only) → snapshot polling. Each step degrades gracefully.

## Consumer Onboarding (Home Camera Plugin)
The hardest product problem: non-technical users have an NVR behind NAT with no port-forwarding skill. Solved with:
- A small Docker agent on the user's NAS/router/Pi, ONVIF auto-discovery + manual RTSP fallback per brand.
- One outbound-only, device-token-authenticated control WebSocket to the backend — no inbound ports, no relay hop.
- 6-digit pairing code (10-min TTL, single-use) → long-lived device token bound to the agent's pubkey, scoped to one org. The same token authenticates the pipeline sidecar's own backend calls.
- The box runs detection itself, so onboarding a home camera adds no cloud video processing at all.

## Notable Engineering Decisions (good interview material)

### The delete-orphan incident ("tell me about a bug")
**Symptom:** an org delete wiped far more than the org — cascaded through users, sites, cameras, and (via FK) every event.
**Root cause:** `DELETE /api/admin/orgs/{id}` called `db.delete(org)`, and the ORM relationships were declared `cascade="all, delete-orphan"`. One call cascade-deleted every child row, and FK cascades took it the rest of the way to events.
**Fix:** replaced hard deletes with a `SoftDeleteService` — `deleted_at` columns on the 5 deletable entities, explicit cascaded soft-delete/restore that mirrors the old cascade shape but reversibly, and removed the `delete-orphan` relationships entirely so a future accidental `db.delete()` can't cascade-destroy data again.
**Process note:** the fix was built and committed correctly the first time — but on an isolated worktree branch that never got merged to `main`, so the vulnerable code kept running for a while after the fix existed. Good illustration of why branch hygiene matters as much as the fix.

### The cross-tenant assignment leak
`GET /internal/assignments` returned *every camera in the database* rather than those belonging to the calling agent. Fixed by scoping to the agent and making the backend the single assignment authority, with a deterministic sticky bin-packer distributing cameras across a site's appliances. Verified to hold from 4 to 800 cameras.

### Deliberately declining features
Worth having ready, because "what did you choose *not* to build" is a real question:
- **Cross-camera re-identification:** declined. GPU-dependent and far more privacy-sensitive. Journeys are built from operator-drawn adjacency plus event timing instead, and the summary sentence is *templated, never model-generated*, so the "may or may not be the same person" caveat cannot drift into a certainty.
- **Footfall as absolute counts:** declined. It's tracking without re-ID, so it over-counts on occlusion and under-counts in crowds. The API returns `estimate: true` plus a caveat string so a client cannot render it as a turnstile figure by omission.
- **Fall detection:** not promised. Pose labels exist but there is no validated fallen state.

## Current Status
**Done:** backend (auth, CRUD, alert engine, WebSocket, admin, impersonation, digests, soft delete), edge-detection architecture (self-contained agent + pipeline sidecar + credential brokers + coturn), mall/estate scale (placement, self-sizing, fleet health, failover, retention, per-site budgets), cross-camera journeys, footfall, agentic camera setup, frontend (36 routes, onboarding tour, help widget, chat panel), CI/CD.

**Not yet done:** end-to-end test with a real physical camera (P0 — still the highest-value pre-pilot check), setup-run AI budget metering, applying proposed alert rules, per-site scheduled digests, Gemini token-usage instrumentation, analytics/charts page, cross-entity search.

## Likely Interview Angles This Project Supports
- **Distributed systems / real-time:** WebSocket fan-out per org, Redis-backed alert cooldown, adaptive frame sampling (1fps idle → 5fps active) with dedup, sticky bin-packing camera placement with failover reconciliation.
- **Security:** session design (why not JWT), multi-tenant isolation strategy, the org-filter-by-role rule, brute-force/lockout, HMAC-signed short-TTL stream URLs, and the no-standing-secrets credential broker for customer-owned hardware.
- **Cost engineering:** motion gate → YOLO gate → Gemini escalation ladder, per-site daily AI spend caps, single text call for digests. Ongoing: a CVPR-2025-derived foveated-sampling proposal (`docs/superpowers/specs/2026-08-20-foveated-sampling-design.md`) that is *gated behind its own evaluation* rather than built on the paper's word — a good example of treating a published result as a hypothesis about your own data.
- **Systems/networking:** NAT traversal (outbound-only control WebSocket, WebRTC P2P with coturn TURN fallback), and the architectural decision to delete a whole relay hop from the default path.
- **Incident/postmortem:** the delete-orphan cascade and the cross-tenant assignment leak.
- **Product judgement:** the declined-features list above.
