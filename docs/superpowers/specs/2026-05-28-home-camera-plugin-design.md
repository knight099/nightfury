# Home-Camera Plugin & Time-Window Summaries — Design Spec

**Date:** 2026-05-28
**Status:** Draft (pending user review)
**Owner:** Nightwatch

## 1. Goal

Let non-technical home users connect their existing CCTV NVRs (CP Plus, Hikvision, Dahua, Reolink, generic ONVIF) to Nightwatch and get human-readable summaries of what happened over any time window — without needing a PC, port-forwarding, or static IPs.

Two user-facing capabilities:

1. **Plug in a home NVR** in under 10 minutes via a small LAN agent the user installs on a NAS / OpenWRT router / Raspberry Pi.
2. **Get summaries** — auto-scheduled morning recap (last night) and evening recap (today), plus on-demand custom-range digests, delivered to the dashboard and via WhatsApp.

## 2. Non-goals

- Per-vendor cloud SDK integrations (Ring, Nest, Tapo Cloud) — out of scope.
- Native mobile app — reuse existing Nextjs dashboard (mobile-responsive) + WhatsApp.
- Streaming raw video to the cloud worker without an agent — explicitly avoided (CGNAT, security).
- Supporting users behind CGNAT *without* an agent — the agent's outbound tunnel handles this cleanly; no port-forwarding is ever required.
- Sending raw video frames to Gemini for digests — digests use event metadata only.

## 3. Decisions made during brainstorm

| Question | Choice |
|---|---|
| Plugin shape | Standalone consumer onboarding flow with ONVIF auto-discovery |
| Capture point | Cloud relay via tiny LAN agent (no PC, no port-forwarding) |
| Summary UX | Auto-scheduled digests (morning + evening) + on-demand custom range |
| Delivery | Existing web dashboard + WhatsApp |
| Onboarding | ONVIF auto-discover with manual RTSP fallback per brand |
| Transport | gRPC primary, WebRTC fallback if gRPC fails 3× with non-auth errors |

## 4. Architecture

```
┌─ User's home ──────────────┐         ┌─ Nightwatch cloud ─────────────┐
│  NVR ── RTSP/ONVIF ──┐     │         │                                │
│                      ▼     │         │  ┌─ Relay (NEW) ──────────┐    │
│            ┌─────────────┐ │  TLS    │  │ - terminates tunnel    │    │
│            │ LAN Agent   │◄┼─tunnel──┼──► - republishes per-cam  │    │
│            │  (NEW)      │ │ gRPC/   │  │   as local RTSP        │    │
│            └─────────────┘ │ WebRTC  │  └────────────────────────┘    │
│                            │         │             │                  │
└────────────────────────────┘         │             ▼                  │
                                       │     existing Worker            │
                                       │     (FFmpeg + Gemini Vision)   │
                                       │             │                  │
                                       │             ▼                  │
                                       │     existing Backend           │
                                       │     (events, alerts, WS)       │
                                       │             │                  │
                                       │             ▼                  │
                                       │  ┌─ Digest service (NEW) ─┐    │
                                       │  │ scheduled + on-demand  │    │
                                       │  │ event-metadata summary │    │
                                       │  └────────────────────────┘    │
                                       │             │                  │
                                       │             ▼                  │
                                       │   existing WhatsApp/email      │
                                       │   alert engine + frontend      │
                                       └────────────────────────────────┘
```

**New components:** `agent/` (Go binary), `relay/` (Go service), `backend/app/services/digest/` (Python module inside existing backend).

**Untouched:** worker pipeline, event schema, alert engine, WS broadcast, auth, frontend shell, DB models for orgs/users/sites/cameras/events/alerts.

## 5. Components

### 5.1 LAN Agent (`agent/`)

New top-level service. Single static Go binary (~15 MB) packaged as `nightwatch/agent:latest` Docker image and a flashable ARM image for Pi-class boxes.

**Responsibilities:**
- ONVIF WS-Discovery on LAN (UDP 3702) to find NVRs.
- Manual RTSP URL fallback flow via the agent's local web UI on `:8765`.
- Pair with cloud once via short code; persist long-lived device token bound to agent pubkey.
- Maintain outbound tunnel to relay; multiplex N camera streams over it.
- Heartbeat to backend (extended `/internal/heartbeat` with agent metadata: version, transport, machine_id).
- Auto-update on a stable channel (signed releases).

