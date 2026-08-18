# Mall-Scale Architecture — Gap Analysis & Change Plan

*Date: 2026-08-18*
*Driver: pitching a mall estate (~150–400 cameras, 24/7 shift-based control room, multiple tenants and floors) on the default edge-box deployment.*

## Framing

The current architecture was designed for the home/small-site case: **one edge box, one site, a handful of cameras, one or two users who are also the owner.** A mall inverts every one of those assumptions:

| Assumption today | Mall reality |
|---|---|
| One agent per site | A fleet of agents per site |
| ≤12 cameras | 150–400 cameras |
| Users ≈ owner | Shift-based operators, floor managers, tenants, GM |
| Alert → the owner's phone | Alert → whoever is on duty, escalating if unanswered |
| Events are read | Events are *worked* — acknowledged, assigned, handed over |
| A box going down is the user's problem | A box going down blinds a floor |

None of the gaps below are architectural rewrites. The foundations are right — `cameras.agent_id` exists, `sites` exist, `users.sites_access` exists as a column, `verify_worker_key` already resolves an agent to an `org_id`. The work is mostly **completing** things that were stubbed for the single-box case.

The plan is phased against the sales motion: Phase 0 must land before a pilot install, Phase 1 before an estate rollout is credible, Phase 2 before an estate rollout is *safe*.

---

# Part I — How the architecture scales with camera count

This is the core of the plan. "Adjusts to the number of cameras" is not one change; it is **three control loops** — one in the backend, one in the agent, one across the fleet — plus a set of backend limits that only bite past a few hundred cameras.

## I.0 — The blocking defect: assignment is global, not agent-scoped

`backend/app/api/internal.py:73` is the single thing that prevents any of this from working:

```python
@router.get("/assignments", response_model=AssignmentsResponse)
async def list_assignments(worker_id: str | None = None, ...):
    """For MVP, `worker_id` is accepted but ignored — every worker pulls the full
    set of cameras whose ingest_mode is supported by the worker pipeline."""
```

The query filters on `ingest_mode` and soft-deletion **and nothing else** — not `org_id`, not `agent_id`. Three consequences, in descending order of severity:

1. **Cross-tenant data leak.** Any paired agent holding a valid device token receives every camera row in the database, including `rtsp_url` — which for most NVRs embeds credentials as `rtsp://user:pass@host/...`. `verify_worker_key` (`backend/app/core/dependencies.py:80`) already attaches `request.state.internal_principal` with the resolved `agent_id` and `org_id`; the endpoint simply never reads it. **This is a live defect against the current single-tenant-per-box product, independent of malls.**

2. **Agents collide instead of sharding.** Every agent receives an identical list and independently applies `cameras[:config.max_cameras]` (`agent/pipeline/supervisor.py:74`). Two boxes on the same site therefore run the *same* first twelve cameras, and everything past the twelfth is analysed by nobody. Adding hardware currently adds duplicate work, not coverage.

3. **Poll cost grows as agents × cameras.** Each agent re-fetches the entire global camera table every `assignment_poll_interval` (10s, `agent/pipeline/config.py`). At 25 agents and 400 cameras that is a full unbounded join every 400ms.

Everything else in Part I depends on fixing this first. `cameras.agent_id` already exists and is already indexed — the model was built for this and the endpoint was never updated.

## I.1 — Loop 1: the backend is the assignment authority

The backend decides which cameras go on which box. Agents never choose; they execute what they are told. This keeps placement decisions in one place where they can be reasoned about, audited, and overridden by a human.

**Capacity on the agent record** — add to `backend/app/models/agent.py`:

| Column | Meaning |
|---|---|
| `site_id` | The site this box is physically on. A camera can only be placed on an agent that shares its site — the box must be on that LAN. |
| `capacity_cameras` | How many cameras this box says it can handle, reported by the agent (see I.2). Backend never exceeds it. |
| `assigned_count` | Denormalised count for fast placement decisions. |
| `capacity_source` | `declared` (hardware guess) or `measured` (from observed load). Lets the UI say how much to trust the number. |

**A placement reconciler** — `backend/app/services/camera_placement.py`, a pure function plus a thin caller:

```
place(cameras_on_site, agents_on_site) -> {camera_id: agent_id}
```

- Deterministic and idempotent — same inputs, same output, so it can run freely without churn.
- **Sticky:** a camera already assigned to a healthy agent with capacity stays there. Placement changes cause stream restarts, so movement must be justified, never incidental.
- Bin-packs remaining cameras onto agents with spare capacity, preferring the least-loaded box.
- Cameras that fit nowhere get `agent_id = NULL` and camera status `unassigned` — an explicit, visible state (see I.4).
- Runs on: camera create/delete, agent pair/unpair, capacity change, and agent-stale detection. Not on a timer — it is event-driven, because nothing changes placement except those events.

**The scoped endpoint** — `list_assignments` reads `request.state.internal_principal` and returns only `Camera.org_id == principal.org_id AND Camera.agent_id == principal.agent_id`. The `worker_id` query parameter is dropped (a client-supplied identity that the server can resolve from the token is a footgun, not a feature).

Keep the legacy `kind == "worker"` principal returning the org-wide list for the cloud-VM fallback path, which has no `agent_id` — but scope it to that path explicitly rather than leaving it as the default for everyone.

**Manual override:** the fleet view (I.4) can pin a camera to a specific agent. The reconciler respects pins and never moves them; it only places unpinned cameras. Operators will always know something about their building that the packer does not.

## I.2 — Loop 2: the agent sizes itself

`max_cameras: int = 12` (`agent/pipeline/config.py:58`) is a guess baked into a constant. It should be a **measurement**, because the real number depends on stream resolution, frame rates, how many cameras have `step_sequence` configured (pose detection is far more expensive than the YOLO gate), and the hardware the box happens to be.

**Declared capacity at startup.** The agent computes a starting capacity from CPU core count and available RAM, and reports it in the heartbeat as `capacity_cameras` with `capacity_source: "declared"`. `max_cameras` stays as an operator-settable *ceiling*, not the primary number.

**Measured capacity in steady state.** The pipeline already tracks per-worker health. Extend the heartbeat with per-camera analysis cost — mean frame-processing latency and CPU share — and let the agent revise its own capacity upward or downward, reporting `capacity_source: "measured"`. Revisions are damped (only after a sustained window, with hysteresis) so a busy afternoon does not cause placement thrash.

This is also what makes estate pricing honest: the technical proposal deliberately refuses to quote a rollout before the pilot measures cameras-per-box on the customer's actual streams. This is the mechanism that produces that number.

