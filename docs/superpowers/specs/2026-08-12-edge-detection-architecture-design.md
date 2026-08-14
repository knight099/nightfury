# Edge Detection Architecture — Design

*Date: 2026-08-12*

## Problem

Today, event detection (motion gate → Gemini Vision → event packaging) runs in the cloud Worker, which requires either a direct RTSP connection to the camera (direct-connect path) or a continuous RTSP tunnel from the customer's LAN through Relay to a cloud Worker VM (home-camera/agent path). Both paths mean video is processed on cloud compute and, for the agent path, continuously tunneled to the cloud even when no one is watching. This drives cloud compute and bandwidth cost that scales with camera count rather than with actual usage.

## Goal

Move detection to run at the edge (on customer premises) for every camera, so the cloud only ever handles: (1) small event payloads (metadata + already-uploaded snapshot/clip references), and (2) on-demand live-view video, only while a viewer has the dashboard open. No continuous video reaches the cloud.

## Architecture

```
Camera (RTSP) → Edge box (customer premises: Pi / NAS / on-prem server)
                  │
                  ├─ Go agent process (edge mode)
                  │    - pairing (6-digit code → device token, pubkey-bound, per-org scoped)
                  │    - supervises Python detection sidecar as a child process
                  │      (spawns it, restarts on crash, merges its health into heartbeat)
                  │    - keeps ONE persistent, authenticated control WebSocket open to
                  │      Backend — carries heartbeat, events-in-flight signaling, AND
                  │      (new) WebRTC signaling (SDP/ICE) for live view requests
                  │    - embeds a WebRTC peer connection stack (pion/webrtc) — answers
                  │      view requests directly, no separate video-relay hop
                  │
                  └─ Python detection sidecar (existing Worker pipeline, unmodified logic)
                       - FFmpeg → motion gate → Gemini Vision → event packaging
                       - requests a signed GCS upload URL from Backend, uploads
                         snapshot/clip directly (no service-account key on device)
                       - sends events to Backend via the Go agent's local device-token
                         auth (no more static WORKER_API_KEY)
                       - existing SQLite offline queue, unchanged, drains on reconnect

Backend (unchanged contract, still no video):
  - /internal/events, /internal/heartbeat (now carrying merged agent+pipeline health)
  - issues signed GCS upload URLs (extends existing signed-URL service used for reads)
  - holds the control WebSocket per paired edge box; on a live-view request, mints a
    short-lived signed view request and forwards it down that channel, then relays the
    edge box's SDP answer/ICE candidates back to the frontend's WebRTC peer connection
  - never touches media — only small signaling messages, same as before

TURN server (coturn, cloud VM, public IP — fallback-only media relay):
  - standard, off-the-shelf coturn deployment, not custom code
  - only used when direct P2P fails (symmetric NAT/CGNAT — common on Indian home ISPs)
  - carries the fraction of sessions that can't go direct, not 100% of video like a
    always-on relay would

Media path: browser ⇄ edge box, ICE-negotiated (STUN first, TURN fallback) — never
            touches Backend.

Frontend (unchanged):
  - live view priority: WebRTC direct-or-TURN-fallback → MJPEG (Worker-VM-fallback
    deployments only) → snapshot polling
```

### Components changed — code reuse via duplication, not rewrites

The existing `relay/` and `worker/` code is **not rewritten**. It's **copy-pasted** into `agent/` as independent, standalone subdirectories — the top-level `relay/` and `worker/` folders stay exactly as they are today (still used for the cloud-VM fallback deployment), and `agent/` gets its own full copy so the edge-box install is self-contained (no cross-directory dependency back into the monorepo's `relay/`/`worker/` at install time).

```
relay/                   # UNCHANGED — stays as its own deployable module,
worker/                  # UNCHANGED — used for the cloud-VM fallback deployment

agent/
├── cmd/agent/            # existing Go entrypoint, extended: adds control-channel
│                            signaling handling, spawns/supervises the pipeline copy
├── webrtcsignal/         # COPY of relay's WebRTC-serving package (viewer.go etc.) —
│                            duplicated from relay/, not imported from it
└── pipeline/             # COPY of worker's Python pipeline — duplicated from
                             worker/, not imported from it (FFmpeg, motion gate,
                             Gemini Vision, event packaging, offline queue)
```