**Transport:**
- **Primary:** gRPC bidi-stream over TLS/443. Each camera stream = framed RTP packets.
- **Fallback:** WebRTC. Triggered if gRPC connect fails 3× with connect/timeout errors (auth errors do NOT trigger fallback). Signaled via small HTTPS endpoint on relay; SCTP data channel per camera carrying the same framed payload. Public STUN; we host TURN for last-resort.
- Sticky per session, re-evaluated on reconnect. Stored in `agents.transport`.

**Why Go:** small static binary, trivial cross-compile (arm64/armv7/amd64), good gRPC + Pion (WebRTC) libraries, no Python runtime to ship to user devices.

### 5.2 Relay service (`relay/`)

New cloud service. Sits between agents and the existing worker.

**Responsibilities:**
- Terminate gRPC tunnels (one connection per agent, multiplexed cameras).
- Terminate WebRTC peer connections from fallback agents.
- For each connected camera, expose a local-only RTSP URL `rtsp://relay-internal:8554/<camera_id>` that the worker pulls from. Worker config gets this URL — that's the only worker-facing change.
- Auth: device tokens (issued during pairing) → maps to `org_id` + allowed `camera_ids`.
- Per-camera bounded buffers; on overflow drop oldest frames and emit a metric. Never block agent.
- Metrics: bytes in, drops, reconnects, transport per camera.

**Implementation:** Go (shares protobuf with agent). Embeds gortsplib for the inner RTSP server.

### 5.3 Digest service (`backend/app/services/digest/`)

Lives inside existing backend (not a new service).

**Scheduled digests:**
- Per-org per-slot, run by APScheduler (or a Postgres-backed job table) in the org's timezone.
- Defaults: 07:00 local "last night recap" (covers prior 22:00–06:59), 19:00 local "today recap" (covers 07:00–18:59).
- Configurable per org via `digest_preferences`.

**On-demand digests:**
- New API: `POST /api/digests` body `{ start, end, camera_ids?, site_id? }` → 202 + `digest_id`. Frontend subscribes via existing WS for `digest.ready`.
- Range hard-capped at 7 days; longer ranges return 400.
- Per-user rate limit: 10/hour. Per-org daily Gemini spend cap (env-configurable).

**Both share the same core:**
1. Query `events` where `created_at` in `[start, end]` and `org_id` matches, ordered by time, capped at 200. If more, sample evenly across the window.
2. Build a compact prompt: per-event `time, camera_name, ai_summary, severity, label`. No images sent.
3. Call Gemini 2.5 with structured-output schema:
   ```
   { headline, period, total_events, by_severity, narrative, highlights[{time,camera,why_notable}], quiet_periods[] }
   ```
4. Persist to `digests` table.
5. Render two formats:
   - **WhatsApp:** headline + 3-line narrative + top 3 highlights + dashboard link. Reuses existing alert engine's WhatsApp transport with a new template.
   - **Dashboard view:** full structured render with snapshot thumbnails fetched lazily per highlight via signed URLs.

**Empty windows:** skip Gemini entirely; send templated "all quiet" digest.
**Gemini failure:** retry once; on second failure persist a degraded fallback digest built from event metadata (count + severities + raw event list) with `payload.degraded=true`. Users always receive something.

### 5.4 Onboarding flow (frontend changes)

New `/onboard` route:
1. **"Install the Nightwatch Agent"** — choose device (NAS / Router with Docker / Pi / Other) → copy-paste install command OR download flashable image.
2. **"Pair your agent"** — show 6-digit code; agent prompts user for it on first run; pairing succeeds → org gets a registered agent.
3. **"Find your cameras"** — agent reports ONVIF discoveries; user picks which to enable, enters NVR credentials once. If discovery returns nothing → guided "find your RTSP URL" flow with brand picker (CP Plus, Hikvision, Dahua, Reolink, Tapo, generic).
4. **"Test stream"** — relay confirms a frame arrived; user names the camera; done.