**Graceful degradation instead of a hard cliff.** Today, camera thirteen is simply not started. That is the worst possible failure mode — a silent coverage hole. Replace it with a ladder:

1. **Within capacity** — normal `idle_fps` / `active_fps`.
2. **Over capacity, mild** — the agent lowers sampling rates across *all* its cameras and tightens the motion gate. Every camera stays analysed, slightly less often. Reported as `degraded` with the reason.
3. **Over capacity, severe** — the agent refuses the excess and reports `rejected_cameras: [camera_id]` in the heartbeat, which the backend turns into `unassigned` status and feeds back to the reconciler for placement elsewhere.

Uniform degradation across many cameras is almost always better for a mall than perfect analysis on some and zero on others — but it must be *visible*, never silent. The existing truncation at `supervisor.py:74` becomes a last-resort assertion that reports rather than a routine path that swallows.

## I.3 — Loop 3: the fleet responds to change

With I.1 and I.2 in place, the estate self-adjusts to camera count through ordinary events:

| Event | Response |
|---|---|
| Cameras added to a site | Reconciler places them on boxes with spare capacity |
| Capacity exhausted across the site | Cameras go `unassigned`, dashboard says "add an appliance to cover N cameras" with the number |
| A new appliance is paired | Reconciler drains `unassigned` cameras onto it |
| An appliance goes stale | Its cameras are marked `unassigned` and the org is alerted — a coverage gap is itself an event worth notifying about |
| An appliance recovers | Sticky placement returns its cameras without disturbing others |
| A camera gets `step_sequence` configured | Its measured cost rises, the agent's measured capacity falls, the reconciler sheds the overflow |

The important property: **the number of cameras is an input, never a configured constant.** Nobody edits `max_cameras` to scale from 12 to 400. They pair more boxes, and the estate rebalances.

## I.4 — Making capacity visible

Scaling behaviour nobody can see is indistinguishable from a bug. A site-level fleet view is part of the mechanism, not a reporting nicety:

- Each appliance: assigned vs capacity, last heartbeat, degradation state and reason, camera list.
- Site totals: cameras analysed / cameras configured — the honest coverage number, shown prominently.
- `unassigned` cameras listed with the remedy ("no capacity on this site — one more appliance covers these 9").
- `unassigned` must render as an alarming state in the camera list, clearly distinct from `offline`. Offline means the camera is down; unassigned means **we are not watching it and you did not ask for that.**

## I.5 — Where the backend itself bends

The loops above scale the edge. These are the backend limits that only appear past a couple of hundred cameras.

**Heartbeat write amplification** *(bites around 100+ cameras)*
`agent/pipeline/supervisor.py::_health_check` iterates every worker and calls `worker.send_heartbeat()` individually every `health_report_interval` (30s), and `api_client.send_heartbeat` POSTs one request per camera. At 400 cameras that is ~13 requests/sec and ~13 camera-row updates/sec, permanently, purely for health. **Fix:** batch to one `POST /internal/heartbeat` per agent carrying all its cameras, and write with a single bulk update. This is the highest-value backend change in Part I and is worth doing well before mall scale.

**Assignment polling** *(bites around 20+ agents)*
Once assignments are agent-scoped the query is small, but 25 agents polling every 10s still re-transfers unchanged config constantly. **Fix:** an assignment version/ETag per agent — the agent sends its current version, and the backend returns `304` when nothing changed. The reconciler bumps the version when it touches that agent. Cheap, and it makes the poll interval a non-issue.

*Optional follow-on:* push assignment-changed notifications down the existing control WebSocket and let the poll become a slow safety net. Worth doing only if the ETag proves insufficient — the poll is not the problem, the payload is.

**WebSocket fanout** *(bites at mall scale with many operators)*
`broadcast_to_org` sends every event to every connected client of the org, and `internal.py` additionally broadcasts every event to an `"all"` channel. At 400 cameras with a dozen operators connected, every operator receives every event across the whole estate — and once `sites_access` is enforced (G2), a scoped user must not even *receive* out-of-scope events, not merely hide them. **Fix:** per-site channels, with subscription derived from the user's permitted sites. The `"all"` firehose needs an explicit opt-in rather than being unconditional.

**Event volume and retention** *(bites at 300+ cameras)*
`ix_events_org_timestamp` covers the org+time query pattern, which is the right index. The pressure is storage: 400 cameras producing snapshots and ~10s clips indefinitely, with no retention policy anywhere in the codebase (G5). Retention is what keeps event storage from growing without bound, so it is a scaling item as much as a compliance one.

**AI spend** *(bites immediately at scale)*
A single org-wide daily cap means one busy floor can exhaust the estate's budget and silently degrade every other floor to local-detection-only. Needs per-site budgets and a visible degraded state (G10).

## I.6 — What scales without changes

Worth stating, so effort goes where it is needed:

- **Detection itself.** Analysis is per-camera and per-box. Adding cameras adds boxes; nothing centralises.
- **Bandwidth.** There is no video uplink. Traffic is proportional to events, not cameras — the pitch's core claim, and it holds.
- **Live view.** Media is browser ⇄ appliance direct. A hundred concurrent viewers cost the backend only signaling. (The *agent* does need a concurrent-session cap — see G6.)
- **Event ingestion.** ~12k events/day at 400 cameras is unremarkable for Postgres. Burst handling matters; sustained rate does not.

---

# Part II — Remaining gaps

### G2 — `sites_access` is stored but never enforced *(rollout-blocking, security)*

`users.sites_access` (`backend/app/models/user.py:27`) is written at `backend/app/api/auth.py:207` and `backend/app/api/admin.py:390`, and read **nowhere**. Every query filters by `org_id` only.

Consequence: a Level-2 floor manager, a parking supervisor and a tenant's staff member all see every camera and every event across the entire estate. This is a real access-control hole, not a missing feature — the column's existence implies an enforcement that does not happen.

Together with I.0, this is one of two findings that could become an incident with a customer, and it is among the cheapest to close.

### G3 — No incident workflow *(rollout-blocking)*

`events` carries `feedback` / `feedback_label` / `feedback_by` (was this detection correct?) but has **no operational state**: no status, no assignee, no acknowledgement, no resolution note, no shift boundary.

A control room with three operators across rotating shifts cannot run on a feed where "seen by a human" and "acted on" are indistinguishable, and where a handover carries no record of what is still open.

### G4 — Alert routing has no site scope and no escalation *(rollout-blocking)*

