# Super-Admin Monitoring/Control Dashboard — Design (Project E of 3)

*Date: 2026-08-14*

## Context

This is Project E of a three-project super-admin decomposition (see [Project D](2026-08-14-test-ai-v2-design.md), [Project F](2026-08-14-impersonation-design.md)). `/app/admin` (built in an earlier plan) is currently a bare, read-only Users/Orgs tab list — no health data, no control actions wired up. The backend already has real control capability with zero V2 UI: `POST /api/admin/users/{id}/force-logout`, `GET /api/admin/users/{id}/sessions`, `DELETE`/`POST .../restore` for both orgs and users.

## Goal

Turn `/app/admin` into a real client-health monitoring view (which org needs attention, at a glance) and give every existing backend control action a place to be triggered from in the V2 UI. This is also the entry point for Project F's "Login as" action, at the org's user-list level.

## Architecture

```
backend/app/api/admin.py         # MODIFY: add org-health aggregation route
frontend/src/app/app/admin/page.tsx           # MODIFY: org list with health, not just names
frontend/src/app/app/admin/orgs/[id]/page.tsx # NEW: org detail — users, sessions, controls
```

**New backend route — org health aggregation:**
```python
GET /api/admin/orgs-health
  -> list[{
       org_id, name, plan,
       camera_count, cameras_online, cameras_offline,
       events_last_24h, events_last_7d,
       last_event_at,  # max(Event.timestamp) for this org, null if none ever
     }]
```
Computed via grouped aggregate queries against `Camera` (`org_id`, `status`) and `Event` (`org_id`, `timestamp`) — both already indexed on `org_id` (`Event` additionally has `ix_events_org_timestamp`). Gated by the same `_require_super_admin(user)` pattern already used by every other route in `admin.py`. No new tables.

**Org detail page** (`/app/admin/orgs/[id]`): fetches the org's health row (reuse the list endpoint client-side, or add a `GET /api/admin/orgs/{id}/health` single-org variant — implementation-plan-level choice) plus `GET /api/admin/users?org_id={id}` (existing route, already supports this filter) to list the org's team. Each user row gets:
- **Force logout** → `POST /api/admin/users/{id}/force-logout` (existing)
- **View sessions** → `GET /api/admin/users/{id}/sessions` (existing) — shown inline or in a small expandable panel
- **Login as** → Project F's impersonation flow (this page is where that button lives)

Org-level controls (soft-delete/restore) reuse the existing `DELETE`/`POST .../restore` routes, surfaced as buttons on the org detail page.

## Data flow

`/app/admin` → `GET /api/admin/orgs-health` → render as a sortable/scannable list (status color derived from `cameras_online/camera_count` ratio and `last_event_at` staleness — e.g. an org with cameras but no event in 7 days is a visible warning signal) → click a row → `/app/admin/orgs/{id}` → the detail/control view described above.

## Error handling

Same established V2 pattern from the frontend-v2-shell project: distinct loading skeleton, empty state (no orgs), and inline error state (oklch error token) for every query on both pages. Control-action mutations (force-logout, delete, restore) get their own error surfacing on failure — don't let a failed action fail silently, matching the digests-preferences fix from that earlier project.

## Testing

No automated tests (standing project preference) — manual verification: confirm health numbers match reality for a real org with cameras/events, confirm each control action's backend effect actually occurs (a forced-logout user's session is genuinely revoked, checkable via the sessions list).

## Non-goals

- Not building a generic cross-tenant data browser (e.g. viewing a client's raw event list from the admin side) — that's what Project F's impersonation is for; this dashboard is health/status + account-level controls only.
- Not adding any new soft-delete/restore/session capability beyond what the backend already has — pure UI wiring plus one new aggregation route.

## Open questions

- Single-org health route vs. reusing the list endpoint and filtering client-side — implementation-plan-level, doesn't change this design.
- Exact staleness threshold for the "needs attention" visual signal (7 days used above as a placeholder) — tune once there's real data to look at.
