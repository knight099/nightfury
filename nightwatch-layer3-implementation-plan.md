# NightWatch — Layer 2/3 Implementation Plan
### Alert Verification + Embedding/Search + Agent/Summarize Layer + Production-Readiness Hardening
*Hand-off document for implementation. All code to be written fresh against the real NightFury repo — no cloning of third-party repositories, no NVIDIA NIM dependencies. Architecture patterns are informed by NVIDIA VSS / NVIDIA-AI-Blueprints (`rag`, `aiq`) but reimplemented independently on NightFury's own stack. Production-readiness tooling recommendations are open-source/free-or-minimal-cost, license-vetted (see §6 for full sanity check).*

---

## Document map
- **§1–3**: Layer 2/3 feature build (Alert Verification, Embedding/Search, Agent/Summarize) — original scope
- **§4**: Build order for §1–3
- **§5**: Open questions to resolve before/during §1–3
- **§6**: Production-readiness hardening — infra, security, testing, demo polish, MLOps, India-specific — to be sequenced around or after §1–3 per the priority list in §6.9

---

## 0. Scope and non-goals

**In scope for this build:**
1. Alert Verification step (fixes false-positive alerts + the fire-and-forget notification bug)
2. Embedding + Search layer (pgvector-based "search my camera history")
3. Agent/Summarize layer (LangGraph-style plan-and-execute over event history, citation-grounded)

**Explicitly out of scope for this build:**
- RTVI/Pipecat live conversational "ask a camera a question" (Stage 2 — gated on developer pull signal per prior roadmap)
- Any Jetson/DeepStream edge tier work
- TAO action-classifier training (separate offline workstream)
- Any NVIDIA NIM microservice, Cosmos/Nemotron model, or Elastic-licensed container — not to be imported, called, or deployed anywhere in this build

**License posture:** All three components below are original NightWatch implementations. They are *architecturally informed* by patterns published in NVIDIA's VSS docs and the Apache-2.0 `NVIDIA-AI-Blueprints/rag` and `aiq` repos (e.g., "plan-and-execute over a vector-indexed event store," "verify before alert," "citation-grounded generation") — no code, containers, or models from those repos are to be cloned, imported, or called. This should be built the same way you'd implement a design pattern you read about in a blog post: understand the shape, write it in NightWatch's own code, against NightWatch's own models (Gemini/YOLO/Moondream), NightWatch's own database.

---

## 1. Component A — Alert Verification

### 1.1 Purpose
Insert a verification pass between "Gemini Vision confirms an event" and "WhatsApp/email fires," to reduce false-positive alerts and to fix the existing fire-and-forget notification-dispatch bug by making notification dispatch the natural next stage of an async pipeline instead of an inline blocking call.