`alert_rules` supports `cameras[]`, `event_types[]`, `min_severity`, `time_window`, `zones[]`, `cooldown_seconds` — good primitives, but no `site_id` (rules are org-wide, so a multi-site operator manages one flat list), no escalation ladder (duty manager → unacknowledged after 5 min → security head → 10 min → GM), and no on-call rota (contacts are static in `notify_contacts`, so a shift change means editing rules).

Escalation depends on G3 — acknowledgement must exist before "unacknowledged" can trigger anything.

### G5 — No retention configuration *(pilot-blocking, compliance + storage)*

No `retention` anywhere in `backend/app/` or the pipeline. Snapshots and clips accumulate in GCS indefinitely. Under DPDP, "how long do you keep it and who decides" currently has no product answer, only an operational promise. It is also the thing bounding storage growth at estate scale (I.5).

### G6 — Live view is one camera at a time *(rollout, UX)*

`WebRTCPlayer` negotiates a single camera. A control room replacing part of its wall expects a multi-tile view. Signaling can already support N tiles, but nothing composes them and **nothing bounds concurrent sessions per agent** — a 16-tile wall is a very different load profile on the box than one tile, and the cap must be enforced agent-side, not just in the UI.

### G7 — No appliance redundancy *(rollout, availability)*

One agent down = its cameras unanalysed. Acceptable on a home box; on a mall floor it is a coverage hole. I.3 covers detection and re-placement; what remains is whether a site keeps deliberate spare capacity so failover has somewhere to land, which is a commercial decision (N+1 boxes per site) as much as a technical one.

### G8 — Ask/chat is per-camera *(differentiator)*

`chat_service.py` handles a camera-scoped Q&A turn as a single text call. The mall question is site-wide — *"anything near the food court between 9 and 11?"* — which spans cameras and needs event retrieval before generation.

### G9 — Journeys designed, not built *(differentiator)*

`docs/superpowers/specs/2026-08-13-camera-map-journeys-design.md` specifies `camera_connections` plus an on-demand correlation query. No `backend/app/models/camera_connection.py` exists. The single most mall-shaped feature in the backlog, and explicitly *not* biometric.

### G10 — Spend cap granularity *(rollout, cost)*

Covered in I.5. Per-org daily cap was sized for a home box; needs per-site budgeting and a visible degraded state.

---

# Part III — Change plan

Per standing preference: implement directly and self-review for correctness, simplicity, SOLID and flow — no TDD/pytest steps in these tasks.

## Implementation status — Part I is built (2026-08-18)

The elastic-scaling mechanism described in Part I is implemented. Files:

| Concern | Where |
|---|---|
| Assignment scoping + ETag/304 | `backend/app/api/internal.py::list_assignments` |
| Batched heartbeat + capacity intake + reconcile trigger | `backend/app/api/internal.py::worker_heartbeat` |
| Placement policy (pure) and reconciler | `backend/app/services/camera_placement.py` |
| Capacity/placement columns + **backfill** | `backend/alembic/versions/b1c4e7a2d9f3_*.py` |
| `agents.site_id/capacity_cameras/…`, `cameras.pinned_agent_id` | `backend/app/models/{agent,camera}.py` |
| Fleet view + camera pinning | `backend/app/api/fleet.py`, `backend/app/schemas/fleet.py` |
| Self-sizing capacity, hysteresis, load state | `agent/pipeline/capacity.py` |
| Admission control, degradation ladder, batched beat | `agent/pipeline/supervisor.py` |
| Utilisation measurement | `agent/pipeline/camera_worker.py` |
| Runtime sampling multiplier | `agent/pipeline/frame_sampler.py` |
| Batched heartbeat + assignment ETag cache | `agent/pipeline/api_client.py` |

**Verified:** placement properties (spread, idempotence, determinism, explicit overflow, hard site affinity, pin precedence, stickiness, re-placement when an agent disappears); capacity hysteresis and ceiling; degradation halving sample rate without changing the stream signature; migration backfill SQL parses as Postgres; single alembic head; backend imports and routes register.

**Verified against a real Postgres 15 (2026-08-18)** — a throwaway Docker instance, never the production database:

- All three migrations (`b1c4e7a2d9f3`, `c3d7f2b9e814`, `d5e9a3c07f26`) apply from scratch **and downgrade cleanly**.
- **One real bug found and fixed by running them: `MIN(uuid)` does not exist in Postgres.** Two backfills used `MIN(id)` to pick the sole agent/site in a group. sqlglot parsed it (the syntax is valid) but it fails at execution with `UndefinedFunctionError`. Replaced with `(array_agg(id))[1]`, which is correct because `HAVING COUNT(*) = 1` guarantees a single row per group. **Static SQL parsing was not sufficient to catch this** — worth remembering for future migrations.
- Backfill proven on seeded pre-migration data across four real org shapes: single-agent org with 5 NULL `agent_id` cameras → **0 NULL after** (no customer blinded); already-assigned org untouched; multi-agent org left NULL by design; every agent got a `site_id`; `assigned_count` matches reality.
- Reconciler proven on live data: the multi-agent org's 6 NULL cameras spread 3/3 across two boxes at capacity 4; re-running moves nothing (idempotent against a real DB, not just in the pure function); dropping capacity to 2+2 leaves exactly 2 cameras with `agent_id NULL` **and `status='unassigned'`** — visible, not silently dropped; `assignment_version` bumps 1→2→3.
- **Existing test suite: 133 passed.** The 5 remaining failures were reproduced on a pristine `git worktree` of HEAD, so they pre-date this work (a `{'devices': []}` vs `{'cameras': []}` response-shape drift, plus tests reaching the real Upstash Redis and hitting event-loop errors). `test_agents_pair_codes` is flaky in full-suite runs and passes 3/3 in isolation.
- One existing test legitimately needed updating: `test_assignments_empty_list` asserted whole-dict equality and now checks fields, since the response gained `assignment_version`.

## Implementation status — 2.3 appliance failover is built (2026-08-18)

`backend/app/services/fleet_health.py`, scheduled every minute in `main.py`, plus the recovery path in `internal.py::worker_heartbeat`.

