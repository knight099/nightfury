# Impersonation ("Login as Client") — Design (Project F of 3)

*Date: 2026-08-14*

## Context

This is Project F of a three-project super-admin decomposition (see [Project D](2026-08-14-test-ai-v2-design.md), [Project E](2026-08-14-admin-dashboard-v2-design.md)). No impersonation, "acting as," or session-stacking capability exists anywhere in this codebase today — confirmed by exhaustive grep across backend and frontend. This is new capability, and it is the highest-risk piece of this whole decomposition: it grants a super admin the ability to read and write a client's private data as that client.

**Decisions already made and approved, binding on this design:**
- Full read+write while impersonating, matching the target user's own role exactly — not a restricted/read-only mode.
- The super admin picks a *specific user* at the target org (not always "the owner") — useful for reproducing a lower-privileged user's exact view.
- Every action taken while impersonating is audit-logged, not just session start/end.
- No nested impersonation — must exit before impersonating someone else.
- A persistent, unmissable visual banner while impersonating, with one-click exit.
- Explicitly **not** wanted: shortened session expiry — impersonation sessions run the normal session length, not a special shorter timeout.

## Goal

A super admin, from Project E's org detail page, clicks "Login as {user}" and is transparently switched into that user's exact session — every existing view, route, and permission check in the app just works, because the impersonated session **is** a normal session for that user (same role, same org_id), with one extra marker that makes it distinguishable for audit and guardrail purposes. Exiting cleanly restores the super admin's own session.

## Architecture

### Approach: mint a real session, not a synthetic view mode

The alternative (a client-side "pretend to be this org" flag that reinterprets the current super-admin session) was rejected: it would require threading an override through every existing org-scoped route and query, duplicating and drifting from the real authorization logic. Minting an actual session for the target user means **zero changes to any of the ~10 existing route files** that already do `if user.role == "super_admin"` branching — the impersonated request simply isn't a super-admin request at all from those routes' point of view. This is also why the "matching the client's own role" decision (already approved) is the natural fit, not an added complexity: it's what a real session for that user already looks like.

```
backend/app/core/sessions.py         # MODIFY: create_session gains optional
                                        impersonated_by param, stored in session_data
backend/app/models/audit_log.py      # NEW: audit_log table
backend/app/services/audit_log_service.py  # NEW: record(...) — one insert,
                                              matches this codebase's existing
                                              services-layer convention (routes
                                              stay thin, call into services/)
backend/app/api/admin.py             # MODIFY: add POST .../impersonate route
backend/app/core/impersonation_audit.py  # NEW: ASGI middleware, calls
                                            audit_log_service.record(...) too
backend/app/main.py                  # MODIFY: register the middleware

frontend/src/lib/store.ts            # MODIFY: add originalToken/originalUser +
                                        startImpersonation/exitImpersonation actions
frontend/src/components/v2/ImpersonationBanner.tsx  # NEW
frontend/src/components/v2/AppShellV2.tsx           # MODIFY: render the banner
frontend/src/app/app/admin/orgs/[id]/page.tsx        # MODIFY (Project E's file):
                                                         "Login as" button per user
```

### Backend: session schema + impersonate endpoint

`sessions.py`'s `create_session` signature grows one optional parameter:
```python
async def create_session(
    self, user_id: str, username: str, role: str, org_id: str | None,
    ip: str, user_agent: str,
    impersonated_by: dict | None = None,   # {"user_id": str, "username": str}
) -> str:
    ...
    session_data = {
        "user_id": user_id, "username": username, "role": role,
        "org_id": org_id or "", "fingerprint": fingerprint,
        "created_at": now, "last_active": now, "ip": ip,
        "impersonated_by": impersonated_by,   # None for a normal login
    }
```
This field round-trips through Redis exactly like every other session field already does — no change to `validate_session`'s fingerprint/idle/absolute-expiry logic, which stays exactly as strict for impersonated sessions as for real ones (confirmed: the fingerprint binds to whoever is currently holding the browser, which is correctly the super admin's own browser during impersonation — no special-casing needed there).

