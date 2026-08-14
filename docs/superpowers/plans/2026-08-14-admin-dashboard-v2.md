# Super-Admin Monitoring/Control Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `/app/admin` into a real org-health monitoring view and give the backend's existing control actions (force-logout, view-sessions, soft-delete/restore) a V2 UI, via a new org detail page.

**Architecture:** One new backend aggregation route (`GET /api/admin/orgs-health`) computed from existing `Camera`/`Event` tables — no new tables, no schema migration. Two frontend changes: `/app/admin`'s org tab gains health columns, and a new `/app/admin/orgs/[id]` page hosts the org's user list plus every control action, wired to backend routes that already exist and are already exposed client-side in `api.ts`.

**Tech Stack:** FastAPI/SQLAlchemy (backend), Next.js/TanStack Query (frontend) — same stack as every prior V2 task.

**Spec:** `docs/superpowers/specs/2026-08-14-admin-dashboard-v2-design.md`

## Global Constraints

- No TDD, no automated tests — standing project preference.
- `npm run build` (frontend) and `python3 -c "from app.main import app"` (backend) must both stay clean.
- Every view/section gets a genuinely distinct, reachable loading state, empty state, and inline error state — established pattern from the frontend-v2-shell project, enforced task-by-task there via review; follow it here too.
- No new database tables or migrations in this plan — the health route is a pure aggregation over existing `Camera`/`Event` data.
- This plan is where Project F's "Login as" button will be added later (a separate plan) — leave a clear, obvious per-user row structure on the org detail page for that to slot into, but do not build the impersonate button itself here (out of scope for this plan).

---

## File Structure

```
backend/app/api/admin.py                       # MODIFY — add GET /orgs-health
frontend/src/lib/api.ts                         # MODIFY — add adminGetOrgsHealth,
                                                    adminGetUsersByOrg convenience wrapper
                                                    is unnecessary (adminGetUsers already
                                                    supports org_id)
frontend/src/app/app/admin/page.tsx             # MODIFY — org tab shows health columns,
                                                    each row links to /app/admin/orgs/[id]
frontend/src/app/app/admin/orgs/[id]/page.tsx   # CREATE — org detail: health + user list
                                                    + control actions
```

---

### Task 1: Backend — org health aggregation route

**Files:**
- Modify: `backend/app/api/admin.py`

**Interfaces:**
- Produces: `GET /api/admin/orgs-health` → `list[{org_id, name, plan, camera_count, cameras_online, cameras_offline, events_last_24h, events_last_7d, last_event_at}]` (`last_event_at` is an ISO string or `null`).

- [ ] **Step 1: Add the imports this route needs**

`backend/app/api/admin.py` already imports `datetime, timedelta, timezone` and `desc, func, select` (confirmed against the real file). Add:

```python
from sqlalchemy import case  # alongside the existing "from sqlalchemy import desc, func, select" line
from app.models.camera import Camera
from app.models.event import Event
```

- [ ] **Step 2: Add the route**

```python
@router.get("/orgs-health")
async def orgs_health(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Per-org camera/event health snapshot — super_admin only."""
    _require_super_admin(user)

    orgs = (
        await db.execute(
            select(Organization).where(Organization.deleted_at.is_(None)).order_by(Organization.name)
        )
    ).scalars().all()

    cam_rows = (
        await db.execute(
            select(
                Camera.org_id,
                func.count(Camera.id).label("camera_count"),
                func.sum(case((Camera.status == "online", 1), else_=0)).label("cameras_online"),
            )
            .where(Camera.deleted_at.is_(None))
            .group_by(Camera.org_id)
        )
    ).all()
    cam_map = {r.org_id: r for r in cam_rows}

    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)

    ev24_map = {
        r.org_id: r.c
        for r in (
            await db.execute(
                select(Event.org_id, func.count(Event.id).label("c"))
                .where(Event.timestamp >= since_24h)
                .group_by(Event.org_id)
            )
        ).all()
    }
    ev7_map = {
        r.org_id: r.c
        for r in (
            await db.execute(
                select(Event.org_id, func.count(Event.id).label("c"))
                .where(Event.timestamp >= since_7d)
                .group_by(Event.org_id)
            )
        ).all()
    }
    last_ev_map = {
        r.org_id: r.last
        for r in (
            await db.execute(select(Event.org_id, func.max(Event.timestamp).label("last")).group_by(Event.org_id))
        ).all()
    }

    result = []
    for org in orgs:
        cam = cam_map.get(org.id)
        camera_count = cam.camera_count if cam else 0
        cameras_online = int(cam.cameras_online) if cam and cam.cameras_online else 0
        last_event_at = last_ev_map.get(org.id)
        result.append(
            {
                "org_id": str(org.id),
                "name": org.name,
                "plan": org.plan,
                "camera_count": camera_count,
                "cameras_online": cameras_online,
                "cameras_offline": camera_count - cameras_online,
                "events_last_24h": ev24_map.get(org.id, 0),
                "events_last_7d": ev7_map.get(org.id, 0),
                "last_event_at": last_event_at.isoformat() if last_event_at else None,
            }
        )
    return result
```