**Design decisions worth keeping:**
- **Failover reuses the placement reconciler; there is no second algorithm.** Marking a silent agent `offline` makes it fail `plan_placement`'s health check, so the next reconcile relocates its cameras to siblings with spare capacity — or leaves them `unassigned` and visible if there is none. Nothing to keep in sync with placement.
- **Two thresholds, on purpose.** The fleet view calls a box stale at ~100s so an operator sees trouble fast; failover waits **5 minutes**, because relocating cameras restarts streams and a rebooting box must not trigger a stampede of reassignments that then get undone.
- **The recovery path is the load-bearing half.** Without `worker_heartbeat` flipping `offline → online`, failover is one-way: the box would keep heartbeating, keep being skipped by the reconciler, and never get cameras back.
- **Idempotent by transition.** Only `status == "online"` agents are swept, so an already-failed-over box is never re-processed or re-notified.
- **A coverage gap is itself alert-worthy.** The whole promise is that something is watching, so silence when it stops is the one failure the product must not have. Sent via `send_text_whatsapp` (the digest path) rather than the alert-rule engine, which is Event-shaped and would need a fabricated one. Respects each contact's `enabled` flag.

**Verified end-to-end against real Postgres** (temporary test, run then removed): silence under 5 minutes does **not** fail over; a stale box relocates all 4 cameras to its sibling; an already-offline agent is not re-swept; with no sibling, all 3 cameras become `agent_id NULL` **and** `status='unassigned'`; and a recovered box gets its cameras back. Full suite re-run: **133 passed**, same 5 pre-existing failures.

## Implementation status — 1.1 `sites_access` enforcement is built (2026-08-18)

`permitted_site_ids()` / `scope_to_sites()` / `user_may_access_site()` in `backend/app/core/dependencies.py`, applied across:

| Path | Note |
|---|---|
| `events.py` | `_event_query`, **and** the separate `count_q` and `event_stats` base query — each builds its own filter, so scoping only the first would have hidden rows while the pagination total and the aggregates still counted them |
| `cameras.py` | `_camera_query`, plus `restore_camera`'s own soft-delete-inclusive query |
| `sites.py` | all four lookups (list / update / delete / restore) — a scoped user must not be able to *enumerate* the estate |
| `agents.py` | list + `_load_agent_for_user`, scoped on the new `agents.site_id` |
| `fleet.py` | `_load_site` and `pin_camera` |
| `chat.py` | `_validate_camera`, `_validate_event` |
| `ws/events.py` | rewritten: per-subscriber scope resolved from the DB at connect, filtered at send time |

**Design decisions worth keeping:**
- **Empty `sites_access` means unrestricted, not deny-all.** Nothing has ever written a non-empty value, so deny-all would have locked out every existing account the moment enforcement shipped. Restriction is opt-in per user.
- **`None` vs `[]` are not interchangeable** in the helper's return — `None` is "apply no filter", `[]` would mean "match nothing". Callers must check for `None` explicitly.
- **WebSocket scope is read from the DB at connect, not carried in the session.** Sessions live up to 24h; a permissions change must not wait for a re-login. Sockets connect rarely, so it costs one query per connection. Failure to resolve closes the socket rather than falling back to an unscoped feed.
- **Unattributable messages are not delivered to scoped subscribers.** A payload with no `site_id` fails closed.
- **Digests fail closed with a 403 for site-scoped users.** `digests` has no `site_id` column — they are computed org-wide over every event in the window, so there is no way to narrow an existing row to one site. The only honest options were deny or leak; this denies, on both the read and the on-demand-generation path.

**Verified:** unscoped accounts (`None` and `[]`) and super_admin remain unrestricted and produce no SQL filter; a scoped account filters the query, allows its own site, and denies both other sites and `None`; WebSocket subscribers receive only in-scope events and reject unattributable payloads.

**Follow-up this created:** per-site digests need a `digests.site_id` column plus scoped generation. Until then site-restricted accounts have no digest at all, which is safe but not good.

## Implementation status — 1.5 incident workflow + 0.4/1.6 escalation are built (2026-08-18)

| Concern | Where |
|---|---|
| `events.status` / acknowledged / resolved / note | `models/event.py`, migration `c3d7f2b9e814` |
| `PATCH /api/events/{id}/status` + `?status=open` handover filter | `api/events.py` |
| `alert_rules.site_id` (0.4) | `models/alert_rule.py`, `services/alert_service.py::_matches` |
| `alert_rules.escalation` + `alert_history.escalation_rung` | migration `d5e9a3c07f26` |
| Escalation sweep | `services/alert_escalation.py`, scheduled in `main.py` |

**Design decisions worth keeping:**
- **`status` and `feedback` stay orthogonal.** `feedback` = "was the detection correct?", `status` = "did somebody deal with it?". A true detection can sit unresolved and a false one can be dismissed; collapsing them would leave a handover unable to tell "reviewed the AI's guess" from "sent someone to look".
- **First acknowledgement wins.** A second operator opening the same event does not overwrite who actually picked it up.
- **Closing backfills acknowledgement**, so there is no resolved-but-never-acknowledged state.
- **`new` is a reachable state**, so an event acknowledged by mistake returns to the queue instead of staying owned by whoever mis-clicked.
- **Attribution lives on the event row, not `audit_log`.** That table is HTTP-request-shaped (method/path/status) and middleware-driven; "who acknowledged this and when" is a domain fact the handover view queries directly.
- **The ladder holds no state of its own.** Which rungs have fired is derived from `alert_history.escalation_rung`, so the sweep cannot drift out of sync or double-send after a restart — history *is* the record.
- **Escalation reuses `_matches`**, so a rung can never reach people the rule would not have notified initially.
- **Sweep interval bounds rung resolution.** It runs every minute with `max_instances=1` and `coalesce=True`; sub-minute `after_seconds` is a promise the scheduler cannot keep.
- **Defaults preserve today's behaviour**: `site_id` NULL = all sites, `escalation` empty = notify once and never chase.

**Verified:** ladder fires rung 0 at 400s / rung 1 at 1000s / rung 2 at 2000s, never re-fires a rung already in history, treats an empty ladder as notify-once, and skips a malformed rung rather than crashing. Alembic chain is a single head at `d5e9a3c07f26`.

**Migrations now executed and verified** against a throwaway Postgres 15 — see the Part I status section above for the full results, including the `MIN(uuid)` bug that only surfaced by actually running them. Existing suite: 133 passed, with every remaining failure reproduced on a pristine checkout of HEAD.

## Implementation status — 0.3 retention is built (2026-08-18)

`services/retention.py` + `delete_gcs_object` in `services/gcs.py`, `GET`/`PUT /api/settings/org/retention`, swept nightly at 03:30 from `main.py`. No migration — the value lives in the existing `organizations.settings` JSONB.

