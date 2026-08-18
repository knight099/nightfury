# Agentic Camera Setup — Design

*Date: 2026-08-18*

## Problem

Configuring a camera today is entirely manual: an operator picks event types,
draws detection zones, sets sensitivity and frame rates, decides whether pose
tracking is worth enabling, and writes any alert rules. That is a reasonable
ask for the four cameras a home user owns.

At mall scale it is the bottleneck. A 400-camera estate is 400 rounds of the
same judgement, made by someone who is not a computer-vision engineer, and the
usual outcome is that most cameras keep whatever default they were created
with — `person, vehicle, intrusion` at medium sensitivity, no zones, no
counting lines. The platform then under-performs for reasons that look like
model quality but are really configuration.

## Goal

An operator points the system at a batch of cameras. For each one, the agent
watches the actual camera for a few minutes, works out what it is looking at,
and **proposes** a complete configuration with a plain-English rationale.
Similar cameras are grouped so the operator reviews a handful of proposals
rather than hundreds. Nothing takes effect until a human approves it.

## Non-goals

- **No camera adjacency.** Whether camera A connects to camera B is a fact
  about the building, not something visible in either camera's frames. The
  honest signal is event co-occurrence over weeks, which does not exist at
  onboarding, and name heuristics ("Corridor 2A" next to "Corridor 2B")
  produce confident-looking garbage. Journeys built on wrong adjacency invent
  narratives about people, which is precisely what that feature is designed
  not to do. Adjacency stays manual, in the existing Map UI, and the setup
  flow prompts for it after a batch is approved.
- **No auto-apply.** The agent never writes a live configuration. This matches
  the existing sequence compiler: AI drafts, a human commits.
- **No continuous re-tuning.** A camera is proposed once. Re-running setup on
  an already-configured camera is an explicit operator action, not a
  background process that quietly changes what a site detects.
- **No new detection models.** The agent chooses among the models that already
  exist (YOLO gate, pose) — it does not train, fetch or swap anything.
- **No whole-site "configure everything" button.** Setup runs on an
  operator-selected batch (see Batching).

## Architecture

```
Operator selects a batch of cameras, clicks "Propose setup"
  → POST /api/sites/{id}/setup-runs {camera_ids}
  → backend creates a setup_run + one camera_setup_proposal per camera
    (status: pending) and enqueues one job per camera onto that camera's
    OWN agent's Redis job list

Agent (per box, already sharded by camera placement)
  → GET /api/agents/me/setup-jobs        (drain, same pattern as resolve-jobs)
  → for each job: sample 10 frames over 3 minutes from the live stream
    (defaults; see Open questions)
  → ONE structured Gemini Vision call (credentials from the existing broker;
    frames go pipeline → Gemini directly, never through backend)
  → POST /api/agents/me/setup-jobs/{camera_id}  {proposal | error}

Backend
  → validate proposal against the same rules the manual API enforces
  → cluster proposals in the batch by scene_type into review groups
  → status: proposed | needs_input | failed

Operator reviews groups
  → GET  /api/sites/{id}/setup-proposals?run_id=...   (grouped)
  → POST /api/setup-proposals/{id}/approve            (one camera)
  → POST /api/setup-runs/{id}/approve-group {scene_type}  (bulk, detection only)
  → approval writes camera config; alert rules are confirmed per item
  → on batch completion, prompt: "link these cameras on the map"
```

### Why the agent does the looking

Frames never leave the premises. The pipeline already holds decoded frames and
already calls Gemini with a device-token-brokered credential; the setup call
is the same path with a different prompt. Doing this backend-side would mean
either shipping frames to the cloud (breaking the core promise) or working
from the single stored `latest/{camera_id}.webp` snapshot, which cannot show
what *moves* through a scene — and movement is what decides event types,
sensitivity and where a counting line belongs.

### Job dispatch reuses an existing pattern

`api/agents.py` already enqueues ONVIF resolve jobs to a per-agent Redis list,
which the agent drains and reports back on. Setup jobs use the same mechanism,
with one deliberate difference: **resolve jobs are popped and lost if an agent
dies mid-job; setup jobs are backed by a `camera_setup_proposals` row**, so a
lost job leaves a visible `pending` proposal that the operator can retry. The
queue is a dispatch hint; the database is the truth.

## Batching

Setup runs on an operator-selected batch, never a whole site at once. Three
reasons, in order of importance:

1. **The operator learns from batch one.** If the agent misjudges a parking
   level, that is discovered on 12 cameras, not 400.
2. **It bounds AI spend per run.** One Gemini Vision call per camera is
   cheap individually and material at 400. Runs also charge the per-site
   daily budget, so a large batch degrades to "queued" rather than
   overspending.
3. **A batch is usually already scene-coherent** — an operator selects a floor
   or a wing — so the grouping has less work to do and the groups are more
   likely to match how the operator thinks about the building.

A batch is capped (default 50 cameras) so a single run stays reviewable.

