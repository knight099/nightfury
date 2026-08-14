# Impersonation ("Login as Client") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A super admin can click "Login as {user}" on the org detail page (built in the admin-dashboard-v2 plan) and be transparently switched into that user's real session — full read+write, matching their exact role — with every action audit-logged, no nested impersonation, and a persistent exit banner.

**Architecture:** Impersonation mints a genuine new Redis session for the target user (their real `role`/`org_id`), tagged with one extra field (`impersonated_by`) — so every existing route's authorization logic (all ~10 files that branch on `user.role`) needs zero changes. `get_current_user` attaches the resolved session dict to `request.state.session`, which both the no-nesting check and a new audit-logging middleware read directly — no duplicate token decryption anywhere.

**Tech Stack:** FastAPI/SQLAlchemy/Redis (backend), Next.js/Zustand (frontend) — same stack as every prior task in this project. New: one Alembic migration for an `audit_log` table.

**Spec:** `docs/superpowers/specs/2026-08-14-impersonation-design.md`

**Depends on:** `docs/superpowers/plans/2026-08-14-admin-dashboard-v2.md` Task 4 (`frontend/src/app/app/admin/orgs/[id]/page.tsx` must exist before this plan's Task 6, which modifies it).

## Global Constraints

- No TDD, no automated tests — standing project preference.
- `npm run build` (frontend) and `python3 -c "from app.main import app"` (backend) must both stay clean at every task.
- Full read+write while impersonating, matching the target's own role exactly — approved, binding decision, not a restricted/read-only mode.
- No nested impersonation — enforced server-side (the authoritative check), not merely hidden in the UI.
- No impersonating a `super_admin` target, and no impersonating a user whose org is soft-deleted.
- Every action while impersonating is audit-logged — not just session start/end.
- Explicitly NOT wanted: shortened session expiry for impersonated sessions — they use the same TTLs as any normal session.
- Zero changes to any existing route's `if user.role == "super_admin"` authorization logic — this plan's entire safety property depends on impersonated sessions being indistinguishable from real ones everywhere except the audit middleware and the no-nesting check.

---

## File Structure

```
backend/app/core/sessions.py           # MODIFY — create_session gains impersonated_by param
backend/app/core/dependencies.py       # MODIFY — get_current_user sets request.state.session
backend/app/models/audit_log.py        # CREATE — AuditLog table
backend/alembic/versions/<generated>.py # CREATE — migration for audit_log
backend/app/services/audit_log_service.py  # CREATE — record(...)
backend/app/api/admin.py               # MODIFY — add POST .../impersonate route
backend/app/core/middleware.py         # MODIFY — add ImpersonationAuditMiddleware
backend/app/main.py                    # MODIFY — register the middleware

frontend/src/lib/api.ts                # MODIFY — add adminImpersonateUser
frontend/src/lib/store.ts              # MODIFY — originalToken/originalUser,
                                          startImpersonation/exitImpersonation
frontend/src/components/v2/ImpersonationBanner.tsx  # CREATE
frontend/src/components/v2/AppShellV2.tsx           # MODIFY — render the banner
frontend/src/app/app/admin/orgs/[id]/page.tsx        # MODIFY — wire the "Login as" button
                                                        (this file is created by the
                                                        admin-dashboard-v2 plan; Task 6
                                                        below fills in the comment
                                                        placeholder that plan left)
```

---

### Task 1: Backend — session schema gains `impersonated_by`

**Files:**
- Modify: `backend/app/core/sessions.py`
- Modify: `backend/app/core/dependencies.py`

**Interfaces:**
- Produces: `SessionManager.create_session(..., impersonated_by: dict | None = None)`; every validated session dict now has an `impersonated_by` key (`None` for a normal login); `request.state.session` — the full session dict, set by `get_current_user` on every successful auth, consumed by Task 3 (no-nesting check) and Task 3's middleware.

- [ ] **Step 1: `create_session` gains the parameter**

In `backend/app/core/sessions.py`, change the signature and the `session_data` dict it builds:

```python
    async def create_session(
        self,
        user_id: str,
        username: str,
        role: str,
        org_id: str | None,
        ip: str,
        user_agent: str,
        impersonated_by: dict | None = None,
    ) -> str:
        """
        Create a new session. Returns an encrypted opaque token.
        """
        redis_client = await get_redis()
        session_id = generate_session_id()
        fingerprint = compute_device_fingerprint(ip, user_agent)
        now = time.time()

        session_data = {
            "user_id": user_id,
            "username": username,
            "role": role,
            "org_id": org_id or "",
            "fingerprint": fingerprint,
            "created_at": now,
            "last_active": now,
            "ip": ip,
            "impersonated_by": impersonated_by,
        }
```
(Only the signature line and the `session_data` dict change — everything else in the method, and every other method in this class, stays exactly as-is. Every existing caller of `create_session` — the normal login path in `auth.py` — doesn't pass this new parameter, so it defaults to `None`, meaning zero behavior change for normal logins.)

- [ ] **Step 2: `get_current_user` attaches the session to `request.state`**

In `backend/app/core/dependencies.py`, find this line inside `get_current_user` (confirmed real, current code):
```python
    session = await session_manager.validate_session(token, ip, user_agent)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
```
Add one line immediately after the `if not session` check:
```python
    session = await session_manager.validate_session(token, ip, user_agent)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
    request.state.session = session
```
(Confirmed no existing code anywhere uses `request.state.session` for anything else — grepped for `request.state.` across the whole backend; the only other uses are `request.state.internal_principal` and `request.state.request_id`, no collision.)

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/backend && uv run python3 -c "from app.main import app"
```
Expected: imports cleanly.

- [ ] **Step 4: Manual verification**

Log in normally (existing flow, unchanged) and confirm the app still works exactly as before — this step only adds a field, it must not change any existing behavior. If you can inspect Redis directly, confirm a freshly-created session's stored JSON now includes `"impersonated_by": null`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/sessions.py backend/app/core/dependencies.py
git commit -m "backend: sessions carry an impersonated_by marker, attached to request.state"
```

---

### Task 2: Backend — `audit_log` table + service

**Files:**
- Create: `backend/app/models/audit_log.py`
- Create: `backend/alembic/versions/<generated>.py` (filename generated by Alembic, see Step 2)
- Create: `backend/app/services/audit_log_service.py`

**Interfaces:**
- Produces: `AuditLog` model; `audit_log_service.record(db, actor_user_id, actor_username, method, path, status_code, target_user_id=None, target_org_id=None) -> None` (calls `db.add(...)` + `db.flush()` — does NOT commit, matching this codebase's existing `soft_delete_service` convention where the caller's `Depends(get_db)` commits at request end; the one caller that has no such surrounding dependency, Task 3's middleware, must commit explicitly itself).

- [ ] **Step 1: The model**

```python
# backend/app/models/audit_log.py
import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    """Append-only record of admin/impersonation actions.

    TimestampMixin's `updated_at` is unused here (this table is never
    updated after insert) but every other model in this codebase shares
    the same mixin, so this stays consistent rather than hand-rolling a
    one-off append-only variant for a single table.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    actor_username: Mapped[str] = mapped_column(Text, nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
```

- [ ] **Step 2: Generate the migration**

Do NOT hand-write a revision ID — generate it the same way every other migration in this repo was created, so it gets a real, correctly-chained revision hash:

```bash
cd /Users/vaibhaw/Developer/vision/backend
uv run alembic revision -m "audit_log"
```
This creates a new file in `alembic/versions/` with `down_revision` auto-set to the current head (`c2e8a4b1d7f3` at the time this plan was written — confirmed by walking the full revision chain; if a later task in another plan has since added a newer migration, Alembic will correctly pick up whatever the actual current head is instead). Open the generated file and fill in `upgrade()`/`downgrade()`:

```python
def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_username", sa.Text(), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_target_org_id", "audit_log", ["target_org_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_target_org_id", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_user_id", table_name="audit_log")
    op.drop_table("audit_log")
```
Add `from sqlalchemy.dialects import postgresql` to the generated file's imports if Alembic's template didn't already include it (check the generated file — this codebase's other migrations that use UUID columns, e.g. `c2e8a4b1d7f3_agent_device_token_id.py`, already follow this exact import pattern).

- [ ] **Step 3: The service**

```python
# backend/app/services/audit_log_service.py
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditLogService:
    async def record(
        self,
        db: AsyncSession,
        actor_user_id: uuid.UUID,
        actor_username: str,
        method: str,
        path: str,
        status_code: int,
        target_user_id: uuid.UUID | None = None,
        target_org_id: uuid.UUID | None = None,
    ) -> None:
        db.add(
            AuditLog(
                actor_user_id=actor_user_id,
                actor_username=actor_username,
                target_user_id=target_user_id,
                target_org_id=target_org_id,
                method=method,
                path=path,
                status_code=status_code,
            )
        )
        await db.flush()


audit_log_service = AuditLogService()
```

- [ ] **Step 4: Run the migration**

```bash
cd /Users/vaibhaw/Developer/vision/backend && uv run alembic upgrade head
```
Expected: applies cleanly, no errors. (Requires a real `DATABASE_URL` in the environment — if this environment can't reach the real DB, verify the migration file's syntax carefully by reading it instead, and note in your report that the actual `alembic upgrade head` run needs to happen before Task 3 is usable in a live environment.)

- [ ] **Step 5: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/backend && uv run python3 -c "from app.main import app; from app.models.audit_log import AuditLog; from app.services.audit_log_service import audit_log_service"
```
Expected: imports cleanly.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/audit_log.py backend/alembic/versions/ backend/app/services/audit_log_service.py
git commit -m "backend: add audit_log table and recording service"
```

---

### Task 3: Backend — impersonate route + audit middleware

**Files:**
- Modify: `backend/app/api/admin.py`
- Modify: `backend/app/core/middleware.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `session_manager.create_session(..., impersonated_by=...)` (Task 1), `request.state.session` (Task 1), `audit_log_service.record(...)` (Task 2).
- Produces: `POST /api/admin/users/{user_id}/impersonate` → `TokenResponse` (`{token, user}`, same shape as a normal login response).

- [ ] **Step 1: Add imports to `admin.py`**

`admin.py` already imports `Request` indirectly via FastAPI's route signatures elsewhere in this codebase — confirm and add if missing:
```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request
```
Add `TokenResponse` to the existing schema import line:
```python
from app.schemas.auth import ChangePasswordRequest, TokenResponse, UpdateUserRequest, UserResponse
```
Add the session manager and audit service imports:
```python
from app.core.sessions import session_manager
from app.services.audit_log_service import audit_log_service
```
(`session_manager` may already be imported in `admin.py` for the existing force-logout/sessions routes — check before adding a duplicate import line.)

- [ ] **Step 2: The route**

```python
@router.post("/users/{user_id}/impersonate", response_model=TokenResponse)
async def impersonate_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mint a real session for the target user, tagged with who's impersonating.
    No nested impersonation, no impersonating a super_admin or a user in a
    soft-deleted org."""
    _require_super_admin(user)

    if request.state.session.get("impersonated_by"):
        raise HTTPException(status_code=400, detail="Exit your current impersonation session before starting another.")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target or target.deleted_at is not None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role == "super_admin":
        raise HTTPException(status_code=403, detail="Cannot impersonate a super admin")
    if target.org_id:
        org_result = await db.execute(select(Organization).where(Organization.id == target.org_id))
        org = org_result.scalar_one_or_none()
        if org and org.deleted_at is not None:
            raise HTTPException(status_code=400, detail="Cannot impersonate a user in a deleted org")

    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    token = await session_manager.create_session(
        str(target.id),
        target.username,
        target.role,
        str(target.org_id) if target.org_id else None,
        ip,
        ua,
        impersonated_by={"user_id": str(user.id), "username": user.username},
    )

    await audit_log_service.record(
        db,
        actor_user_id=user.id,
        actor_username=user.username,
        method="IMPERSONATE",
        path=f"/api/admin/users/{user_id}/impersonate",
        status_code=200,
        target_user_id=target.id,
        target_org_id=target.org_id,
    )

    return TokenResponse(token=token, user=UserResponse.model_validate(target))
```
(`request.state.session` is guaranteed present here — it's set unconditionally by `get_current_user`, which this route requires via `Depends(get_current_user)`, per Task 1.)

- [ ] **Step 3: Verify backend imports**

```bash
cd /Users/vaibhaw/Developer/vision/backend && uv run python3 -c "from app.main import app"
```
Expected: imports cleanly.

- [ ] **Step 4: The audit middleware**

Add to `backend/app/core/middleware.py`, alongside the existing `RequestIDMiddleware`/`TimingMiddleware`:

```python
from app.core.database import async_session_factory
from app.services.audit_log_service import audit_log_service


class ImpersonationAuditMiddleware(BaseHTTPMiddleware):
    """Logs every mutating request made during an impersonated session.

    Reads request.state.session (set by get_current_user, per Task 1) AFTER
    call_next() returns — at that point every route dependency, including
    auth, has already run. Requests that never reach an authenticated route
    (public endpoints, failed auth) simply have no request.state.session,
    handled via getattr's default.
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return response

        session = getattr(request.state, "session", None)
        impersonated_by = session.get("impersonated_by") if session else None
        if not impersonated_by:
            return response

        async with async_session_factory() as db:
            await audit_log_service.record(
                db,
                actor_user_id=uuid.UUID(impersonated_by["user_id"]),
                actor_username=impersonated_by["username"],
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                target_user_id=uuid.UUID(session["user_id"]),
                target_org_id=uuid.UUID(session["org_id"]) if session.get("org_id") else None,
            )
            await db.commit()

        return response
```
Add `import uuid` at the top of `middleware.py` if not already present.

**Why an explicit `db.commit()` here and not elsewhere:** every route-level call to `audit_log_service.record(...)` (Task 3's route above) relies on `Depends(get_db)`'s own commit-at-request-end behavior (confirmed: `get_db` commits on success). This middleware opens its own session directly via `async_session_factory()` — there's no surrounding `get_db` dependency to commit for it, so it must commit itself. This is a deliberate choice to `await` the write inline (guaranteeing the audit row is durably written before the response is returned to the client) rather than firing it as an unawaited background task — for a security audit trail, a guaranteed write is worth more than shaving a few milliseconds of response latency.

- [ ] **Step 5: Register the middleware**

In `backend/app/main.py`, find the existing middleware registration block:
```python
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(RateLimitMiddleware)
```
Add the import and one more line (position among these three doesn't matter functionally — this middleware only reads `request.state.session` after `call_next()` returns, by which point routing/auth has already happened regardless of middleware ordering):
```python
from app.core.middleware import RequestIDMiddleware, TimingMiddleware, ImpersonationAuditMiddleware
...
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(ImpersonationAuditMiddleware)
app.add_middleware(RateLimitMiddleware)
```

- [ ] **Step 6: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/backend && uv run python3 -c "from app.main import app"
```
Expected: imports cleanly.

- [ ] **Step 7: Manual verification**

If you can reach a running backend + real DB + Redis: log in as a super admin, call the impersonate endpoint for a real test user, confirm the response is a valid `{token, user}` pair, confirm a row was written to `audit_log` with `method="IMPERSONATE"`. Then make a mutating request (e.g. a `PATCH`) using the impersonated token, confirm a second `audit_log` row appears with the real HTTP method/path and the target's `org_id`. Confirm calling impersonate a second time with the impersonated token (attempting to nest) returns 400. If you cannot reach a live environment, trace through the code paths by hand instead and say so explicitly in your report — this is exactly the kind of logic where "looks right" isn't sufficient confidence for a security feature, so be honest about what you could and couldn't actually exercise.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/admin.py backend/app/core/middleware.py backend/app/main.py
git commit -m "backend: add impersonate endpoint and per-action audit logging middleware"
```

---

### Task 4: Frontend — store + API method

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/store.ts`

**Interfaces:**
- Produces: `api.adminImpersonateUser(userId: string): Promise<{token: string; user: User}>`; `useAuthStore`'s `originalToken`, `originalUser`, `startImpersonation(token, user)`, `exitImpersonation()` — consumed by Task 5 (banner) and Task 6 ("Login as" button).

- [ ] **Step 1: API method**

Add to `frontend/src/lib/api.ts`, near the other `admin*` methods:

```ts
async adminImpersonateUser(userId: string) {
  return this.request<{ token: string; user: User }>(`/api/admin/users/${userId}/impersonate`, {
    method: "POST",
  });
}
```
(`User` type is already imported in this file — confirm before adding a duplicate import.)

- [ ] **Step 2: Store changes**

Replace the current `frontend/src/lib/store.ts` content:
```ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { User } from "@/types";

interface AuthState {
  token: string | null;
  user: User | null;
  originalToken: string | null;
  originalUser: User | null;
  setAuth: (token: string, user: User) => void;
  logout: () => void;
  startImpersonation: (token: string, user: User) => void;
  exitImpersonation: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      originalToken: null,
      originalUser: null,
      setAuth: (token, user) => set({ token, user }),
      logout: () => set({ token: null, user: null, originalToken: null, originalUser: null }),
      startImpersonation: (token, user) => {
        const { token: currentToken, user: currentUser } = get();
        set({ originalToken: currentToken, originalUser: currentUser, token, user });
      },
      exitImpersonation: () => {
        const { originalToken, originalUser } = get();
        set({ token: originalToken, user: originalUser, originalToken: null, originalUser: null });
      },
    }),
    { name: "nightwatch-auth" }
  )
);
```
Note: `logout()` now also clears `originalToken`/`originalUser` — if a super admin is impersonating and hits the normal logout path (not the impersonation-exit path) for any reason, this prevents a stale stashed token from lingering in persisted storage.

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/frontend && npx tsc --noEmit
```
Expected: no new type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/store.ts
git commit -m "frontend: add impersonation state (originalToken/originalUser) to auth store"
```

---

### Task 5: Frontend — persistent banner

**Files:**
- Create: `frontend/src/components/v2/ImpersonationBanner.tsx`
- Modify: `frontend/src/components/v2/AppShellV2.tsx`

**Interfaces:**
- Consumes: `useAuthStore`'s `originalToken`, `user`, `exitImpersonation` (Task 4).

- [ ] **Step 1: The banner**

```tsx
// frontend/src/components/v2/ImpersonationBanner.tsx
"use client";

import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";

export function ImpersonationBanner() {
  const router = useRouter();
  const { user, originalToken, exitImpersonation } = useAuthStore();

  if (!originalToken) return null;

  const handleExit = () => {
    api.logout().catch(() => {});
    exitImpersonation();
    router.push("/app/admin");
  };

  return (
    <div className="w-full flex-shrink-0 bg-[oklch(70.4%_0.191_22.216)] text-[oklch(9%_0.015_265)] text-sm font-semibold px-4 py-2 flex items-center justify-center gap-3">
      <span>Viewing as {user?.username}</span>
      <button onClick={handleExit} className="underline">Exit</button>
    </div>
  );
}
```
`api.logout()` revokes whatever token is currently set on the `ApiClient` singleton — at the moment this fires, that's still the impersonated token (the store hasn't been restored yet), so this correctly revokes the impersonated session, not the super admin's own. Restoring the original token/user happens synchronously right after via `exitImpersonation()`.

- [ ] **Step 2: Wire it into `AppShellV2`**

Current `frontend/src/components/v2/AppShellV2.tsx`'s render (confirmed real, current):
```tsx
  return (
    <div className="flex min-h-screen bg-[oklch(9%_0.015_265)] text-[oklch(97%_0.005_265)]">
      <SidebarV2 />
      <main className="flex-1 overflow-y-auto min-w-0">{children}</main>
    </div>
  );
```
Change to a column layout with the banner on top, sidebar+main in a row below:
```tsx
  return (
    <div className="flex flex-col min-h-screen bg-[oklch(9%_0.015_265)] text-[oklch(97%_0.005_265)]">
      <ImpersonationBanner />
      <div className="flex flex-1 min-h-0">
        <SidebarV2 />
        <main className="flex-1 overflow-y-auto min-w-0">{children}</main>
      </div>
    </div>
  );
```
Add the import:
```tsx
import { ImpersonationBanner } from "@/components/v2/ImpersonationBanner";
```

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/frontend && npm run build
```
Expected: zero type errors.

- [ ] **Step 4: Manual verification**

Confirm (by reasoning through the code, or live if Task 6 has landed and you can trigger real impersonation) that the banner is invisible when `originalToken` is null (the normal case for every existing user of this app), and would render correctly once it's non-null.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/v2/ImpersonationBanner.tsx frontend/src/components/v2/AppShellV2.tsx
git commit -m "frontend: add persistent impersonation banner with exit"
```

---

### Task 6: Frontend — wire the "Login as" button

**Files:**
- Modify: `frontend/src/app/app/admin/orgs/[id]/page.tsx` (created by the admin-dashboard-v2 plan's Task 4 — this task must run after that one)

**Interfaces:**
- Consumes: `api.adminImpersonateUser(userId)` (Task 4), `useAuthStore().startImpersonation` (Task 4).

- [ ] **Step 1: Confirm the target file exists**

```bash
test -f /Users/vaibhaw/Developer/vision/frontend/src/app/app/admin/orgs/\[id\]/page.tsx && echo "exists"
```
If this doesn't print `exists`, STOP — the admin-dashboard-v2 plan's Task 4 must be completed first; do not recreate this file from scratch here.

- [ ] **Step 2: Add the mutation and button**

The admin-dashboard-v2 plan left this exact comment in the per-user row's button group: `{/* Project F (separate plan) adds a "Login as" button here */}`. Find it and replace it.

Add imports (if not already present in the file):
```tsx
import { useRouter } from "next/navigation";
```
Add `useAuthStore` import and destructure `startImpersonation`:
```tsx
import { useAuthStore } from "@/lib/store";
// ...
const { user, startImpersonation } = useAuthStore();
```
(The file already destructures `user` from `useAuthStore()` per the admin-dashboard-v2 plan — add `startImpersonation` to that same destructure, don't create a second `useAuthStore()` call.)

Add the router and mutation, alongside the file's existing mutations (`forceLogout`, `deleteOrg`, `restoreOrg`):
```tsx
const router = useRouter();

const impersonate = useMutation({
  mutationFn: (userId: string) => api.adminImpersonateUser(userId),
  onSuccess: (data) => {
    startImpersonation(data.token, data.user);
    router.push("/app");
  },
});
```

Replace the placeholder comment with the actual button:
```tsx
{/* Project F (separate plan) adds a "Login as" button here */}
```
→
```tsx
<button
  onClick={() => impersonate.mutate(u.id)}
  disabled={impersonate.isPending}
  className="text-[12px] text-[oklch(85%_0.16_84)] disabled:opacity-50"
>
  Login as
</button>
```

Add error surfacing near the existing `deleteOrg.isError || restoreOrg.isError` block (or as its own line right after the user row it applies to — implementation-level choice, keep it visible near the action):
```tsx
{impersonate.isError && (
  <div className="mt-2 text-[12px] text-[oklch(70.4%_0.191_22.216)]">
    {impersonate.error instanceof Error ? impersonate.error.message : "Couldn't start impersonation."}
  </div>
)}
```

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/frontend && npm run build
```
Expected: zero type errors.

- [ ] **Step 4: Manual verification**

If you can reach a running full stack (frontend + backend + DB + Redis): as a super admin, visit an org's detail page, click "Login as" for a real test user, confirm you land on `/app` seeing that user's real Home page (their real cameras/events, not the super admin's), confirm the banner shows their username, click "Exit," confirm you're back as the super admin on `/app/admin`. If you can't reach a live stack, trace the full flow by hand (button → mutation → `startImpersonation` → `router.push` → `AppShellV2`'s guard re-running with the new token → banner rendering) and report exactly what you verified vs. what you reasoned through.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/app/admin/orgs/\[id\]/page.tsx
git commit -m "frontend: wire Login as button into org detail page"
```

---

## Self-Review

**Spec coverage:** every requirement from the impersonation design spec is covered — full read+write via real session minting (Task 1, 3), specific-user targeting (Task 6's per-user button), every-action audit logging (Task 2, 3's middleware), no nested impersonation (Task 3's server-side check), persistent banner + exit (Task 5), normal (not shortened) session TTLs (Task 1 — `create_session`'s existing `SESSION_MAX_TTL`/idle logic is untouched).

**Placeholder scan:** no TBD/TODO. The one deliberate placeholder-turned-real-code is Task 6 replacing the admin-dashboard-v2 plan's explicit handoff comment — that's the intended cross-plan dependency working as designed, not a shirked requirement.

**Type consistency:** `api.adminImpersonateUser`'s return shape (`{token: string; user: User}`, Task 4) is consumed identically by `startImpersonation(token: string, user: User)` (Task 4's own store signature) at its Task 6 call site — no mismatch. `request.state.session`'s shape (a plain `dict` with `user_id`/`org_id`/`impersonated_by` keys, Task 1) is read identically by Task 3's route and Task 3's middleware — same key names, same optionality (`impersonated_by` is `None`/absent-checked via `.get()` in both places).