New route in `admin.py`, following the file's existing `_require_super_admin` pattern:
```python
@router.post("/users/{user_id}/impersonate", response_model=TokenResponse)
async def impersonate_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_super_admin(user)

    # No nested impersonation — check the CALLER's own current session
    authorization = request.headers.get("authorization", "")
    caller_token = authorization.removeprefix("Bearer ")
    caller_session = await session_manager.get_session_dict(caller_token)  # new small helper, or inline the existing decrypt+redis-get logic already in validate_session
    if caller_session and caller_session.get("impersonated_by"):
        raise HTTPException(400, "Exit your current impersonation session before starting another.")

    target = await db.get(User, user_id)
    if not target or target.deleted_at is not None:
        raise HTTPException(404, "User not found")
    if target.role == "super_admin":
        raise HTTPException(403, "Cannot impersonate a super admin")
    if target.org_id:
        org = await db.get(Organization, target.org_id)
        if org and org.deleted_at is not None:
            raise HTTPException(400, "Cannot impersonate a user in a deleted org")

    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "unknown")
    token = await session_manager.create_session(
        str(target.id), target.username, target.role,
        str(target.org_id) if target.org_id else None,
        ip, ua,
        impersonated_by={"user_id": str(user.id), "username": user.username},
    )

    await audit_log_service.record(
        actor_user_id=user.id, actor_username=user.username,
        target_user_id=target.id, target_org_id=target.org_id,
        method="IMPERSONATE", path=f"/api/admin/users/{user_id}/impersonate",
        status_code=200,
    )

    return TokenResponse(token=token, user=UserResponse.model_validate(target))
```
Response shape deliberately matches the existing `TokenResponse` (`{token, user}`) used by the real login route — the frontend treats it almost identically, just routed through a different store action (below) instead of the normal `setAuth`.

Exiting impersonation reuses the **existing, unmodified** `POST /api/auth/logout` route — it already revokes whatever token is in the `Authorization` header, so calling it while holding the impersonated token correctly and immediately revokes just that session. No new backend route needed for exit.

### Backend: audit logging — new table + generic middleware

```python
# backend/app/models/audit_log.py
class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    actor_username: Mapped[str] = mapped_column(Text, nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    target_org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```
Requires an Alembic migration (this codebase already uses Alembic for schema changes, per `backend/CLAUDE.md`).