Place this route in `admin.py` near the other `/orgs*` routes (e.g. directly after `list_all_orgs`), for readability.

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/backend && uv run python3 -c "from app.main import app"
```
Expected: imports cleanly.

- [ ] **Step 4: Manual verification**

Start the backend, call `GET /api/admin/orgs-health` with a super_admin session (or reason through the query logic carefully if you can't reach a running backend+DB in this environment) — confirm the numbers for at least one real org with cameras/events match what you'd expect by cross-checking against `GET /api/cameras?org_id=...` and `GET /api/events?org_id=...` directly.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/admin.py
git commit -m "backend: add per-org camera/event health aggregation route"
```

---

### Task 2: Frontend — `adminGetOrgsHealth` API method

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: Task 1's `GET /api/admin/orgs-health`.
- Produces: `api.adminGetOrgsHealth(): Promise<OrgHealth[]>`, used by Task 3.

- [ ] **Step 1: Add the typed method**

Add near the existing `adminGetOrgs`/`adminGetUsers` methods:

```ts
async adminGetOrgsHealth() {
  return this.request<
    {
      org_id: string;
      name: string;
      plan: string;
      camera_count: number;
      cameras_online: number;
      cameras_offline: number;
      events_last_24h: number;
      events_last_7d: number;
      last_event_at: string | null;
    }[]
  >("/api/admin/orgs-health");
}
```

- [ ] **Step 2: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/frontend && npx tsc --noEmit
```
Expected: no new type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "frontend: add adminGetOrgsHealth API method"
```

---

### Task 3: Frontend — `/app/admin`'s Orgs tab shows health columns

**Files:**
- Modify: `frontend/src/app/app/admin/page.tsx`

**Interfaces:**
- Consumes: `api.adminGetOrgsHealth()` (Task 2).
- Produces: each org row links to `/app/admin/orgs/{org_id}` (Task 4).

- [ ] **Step 1: Read the current file**

The current `frontend/src/app/app/admin/page.tsx` (read in full during design — reproduced above in this plan's research, not re-pasted here since it's unchanged boilerplate for the Users tab) has a `tab === "orgs"` branch rendering `(orgs ?? []).map((o: {id, name}) => <div>{o.name}</div>)` using `api.adminGetOrgs()`. Replace that data source and row rendering — the Users tab and the tab-switcher buttons stay untouched.

- [ ] **Step 2: Swap the orgs query and row rendering**

Replace:
```tsx
const { data: orgs, isLoading: orgsLoading, isError: orgsError, error: orgsErrorObj } = useQuery({
  queryKey: ["admin", "orgs"],
  queryFn: () => api.adminGetOrgs(),
  enabled: user?.role === "super_admin",
});
```
with:
```tsx
const { data: orgsHealth, isLoading: orgsLoading, isError: orgsError, error: orgsErrorObj } = useQuery({
  queryKey: ["admin", "orgs-health"],
  queryFn: () => api.adminGetOrgsHealth(),
  enabled: user?.role === "super_admin",
});
```

