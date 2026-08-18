# Camera Map & Journeys — Design (Project B of 3)

*Date: 2026-08-13*

## Context

This is Project B of the three-project frontend-v2 decomposition (see [Project A's spec](2026-08-13-frontend-v2-shell-design.md)). The mockup's "Map" view lets a user click two camera tiles to mark them as physically connected ("a doorway, hallway, or gate"), then uses those connections to correlate events across cameras into a "journey" — e.g. someone entering on Camera A, then appearing on connected Camera B a few minutes later.

**Corrected scope, important:** this is **not** biometric person re-identification. No appearance embeddings, no cross-camera visual identity matching, no GPU. It's a manually-curated adjacency graph over existing per-camera detections, correlated by time. A prior design in this repo (`docs/superpowers/specs/2026-08-01-remind-reid-integration-design.md`) explicitly scoped true re-identification as a separate, harder, GPU-dependent, more privacy-sensitive problem and left it undone — this project does not touch that territory. Journeys here are a **probabilistic correlation signal** ("plausibly the same visitor, based on timing and physical adjacency"), never a certain identity match, and all UI copy must reflect that honestly.

## Goal

Let users draw physical adjacency between cameras at a site, and see events correlated across that adjacency as a "journey" — both as a dedicated Map view (drawing connections) and woven into Home/Activity (showing a journey's steps when relevant).

## Architecture

```
backend/app/models/camera_connection.py   # new model
backend/app/schemas/camera_connection.py  # new schema
backend/app/api/camera_connections.py     # new CRUD route (site-scoped)
backend/app/services/journeys.py          # new: on-demand journey query,
                                             not a background job

frontend/src/components/v2/Map.tsx        # port of mockup's Map view
frontend/src/components/v2/JourneyCard.tsx # reusable journey display,
                                              used in Home/Activity too
```

**Data model — `camera_connections` table:**
```
id            uuid, pk
org_id        uuid, fk organizations
site_id       uuid, fk sites          -- both cameras MUST belong to this site
camera_a_id   uuid, fk cameras
camera_b_id   uuid, fk cameras
label         text, nullable          -- e.g. "Back hallway", user-editable
created_at    timestamptz
```
Constraint: `camera_a_id` and `camera_b_id` must both have `site_id` matching the connection's `site_id` (physical adjacency only makes sense within one location) — enforced at the service layer, matching this project's existing pattern of application-level multi-tenant checks rather than DB-level cross-table constraints. Unordered pair (A-B same as B-A) — dedupe by normalizing `(min(a,b), max(a,b))` before insert, matching the mockup's own `connectionKey()` behavior (`[a, b].sort().join('|')`).

**Journey construction — a query, not a pipeline:**
Given a "seed" event on camera A at time T, a journey step exists on camera B if: (1) A and B are connected (directly, or transitively through a chain of connections), (2) B has an event within a configurable window after T (default 10 minutes, matching a reasonable walking-across-a-building timeframe), (3) chain stops at the first camera with no further connected-camera event within the window, or after a max chain length (default 5, to bound the query). Computed on-demand when the Map or Activity view requests it — no new background job, no new table for materialized journeys in this first version. If this proves too slow at scale (many events, many connections), materializing it becomes a documented follow-up, not built now.

## Data flow

1. User opens Map view → `GET /api/sites/{id}/camera-connections` → renders nodes (cameras) + edges (connections), matching mockup's `mapNodes`/`mapLines`.
2. User clicks two camera nodes → `POST /api/sites/{id}/camera-connections {camera_a_id, camera_b_id}` → creates the edge, default label empty (editable inline, matching mockup's `ln.onLabelChange`).
3. User clicks the `×` on a connection label → `DELETE /api/sites/{id}/camera-connections/{connection_id}`.
4. Home/Activity/Camera Detail views that want to show "this event is part of a journey" call `GET /api/events/{id}/journey` → runs the on-demand correlation query starting from that event, returns the mockup's `journeysData` shape: `{subject, severity, steps: [{camera, time, event_id}], summary}`. `summary` is a short templated sentence (not LLM-generated in this first version — e.g. `"Event on {camera_a} at {time_a}, followed by an event on {camera_b} ({label}) at {time_b}."`), assembled server-side from the correlated steps.

## Error handling

- No connections drawn yet → Map shows the mockup's existing empty state ("No connections yet — click two cameras to link them").
- Journey query on an event with no correlated follow-on events → no journey card shown at all (not an error, just nothing to correlate — most events won't have one).
- Deleting a connection that a UI is mid-edit on → standard optimistic-update-with-revert pattern already used elsewhere in this frontend (per `frontend/CLAUDE.md`'s existing rules for mutations).

## Testing

No automated tests for this project (standing preference, consistent with every other project in this session) — manual verification: draw a connection between two real cameras at a test site, generate events on both within the time window, confirm the journey query correlates them; confirm an event outside the window or on an unconnected camera does NOT get correlated (false-positive check matters more than false-negative here, given the "plausibly the same visitor" framing).

## Non-goals

- No appearance-based / biometric person re-identification. No embeddings, no GPU, no visual identity matching of any kind.
- No claim of certain identity — all UI copy frames this as a timing/adjacency correlation, never "we identified this person."
- No background job / materialized journey table in this first version — pure on-demand query. Revisit only if query performance becomes a real, measured problem.
- Connections are scoped to one site — no cross-site adjacency (doesn't make physical sense: two different buildings aren't "connected by a hallway").
- Multi-camera "Agents" (notify-me-on-a-journey rules) is Project C's job, built on top of this data — not built here.

## Open questions

- Time-window default (10 min) and max chain length (5) are reasonable starting guesses, not validated against real usage — worth tuning once there's real pilot data.
- Whether `GET /api/events/{id}/journey` should be called eagerly for every event shown in Activity (more requests, always-fresh) or only on-demand when a user expands an event (fewer requests, matches the mockup's click-to-see-journey interaction pattern more closely) — implementation-plan-level decision.