New `/digests` page:
- Preset chips: Last night / Today / This week.
- Custom range picker.
- History of past digests (paginated).
- Settings: enable/disable scheduled morning/evening, change schedule times, WhatsApp on/off, email on/off.

## 6. Data flow

### 6.1 Live event flow (per camera, steady state)

```
NVR ──RTSP──► Agent ──framed RTP over gRPC/WebRTC──► Relay
                                                       │
                                       republished as RTSP
                                                       ▼
                                              existing Worker
                                          (motion → Gemini → event package)
                                                       │
                                                       ▼
                                              POST /internal/events
                                                       │
                                                       ▼
                                              existing pipeline:
                                              DB → alerts → WS → frontend
```

### 6.2 Pairing flow (one-time)

```
User  ─► Frontend: "Pair agent" ─► Backend: POST /api/agents/pair-codes
                                       │ creates row { code, org_id, expires_at=10min }
                                       ▼
                                   returns 6-digit code
Agent (fresh install) ─► local web UI prompts user for code
                              │
                              ▼ POST /api/agents/pair  { code, agent_pubkey, machine_id }
                              ▼
                       Backend: validates code, mints device_token (long-lived,
                                bound to agent_pubkey), inserts into agents table
                              │
                              ▼ returns { device_token, relay_url, org_id }
Agent: stores token, opens tunnel to relay
```

### 6.3 Digest flow (scheduled)

```
Scheduler tick ─► for each org with digests enabled:
                    range = computeRange(slot, org.timezone)
                    events = SELECT … WHERE org_id=? AND created_at BETWEEN ?…?
                              ORDER BY created_at LIMIT 200
                    if len(events) == 0: send "all quiet" digest, skip Gemini
                    else:
                       payload = gemini.summarize(events_compact)
                       INSERT INTO digests (...)
                       alerts.sendWhatsApp(org.whatsapp_number, render(payload))
                       (web dashboard reads from digests table)
```

### 6.4 Digest flow (on-demand)

Same core triggered by `POST /api/digests`. Returns 202 + `digest_id`; frontend subscribes via existing WS for `digest.ready`.

## 7. Schema changes

### 7.1 New tables

```sql
-- Agent registration
CREATE TABLE agents (
  id                 UUID PK,
  org_id             UUID FK organizations,
  machine_id         TEXT,                 -- stable hash from agent host
  pubkey             TEXT,
  device_token_hash  TEXT,                 -- argon2 of issued token
  version            TEXT,
  transport          TEXT,                 -- 'grpc' | 'webrtc' | null
  last_seen_at       TIMESTAMPTZ,
  status             TEXT,                 -- 'online' | 'offline' | 'unpaired'
  created_at         TIMESTAMPTZ,
  UNIQUE (org_id, machine_id)
);

-- Short-lived pairing codes
CREATE TABLE agent_pair_codes (
  code         TEXT PK,                    -- 6-digit
  org_id       UUID FK organizations,
  created_by   UUID FK users,
  expires_at   TIMESTAMPTZ,
  consumed_at  TIMESTAMPTZ
);

-- Persisted digests (scheduled + on-demand)
CREATE TABLE digests (
  id                  UUID PK,
  org_id              UUID FK organizations,
  kind                TEXT,                -- 'scheduled_morning' | 'scheduled_evening' | 'on_demand'
  range_start         TIMESTAMPTZ,
  range_end           TIMESTAMPTZ,
  event_count         INT,
  payload             JSONB,
  delivered_channels  TEXT[],              -- ['whatsapp','dashboard']
  created_at          TIMESTAMPTZ,
  requested_by        UUID FK users NULL   -- null for scheduled
);
CREATE INDEX ON digests (org_id, range_end DESC);

-- Per-org digest preferences
CREATE TABLE digest_preferences (
  org_id              UUID PK FK organizations,
  morning_enabled     BOOLEAN DEFAULT true,
  morning_local_time  TIME    DEFAULT '07:00',
  evening_enabled     BOOLEAN DEFAULT true,
  evening_local_time  TIME    DEFAULT '19:00',
  whatsapp_enabled    BOOLEAN DEFAULT true,
  email_enabled       BOOLEAN DEFAULT false
);
```

### 7.2 Existing schema additions

