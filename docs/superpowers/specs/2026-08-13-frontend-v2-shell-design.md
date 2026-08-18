# Frontend V2 Shell — Design (Project A of 3)

*Date: 2026-08-13*

## Context

`newdesign/Nightwatch.dc.html` is a Figma-generated design mockup (static HTML with `{{ }}` template bindings and a `data-dc-script` mock-state controller) covering a full redesign of the Nightwatch dashboard: new navigation (Home, Cameras, Map, Agents, Activity, Digests, Settings), new visual language (oklch color tokens vs. the current app's hex tokens), and 18 distinct views including a separate Admin mode.

This is Project A of a three-project decomposition:
- **Project A (this doc):** the frontend shell, navigation, and every view backed by data that already exists in the backend today. Ships behind a flag, becomes the eventual full replacement for the current dashboard.
- **Project B (separate spec, later):** the Map view — cross-camera "journeys," person tracking across cameras. Requires new cross-camera re-identification backend work; a genuinely hard, previously-flagged problem.
- **Project C (separate spec, later):** the "Agents" view's per-camera natural-language "jobs" list (single-camera only — the multi-camera variant depends on Project B). Smaller than Project B: largely assembly over the already-existing `compileSequence` AI wizard and `AlertRule` model, not a new AI capability.

## Goal

Port the mockup's shell, navigation, and every view with real backend support into the existing Next.js app, gated behind a build-time flag (`NEXT_PUBLIC_NEW_UI`), reusing all existing data-fetching (`api.ts`, TanStack Query, Zustand auth) — only the visual/navigation layer is new. The current dashboard keeps working unchanged when the flag is off, and is the intended target for full replacement once V2 is dogfooded.

## Scope

**In scope — ported with real data:**
- Home (camera summary tiles, recent activity feed, "all quiet" status)
- Cameras (grid) + Camera Detail (live view, event feed for that camera)
- Chat ("Ask Nightwatch" — already fully wired to `/api/chat`)
- Playback (step through a camera's recent events' snapshots/clips)
- Activity (full event feed with filters)
- Digests (list + preferences)
- Settings — **trimmed**: team management, WhatsApp alert contacts, digest preferences only. Quiet hours, generic call/text contacts, and the Slack/integrations list are **omitted** — none of that exists in the backend today, and this project ships only what's real, not fabricated UI.
- Admin Overview + Admin Accounts (orgs/users CRUD, already real)
- Admin AI (usage/cost) — **requires one small new backend route**: a super-admin-scoped variant of the existing `/api/settings/ai-usage` (currently org-owner-scoped only). This is the only backend work in Project A; everything else is a pure frontend port over already-existing endpoints.

**Explicitly out of scope for Project A:**
- Map view — Project B.
- Agents view (both single- and multi-camera "jobs") — Project C, once it exists. Project A's nav includes an "Agents" link that shows a "coming soon" placeholder, not a 404 or fabricated data.
- Admin System (service uptime %) — no backend data source exists anywhere in this codebase (only a trivial `/health` liveness check, no per-service uptime tracking). Dropped from this port entirely rather than fabricated. Revisit if/when real observability/uptime tracking gets built as its own project.
- Any change to the current (non-flagged) dashboard's behavior.

## Architecture

```
frontend/
├── src/app/                    # existing routes, UNCHANGED, served when flag is off
├── src/app-v2/  (or a route-group, TBD at plan time)
│   ├── layout.tsx              # AppShellV2 — new sidebar/nav (Home/Cameras/Map/Agents/
│   │                              Activity/Digests/Settings), reuses auth guard pattern
│   │                              from existing AppShell
│   ├── page.tsx                # Home
│   ├── cameras/page.tsx        # Cameras grid
│   ├── cameras/[id]/page.tsx   # Camera Detail
│   ├── activity/page.tsx       # Activity feed
│   ├── digests/page.tsx        # Digests list + preferences
│   ├── settings/page.tsx       # Settings (trimmed)
│   ├── admin/page.tsx          # Admin Overview + Accounts tabs
│   └── admin/ai/page.tsx       # Admin AI usage
├── src/components/v2/          # new view components, one per mockup section,
│                                  ported 1:1 from newdesign/Nightwatch.dc.html's
│                                  markup/interaction structure, restyled with the
│                                  mockup's oklch tokens as a new theme layer
│                                  (does not touch the existing hex-token theme)
└── src/lib/flags.ts            # isNewUiEnabled() reading NEXT_PUBLIC_NEW_UI
```

**Flag mechanism:** `NEXT_PUBLIC_NEW_UI=true` in `.env` (build-time, per the project's existing "everything configurable via env" convention — matches `NEXT_PUBLIC_API_URL` etc. already in use). Root route (`/`) checks the flag and redirects to the V2 shell or the existing dashboard accordingly. No runtime per-user toggle in this pass — flip the env var per environment (off in prod, on in a preview/dogfood deploy) until ready to cut over.

**Component reuse:** existing components (`WebRTCPlayer`, `SeverityBadge`, `HelpWidget`, live-view fallback chain) are reused as-is inside the new V2 views wherever the mockup's visual intent matches — restyled via props/wrapper, not rebuilt. Chat reuses the existing `ChatSidePanel`'s data layer (`chatSend`/`chatListConversations`/`chatGetMessages`) behind the mockup's new "Ask Nightwatch" visual treatment.

## Data mapping (every view → real endpoint)

| View | Backend calls | Notes |
|---|---|---|
| Home | `getCameras()`, `getEvents()` (recent) | "All quiet" banner derived client-side from recent-event count |
| Cameras | `getCameras()` | |
| Camera Detail | `getCameras()` (single), `getEvents({camera_id})`, existing live-view chain | Jobs-list section of Camera Detail ships as a "coming soon" placeholder pending Project C |
| Chat | `chatSend`, `chatListConversations`, `chatGetMessages`, `chatDeleteConversation` | Already fully real; new visual treatment only |
| Playback | `getEvents({camera_id})`, `Event.snapshot_url`/`clip_url` | Step-through UI is new (mockup has no equivalent today) |
| Activity | `getEvents()` with filters | |
| Digests | `getDigests()`, `getDigest(id)`, `getDigestPreferences()`, `updateDigestPreferences()` | |
| Settings | `getMyOrg`, `updateMyOrg`, `getTeam`, WhatsApp contact CRUD, digest preferences | Quiet hours / generic contacts / integrations list omitted (not real) |
| Admin Overview/Accounts | `adminGetOrgs`, `adminGetUsers`, admin CRUD methods | |
| Admin AI | New: `GET /api/admin/ai-usage` (super-admin-scoped mirror of the existing org-scoped `/api/settings/ai-usage`, same `AIUsage` table, no new data model) | Only backend change in this project |

## Error handling

The mockup is a static design mock with no loading/empty/error states. Every ported view gets, per this project's existing frontend rules (`frontend/CLAUDE.md`): a loading skeleton (not blank/spinner-only), an empty state matching the mockup's "quiet"/empty copy where it already has one (e.g. Home's "All quiet" banner, Agents' "No agents yet" pattern reused for other empty lists), and an inline error state on fetch failure (not a blank page). None of this is new UX design — the visual language is the mockup's, the states are net-new engineering the mockup didn't need to define.

## Testing

`npm run build` must stay clean (existing project rule — zero type errors). No automated component tests, matching this project's standing no-TDD preference for this kind of UI work — manual verification per view against the running dev server, checking real data renders correctly and the flag correctly gates old vs. new.

## Non-goals

- Not touching the current (flag-off) dashboard's code or behavior.
- Not building Map, Agents (jobs), or Admin System — separate projects/dropped.
- Not adding a runtime per-user UI toggle — env-var flag only, for this pass.
- Not adding quiet hours, generic contacts, or third-party integrations to Settings — no backend to back them.

## Open questions

- Exact V2 route structure (route group like `(v2)` vs. a separate `app-v2` directory vs. path-prefixed routes) — implementation-plan-level decision, doesn't change this design.
- Whether the flag redirect happens in middleware or in the root page component — implementation detail.