## Grouping

Proposals in a run are clustered by `scene_type` — a closed enum the model
must choose from, not free text, so clustering is exact rather than fuzzy
string matching:

`parking` · `corridor` · `retail_frontage` · `entrance` · `loading_bay` ·
`atrium` · `perimeter` · `other`

A group is presented with the config its members share. Where members differ
(one corridor camera saw vehicles), the difference is shown and that camera is
split into its own review card rather than silently averaged into the group.

Proposals with `confidence < 0.6`, a validation failure, or `scene_type:
other` go to a **"Needs your input"** group and are never bulk-approvable.

## The proposal

Gemini returns one structured JSON object per camera:

| Field | Meaning |
|---|---|
| `scene_type` | One of the closed enum above. Drives grouping. |
| `scene_description` | One sentence, shown to the operator. |
| `confidence` | 0–1. Below 0.6 routes to "Needs your input". |
| `enabled_events` | Subset of the event types this camera should watch for. |
| `sensitivity` | `low` / `medium` / `high`. |
| `zones` | Named polygons in frame coordinates. |
| `counting_lines` | Named segments for footfall, only where a natural crossing exists. |
| `suggest_pose` | Whether pose tracking earns its cost here. |
| `suggested_alert` | Draft alert rule, or null. Per-item confirm only. |
| `rationale` | Why, in plain English. Shown verbatim — never summarised. |

The rationale is the load-bearing field. An operator approving twelve cameras
at once needs to know *why* vehicle detection was left off, and a proposal
they cannot interrogate is one they will either rubber-stamp or ignore.

## Validation

Every proposal passes through the same validation the manual camera API
enforces before it is stored. Concretely: any `step_sequence` in a proposal
goes through `cameras.py::_validate_step_sequence` unchanged (zone names must
resolve, poses must be valid), and in addition:

- Polygons must have ≥3 points and lie within frame bounds.
- Counting lines must be a segment of non-zero length within frame bounds.
- `enabled_events` must be non-empty and drawn from known types.
- `sensitivity` must be one of the three valid values.

A proposal failing validation becomes `needs_input` with the reason attached.
**It is never silently corrected**, because a corrected proposal is no longer
the thing the model justified in its rationale.

## Data model

```
setup_runs
  id, org_id, site_id, requested_by, created_at
  status: running | complete | cancelled
  camera_count

camera_setup_proposals
  id, org_id, site_id, camera_id, run_id
  status: pending | proposed | needs_input | failed | approved | rejected
  scene_type, scene_description, confidence
  proposal        jsonb   -- the full returned object
  rationale       text
  error           text    -- why it failed / what needs input
  approved_by, approved_at
  created_at
```

Proposals are retained after approval as the record of what was proposed and
who accepted it — the audit trail for a configuration a human did not write
by hand.

## Error handling

| Condition | Behaviour |
|---|---|
| Camera offline when the job runs | Proposal stays `pending`; retryable from the UI. Never a proposal from no frames. |
| Too few frames sampled (stream unstable) | `needs_input` with "could not observe this camera long enough". |
| Gemini unavailable / circuit breaker open | `failed`, retryable. No partial config. |
| Malformed or unparseable model output | `needs_input`. One corrective re-prompt first, matching the sequence compiler. |
| Validation failure | `needs_input` with the specific rule that failed. |
| Per-site AI budget exhausted | Remaining jobs stay `pending` and the run reports "queued — daily AI budget reached". |
| Agent dies mid-run | Jobs lost from Redis, proposals stay `pending`, operator retries the run. |

## Scale

- Jobs are enqueued to **each camera's own agent**, so dispatch is already
  sharded by the placement reconciler — no central worker to saturate.
- Concurrent setup jobs per agent are capped (default 2) so onboarding never
  competes with detection for the box's capacity. Setup is not urgent;
  detection is.
- Clustering operates on a batch of ≤50 small rows — trivial.
- One Gemini Vision call per camera, once. A 400-camera estate onboarded in
  batches of 50 is 8 runs and 400 calls total, charged against the per-site
  budget.

## Testing

No automated tests, per the standing preference — implement directly and
self-review. Manual verification, weighted toward the failure paths, which is
where this design's risk sits:

- A camera pointed at a wall produces `needs_input`, not a confident empty
  config.
- A proposal with an out-of-bounds polygon is rejected rather than clamped.
- A batch where one camera is offline completes for the rest and leaves that
  one retryable.
- Approving a group writes exactly the config shown, and approving nothing
  leaves every camera untouched.
- Alert rules cannot be approved in bulk.

## Open questions

- Frame count and observation window (proposed: 10 frames over 3 minutes) are
  a starting guess. Too short misses the activity that decides event types;
  too long makes onboarding tedious. Worth tuning against a real site.
- Whether `retail_frontage` and `atrium` are distinct enough to be separate
  scene types, or whether they collapse in practice, will only be answerable
  with real mall footage.