**Design decisions worth keeping:**
- **Absent or zero means keep forever.** Retention is opt-in. A default appearing in a deploy and silently deleting a customer's evidence would be indefensible, so the unconfigured path is exactly today's behaviour.
- **Media is deleted before the row, and the row is kept if media deletion fails**, so the next pass retries. The opposite order orphans objects in the bucket with nothing left pointing at them.
- **A missing object counts as a successful delete** — the desired end state holds, and a retry-safe delete must treat "not there" as done.
- **Dedicated validated endpoint, not raw JSONB.** This value causes irreversible deletion, so an out-of-range typo is rejected at the edge rather than discovered by the nightly purge. It merges into `settings` (and reassigns rather than mutates, since SQLAlchemy does not track in-place JSONB changes) so it cannot clobber unrelated keys.
- **Batched at 5000/pass and per-org isolated** — one org's stuck bucket cannot halt retention estate-wide, and no single pass holds a long transaction.

**Verified:** absent / null / zero / negative / non-numeric all resolve to keep-forever; a normal value is honoured; a numeric string is coerced; an absurd value is clamped to `MAX_RETENTION_DAYS` rather than obeyed.

**Known hazard, not changed:** `PATCH /api/settings/org` still accepts an arbitrary `settings` dict and **replaces** it wholesale, so it can both clobber unrelated keys and set an unvalidated `retention_days`. The new endpoint is the safe path; the generic one should probably stop accepting `settings`, but that risks breaking existing frontend callers and was left alone deliberately.

## Implementation status — 1.4 fleet view is built (2026-08-18)

`frontend/src/app/fleet/page.tsx` (+ `layout.tsx`), `FleetResponse`/`FleetAgent`/`FleetCamera` types, `api.getSiteFleet()` / `api.pinCamera()`, and a **Fleet** entry in the sidebar. `npm run build` compiles with zero type errors.

**Design decisions worth keeping:**
- **`unassigned` got its own colour in `StatusDot` (amber), not gray.** It previously fell through to the `offline` default, which is precisely the conflation the whole design warns against: *offline* means the camera is down and the customer can see that themselves; *unassigned* means the camera is fine and **we are not watching it**. That state must not look calm.
- **Coverage is the headline** — "cameras analysed N/M", coloured amber whenever it is short. Anything less than full coverage is a problem, not a neutral statistic.
- **The remedy is a number, not a vague prompt.** With no spare capacity the page says "one more appliance would cover N cameras" rather than "add hardware".
- **Capacity provenance is shown** ("measured from load" vs "estimated from hardware") so an operator knows how much to trust the number.
- **Staleness outranks load state.** A box that is not reporting is rendered "not reporting", never "healthy", whatever its last load reading said — a stale agent also contributes no capacity or coverage server-side.
- **Pinning is inline**: assign an unassigned camera to a box with spare capacity, and unpin from the appliance card to return it to automatic placement.
- 30s refetch, matching the heartbeat interval — polling faster only re-renders identical numbers.

## Implementation status — 1.5 incident workflow UI is built (2026-08-18)

`frontend/src/app/events/page.tsx` gains a status filter (defaulting to **Open**) and per-row Ack / Resolve controls; `Event` type and `api.setEventStatus()` added. `npm run build` compiles clean.

**Design decisions worth keeping:**
- **The workflow lane is visually separate from the feedback lane**, mirroring the backend's orthogonality. Ack/Resolve answers "did somebody deal with it"; approve/reject answers "was the detection right". Merging them in the UI would undo the point of separating them in the schema.
- **The page defaults to `?status=open`.** A control room opens it to see what still needs attention, not to browse history.
- **The live WebSocket insert respects the status filter** — a newly-arrived event is always `new`, so it belongs under "open"/"new" but must not appear while viewing "resolved".
- Viewers (no mutate permission) see the state as a label rather than a disabled button.

**Verified end-to-end over HTTP against real Postgres** (temporary test, run then removed): status defaults to `new`; acknowledge records actor and timestamp; **re-acknowledging does not rewrite who picked it up**; resolve records actor and note; reopening clears attribution; dismissing straight from `new` backfills acknowledgement; an invalid status is rejected with 400; and `feedback` and `status` move independently. `?status=open` returns exactly `new` + `acknowledged`, with the pagination total matching the filtered rows.

## Phase 0 — Before a pilot install day

**0.1 — Scope `/internal/assignments` to the calling agent** *(I.0)* — *do this first, regardless of any deal*
- Read `request.state.internal_principal` in `list_assignments`; filter by `org_id` and `agent_id` for `kind == "agent"`.
- Preserve the org-wide behaviour only for `kind == "worker"` (cloud-VM fallback, which has no `agent_id`).
- Drop the client-supplied `worker_id` parameter.
- **Note the ordering trap:** once assignments are agent-scoped, any camera with `agent_id = NULL` stops being analysed by anyone. Backfill existing single-agent deployments — assign every camera in an org to that org's sole agent — in the same change. Doing 0.1 without the backfill silently stops detection for every existing customer.

**0.2 — Stop silent truncation; report instead** *(I.2)*
- `agent/pipeline/supervisor.py` — report cameras that could not be started as `rejected_cameras` in the heartbeat rather than only logging.
- `backend/app/api/agent_control.py` — persist as a new `unassigned` value on `cameras.status`, alongside `online` / `offline` / `error`.
- Frontend camera list — render `unassigned` as its own alarming state ("not being analysed — no capacity on this appliance"), never as plain offline.

**0.3 — Retention window** *(G5)*
- `organizations.settings` JSONB already exists — put `retention_days` there rather than adding a migration; read it in a scheduled cleanup that deletes GCS objects and event rows past the window.
- Read-only in `/settings` for the pilot (agreed in the SOW, changed by us); self-service in Phase 1.

**0.4 — Site scoping on alert rules** *(G4, partial)*
- Add nullable `site_id` to `alert_rules` (+ migration). Null = all sites, preserving current behaviour.
- Filter rule evaluation in `alert_service.py` by the event's `site_id`.

## Phase 1 — Before an estate rollout is credible

**1.1 — Enforce `sites_access`** *(G2)* — *highest priority in Part II*
- One query-scoping helper in `backend/app/core/dependencies.py` returning the caller's permitted site ids: `super_admin` → all; empty `sites_access` → all sites in org (preserving today's behaviour); non-empty → that list.
- Apply in `events.py`, `cameras.py`, `digests.py`, `chat.py`, `sites.py`, and the WebSocket subscription path.
- Empty-list-means-all is the safe default that keeps every existing account working unchanged.