- `organizations`: add `timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata'`, `whatsapp_number TEXT NULL`.
- `cameras`: add `agent_id UUID NULL FK agents`. Worker config consults this to choose between direct RTSP and the relay URL.

## 8. Error handling

### 8.1 Agent ↔ Relay tunnel
- Reconnect with exponential backoff (1s → 30s cap, jitter), forever.
- gRPC fails 3× with connect/timeout → switch to WebRTC, mark `agents.transport='webrtc'`. Auth errors do NOT trigger fallback.
- Reconnect resets the per-camera RTSP republish on relay; worker's existing FFmpeg auto-reconnect handles the gap.
- Per-camera bounded buffers on relay; overflow drops oldest, emits metric.

### 8.2 NVR misbehavior
- ONVIF discovery returns nothing → onboarding falls back to manual brand-picker flow.
- RTSP auth fails on agent side → surface clear error in dashboard ("NVR rejected the password"), not generic "camera offline."
- NVR drops stream → agent retries locally with backoff; agent stays `online`, camera flips to `offline` via existing camera-status mechanism.

### 8.3 Pairing
- Expired or consumed codes → clear user message, ask for fresh code.
- Codes are single-use, 10-min TTL, per-org. Rate limit: 5/hour per user.

### 8.4 Digest generation
- Empty window → templated "all quiet" digest, no Gemini call.
- Gemini failure → retry once; second failure → degraded fallback digest from event metadata, `payload.degraded=true`.
- Range > 7 days for on-demand → 400 with message to narrow.
- > 200 events → sample evenly across window.
- Per-org daily Gemini spend cap → on-demand returns 429; scheduled still runs.

### 8.5 WhatsApp delivery
- Reuses existing alert-engine retry + dead-letter logic.
- Permanent failure → digest still in dashboard; log delivery failure on `digests.delivered_channels`.

### 8.6 Auth & multi-tenancy
- Agent device tokens scoped strictly to one `org_id`.
- Relay rejects any stream tagged with a `camera_id` not in the token's org.
- Same `org_id` filter on every digest query. super_admin bypass works as elsewhere.

## 9. Testing

### 9.1 Unit
- Digest event-compaction + sampling logic (deterministic).
- Pair-code lifecycle (mint, consume, expire, reject reuse).
- Transport-fallback decision (which errors flip gRPC→WebRTC, which don't).

### 9.2 Integration (cloud side)
- Spin up relay + worker with a stubbed agent pushing recorded RTSP via gRPC; assert worker emits events normally.
- Same with WebRTC transport.
- Scheduled digest end-to-end: seed events → trigger tick → assert `digests` row + WhatsApp transport invoked with correct payload.
- Authz negative test: agent of org A cannot publish to camera of org B.

### 9.3 Agent-side
- Go unit tests: ONVIF parser, manual-URL validator, pair flow.
- "Loopback" mode connecting to a local relay stub, runnable in CI.

### 9.4 Manual / pilot
- One real CP Plus NVR + 2 cameras; agent on a Pi; full flow including 24h of scheduled digests. Used to calibrate digest prompt and "all quiet" thresholds.
- Network-fault drill: kill agent's internet for 60s, confirm clean reconnect, no duplicate events.

### 9.5 Explicitly NOT tested up front
- Every NVR brand. Test CP Plus, Hikvision, one generic ONVIF cam. Long-tail brands route through the manual-URL flow.

## 10. Rollout

1. Build and ship `relay/` + agent skeleton with gRPC transport only. Internal alpha with one Pi + CP Plus NVR.
2. Add WebRTC fallback. Test on a hostile network (corporate WiFi, restrictive ISP).
3. Build digest service + `/digests` page + WhatsApp template. Pilot with internal team using existing camera setup.
4. Onboarding `/onboard` flow + brand-specific manual fallback.
5. Closed beta with 5 home users.
6. Public.

## 11. Open questions

- TURN hosting cost — bound expected usage, decide self-hosted (coturn on small VM) vs managed (Twilio/Cloudflare).
- Auto-update channel for the agent — signing infra and rollback story.
- Should digests include video clips or just thumbnail snapshots? (Default: snapshots only, for bandwidth.)