### 1.2 Where it sits in the existing pipeline
Existing flow (per NightFury's documented architecture):
```
Motion Gate → YOLO Gate → Gemini Vision (event detected) → Alert eval + notification (inline, blocking) → WS broadcast
```
New flow:
```
Motion Gate → YOLO Gate → Gemini Vision (event detected) 
  → [NEW] Alert Verification Queue (async)
      → re-fetch clip/frames around event timestamp
      → second, narrower VLM prompt: "does this clip specifically confirm {rule}?"
      → verdict: confirmed / rejected / unverified
  → if confirmed: notification dispatch (WhatsApp/email) + WS broadcast
  → if rejected: log only, no alert, no WS broadcast
  → if unverified (VLM uncertain / low confidence): dispatch alert but flag as "unverified" in UI, log for later review
```

### 1.3 Implementation tasks for the agent
- [ ] Add a new async worker/consumer stage (reuse existing Kafka topic pattern already in the codebase — do not introduce a new broker)
- [ ] Define event schema addition: `verification_status` (enum: `pending`, `confirmed`, `rejected`, `unverified`), `verification_reasoning` (text, the VLM's stated reason), `verified_at` (timestamp)
- [ ] Implement clip re-fetch: pull the 3–5 second window of frames/clip around the original event timestamp from wherever NightFury currently stores/buffers snapshots or clips (locate this in the existing edge/worker code — do not assume, check the actual snapshot/clip storage implementation first)
- [ ] Write a second, narrower Gemini Vision prompt template specifically for verification (should ask a yes/no/uncertain confirmation question referencing the *specific* alert rule that triggered, not a generic "what do you see")
- [ ] Move notification dispatch (WhatsApp/email) to be triggered only after a `confirmed` or `unverified` verdict — this becomes the fix for the existing "notification dispatch blocks ingestion hot path" bug, since dispatch now naturally happens in the async verification consumer, not inline in the ingestion request path
- [ ] Update WebSocket broadcast to only fire post-verification (this also fixes the existing "WS broadcast fires before Postgres commit" ordering bug if the verification write is sequenced to commit before broadcast — confirm this ordering explicitly in implementation)
- [ ] Add `verification_status` as a visible field/badge in the existing frontend event list/detail view
- [ ] Log verification verdicts with enough structure to compute a false-positive rate over time (this number should become measurable, not estimated)

### 1.4 Explicit non-goals for this component
- Do not attempt to fix Gemini's underlying classification blind spots (e.g., scan-vs-pat-down) with this step — that's the separate TAO action-classifier workstream. Verification catches *inconsistent* misfires only, not *systematic* model limitations.
- Do not add a third verification pass or escalation chain in this build — one verification step only.

---

## 2. Component B — Embedding + Search Layer

### 2.1 Purpose
Enable natural-language search over historical camera events ("show me events where someone was near the loading dock after 8pm"). This is purely additive — it does not change or improve real-time detection/alerting accuracy.

### 2.2 Architecture
```
Confirmed event (post-verification) 
  → generate embedding of event snapshot/description (model TBD — see 2.3)
  → store embedding in pgvector, linked to existing event row (Postgres — reuse existing DB, add pgvector extension)
  → expose search endpoint: natural-language query → query embedding → cosine similarity search → ranked event results
```

### 2.3 Implementation tasks for the agent
- [ ] Add `pgvector` extension to the existing PostgreSQL instance (confirm current Postgres version supports it; document any migration needed)
- [ ] Add an `event_embeddings` table (or `embedding` column on the existing events table — decide based on actual schema, check existing events table structure first) storing: `event_id` (FK), `embedding vector(N)`, `embedding_model` (text, for future model migrations), `created_at`
- [ ] Choose and implement the embedding generation step — options to evaluate against NightFury's existing cost constraints:
  - CLIP-style embedding of the event snapshot image (cheap, fast, no extra API cost if run locally)
  - Text embedding of Gemini's existing event description/caption (reuses text already generated, no new image processing)
  - Recommend starting with **text embedding of the existing Gemini-generated event description** — lowest implementation cost, reuses data already produced, avoids adding a new model dependency to evaluate
- [ ] Implement embedding generation as an async step triggered after event confirmation (same queue/consumer pattern as Component A — consider whether this should be the same consumer stage as verification, to avoid adding a third async hop)
- [ ] Build the search endpoint: accepts natural-language query string → embeds query with same model → pgvector cosine similarity search against `event_embeddings` → returns ranked event IDs with scores → hydrate full event details from existing events table
- [ ] Add basic filtering support alongside semantic search: date range, camera/site ID, confirmed-only (reuse existing tenant/org_id filtering pattern already in the codebase — do not bypass existing multi-tenancy filtering)
- [ ] Add a minimal search UI (search bar + results list, reusing existing frontend event-list component styling) to the existing Next.js frontend
- [ ] Backfill: decide and document whether historical (pre-this-feature) events get embedded retroactively or only events going forward — flag this as a decision point, not an assumption

### 2.4 Explicit non-goals for this component
- No conversational/chat interface in this build — this is a search box, not a chatbot. (Conversational Q&A is Component C below, and even that is summarization, not live chat — live chat is Stage 2, out of scope entirely.)
- No cross-camera correlation or embedding-based re-identification in this build — that remains the separately-tracked "biggest unsolved problem" from existing interview prep material, unchanged.

---

## 3. Component C — Agent/Summarize Layer

### 3.1 Purpose
"Summarize what happened today at Site X" or "what confirmed alerts fired this week" — a plan-and-execute style agent that queries the event store (including the new search layer) and produces a grounded summary with citations back to specific events/clips, rather than a single unstructured LLM call.

### 3.2 Architecture (pattern reference: `NVIDIA-AI-Blueprints/rag`'s Agentic RAG mode and `aiq`'s tool-calling + citation pattern — reimplemented independently)
```
User query ("summarize today's events at Site X")
  → Query understanding step: what's being asked — date range? site/camera scope? event type filter?
  → Tool-calling agent (LangChain/LangGraph — reuse existing LangChain expertise/patterns already used elsewhere in Vaibhaw's stack at Gebra AI) with access to:
      - search_events(query, filters) → calls Component B's search endpoint
      - get_event_detail(event_id) → fetches full event record + clip/snapshot reference
      - get_events_by_filter(date_range, camera_id, status) → direct structured query, bypassing semantic search when the ask is filter-based not semantic
  → Agent composes a natural-language summary, with each claim tagged to the event_id(s) it's grounded in
  → Response includes both the summary text AND a structured list of cited event_ids (so the frontend can render "confirmed" links/thumbnails next to each claim)
```

### 3.3 Implementation tasks for the agent
- [ ] Define the tool interface (the three tools listed in 3.2, or revise based on what's actually useful once Components A/B exist) as callable functions/endpoints
- [ ] Implement the agent orchestration using LangChain/LangGraph (reuse whatever LangChain version/patterns are already established in Vaibhaw's other work — check for consistency rather than introducing a second LangChain convention)
- [ ] Design the prompt/system instructions so the agent **must** cite event_ids for factual claims and should say so explicitly when it cannot find supporting events for a request, rather than fabricating a summary
- [ ] Build a response schema that separates the human-readable summary from the structured citation list, so the frontend doesn't need to parse citations out of prose
- [ ] Add an API endpoint (e.g., `/api/events/summarize`) accepting a natural-language request and the existing tenant/org scoping
- [ ] Add a minimal frontend surface — a text input + rendered summary with clickable citation chips linking to the cited events (can reuse Component B's event-detail view for the click-through target)
- [ ] Add basic cost/rate controls (this is the most LLM-call-heavy of the three components — multiple tool calls per request — so token/cost logging should hook into NightFury's existing AI usage instrumentation page from day one, not be added later)

### 3.4 Explicit non-goals for this component
- No live/streaming conversational interface (that's RTVI/Pipecat, Stage 2, explicitly out of scope here)
- No multi-turn conversation memory in this build — treat each summarize request as independent. Multi-turn can be added later once single-turn is proven useful.
- Do not build a general-purpose chatbot — scope the tool set tightly to event search/retrieval, not open-ended capability.

---

## 4. Suggested build order

1. **Component A (Verification) first** — smallest surface area, fixes two already-known bugs (WS ordering, blocking notification dispatch) as a side effect, and produces the false-positive-rate data that should inform whether further investment here is justified.
2. **Component B (Search) second** — depends on confirmed/verified events existing in a clean state from Component A; establishes the embedding infrastructure that Component C needs as a tool.
3. **Component C (Agent/Summarize) third** — depends on B's search endpoint existing as a callable tool.

Each component should be independently shippable and testable — do not build all three in one branch/PR. Confirm Component A is stable (verification verdicts look sane on real event data) before starting B.

## 5. Open questions to resolve before/during implementation (flag to Vaibhaw, do not silently assume)

- Where exactly are event snapshots/clips currently stored and how are they addressed/retrieved by timestamp? (Needed for Component A's clip re-fetch.)
- What is the current PostgreSQL version and hosting setup, to confirm pgvector extension availability?
- Is there an existing LangChain/LangGraph convention or version already in use in Vaibhaw's other codebases that Component C should match, to avoid dependency drift?
- Should Component A and Component B's async steps share one consumer/queue stage or be separate? (Affects latency and complexity — recommend starting combined, split later if needed.)
- Backfill decision for Component B (historical events) — cost/value tradeoff needs a decision, not an assumption.

---

## 6. Production-Readiness Hardening

*This section is a separate workstream from §1–3 (Layer 2/3 features). It addresses existing known bugs/gaps and general production-launch readiness for client demos. All tools below are open-source or free/minimal-cost; license type is stated for each — flag anything marked ⚠️ before adopting.*

### 6.1 Job queue — fixes fire-and-forget notification dispatch

- [ ] **Adopt Dramatiq** (LGPL-3.0, free, reuses existing Redis as broker) as the job queue. Move WhatsApp/email notification dispatch off the inline/blocking ingestion path onto a Dramatiq actor — ingestion enqueues and returns immediately; a worker pool handles delivery with retries.
  - Alternative if broader ecosystem/scheduled-task support is preferred: **Celery** (BSD-3-Clause) — heavier config, set `acks_late=True` to avoid task loss on worker crash.
  - Alternative for lowest-effort fix: **RQ** (BSD-3-Clause) — simplest setup, fewer reliability guarantees, Redis-only.
- [ ] This directly fixes the existing "notification dispatch is fire-and-forget, blocking ingestion hot path" bug.
- [ ] Note overlap with Component A (§1) — the verification consumer stage and the notification dispatch job may end up as adjacent or combined queue stages; resolve during implementation, not in advance.

### 6.2 WebSocket horizontal scaling + ordering bug fix

- [ ] **Adopt Centrifugo** (MIT, free, self-hosted, Redis-backed fanout) as a dedicated WebSocket server. Backend POSTs events to Centrifugo over HTTP instead of managing raw sockets in-process.
  - This fixes both existing named gaps at once: (a) "WebSocket scaling limited to single instance" (Centrifugo fans out across app instances via Redis), and (b) "WebSocket auth at handshake" (Centrifugo validates JWT at connect time).
  - Lower-effort alternative if a dedicated server is out of scope right now: Redis pub/sub adapter pattern (DIY, subscribe all instances to a Redis channel, fan out to local WS clients).
- [ ] **Fix the WebSocket-before-commit ordering bug explicitly**: sequence the Centrifugo publish (or WS broadcast) call to fire only *after* the Postgres commit succeeds, not before/concurrent with it. Confirm this ordering in code, don't assume it falls out naturally from moving to Centrifugo.
- [ ] If not adopting Centrifugo, implement WebSocket handshake auth manually: validate a short-lived JWT via `websocket.query_params` / `websocket.headers` / `websocket.cookies` in FastAPI **before** calling `websocket.accept()`; close unauthorized connections without accepting.

### 6.3 Data-loss prevention (cascade-delete fix)

- [ ] **Add soft-delete pattern** using `sqlalchemy-easy-softdelete` or `suave-deletes` (both MIT) — mixin generates `deleted_at` timestamp handling with automatic query filtering, replacing hard `DELETE`.
- [ ] **Add audit logging**: append-only audit table populated via SQLAlchemy event listeners (`after_insert`/`after_update`/`before_delete`) capturing who/what/when/before-state for every mutation, not just deletes.
- [ ] **Guard the super-admin delete path specifically**: block cascades by default, require explicit confirmation for any hard delete, log every hard-delete to the audit table before executing.
- [ ] Backfill via Alembic migration: add `deleted_at` column(s) and the audit table; **confirm Alembic is already in use for schema migrations** — if not, adopt it (MIT, standard SQLAlchemy/Postgres migration tool) before making schema changes here.

### 6.4 Multi-tenancy & security hardening

- [ ] **Implement Postgres Row-Level Security (RLS)** as defense-in-depth beyond the existing app-layer `org_id` filtering. Set `app.tenant_id` as a session config variable per request; RLS policies filter rows at the database layer so a forgotten `WHERE org_id = ...` fails closed instead of leaking cross-tenant data. Consider `fastapi-tenancy` (open-source) to accelerate setup.
  - **Write an explicit test**: a query that intentionally omits the tenant filter should still return zero cross-tenant rows once RLS is active. This test locks in the guarantee.
  - Confirm **tenant ID is always derived server-side from authenticated device/session identity, never trusted from request body** (existing named IDOR risk) — audit all routes for this, not just new ones.
- [ ] **Add rate limiting via slowapi** (MIT, Redis-backed for distributed limiting across instances) on login, activation-code, and webhook endpoints specifically.
- [ ] **Implement SSRF protection for webhook URLs**: DNS-resolve-and-validate pattern — resolve the hostname yourself, reject private/reserved IP ranges (`10/8`, `172.16/12`, `192.168/16`, `127/8`, `169.254/16` including the cloud-metadata IP `169.254.169.254`), allow only http/https, don't follow redirects, use one resolve call for both validation and connection to avoid DNS-rebinding. **Do not depend on the `advocate` library — it is archived/unmaintained.** Hand-roll this or use a maintained fork; add an egress firewall as defense-in-depth if available.
- [ ] **Device-scoped, rotatable API keys**: store only a hash (bcrypt/argon2 via passlib, or SHA-256 for high-entropy keys) with a non-secret prefix/key-id for logging; support multiple active keys per device with `expires_at` for zero-downtime rotation. Consider `fastapi-key-auth` or `fastapi_simple_security` (both MIT) as a starting auth-gate; build the hashed/prefixed/rotation lifecycle as a custom layer on top.
- [ ] **Secrets management**: adopt **OpenBao** (MPL-2.0 — chosen specifically over HashiCorp Vault, which is BSL-licensed and carries the same commercial-resale-restriction concern already flagged for NVIDIA's Elastic-licensed components) to centralize API keys, DB credentials, and device provisioning secrets out of env files. If OpenBao's operational overhead is too high for current team size, use **Infisical** (MIT core) as a lighter alternative.
- [ ] **KMS envelope encryption for video/snapshot storage, per-tenant keys**: implement via AWS KMS (~$1/key/month + 20k free requests/month, then $0.03/10k ops) or GCP KMS (~$0.06/key/month, cheaper per-key at higher tenant counts) — use short-lived signed URLs for all retrieval, never permanent public links.
- [ ] **Encrypt the edge SQLite offline queue at rest** on Raspberry Pi devices — SQLCipher or OS-level disk encryption (existing named gap: device may be physically accessible/stolen).
- [ ] **Enable free security scanning in CI**: GitHub Dependabot + code scanning (free on the repo), **Trivy** (Apache-2.0) for container/dependency/IaC/secret scanning, **Opengrep** (open rules fork) or **Semgrep CE** (LGPL-2.1, note: default maintained rules are separately licensed and not resellable — use Opengrep if rule redistribution matters) for SAST.

### 6.5 Observability & error tracking

- [ ] **Add Sentry** for error tracking — use the **hosted free "Developer" tier** (5,000 errors/month, 1 user, 30-day retention) rather than self-hosting. ⚠️ Note: self-hosted Sentry web-app code is FSL-1.1-Apache-2.0 (not OSI open-source, converts to Apache-2.0 after 2 years) — the SDKs themselves are MIT and unrestricted; the hosted free tier sidesteps the question entirely and is the recommended path.
  - Lighter self-hosted alternative if preferred: **GlitchTip** (Sentry-SDK-compatible, OSS-friendly license).
- [ ] **Add Prometheus** (Apache-2.0) for metrics, extending the existing AI-usage/cost/latency instrumentation page into per-service dashboards.
- [ ] ⚠️ **Do not self-host Grafana or Grafana Loki for a resold/multi-tenant product** — both are AGPLv3 (copyleft, network-use trigger), a genuine concern for embedding in a service you resell. Use the **hosted Grafana Cloud free tier** for dashboards, or prefer **SigNoz** (core is MIT; note the open-core boundary has shifted between versions, verify per-version) as an all-in-one logs+metrics+traces alternative.
- [ ] **Deploy Uptime Kuma** (MIT, free, self-hosted on a small ~₹150–400/mo VPS) for uptime monitoring with a public status page (e.g. `status.nightfury...`) plus internal alerts (WhatsApp/Telegram/email) when the relay or backend goes down.

### 6.6 Testing & QA

- [ ] **Add Locust** (MIT) for load testing — Python-based, reuses domain code to simulate realistic camera-count/event-volume load. Run this **before go-live on any pilot exceeding ~20 cameras/tenant**.
- [ ] **Add pytest** (MIT) backend test coverage if not already comprehensive — explicitly include the RLS "forgotten tenant filter" test from §6.4.
- [ ] **Add Playwright** (Apache-2.0, preferred over Cypress for zero-budget parallelization) for E2E smoke tests on the Next.js dashboard: login → live feed → event → alert, to catch demo-breaking regressions before a client pitch.

### 6.7 Demo/client-facing polish

- [ ] **Set up MediaMTX** (MIT) **+ ffmpeg** (LGPL/GPL, CLI use only) to simulate RTSP camera feeds from pre-recorded video clips (`ffmpeg -re -stream_loop -1 -i demo.mp4 ... -f rtsp ...`). Lets the Pi agent's real motion→YOLO→Gemini pipeline run live against simulated "cameras" (loading dock, gold-loan counter, QSR till, school gate) with no physical hardware needed at a client pitch. Pre-record clips containing the specific events (loitering, bag left, shutter tampered) the demo should trigger.
- [ ] **Seed synthetic demo data** (Python + Faker, MIT) — realistic event history across time/cameras/tenants so the dashboard and AI-cost page look like a populated production system rather than an empty prototype. Combine with the MediaMTX feeds so live events land on top of an already-rich backlog.
- [ ] **Deploy a separate marketing site** distinct from the app dashboard — a second Next.js app on Vercel's free Hobby tier (reusing existing skillset/theme), covering sales narrative, pricing, DPDP compliance posture, testimonials — kept separate from the login-gated dashboard.

### 6.8 MLOps (extends existing MLflow target)

- [ ] **MLflow** (Apache-2.0) remains the target for experiment tracking + model registry — confirm this directly fixes "model files overwritten on retrain, no rollback."
- [ ] **Adopt BentoML** (Apache-2.0) to package the YOLO object-gate into a versioned REST/gRPC serving layer independent of the FastAPI monolith, pairing with MLflow for registry→serving handoff. (Gemini Vision remains an external API call — BentoML serves the YOLO gate only.)
- [ ] **Export YOLO to ONNX Runtime** (MIT) for faster, lighter CPU inference on the Raspberry Pi 5 edge — validate accuracy parity against the current PyTorch model before switching.
- [ ] **Add Evidently AI** (Apache-2.0) for drift detection — monitors whether shifting camera scenes/lighting/customer behavior are degrading the YOLO gate or Gemini prompts over time; integrates with Prometheus/Grafana-equivalent dashboards from §6.5.
- [ ] Defer NVIDIA Triton Inference Server — only relevant once GPU-backed cloud inference is in use; ⚠️ re-review its container/NVIDIA EULA terms for managed-service-resale restrictions (same scrutiny already applied elsewhere) before adopting.

### 6.9 India-specific production considerations

- [ ] **Evaluate migrating Postgres/Redis/Kafka hosting to an Indian cloud** (E2E Networks or AceCloud) if/when a client requires India data residency for DPDP purposes, or once cost at scale makes the ~30–50% saving vs. AWS Mumbai material. Not urgent at current scale — flag as a threshold-triggered migration, not immediate work.
- [ ] **Route WhatsApp alert dispatch to minimize cost**: use utility/authentication message templates (₹0.1150/message per Meta's India rate card, effective Jul 1, 2026, plus 18% GST) rather than marketing templates, and reply within the free 24-hour service window where possible. This dispatch should run through the §6.1 job queue with retries, not inline.
- [ ] **Write a one-page DPDP Act 2023 compliance posture + draft Data Processing Agreement** — NightWatch is a Data Processor, clients are Data Fiduciaries. Cover: visible CCTV signage requirement, purpose limitation, configurable data-retention/auto-deletion (industry norm 30–90 days), right-to-erasure workflow, breach notification (~72h for serious breaches), and map technical controls already built in §6.3–§6.4 (encryption, RLS, audit logs) to this posture. This turns compliance into a sales asset for gold-loan NBFC/CBSE school buyers rather than an objection. Have the final DPA reviewed by an Indian data-protection lawyer before signing enterprise clients — this document is a starting draft, not legal advice.

### 6.10 Priority shortlist — if only 10 things get done before a client demo

Ranked by impact-to-effort ratio; items 1–5 make the demo *work and look production-grade*, items 6–10 make it *survive due diligence*:

1. Dramatiq (or RQ) for notification dispatch (§6.1) — ½ day
2. Fix WebSocket-before-commit ordering bug (§6.2) — hours
3. Sentry hosted free tier (§6.5) — 1–2 hours
4. MediaMTX + ffmpeg simulated feeds + synthetic demo data (§6.7) — 1 day
5. Uptime Kuma + public status page (§6.5) — 2–3 hours
6. GitHub Dependabot + code scanning + Trivy in CI (§6.4) — 2–3 hours
7. Postgres RLS + server-derived tenant ID audit (§6.4) — 1–2 days
8. Soft-deletes + audit logging + guarded admin delete path (§6.3) — 1 day
9. slowapi rate limiting + WebSocket handshake auth (§6.2, §6.4) — ½–1 day
10. DPDP posture doc + DPA draft + API-key hashing/rotation (§6.4, §6.9) — 1 day

**Sequencing relative to §1–3**: §6.1 and §6.2 overlap directly with Component A (§1, Alert Verification) — implement them together, since fixing the notification/WebSocket hot path is a shared prerequisite. Items 3–10 above can proceed in parallel with or after §1–3 depending on demo timing.

### 6.11 Licensing sanity check (flag before adopting)

| Tool | License | Flag |
|---|---|---|
| Sentry (self-hosted) | FSL-1.1-Apache-2.0 | ⚠️ Not OSI open-source; use hosted free tier instead |
| Grafana / Grafana Loki | AGPLv3 | ⚠️ Avoid self-hosting for resold/multi-tenant use; use Grafana Cloud free tier or SigNoz instead |
| HashiCorp Vault | BSL | ⚠️ Avoid — use OpenBao (MPL-2.0) instead |
| `advocate` (SSRF lib) | Apache-2.0 | ⚠️ Archived/unmaintained since 2023 — don't depend on it |
| Semgrep CE rules (default) | Restrictive (not resellable) | ⚠️ Use Opengrep for open, redistributable rules |
| NVIDIA Triton containers | BSD-3-Clause core + NVIDIA EULA | ⚠️ Re-review EULA before any managed-service resale |
| k6 | AGPL-3.0 | Running tests is fine; don't redistribute modified k6 |

All other tools referenced in §6 (Dramatiq, Celery, RQ, Centrifugo, Alembic, sqlalchemy-easy-softdelete, suave-deletes, slowapi, fastapi-limiter, fastapi-key-auth, fastapi_simple_security, fastapi-tenancy, OpenBao, Infisical, Trivy, Opengrep, Locust, pytest, Playwright, MediaMTX, Faker, BentoML, ONNX Runtime, Evidently AI, MLflow) carry permissive licenses (MIT/Apache-2.0/BSD/LGPL-as-library) with no commercial-resale restriction identified.