**1.2 — Agent capacity model and placement reconciler** *(I.1, I.2)*
- Add `site_id`, `capacity_cameras`, `assigned_count`, `capacity_source` to `agents` (+ migration).
- Agent reports declared capacity from CPU/RAM at startup, in the heartbeat.
- `backend/app/services/camera_placement.py` — the deterministic, sticky, pin-respecting bin-packer described in I.1, called on camera/agent lifecycle events.

**1.3 — Batched heartbeat** *(I.5)*
- One heartbeat per agent carrying all cameras; single bulk update on the backend. Removes the per-camera request and write amplification.
- Worth doing even for existing small deployments — it is strictly less work at every scale.

**1.4 — Fleet health view** *(I.4)*
- Site-level page: appliances, assigned vs capacity, last heartbeat, degradation state, `unassigned` cameras with the remedy, and site coverage totals.
- Manual camera → agent pinning, writing `cameras.agent_id` (column exists and is indexed).

**1.5 — Incident workflow** *(G3)*
- Add to `events`: `status` (`new` / `acknowledged` / `resolved` / `dismissed`), `acknowledged_by`, `acknowledged_at`, `resolved_by`, `resolved_at`, `resolution_note`.
- Keep **orthogonal to the existing `feedback` fields** — "was the detection right" and "did we act on it" are different questions and must not be collapsed.
- `PATCH /api/events/{id}/status`, written to the audit log.
- Frontend: Open / Acknowledged / Resolved filter, and a shift-handover view of everything still open.

**1.6 — Escalation ladder** *(G4, depends on 1.5)*
- Add `escalation` JSONB to `alert_rules`: ordered `{after_seconds, channels, contacts}`.
- A scheduled sweep finds events still `new` past each rung's threshold and fires the next. Acknowledgement stops the ladder.
- Reuses `notification_service.py` unchanged — scheduling on top of existing delivery, not a new channel.

## Phase 2 — Before an estate rollout is safe

**2.1 — Measured capacity and graceful degradation** *(I.2)*
- Per-camera analysis cost in the heartbeat; agent revises its own capacity with damping and hysteresis; `capacity_source` flips to `measured`.
- Implement the three-rung degradation ladder so over-capacity lowers sampling across all cameras before it ever drops one.

**2.2 — Assignment ETag** *(I.5)*
- Per-agent assignment version; `304` when unchanged; reconciler bumps it. Makes agent count cheap.

**2.3 — Appliance failover** *(G7)*
- Stale-heartbeat detection marks cameras `unassigned` and alerts the org; the reconciler drains them onto siblings with spare capacity, behind a per-site setting (reassignment moves load onto a box that may not have headroom).

**2.4 — Per-site WebSocket channels** *(I.5)*
- Per-site event channels with subscription derived from permitted sites; `"all"` becomes opt-in.

**2.5 — Multi-camera live view** *(G6)*
- Compose N `WebRTCPlayer` instances in a grid, with an **agent-side** cap on concurrent sessions and automatic teardown of off-screen tiles.

**2.6 — Per-site spend budgets** *(G10)*
- Move the daily cap from org-only to org + per-site, with a visible degraded state so "why did detection get worse" is answerable.

## Phase 3 — Differentiators worth selling

**3.1 — Cross-camera journeys** *(G9)* — build the existing design as specified. Keep the honest "plausibly the same visitor" framing in all copy; do not let it drift toward implied identity matching.

**3.2 — Site-wide Ask** *(G8)* — extend `chat_service.py` from a single text call to retrieval-then-generate over a site's events in a time window. The demo moment that lands hardest, and currently the weakest implementation.

**3.3 — Footfall and dwell analytics** — genuinely new detection work, and the highest-value non-security pitch to a mall (tenants pay for footfall data). Deliberately last: the only item here that is not a completion of something already started.

---

## What this plan deliberately does not do

- **No relay/worker involvement.** Everything stays on the default direct-to-backend edge-box path. The mall is not a reason to reach for the cloud-VM fallback.
- **No biometric re-identification.** G9 is adjacency-and-timing correlation. The REMIND integration design remains explicitly out of scope, and "no facial recognition" is a stated commitment in the pitch materials — the architecture must not quietly walk it back.
- **No central detection tier.** Scaling is achieved by adding edge boxes, never by moving analysis to the cloud. That would break the core promise that video does not leave the premises.
- **No new detection model work before Phase 3.** Every mall-blocking gap is platform and workflow, not vision. Fall detection and crowd density are correctly marked roadmap in the technical proposal and must not be pulled forward to win a deal.

## Sequencing note

**0.1 is not a mall feature — it is a live cross-tenant leak** affecting any deployment with more than one paired agent, and it should ship independently of this plan. 1.1 has the same character. Both exist today, in production, for reasons unrelated to the mall opportunity.

Phase 0 is a few days. Phase 1 is the real body of work and the honest gate on selling to an estate.

## Implementation status — 2.6 per-site spend budgets + settings hazard closed (2026-08-18)

`services/digest/spend_tracker.py` now charges two counters; `digest_site_daily_spend_cap_usd` in config (0 disables, preserving org-only behaviour); `site_id` passed at the call sites that know it (`cameras.py` sequence compiler, `chat.py` when camera-scoped).

**Design decisions worth keeping:**
- **The site counter is charged FIRST.** Otherwise a site already over budget would keep consuming the org's headroom on every rejected call — the cap would throttle that site while still draining everyone else's budget.
- **An org-cap rejection refunds the site charge**, so a rejected call leaves both counters exactly as it found them.
- **`site_daily_cap_usd=None` disables the per-site cap entirely**, which is the correct single-site default and keeps existing deployments unchanged.

**Verified:** site 1 caps at 0.30 and its 4th call is blocked; **site 2 is unaffected by site 1 being capped** (the whole point); the org counter reflects only successful charges; five further rejected site-1 calls leave the org counter untouched; an org-cap rejection refunds the site counter; with no site cap configured the behaviour is byte-for-byte the original.

**Regression found and fixed by running the suite:** the new optional `site_id` parameter broke the `_AlwaysAllowSpend` / `_NeverAllowSpend` doubles in `tests/test_chat.py` (`TypeError`), failing 6 tests. The doubles now mirror the real signature. Suite back to **133 passed**, same 5 pre-existing failures. Frontend builds clean.

**Settings hazard closed:** `UpdateOrgRequest.settings` is removed, so `PATCH /api/settings/org` can no longer replace the whole JSONB blob or write an unvalidated `retention_days` around the range-checked `PUT /api/settings/org/retention`. Confirmed safe first — no caller ever sent it (`api.updateMyOrg` is typed `{name?, plan?}`, the settings page sends only `name`, and no test uses it).