This is a deliberate trade: **two copies of the same logic must be kept in sync by hand** going forward (a Gemini prompt tweak, a motion-detection fix, a WebRTC bugfix — each needs to be applied in both `worker/`/`relay/` and `agent/pipeline/`/`agent/webrtcsignal/`). Flagging this explicitly so it's a known, accepted cost, not a surprise later.

| Component | Change |
|---|---|
| `agent/` (Go) | Extended to supervise its own copy of the pipeline and handle control-channel signaling. Gains its own copy of the WebRTC-serving code |
| `agent/webrtcsignal/` (copy of `relay/`) | Duplicated WebRTC-serving code. Runs embedded in the edge process, answering view requests directly, instead of as a separate always-on cloud relay VM |
| `agent/pipeline/` (copy of `worker/`) | Duplicated pipeline code. The only two behavioral differences from the `worker/` original: auth switches from static `WORKER_API_KEY` to the edge agent's local device-token handoff, and GCS upload switches from service-account key to Backend-issued signed upload URLs |
| `worker/`, `relay/` | Unchanged, kept as their own deployable modules for the cloud-VM fallback path |
| `backend/` | `/internal/heartbeat` payload extended to carry pipeline health alongside device/tunnel health. New/extended signed-URL endpoint for *uploads* (reads already supported). New token-broker endpoint issuing short-lived Gemini/Vertex AI access tokens to device-token-authenticated edge boxes (see below). Control-WebSocket signaling relay replaces the old `webrtc-offer` → relay-VM proxy for edge-box deployments (the fallback path's `webrtc-offer` → `relay/` proxy stays as-is). No auth/route removals — `WORKER_API_KEY` and the static Gemini key path can stay live for the Worker-VM-fallback deployment |
| `frontend/` | No changes to the priority chain, but the WebRTC leg now negotiates ICE (STUN/TURN) directly against the edge box for edge-box deployments |

### Deployment models

1. **Default — edge box.** Every new site gets one edge box running `agent/cmd/agent`, which supervises its own copy of the pipeline (`agent/pipeline/`) as a child process and answers live-view requests via its own copy of the WebRTC code (`agent/webrtcsignal/`). Fully self-contained install — nothing outside `agent/` is needed on the device. No per-site or shared relay VM needed for video; only a shared coturn TURN server (fallback path).
2. **Fallback — cloud Worker VM.** Unchanged, deployed from the original top-level `worker/` + `relay/` per today's existing instructions, using the static `WORKER_API_KEY` and direct service-account GCS access as it does today.

### Gemini credential handling on the edge box

Same threat as the GCS service-account key: a long-lived secret sitting on hardware that's physically accessible at a customer site is disproportionate blast radius if a device is stolen or its storage dumped. The edge-box pipeline does **not** hold a static Gemini API key.

- `agent/pipeline/` authenticates to Backend using the device token it already gets handed by `agent/cmd/agent` (same handoff used for event/heartbeat auth).
- Backend brokers a **short-lived Gemini/Vertex AI access token** (15–60 min TTL) in exchange, drawn from a real credential that only ever lives in Backend's secret store.
- The pipeline uses that token for its next batch of Vision calls, and requests a fresh one before it expires — same request-shape as the signed GCS upload URL flow, just for Vertex AI auth instead of GCS.
- If a device is stolen or its device token is revoked, its Gemini access dies within one TTL window — no separate manual key-rotation step needed.
- This does **not** reintroduce the "video to cloud" cost problem the rest of this design avoids: only a small token exchange crosses the network per TTL window, not image/video data. Motion-gated frames are sent straight to Gemini's API from the edge box as before — Backend brokers the *credential*, not the *call*.
- One static Gemini key stays live only for the Worker-VM-fallback deployment path (`worker/`, unchanged), since that already runs on cloud-controlled infrastructure, not customer-owned hardware.

## Data flow

**Pairing:** unchanged — 6-digit code (10-min TTL, single-use) → device token bound to agent pubkey, scoped to one `org_id`.

**Steady state (edge-box deployments):**
```
Edge box → single heartbeat (agent + pipeline health) → Backend, device-token auth
Edge box → event (references snapshot/clip already uploaded via signed URL) → Backend, device-token auth
```

**Live view (on demand only):** Frontend requests view → Backend verifies caller's org/session, mints a short-lived signed view request, forwards it to the target edge box over its existing control WebSocket → edge box's embedded WebRTC stack creates an SDP answer + gathers ICE candidates (STUN first) → Backend relays SDP/ICE back to the frontend's peer connection → media negotiates directly between browser and edge box, falling back to the coturn TURN relay only if a direct path can't be established. Backend and the (optional) TURN server never see this until a viewer opens the page.

**Uploads:** edge box requests a signed GCS upload URL from Backend, uploads snapshot/clip directly to GCS. No standing service-account credential file on the device.

## Error handling

- **Backend unreachable:** existing SQLite offline queue (already in the Worker pipeline) buffers events; drains on next successful heartbeat/reconnect. No new logic — it just runs on-edge now instead of in a cloud VM.
- **Python sidecar crash:** Go agent (child-process supervisor) restarts it and reports `pipeline: down` in the merged heartbeat until it recovers.
- **Control WebSocket down:** no signaling possible → live view unavailable for that camera, falls back to the frontend's existing MJPEG/snapshot-polling chain (Worker-VM-fallback deployments only — pure edge-box deployments have no MJPEG server, so this degrades to "live view unavailable, try again" for those). Detection and event delivery are unaffected — the sidecar's HTTPS calls to Backend don't depend on this channel.
- **Direct P2P fails (symmetric NAT/CGNAT):** ICE falls back to the coturn TURN relay automatically; if TURN is also unreachable, live view fails gracefully to the same fallback chain as above.
- **Gemini failure:** unchanged — existing one-retry-then-degraded-digest/event behavior in the sidecar.
- **Signed upload URL expired/fails:** sidecar retries with a fresh signed URL from Backend before giving up and queuing to the offline store.
- **Gemini access token expired/broker unreachable:** sidecar requests a fresh token before its current one's TTL runs out; if the broker itself is unreachable, Vision calls pause and events fall back to the offline queue (same as a Backend outage) rather than failing the whole pipeline.

## Migration / rollout

- New deployments default to the edge-box model; no changes required to Backend's external contract, so this ships independently of client-facing API changes.
- Existing cloud-VM Worker deployments keep running unmodified as the fallback path — no forced migration, no dual-write period, since `/internal/events` stays backward compatible (the heartbeat payload extension is additive).
- `relay/` and `worker/` stay in place, untouched; `agent/webrtcsignal/` and `agent/pipeline/` are new directories seeded by copying that code in — a one-time copy, not an ongoing sync mechanism (see the duplication trade-off called out above). The one exception: `webrtc-offer` route on Backend is reworked to signal over the control WebSocket for edge-box deployments instead of proxying to a relay VM — this IS an internal contract change between Backend and Agent, so backend + agent must ship together for this piece. The fallback path's existing `webrtc-offer` → `relay/` proxy behavior is untouched.
- Deploying coturn is a new piece of infra (previously explicitly out of scope per project rules) — called out here as a deliberate, explicit exception requested for this design, not a silent rule change.

## Non-goals

- Not changing the live-view priority chain in the frontend (still WebRTC → MJPEG → snapshot polling as fallbacks, just a different transport underneath the WebRTC leg).
- Not touching alerting, digests, or any other Backend subsystem beyond the heartbeat payload, the new signed-upload-URL endpoint, and the webrtc-offer signaling path.

## Open questions

- Signed upload URL endpoint: new route, or extend the existing signed-URL service (`app/services/gcs.py`) to also mint write-scoped URLs? (Recommend extending — same service, same signing key, just a different scope.)
- Gemini token broker: does this call the Google AI Studio API (simple API key, harder to scope/short-live) or move to Vertex AI (service-account-backed, natively supports short-lived OAuth tokens via IAM)? Vertex AI is the more natural fit for this broker pattern — flagging as an implementation-plan-level decision since it may mean re-pointing the existing Gemini client code at a different API surface.
- coturn sizing/hosting: single shared instance vs. per-region — not blocking for this design, can be decided at deploy time.
- Control WebSocket scaling: Backend needs one held connection per paired edge box (not per viewer) — control-plane traffic only (heartbeat + occasional signaling), but worth confirming Backend's serverless platform (Vercel Fluid Compute / Cloud Run) handles the expected device count of held connections before rollout at scale.