Replace the orgs-tab row rendering:
```tsx
{(orgs ?? []).length > 0 ? (
  <div className="flex flex-col gap-2">
    {(orgs ?? []).map((o: { id: string; name: string }) => (
      <div key={o.id} className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-lg px-4 py-3 text-sm">
        {o.name}
      </div>
    ))}
  </div>
) : (
  <div className="text-sm text-[oklch(55%_0.01_265)]">No organizations found.</div>
)}
```
with:
```tsx
{(orgsHealth ?? []).length > 0 ? (
  <div className="flex flex-col gap-2">
    {(orgsHealth ?? []).map((o) => {
      const stale = !o.last_event_at || new Date(o.last_event_at).getTime() < Date.now() - 7 * 24 * 60 * 60 * 1000;
      return (
        <Link
          key={o.org_id}
          href={`/app/admin/orgs/${o.org_id}`}
          className="flex items-center justify-between bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-lg px-4 py-3 text-sm hover:border-[oklch(85%_0.16_84)] transition-colors"
        >
          <div>
            <div className="font-semibold">{o.name}</div>
            <div className="text-[11px] text-[oklch(55%_0.01_265)] mt-0.5">
              {o.camera_count} cameras ({o.cameras_online} online) · {o.events_last_24h} events (24h)
            </div>
          </div>
          {stale && (
            <div className="text-[11px] font-semibold px-2 py-1 rounded-full bg-[oklch(70.4%_0.191_22.216_/_0.16)] text-[oklch(70.4%_0.191_22.216)]">
              No events 7d+
            </div>
          )}
        </Link>
      );
    })}
  </div>
) : (
  <div className="text-sm text-[oklch(55%_0.01_265)]">No organizations found.</div>
)}
```

`orgsErrorObj`/`orgsError` continue to reference the same query (just renamed the underlying data variable, not the error-handling branch) — no changes needed to the existing error-state JSX above this block.

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/frontend && npm run build
```
Expected: zero type errors.

- [ ] **Step 4: Manual verification**

Visit `/app/admin`, Orgs tab — confirm health numbers render, confirm the "No events 7d+" badge shows correctly for an org with no recent events, confirm clicking a row navigates to `/app/admin/orgs/{id}` (404 until Task 4 lands).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/app/admin/page.tsx
git commit -m "frontend: /app/admin Orgs tab shows health snapshot, links to org detail"
```

---

### Task 4: Frontend — org detail page (users + controls)

**Files:**
- Create: `frontend/src/app/app/admin/orgs/[id]/page.tsx`

**Interfaces:**
- Consumes: `api.adminGetUsers({org_id})` (existing, already supports this param), `api.adminForceLogout(userId)`, `api.adminGetUserSessions(userId)`, `api.adminDeleteOrg(orgId)`, `api.adminRestoreOrg(orgId)` (all existing, confirmed present in `api.ts`), `api.adminGetOrgsHealth()` (Task 2, reused here for this org's own health row — filter client-side by `org_id`, no new single-org backend route needed for this plan's scope).

- [ ] **Step 1: Implement the page**

