# Test AI in V2 — Design (Project D of 3)

*Date: 2026-08-14*

## Context

This is Project D of a three-project super-admin decomposition (see [Project E](2026-08-14-admin-dashboard-v2-design.md), [Project F](2026-08-14-impersonation-design.md)). The old (non-V2) app has a `/test-camera` page — a live-camera-frame AI analysis playground hitting `/api/test-camera/{analyze, analyze-local, analyze-combined, chat, local-detection-status, usage}`. It is not role-gated today: any authenticated user, of any role, can use it (`frontend/src/app/test-camera/layout.tsx` wraps it in `<AppShell>` without the `requireRole="super_admin"` prop that other admin-only pages use).

## Goal

Port this page into the V2 shell at `/app/test-camera`, preserving its current availability (any authenticated user, not super-admin-only) and restyled with V2's oklch visual language, consistent with every other Task 1-12 V2 view.

## Architecture

Pure frontend port, one file: `frontend/src/app/app/test-camera/page.tsx`, copying the existing page's logic and API calls verbatim, restyling markup only. No backend changes — the `/api/test-camera/*` routes are already open to any authenticated user and stay that way.

Add a `Test AI` entry to `SidebarV2`'s nav list (`frontend/src/components/v2/SidebarV2.tsx`), matching the old sidebar's unconditional (non-role-gated) placement.

## Data flow

Identical to the existing page — no new endpoints, no new request/response shapes. Whatever loading/error/empty-state handling the existing page has should be preserved; if it's missing any (per the established V2 pattern from the frontend-v2-shell project), add it during the port, matching the convention used by every other V2 view (oklch error color `oklch(70.4% 0.191 22.216)`, distinct loading/empty/error branches).

## Non-goals

- No change to `/api/test-camera/*` route authorization.
- No change to the old (non-V2) `/test-camera` page.
- Not part of the impersonation flow (Project F) — this page works identically whether the current session is a super admin's own session or an impersonated client session, since it was never org-scoped to begin with.

## Open questions

None — this is a straightforward, low-risk port.