A new ASGI middleware, not a per-route dependency — this is what achieves "every action," including future routes, with zero changes to existing route files:
```python
# backend/app/core/impersonation_audit.py
class ImpersonationAuditMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH", "DELETE"):
            return await self.app(scope, receive, send)
        # extract Bearer token from headers, decrypt, look up session in Redis
        # (read-only lookup — reuses session_manager's existing decrypt/redis-get,
        # does NOT re-validate fingerprint/idle here, that's get_current_user's job
        # and already ran or will run inside the route)
        # if session.get("impersonated_by") is set: wrap send() to capture the
        # final status_code, then after the response completes, write one
        # audit_log row via a background task (don't block the response on a DB write)
```
Registered in `main.py` alongside the app's existing middleware stack. The `impersonate` route's own audit row (start event) is written directly in the route, not via this middleware, since that request's session doesn't have `impersonated_by` set yet at request time (it's being created *by* that request).

### Frontend: store + banner + exit

```ts
// frontend/src/lib/store.ts — AuthState grows:
interface AuthState {
  token: string | null;
  user: User | null;
  originalToken: string | null;   // set only while impersonating
  originalUser: User | null;
  setAuth: (token: string, user: User) => void;
  logout: () => void;
  startImpersonation: (token: string, user: User) => void;
  exitImpersonation: () => void;
}
```
`startImpersonation` stashes the CURRENT `token`/`user` into `originalToken`/`originalUser`, then sets `token`/`user` to the impersonated pair — `originalToken` being non-null is exactly the "am I currently impersonating" signal the banner and the "Login as" button's own visibility both key off (hiding the "Login as" button while already impersonating is the UI-level half of the no-nested-impersonation guarantee; the backend check is the enforced half).

`exitImpersonation` calls `api.logout()` (revokes the impersonated Redis session — fire-and-forget is acceptable here, don't block the UI on it) then restores `token`/`user` from `originalToken`/`originalUser` and clears both stash fields.

```tsx
// frontend/src/components/v2/ImpersonationBanner.tsx
export function ImpersonationBanner() {
  const { user, originalToken, exitImpersonation } = useAuthStore();
  if (!originalToken) return null;
  return (
    <div className="fixed top-0 inset-x-0 z-50 bg-[oklch(70.4%_0.191_22.216)] text-[oklch(9%_0.015_265)] text-sm font-semibold px-4 py-2 flex items-center justify-center gap-3">
      Viewing as {user?.username} — 
      <button onClick={exitImpersonation} className="underline">Exit</button>
    </div>
  );
}
```
Rendered unconditionally inside `AppShellV2` (visible on every V2 page while impersonating, including Test AI and every client-facing view — satisfying "what all users have" from the original request, since the super admin is now genuinely logged in as that user for as long as the banner is up).

## Data flow

```
/app/admin/orgs/{id} → click "Login as {user}" → POST /api/admin/users/{id}/impersonate
  → {token, user} → store.startImpersonation(token, user)
  → redirect to /app (now rendering as the client's real Home page)
  → banner visible on every subsequent V2 page
  → every write the super admin makes is a normal authenticated request as that
    user, additionally captured by the audit middleware
  → click "Exit" → api.logout() + store.exitImpersonation()
  → redirect to /app/admin/orgs/{id} (back where impersonation started)
```

## Error handling

- `impersonate` endpoint's failure cases (target not found, target is super_admin, target's org deleted, caller already impersonating) all return clear 4xx errors — surfaced inline on the "Login as" button's click handler (a toast or inline message, matching the established V2 mutation-error pattern), not a silent failure.
- If `exitImpersonation`'s `api.logout()` call fails (network error), the frontend still restores the original token/user locally — the stale impersonated Redis session will simply idle-expire on its own normal TTL. Don't block the user's ability to exit on that network call succeeding.

## Testing

No automated tests (standing project preference) — manual verification: impersonate a real test user, confirm every view (Home, Cameras, Activity, Settings, Test AI) shows that user's real data, confirm a write action (e.g. toggling a digest preference) actually persists under that user's account, confirm the audit_log table gets a row for it, confirm exit restores the super admin's own session and the impersonated Redis session no longer validates, confirm attempting to impersonate a second user while already impersonating is rejected both in the UI (button hidden) and if called directly against the API (400).

## Non-goals

- No UI to browse the full audit log in this project — rows are written and queryable directly against the DB; a dedicated log-viewer page is a natural, separate follow-up if it turns out to be needed, not built here (keeps this project's scope to the mechanism itself).
- No shortened session timeout for impersonated sessions — explicitly declined; they use the same TTLs as any other session.
- No impersonating another super_admin, and no nested impersonation — both explicitly blocked, not configurable.
- Not modifying any of the existing ~10 route files' authorization logic — the entire design depends on impersonated sessions being indistinguishable from real ones to everything except the audit middleware and the no-nesting check.

## Open questions

- Whether `get_session_dict`-style read-only session lookup should be a small new shared helper on `SessionManager` (reused by both the middleware and the no-nesting check) or whether each inlines its own decrypt+redis-get — implementation-plan-level, but a shared helper avoids duplicating the exact same three lines twice; recommend factoring it out.
- Whether the audit middleware's DB write should be a true FastAPI `BackgroundTask` or a fire-and-forget `asyncio.create_task` — implementation-plan-level choice, either avoids blocking the response.