```tsx
// frontend/src/app/app/admin/orgs/[id]/page.tsx
"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuthStore } from "@/lib/store";

export default function AdminOrgDetailPageV2({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user } = useAuthStore();
  const queryClient = useQueryClient();
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);

  const isSuperAdmin = user?.role === "super_admin";

  const { data: orgsHealth, isLoading: healthLoading, isError: healthError } = useQuery({
    queryKey: ["admin", "orgs-health"],
    queryFn: () => api.adminGetOrgsHealth(),
    enabled: isSuperAdmin,
  });
  const org = orgsHealth?.find((o) => o.org_id === id);

  const { data: orgUsers, isLoading: usersLoading, isError: usersError, error: usersErrorObj } = useQuery({
    queryKey: ["admin", "users", id],
    queryFn: () => api.adminGetUsers({ org_id: id }),
    enabled: isSuperAdmin,
  });

  const { data: sessions } = useQuery({
    queryKey: ["admin", "sessions", expandedUserId],
    queryFn: () => api.adminGetUserSessions(expandedUserId!),
    enabled: isSuperAdmin && !!expandedUserId,
  });

  const forceLogout = useMutation({
    mutationFn: (userId: string) => api.adminForceLogout(userId),
  });

  const deleteOrg = useMutation({
    mutationFn: () => api.adminDeleteOrg(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "orgs-health"] }),
  });

  const restoreOrg = useMutation({
    mutationFn: () => api.adminRestoreOrg(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "orgs-health"] }),
  });

  if (!isSuperAdmin) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        Not authorized.
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <Link href="/app/admin" className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
        ← Admin
      </Link>

      {healthLoading ? (
        <Skeleton className="h-24 w-full mb-8" />
      ) : healthError ? (
        <div className="mb-8 text-sm text-[oklch(70.4%_0.191_22.216)]">Couldn&apos;t load org health.</div>
      ) : org ? (
        <div className="mb-8">
          <div className="text-[28px] font-bold tracking-tight mb-1">{org.name}</div>
          <div className="text-sm text-[oklch(58%_0.01_265)]">
            {org.camera_count} cameras ({org.cameras_online} online) · {org.events_last_24h} events (24h) ·{" "}
            {org.events_last_7d} events (7d)
          </div>
        </div>
      ) : (
        <div className="mb-8 text-sm text-[oklch(55%_0.01_265)]">Org not found.</div>
      )}

      <div className="flex gap-2 mb-8">
        <button
          onClick={() => deleteOrg.mutate()}
          disabled={deleteOrg.isPending}
          className="text-sm font-semibold px-4 py-2 rounded-lg text-[oklch(70.4%_0.191_22.216)] border border-[oklch(70.4%_0.191_22.216)] disabled:opacity-50"
        >
          Delete org
        </button>
        <button
          onClick={() => restoreOrg.mutate()}
          disabled={restoreOrg.isPending}
          className="text-sm font-semibold px-4 py-2 rounded-lg text-[oklch(72%_0.01_265)] border border-[oklch(22%_0.015_265)] disabled:opacity-50"
        >
          Restore org
        </button>
      </div>
      {(deleteOrg.isError || restoreOrg.isError) && (
        <div className="mb-4 text-sm text-[oklch(70.4%_0.191_22.216)]">Action failed. Try again.</div>
      )}

      <div className="text-base font-bold mb-3">Team</div>
      {usersLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : usersError ? (
        <div className="text-sm text-[oklch(70.4%_0.191_22.216)]">
          {usersErrorObj instanceof Error ? usersErrorObj.message : "Could not load team."}
        </div>
      ) : (orgUsers ?? []).length > 0 ? (
        <div className="flex flex-col gap-2">
          {orgUsers!.map((u) => (
            <div key={u.id} className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-lg px-4 py-3">
              <div className="flex items-center justify-between text-sm">
                <div>
                  {u.username} · {u.role}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setExpandedUserId(expandedUserId === u.id ? null : u.id)}
                    className="text-[12px] text-[oklch(72%_0.01_265)]"
                  >
                    Sessions
                  </button>
                  <button
                    onClick={() => forceLogout.mutate(u.id)}
                    disabled={forceLogout.isPending}
                    className="text-[12px] text-[oklch(70.4%_0.191_22.216)] disabled:opacity-50"
                  >
                    Force logout
                  </button>
                  {/* Project F (separate plan) adds a "Login as" button here */}
                </div>
              </div>
              {expandedUserId === u.id && (
                <div className="mt-2 pt-2 border-t border-[oklch(22%_0.015_265)] text-[11px] text-[oklch(58%_0.01_265)]">
                  {sessions ? JSON.stringify(sessions) : "Loading sessions..."}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-sm text-[oklch(55%_0.01_265)]">No team members yet.</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/frontend && npm run build
```
Expected: zero type errors, `/app/admin/orgs/[id]` present in the route list.

- [ ] **Step 3: Manual verification**

Visit `/app/admin/orgs/{id}` for a real org — confirm health, team list, force-logout (confirm the target user's session is genuinely revoked afterward — check via the Sessions expand or by trying to use their token), and delete/restore all work and surface errors on failure rather than failing silently.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/admin/orgs
git commit -m "frontend: org detail page with health, team list, and admin controls"
```

---

## Self-Review

**Spec coverage:** health snapshot (Task 1-3), force-logout/sessions/delete/restore UI (Task 4) — both of Project E's spec requirements are covered. The "Login as" button's slot is left as an explicit comment placeholder in Task 4's JSX for Project F to fill in, per this plan's Global Constraints (not building impersonation here).

**Placeholder scan:** no TBD/TODO; the one intentional comment (`{/* Project F (separate plan) adds a "Login as" button here */}`) is a deliberate, documented handoff point, not a shirked requirement — it's explicitly out of scope for this plan.

**Type consistency:** `api.adminGetOrgsHealth()`'s return shape (Task 2) is used identically in Task 3 and Task 4 — same field names (`org_id`, `camera_count`, `cameras_online`, `events_last_24h`, `events_last_7d`, `last_event_at`) in both call sites.