## Implementation status — per-site digests (2026-08-18)

Closes the gap that 1.1 created. `digests.site_id` (migration `e6f1b8d40a37`), persisted by `DigestService._persist_and_deliver`, and `_scope` in `api/digests.py` now filters instead of returning 403.

**Design decisions worth keeping:**
- **Scope is recorded at generation time**, because it is the only moment it is knowable — a digest computed over every event in the org cannot be narrowed to one site afterwards. That fact is exactly why the read path originally had to deny.
- **Org-wide digests (`site_id NULL`) are excluded from a scoped user's list, not shown.** They summarise the whole organisation, so surfacing one would leak precisely what the site restriction exists to prevent. Scheduled morning/evening runs remain org-wide and therefore remain invisible to restricted accounts — per-site scheduled digests are the natural follow-up.
- **On-demand generation requires an explicit `site_id` from a restricted user** (400 without one, 403 for a site they cannot access) rather than silently defaulting to one of their sites — the request should say what it means.
- Digest generation now charges the per-site spend budget too, so a site's digests come out of that site's allowance.

**Verified end-to-end against real Postgres** (temporary test, run then removed): an unrestricted user sees all three digests; a user restricted to one site sees only that site's digest with the org-wide one excluded; the list total matches the scoped rows; a direct fetch of another site's digest returns 404; on-demand generation without a `site_id` is 400 and for a foreign site is 403. Full suite: **133 passed**, same 5 pre-existing failures.

## Implementation status — 2.5 live-view session cap (2026-08-18)

`agent/webrtcsignal/{viewer,answer}.go`: `DefaultMaxSessions = 6`, mutex-guarded acquire/release, `ErrTooManySessions` → HTTP 503 with `Retry-After`, and `ActiveSessions()` for telemetry.

**Design decisions worth keeping:**
- **The cap is enforced agent-side, not in the UI.** The browser is not a trustworthy place to enforce a resource limit on someone else's hardware — a 16-tile wall must be refused by the box, not merely discouraged by the page.
- **Live view is a convenience; detection is the product.** Each session runs its own PeerConnection and pacing loop, so an uncapped wall can starve the pipeline the appliance exists to run. That ordering is the reason a cap exists at all.
- **The slot is held for the life of the stream**, released by `viewerPump`'s defer however it exits (close, failure, disconnect). Releasing at the end of `HandleOffer` would make the cap meaningless — every session would free its slot immediately.
- **Failed negotiation returns its slot.** Everything between acquire and hand-off to the pump is covered by a deferred release, or a failing camera would leak capacity until restart.
- **Acquired after auth**, so an unauthenticated caller cannot exhaust the cap.
- **`SetMaxSessions(n <= 0)` restores the default rather than disabling the limit** — "unlimited" is not a state this box can safely be in.
- **503 + `Retry-After`, not 4xx**: a full appliance is a capacity condition that clears on its own, not a client mistake.

**Verified** (temporary Go test, run then removed): the cap refuses the (n+1)th session; a released slot is reusable; over-release cannot drive the counter negative; `SetMaxSessions(0)` restores the default of 6; and under `-race`, 200 concurrent acquires grant **exactly** 10 with no data race. `go build ./...` clean.

**Still open:** the frontend multi-tile grid itself. The backend/agent side now makes it safe to build — a wall that exceeds the cap gets a clean 503 per tile rather than degrading the appliance.

## Implementation status — 2.5 video wall UI (2026-08-18)

`frontend/src/app/wall/` + a **Video wall** sidebar entry. `WebRTCPlayer.onError` now carries the server's reason (optional param, so existing callers are unchanged).

**Design decisions worth keeping:**
- **Only tiles on screen hold a session.** An `IntersectionObserver` mounts/unmounts the player, and unmounting closes the `RTCPeerConnection` — which is what actually returns the slot to the appliance. Without this, a wall would hold every camera's session for as long as the page stayed open, visible or not. This is the load discipline; the grid is just layout.
- **A 200px `rootMargin`** connects a tile just before it scrolls in, so it is not black for a beat.
- **"At viewer limit" is distinguished from "camera broken".** Only one of those is something the operator can act on (close tiles, drop density), so they must not read the same. This is why `onError` gained a reason.
- **No auto-retry into a 503.** A full appliance is reported with a manual Retry, because hammering it is exactly what a capacity limit is asking you not to do.
- Offline cameras are listed separately rather than rendered as dead tiles — a wall of black squares tells an operator nothing.

`npm run build` compiles clean; `/wall` and `/fleet` both emit as routes.

## Implementation status — 3.1 cross-camera journeys, backend (2026-08-18)

Built to the existing spec (`specs/2026-08-13-camera-map-journeys-design.md`): `models/camera_connection.py`, migration `f7a2c9e15b48`, `services/journeys.py`, `api/camera_connections.py`, `schemas/journey.py`.

**Design decisions worth keeping:**
- **Not re-identification, and the code says so repeatedly.** No embeddings, no biometrics, no visual matching — only operator-drawn adjacency plus event timing. The summary sentence is **templated, never model-generated**, because that wording carries the "may or may not be the same person" caveat that defines what the feature claims; an LLM could restate it as a certainty.
- **Pairs are stored normalised (min, max)**, so `(A,B)` and `(B,A)` are one row enforced by an ordinary unique index rather than an application-level "does the reverse exist?" check. Re-drawing an existing edge is idempotent (returns it) rather than an error, matching what happens when two operators draw the same link.
- **A camera is visited at most once per journey.** Without this, two adjacent cameras with steady traffic bounce the walk back and forth and manufacture a long "path" out of one person standing still — a false positive that would look convincing.
- **The window measures the gap between consecutive sightings**, not total elapsed time from the seed, so a genuine walk across a building is not cut off at an arbitrary total.
- **Cross-site adjacency is rejected**, not stored — two buildings are not joined by a hallway.
- `has_journey: false` is the normal outcome for most events, not an error.

**Verified end-to-end against real Postgres** (temporary test, run then removed), weighted toward false positives as the spec asks: the walk correlates Atrium → Corridor → Loading; an in-window event on an **unconnected** camera is not correlated; an adjacent-camera event **outside the window** is not correlated; `(B,A)` dedupes to the same edge; self-connection is rejected 400; steps carry the operator's connection label; the summary contains the "may or may not be the same person" caveat; an event on an unconnected camera yields no journey; the walk does not bounce between two adjacent cameras; a narrower window drops the correlation. Suite: **133 passed**, same 5 pre-existing failures.

**Still open:** the Map UI (drawing connections) and `JourneyCard` in the frontend.

## Implementation status — 3.1 journeys frontend (2026-08-18)

`components/map/CameraMap.tsx` (shared), `components/map/JourneyCard.tsx`, routes `/map` (live UI) and `/app/map` (v2 shell, replacing its ComingSoon placeholder), plus a **Camera map** sidebar entry. `JourneyCard` is mounted on the event detail page.

**Design decisions worth keeping:**
- **Both shells render the same component.** The v2 map page was a placeholder; pointing it at the shared component means the two shells cannot drift apart on a feature whose copy carries a privacy claim.
- **The caveat travels with the feature, not just the API.** A vertical timeline of camera sightings reads as "we tracked this person" unless it says otherwise, so the disclaimer sits inside `JourneyCard` itself and again on the map page — not only in the backend summary string.
- **`JourneyCard` renders nothing when there is no journey.** Most events correlate with nothing; that is a normal outcome, not an empty state worth drawing.
- **Journeys are fetched on demand, per event detail view**, not eagerly per row in the feed — at mall volumes an eager fetch would be hundreds of requests to usually answer "no journey". (This resolves the spec's open question in favour of the click-to-expand pattern.)
- **Clicking an already-linked pair unlinks it**, and the grid marks linked cameras while a selection is active, so the same gesture is not ambiguous between "connect" and "duplicate".

`npm run build` compiles clean; `/map`, `/app/map`, `/wall`, `/fleet` all emit as routes.

## Implementation status — 3.2 site-wide Ask (2026-08-18)

`api/chat.py::_build_site_context` (retrieval), `ChatRequest.{site_id,start,end}`, grounding rules in `chat_service.SYSTEM_PROMPT`. Reuses the digest subsystem's `compact_events` / `sample_evenly` rather than adding parallel helpers.

**Design decisions worth keeping:**
- **Retrieval is the feature.** Previously a site-wide question reached Gemini with no site data at all, so "what happened near the food court last night?" was answered from the model's prior — i.e. invented. The events are now fetched from the database first and the model is instructed to answer only from them.
- **An empty window says `NONE. Nothing was detected` explicitly** rather than omitting the block. An empty context invites the model to fill the silence; a sentence stating there were none is something it can safely repeat.
- **Sampling is disclosed in the prompt.** Past the 200-event cap the context says it is a sample and that counts are not exhaustive — otherwise the model answers "how many people?" from a truncated list as though it were the whole set.
- **A confidently invented incident is worse than an unhelpful answer**, because a security team may act on it. That is why the system prompt forbids inferring anything not listed and requires citing camera and time.
- Site-wide Asks are charged to that site's spend budget — they are the expensive kind of question.

**Bug found by verification:** `datetime` was never imported in `chat.py`, so the default-window path (`start`/`end` omitted — the branch a real user hits) raised `NameError`. Tests passing explicit windows all passed; only the empty-window case exposed it.

**Verified against real Postgres** (temporary test, run then removed): an empty window states NONE explicitly; 5 events are retrieved with camera names; the window excludes out-of-range events; 250 events cap at 200 in the prompt with the sampling note present. Suite: **133 passed**, same 5 pre-existing failures.

## Implementation status — 3.3 footfall counting (2026-08-18)

`agent/pipeline/footfall.py` (counter), wired into `camera_worker.py` and the batched heartbeat; `cameras.counting_lines` + `footfall_counts` table (migration `a8b3d6f20c94`); ingestion in `internal.py`; `GET /api/fleet/sites/{id}/footfall`.

**This is the one item in the plan that is genuinely new detection work rather than completing something already started, and it is the one whose accuracy is easiest to overstate.**

**Honesty about what it measures** — documented at the top of `footfall.py`, restated on the model, and returned in the API payload:
- Built on tracking **without re-identification**, so it **over-counts on occlusion** (a person hidden behind a pillar gets a fresh track) and **under-counts in crowds** (overlapping detections merge) — the latter precisely when a tenant cares most.
- Detection runs at the sampler's rate, and the degradation ladder lowers it further under load, so fast crossings can be missed.
- None of that is fixable with a better line algorithm; it is a property of tracking without re-ID. The numbers are therefore honest as **relative trend** ("Level 2 is twice as busy after 6pm") and dishonest as **absolute counts** ("4,812 visitors yesterday"). The API returns `estimate: true` plus a caveat string so a client cannot render it as a turnstile figure by omission.

**Design decisions worth keeping:**
- **Runs off the YOLO person detections the gate already produces** — no extra inference, so a camera with counting lines costs no more per frame than one without.
- **Counted before `decide()` branches**, because the "drop" path returns early and a frame that produced no event can still contain a crossing.
- **Bottom-centre, not box centre**, as the tracking point: it approximates where feet meet the floor, which is what actually crosses a line drawn on the ground. Box centre makes tall people cross early.
- **`within_segment` bounds the crossing test to the drawn segment.** An infinite line divides the whole frame, so without this someone walking far past the line's end still counts — the single most common false count in a naive implementation.
- **Raw per-heartbeat buckets, never a running total.** A total cannot be corrected or re-aggregated, and one duplicated heartbeat would corrupt it permanently. Counts are drained agent-side so each bucket is reported exactly once; a dropped heartbeat loses that interval rather than double-counting the next.
- **Zero buckets are not stored**, so idle cameras cost nothing.

**Weakness found by verification, then fixed:** IoU-only association broke whenever a person moved further than their own box width between two *analysed* frames — routine at 1fps idle sampling — so the track reset and the crossing was never counted. Added a centroid-proximity fallback bounded to twice the box width, which recovers those crossings without associating two different people; verified that distant detections are still not merged.

**Verified.** Geometry (10 checks, pipeline): direction, no-crossing, beyond-segment rejection, wide-step crossing, round trip, single-frame flicker, two simultaneous crossings, distant-detection separation, stale-track ageing, malformed-config tolerance. End-to-end (real Postgres): counting lines reach the agent via assignments; heartbeat buckets persist; a second beat appends rather than overwrites; a zero bucket writes nothing; the hourly aggregate sums correctly and carries `estimate: true` + caveat. Suite: **133 passed**, same 5 pre-existing failures. Frontend and agent build clean.

**Still open:** a footfall UI. Whatever renders this must carry the estimate framing — a bare number on a dashboard is exactly the misrepresentation the payload's caveat exists to prevent.
