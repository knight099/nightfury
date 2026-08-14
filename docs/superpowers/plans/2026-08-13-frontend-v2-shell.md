# Frontend V2 Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the `newdesign/Nightwatch.dc.html` mockup's shell, navigation, and every real-data-backed view into the existing Next.js app behind a build-time flag (`NEXT_PUBLIC_NEW_UI`), reusing all existing data-fetching — only the visual/navigation layer is new.

**Architecture:** A parallel route tree (`frontend/src/app/(v2)/...`) with its own shell component (`AppShellV2`) mirroring the existing `AppShell`'s auth-guard pattern exactly, but with the mockup's navigation and visual language (oklch color tokens via Tailwind arbitrary values). The flag is checked once, centrally, in `AppShellV2` and in the existing `AppShell` (so both directions redirect correctly) — no changes to any existing route's page component.

**Tech Stack:** Next.js 16 App Router, TypeScript strict, Tailwind, TanStack Query v5, Zustand — all existing, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-13-frontend-v2-shell-design.md`

## Global Constraints

- No TDD — implement each task directly, verify manually against the running dev server, then self-review, per this project's standing preference (confirmed across every prior plan in this session). No automated component tests.
- `npm run build` must stay clean (zero TypeScript errors) after every task — this project's existing hard rule.
- Every view gets a loading skeleton (reuse `Skeleton` from `@/components/ui/Skeleton`), an empty state, and an inline error state — never a blank page. The mockup has none of these (it's a static design mock); this is net-new engineering per task, not optional polish.
- Visual reference for every view is `newdesign/Nightwatch.dc.html` — the line ranges cited per task are the exact structure/copy/interaction source of truth. Colors are the mockup's literal oklch values, applied via Tailwind arbitrary-value syntax (e.g. `oklch(9% 0.015 265)` → `bg-[oklch(9%_0.015_265)]`, spaces become underscores) — this is a new, separate visual language from the existing hex-token theme (`frontend/CLAUDE.md`'s `#0D0D0D` etc.); do not mix the two or touch the existing theme's tokens.
- Existing routes (`/dashboard`, `/cameras`, `/events`, `/alerts`, `/digests`, `/settings`, `/admin`, etc.) and their page components are never modified in this plan — V2 is fully additive.
- Dropped from this port entirely (per the approved spec, not silently omitted): Admin System (no uptime data source exists), Settings' quiet hours / generic call-text contacts / Slack integration (none of this exists in the backend). Map and Agents nav items link to a "coming soon" placeholder page, not a 404 or fabricated data.
- Every list of `iceServers`/similar minor prior-session details are irrelevant here — this plan only touches frontend + one small backend route (Task 11).

---

## File Structure

```
frontend/src/app/(v2)/
├── layout.tsx                  # AppShellV2 wrapper (auth guard + nav)
├── page.tsx                    # Home
├── cameras/page.tsx            # Cameras grid
├── cameras/[id]/page.tsx       # Camera Detail
├── chat/page.tsx               # Ask Nightwatch (full page)
├── playback/[cameraId]/page.tsx # Playback (query-param driven start event)
├── activity/page.tsx           # Activity feed
├── digests/page.tsx            # Digests
├── settings/page.tsx           # Settings (trimmed)
├── admin/page.tsx              # Admin Overview + Accounts tabs
├── admin/ai/page.tsx           # Admin AI usage
├── map/page.tsx                # "Coming soon" placeholder
└── agents/page.tsx             # "Coming soon" placeholder

frontend/src/components/v2/
├── AppShellV2.tsx
├── SidebarV2.tsx
├── ComingSoon.tsx               # shared placeholder component
├── HomeCameraTile.tsx
├── ActivityRow.tsx              # shared event-row component (Home + Activity)
└── PlaybackDots.tsx

frontend/src/lib/flags.ts        # isNewUiEnabled()

backend/app/api/admin.py         # MODIFY: add GET /api/admin/ai-usage (Task 11)
```

---

### Task 1: Flag infrastructure + AppShellV2 shell

**Files:**
- Create: `frontend/src/lib/flags.ts`
- Create: `frontend/src/components/v2/AppShellV2.tsx`
- Create: `frontend/src/components/v2/SidebarV2.tsx`
- Create: `frontend/src/components/v2/ComingSoon.tsx`
- Create: `frontend/src/app/(v2)/layout.tsx`
- Modify: `frontend/src/components/layout/app-shell.tsx` (add cross-redirect)
- Modify: `frontend/.env.local` (document the new var, default unset)

**Interfaces:**
- Produces: `isNewUiEnabled(): boolean`, `AppShellV2({children}: {children: React.ReactNode})` — same shape as existing `AppShell`, reused by every V2 page's route segment via the shared `layout.tsx`.
- Consumes: `useAuthStore` (`token`, `user`, `logout`) — exact same store as existing `AppShell`, no new state.

- [ ] **Step 1: Flag helper**

```ts
// frontend/src/lib/flags.ts
export function isNewUiEnabled(): boolean {
  return process.env.NEXT_PUBLIC_NEW_UI === "true";
}
```

- [ ] **Step 2: Cross-redirect in the existing AppShell**

In `frontend/src/components/layout/app-shell.tsx`, inside the existing auth-guard `useEffect` (the one currently redirecting to `/login`/`/change-password`), add a flag check so an authenticated user hitting any old route while the flag is on gets sent to the V2 shell:

```tsx
// add near the top of app-shell.tsx
import { isNewUiEnabled } from "@/lib/flags";

// inside the existing useEffect, as the first check after the token check:
useEffect(() => {
  if (!token) {
    router.replace("/login");
  } else if (isNewUiEnabled()) {
    router.replace("/");
  } else if (user?.must_change_password) {
    router.replace("/change-password");
  } else if (requireRole && user?.role !== requireRole) {
    router.replace("/dashboard");
  } else {
    api.setToken(token);
  }
}, [token, user, router, requireRole]);
```

Note: `/` is the V2 route group's root page (Task 2) — the `(v2)` route group segment is invisible in the URL, so `(v2)/page.tsx` serves at `/`. This means the existing public marketing page at `frontend/src/app/page.tsx` and the V2 Home page cannot both serve `/` — resolve this by moving the current marketing page's content to a new explicit path (e.g. `/welcome`) is OUT of scope for this plan; instead, mount V2 at `/app` (not `/`) to avoid the collision. Revise Step 2's redirect target and the route structure below accordingly:

```tsx
} else if (isNewUiEnabled()) {
  router.replace("/app");
}
```

And the V2 route group's actual path prefix is `/app` — Next.js route groups don't add a URL segment by themselves, so to get a real `/app` prefix, do NOT use a route-group directory; instead create `frontend/src/app/app/` (a real directory named `app`, NOT a `(v2)` group) as the V2 route root. Every path in "File Structure" above and every task below that says `(v2)` actually means `frontend/src/app/app/` (a literal `/app` prefix). Use this real, prefixed path — not a route group — for the rest of this plan.

- [ ] **Step 3: `AppShellV2`**

```tsx
// frontend/src/components/v2/AppShellV2.tsx
"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store";
import { api } from "@/lib/api";
import { isNewUiEnabled } from "@/lib/flags";
import { SidebarV2 } from "@/components/v2/SidebarV2";

export function AppShellV2({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { token, user } = useAuthStore();

  useEffect(() => {
    if (!isNewUiEnabled()) {
      router.replace("/dashboard");
    } else if (!token) {
      router.replace("/login");
    } else if (user?.must_change_password) {
      router.replace("/change-password");
    } else {
      api.setToken(token);
    }
  }, [token, user, router]);

  if (!isNewUiEnabled() || !token || user?.must_change_password) return null;

  return (
    <div className="flex min-h-screen bg-[oklch(9%_0.015_265)] text-[oklch(97%_0.005_265)]">
      <SidebarV2 />
      <main className="flex-1 overflow-y-auto min-w-0">{children}</main>
    </div>
  );
}
```

Port the sidebar structure from `newdesign/Nightwatch.dc.html:27-74` (logo, nav items Home/Cameras/Map/Agents/Activity/Digests/Settings, "On watch" status card, "Super Admin login" link) into `SidebarV2.tsx` — use `usePathname()` + `Link` (matching the existing `Sidebar` component's pattern) instead of the mockup's `onClick={{ goX }}` handlers, since those are mock-controller artifacts, not real navigation. The "On watch" card's `{{ camerasWatchingCount }} of {{ camerasTotalCount }}` binding becomes a real `useQuery(["cameras"], () => api.getCameras())` call, counting `status === "online"` vs total.

- [ ] **Step 4: `ComingSoon` placeholder**

```tsx
// frontend/src/components/v2/ComingSoon.tsx
export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="max-w-[1040px] mx-auto px-12 py-20 text-center">
      <div className="text-2xl font-bold mb-2">{title}</div>
      <div className="text-sm text-[oklch(58%_0.01_265)]">
        This is coming soon. Nothing to see here yet.
      </div>
    </div>
  );
}
```

- [ ] **Step 5: V2 layout**

```tsx
// frontend/src/app/app/layout.tsx
import { AppShellV2 } from "@/components/v2/AppShellV2";

export default function V2Layout({ children }: { children: React.ReactNode }) {
  return <AppShellV2>{children}</AppShellV2>;
}
```

- [ ] **Step 6: Manual verification**

Set `NEXT_PUBLIC_NEW_UI=true` in `.env.local`, run `npm run dev`, log in — confirm you land on `/app` and see the new sidebar (Home page will 404 until Task 2 — that's expected here). Set the flag back to unset/false, confirm the old `/dashboard` still works exactly as before, and that hitting `/app` directly while flag is off redirects to `/dashboard`.

- [ ] **Step 7: Build check**

Run: `cd frontend && npm run build`
Expected: zero type errors (the `/app` route will fail to build cleanly until Task 2 adds `page.tsx` — if so, add a minimal placeholder `frontend/src/app/app/page.tsx` returning `<ComingSoon title="Home" />` in this task so the build passes, and Task 2 replaces its content).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/flags.ts frontend/src/components/v2 frontend/src/app/app frontend/src/components/layout/app-shell.tsx frontend/.env.local
git commit -m "frontend: add V2 shell scaffold behind NEXT_PUBLIC_NEW_UI flag"
```

---

### Task 2: Home view

**Files:**
- Create: `frontend/src/app/app/page.tsx`
- Create: `frontend/src/components/v2/HomeCameraTile.tsx`
- Create: `frontend/src/components/v2/ActivityRow.tsx` (shared with Task 7)

**Interfaces:**
- Consumes: `AppShellV2` (Task 1, wraps this page automatically via the layout).
- Produces: `ActivityRow({event}: {event: Event})` — reused by Task 7 (Activity).

- [ ] **Step 1: `ActivityRow`**

Port the event-row structure from `newdesign/Nightwatch.dc.html:120-128` (severity pill, text, camera+time) — pill color driven by `Event.severity`:

```tsx
// frontend/src/components/v2/ActivityRow.tsx
import type { Event } from "@/types";

const severityColor: Record<Event["severity"], string> = {
  low: "oklch(79.2% 0.209 151.711)",
  medium: "oklch(82.8% 0.189 84.429)",
  high: "oklch(82.8% 0.189 84.429)",
  critical: "oklch(70.4% 0.191 22.216)",
};

export function ActivityRow({ event }: { event: Event }) {
  const color = severityColor[event.severity];
  return (
    <div className="flex items-center gap-3.5 px-[18px] py-3.5 border-b border-[oklch(19%_0.015_265)] bg-[oklch(12%_0.015_265)]">
      <div
        className="text-[11px] font-bold tracking-wide px-2.5 py-1.5 rounded-full whitespace-nowrap flex-shrink-0"
        style={{ color, backgroundColor: `color-mix(in oklab, ${color} 16%, transparent)` }}
      >
        {event.severity.toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] text-[oklch(90%_0.005_265)]">{event.description}</div>
        <div className="text-[11.5px] text-[oklch(55%_0.01_265)] mt-0.5">
          {event.camera_id} · {new Date(event.timestamp).toLocaleString()}
        </div>
      </div>
    </div>
  );
}
```

Note: `event.camera_id` is a UUID, not a display name — the mockup shows `cam.name`. This task's caller must resolve camera name via the already-fetched cameras list (see Step 3 below); pass a `cameraName` prop instead of relying on `camera_id` directly. Revise the component:

```tsx
export function ActivityRow({ event, cameraName }: { event: Event; cameraName: string }) {
  // ...same body, replace {event.camera_id} with {cameraName}
```

- [ ] **Step 2: `HomeCameraTile`**

Port `newdesign/Nightwatch.dc.html:100-112`'s tile structure — image slot becomes a real snapshot via `api.getCameraLatestFrame`, status dot driven by `Camera.status`:

```tsx
// frontend/src/components/v2/HomeCameraTile.tsx
"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Camera } from "@/types";

export function HomeCameraTile({ camera }: { camera: Camera }) {
  const { data: frame } = useQuery({
    queryKey: ["camera-latest-frame", camera.id],
    queryFn: () => api.getCameraLatestFrame(camera.id),
    refetchInterval: 10000,
  });

  const dotColor =
    camera.status === "online" ? "oklch(79.2% 0.209 151.711)" : "oklch(70.4% 0.191 22.216)";

  return (
    <Link
      href={`/app/cameras/${camera.id}`}
      className="block bg-[oklch(14%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] overflow-hidden"
    >
      <div className="h-[100px] relative bg-[oklch(11%_0.015_265)]">
        {frame?.url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={frame.url} alt={camera.name} className="w-full h-full object-cover" />
        )}
        <div
          className="absolute top-2.5 right-2.5 w-[9px] h-[9px] rounded-full"
          style={{ background: dotColor, boxShadow: "0 0 0 3px oklch(9% 0.015 265 / 0.6)" }}
        />
      </div>
      <div className="px-3.5 py-3">
        <div className="text-[13px] font-semibold mb-0.5">{camera.name}</div>
        <div className="text-[11px] text-[oklch(58%_0.01_265)] font-mono">{camera.status}</div>
      </div>
    </Link>
  );
}
```

- [ ] **Step 3: Home page**

Port `newdesign/Nightwatch.dc.html:78-138`'s structure (greeting, "all quiet" banner, camera grid, recent activity, "give a camera a new job" CTA linking to `/app/agents`):

```tsx
// frontend/src/app/app/page.tsx
"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { HomeCameraTile } from "@/components/v2/HomeCameraTile";
import { ActivityRow } from "@/components/v2/ActivityRow";
import { useAuthStore } from "@/lib/store";

export default function HomePage() {
  const { user } = useAuthStore();

  const { data: cameras, isLoading: camsLoading } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  const { data: eventsData, isLoading: eventsLoading } = useQuery({
    queryKey: ["events", "recent"],
    queryFn: () => api.getEvents({ per_page: "5" }),
  });

  const cameraName = (id: string) => cameras?.find((c) => c.id === id)?.name ?? "Unknown camera";

  if (camsLoading || eventsLoading) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Skeleton className="h-8 w-64 mb-6" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const events = eventsData?.events ?? [];

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-1.5">
        Good afternoon, {user?.name ?? user?.username}
      </div>
      <div className="text-[15px] text-[oklch(65%_0.01_265)] mb-8">
        Here&apos;s how things look right now.
      </div>

      <div className="bg-gradient-to-br from-[oklch(18%_0.03_155)] to-[oklch(13%_0.02_265)] border border-[oklch(30%_0.06_155)] rounded-[20px] px-8 py-7 flex items-center justify-between mb-9">
        <div className="flex items-center gap-4.5">
          <div className="w-12 h-12 rounded-full bg-[oklch(79.2%_0.209_151.711_/_0.15)] flex items-center justify-center flex-shrink-0">
            <div className="w-3.5 h-3.5 rounded-full bg-[oklch(79.2%_0.209_151.711)]" />
          </div>
          <div>
            <div className="text-xl font-bold mb-1">
              {events.length === 0 ? "All quiet" : `${events.length} recent events`}
            </div>
            <div className="text-sm text-[oklch(75%_0.01_265)]">
              {events.length === 0
                ? "Nothing needed you recently."
                : "Here's what's happened lately."}
            </div>
          </div>
        </div>
        <Link href="/app/chat" className="text-[13px] font-semibold text-[oklch(85%_0.06_155)]">
          Ask Nightwatch →
        </Link>
      </div>

      <div className="flex items-baseline justify-between mb-4">
        <div className="text-base font-bold">Your cameras</div>
        <Link href="/app/cameras" className="text-[13px] font-semibold text-[oklch(72%_0.01_265)]">
          See all →
        </Link>
      </div>
      {cameras && cameras.length > 0 ? (
        <div className="grid grid-cols-4 gap-4 mb-10">
          {cameras.map((cam) => (
            <HomeCameraTile key={cam.id} camera={cam} />
          ))}
        </div>
      ) : (
        <div className="text-sm text-[oklch(55%_0.01_265)] mb-10">No cameras yet.</div>
      )}

      <div className="flex items-baseline justify-between mb-4">
        <div className="text-base font-bold">Recent activity</div>
        <Link href="/app/activity" className="text-[13px] font-semibold text-[oklch(72%_0.01_265)]">
          See all →
        </Link>
      </div>
      <div className="flex flex-col border border-[oklch(22%_0.015_265)] rounded-[14px] overflow-hidden mb-9">
        {events.length > 0 ? (
          events.map((ev) => <ActivityRow key={ev.id} event={ev} cameraName={cameraName(ev.camera_id)} />)
        ) : (
          <div className="p-6 text-sm text-[oklch(55%_0.01_265)] text-center">No recent events.</div>
        )}
      </div>

      <Link
        href="/app/cameras"
        className="block border border-dashed border-[oklch(30%_0.02_265)] rounded-2xl px-6.5 py-5.5 flex items-center justify-between"
      >
        <div>
          <div className="text-[15px] font-bold mb-1">Give a camera a new job</div>
          <div className="text-[13px] text-[oklch(62%_0.01_265)]">
            Pick a camera and tell it what to watch for, in plain English.
          </div>
        </div>
        <div className="text-[22px] text-[oklch(72%_0.01_265)]">+</div>
      </Link>
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

`npm run dev`, flag on, visit `/app` — confirm real camera tiles and real recent events render, loading skeleton shows briefly, empty states show correctly if you test against an org with zero cameras/events.

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/page.tsx frontend/src/components/v2/HomeCameraTile.tsx frontend/src/components/v2/ActivityRow.tsx
git commit -m "frontend: V2 Home view with real camera/event data"
```

---

### Task 3: Cameras grid view

**Files:**
- Create: `frontend/src/app/app/cameras/page.tsx`

**Interfaces:**
- Consumes: `api.getCameras()` (existing).

- [ ] **Step 1: Implement**

Port `newdesign/Nightwatch.dc.html:141-172`'s 2-column grid structure:

```tsx
// frontend/src/app/app/cameras/page.tsx
"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function CamerasPageV2() {
  const { data: cameras, isLoading } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });

  if (isLoading) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Skeleton className="h-8 w-48 mb-6" />
        <div className="grid grid-cols-2 gap-5">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="flex items-baseline justify-between mb-1.5">
        <div className="text-[28px] font-bold tracking-tight">Cameras</div>
        <div className="text-[13px] text-[oklch(58%_0.01_265)]">Click a camera to give it a job.</div>
      </div>
      <div className="text-[15px] text-[oklch(65%_0.01_265)] mb-7">
        Every camera below is on watch. Click one to see what it&apos;s up to.
      </div>
      {cameras && cameras.length > 0 ? (
        <div className="grid grid-cols-2 gap-5">
          {cameras.map((cam) => (
            <Link
              key={cam.id}
              href={`/app/cameras/${cam.id}`}
              className="block bg-[oklch(14%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-2xl overflow-hidden"
            >
              <div className="h-[180px] bg-[oklch(11%_0.015_265)]" />
              <div className="px-4 py-3.5">
                <div className="text-sm font-semibold mb-0.5">{cam.name}</div>
                <div className="text-[11px] text-[oklch(58%_0.01_265)] font-mono">{cam.status}</div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="text-sm text-[oklch(55%_0.01_265)]">No cameras yet.</div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Visit `/app/cameras` with the flag on — confirm real cameras render, clicking one navigates to `/app/cameras/{id}` (404 until Task 4).

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/cameras/page.tsx
git commit -m "frontend: V2 Cameras grid view"
```

---

### Task 4: Camera Detail view

**Files:**
- Create: `frontend/src/app/app/cameras/[id]/page.tsx`

**Interfaces:**
- Consumes: `WebRTCPlayer` (existing, unchanged), `api.getCameraStreamUrl`, `api.getCameraLatestFrame`, `api.getEvents` — reuse the EXACT live-view fallback chain state machine from `frontend/src/app/cameras/[id]/page.tsx:55-72` (the `webrtcFailed`/`streamFailed` cascade), do not reinvent it.

- [ ] **Step 1: Implement**

```tsx
// frontend/src/app/app/cameras/[id]/page.tsx
"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { ActivityRow } from "@/components/v2/ActivityRow";
import { ComingSoon } from "@/components/v2/ComingSoon";
import { WebRTCPlayer } from "@/components/cameras/WebRTCPlayer";

export default function CameraDetailPageV2({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [webrtcFailed, setWebrtcFailed] = useState(false);
  const [streamFailed, setStreamFailed] = useState(false);

  const { data: cameras, isLoading: camsLoading } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.getCameras(),
  });
  const camera = cameras?.find((c) => c.id === id);

  const { data: streamUrl } = useQuery({
    queryKey: ["camera-stream-url", id],
    queryFn: () => api.getCameraStreamUrl(id),
    refetchInterval: 10 * 60 * 1000,
    enabled: !!camera && webrtcFailed && !streamFailed,
  });

  const { data: frame } = useQuery({
    queryKey: ["camera-latest-frame", id],
    queryFn: () => api.getCameraLatestFrame(id),
    refetchInterval: 1000,
    enabled: !!camera && webrtcFailed && streamFailed,
  });

  const { data: eventsData, isLoading: eventsLoading } = useQuery({
    queryKey: ["events", "camera", id],
    queryFn: () => api.getEvents({ camera_id: id, per_page: "20" }),
    enabled: !!camera,
  });

  if (camsLoading) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Skeleton className="h-8 w-64 mb-6" />
        <Skeleton className="h-[400px] w-full" />
      </div>
    );
  }

  if (!camera) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        Camera not found.
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <Link href="/app/cameras" className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
        ← Cameras
      </Link>
      <div className="text-[28px] font-bold tracking-tight mb-6">{camera.name}</div>

      <div className="rounded-[18px] overflow-hidden mb-6 bg-[oklch(11%_0.015_265)] h-[400px] relative">
        {!webrtcFailed ? (
          <WebRTCPlayer cameraId={id} className="w-full h-full object-cover" onError={() => setWebrtcFailed(true)} />
        ) : !streamFailed && streamUrl?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={streamUrl.url}
            alt={camera.name}
            className="w-full h-full object-cover"
            onError={() => setStreamFailed(true)}
          />
        ) : frame?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={frame.url} alt={camera.name} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-sm text-[oklch(55%_0.01_265)]">
            Live view unavailable
          </div>
        )}
      </div>

      <div className="text-base font-bold mb-3.5">Jobs</div>
      <ComingSoon title="Camera jobs are coming soon" />

      <div className="text-base font-bold mb-3.5 mt-2">Recent events</div>
      {eventsLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="flex flex-col border border-[oklch(22%_0.015_265)] rounded-[14px] overflow-hidden">
          {(eventsData?.events ?? []).length > 0 ? (
            eventsData!.events.map((ev) => <ActivityRow key={ev.id} event={ev} cameraName={camera.name} />)
          ) : (
            <div className="p-6 text-sm text-[oklch(55%_0.01_265)] text-center">No events yet.</div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Visit `/app/cameras/{id}` for a real camera — confirm live view attempts WebRTC first, falls back correctly (test by checking network tab), events list renders.

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/cameras/[id]/page.tsx
git commit -m "frontend: V2 Camera Detail view with live-view fallback chain"
```

---

### Task 5: Chat ("Ask Nightwatch") view

**Files:**
- Create: `frontend/src/app/app/chat/page.tsx`

**Interfaces:**
- Consumes: `api.chatSend`, `api.chatListConversations`, `api.chatGetMessages` (all existing, real).

- [ ] **Step 1: Implement**

Port `newdesign/Nightwatch.dc.html:259-296`'s structure (empty-state suggestion chips, message list, input bar):

```tsx
// frontend/src/app/app/chat/page.tsx
"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { ChatMessage } from "@/types";

const SUGGESTIONS = [
  "What happened today?",
  "Is everything okay at the shop?",
  "Show me anything urgent",
  "Summarize this week",
];

export default function ChatPageV2() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const queryClient = useQueryClient();

  const { data: messages } = useQuery<ChatMessage[]>({
    queryKey: ["chat-messages", conversationId],
    queryFn: () => api.chatGetMessages(conversationId!),
    enabled: !!conversationId,
  });

  const sendMutation = useMutation({
    mutationFn: (message: string) => api.chatSend({ message, conversation_id: conversationId ?? undefined }),
    onSuccess: (msg) => {
      if (!conversationId) setConversationId(msg.conversation_id);
      queryClient.invalidateQueries({ queryKey: ["chat-messages", msg.conversation_id] });
    },
  });

  const send = (text: string) => {
    if (!text.trim()) return;
    sendMutation.mutate(text);
    setInput("");
  };

  const isEmpty = !messages || messages.length === 0;

  return (
    <div className="h-full flex flex-col relative bg-[radial-gradient(circle_at_50%_0%,oklch(20%_0.05_84_/_0.25),transparent_55%)]">
      <div className="text-center pt-7 px-6">
        <div className="text-xs font-bold tracking-widest uppercase text-[oklch(52%_0.01_265)]">
          Master control
        </div>
      </div>

      {isEmpty ? (
        <div className="flex-1 flex flex-col items-center justify-center px-5 text-center">
          <div className="text-4xl font-bold tracking-tight mb-2.5">What do you want to know?</div>
          <div className="text-[15px] text-[oklch(58%_0.01_265)] mb-8 max-w-[440px]">
            Ask about any camera, event, or moment — across everything Nightwatch is watching.
          </div>
          <div className="flex flex-wrap gap-2 justify-center max-w-[580px]">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="text-[13px] px-4 py-2.5 rounded-full border border-[oklch(24%_0.015_265)] bg-[oklch(13%_0.015_265)] text-[oklch(78%_0.01_265)]"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto flex flex-col gap-4 px-6 pt-6 pb-3 max-w-[680px] mx-auto w-full">
          {messages!.map((msg) => (
            <div key={msg.id} className={msg.role === "user" ? "self-end" : "self-start"}>
              <div
                className={`rounded-2xl px-4 py-2.5 text-sm max-w-[440px] ${
                  msg.role === "user"
                    ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]"
                    : "bg-[oklch(15%_0.015_265)] text-[oklch(90%_0.005_265)]"
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="px-6 pt-5 pb-9 flex justify-center">
        <div className="flex gap-2.5 w-full max-w-[640px] bg-[oklch(14%_0.015_265)] border border-[oklch(26%_0.015_265)] rounded-full py-2 pl-5.5 pr-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send(input)}
            placeholder="Ask about anything happening right now"
            className="flex-1 bg-transparent border-none text-[14.5px] text-[oklch(95%_0.005_265)] outline-none"
          />
          <button
            onClick={() => send(input)}
            className="bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)] w-[38px] h-[38px] rounded-full flex items-center justify-center flex-shrink-0"
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Visit `/app/chat`, click a suggestion chip, confirm a real message round-trip via `/api/chat`, confirm conversation continuity (asking a follow-up uses the same `conversation_id`).

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/chat/page.tsx
git commit -m "frontend: V2 Ask Nightwatch full-page chat view"
```

---

### Task 6: Playback view

**Files:**
- Create: `frontend/src/app/app/playback/[cameraId]/page.tsx`

**Interfaces:**
- Consumes: `api.getEvents({camera_id})` (existing) — steps through that camera's recent events' `snapshot_url`.

- [ ] **Step 1: Implement**

Port `newdesign/Nightwatch.dc.html:405-439`'s step-through structure (prev/next arrows, dot indicators):

```tsx
// frontend/src/app/app/playback/[cameraId]/page.tsx
"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function PlaybackPageV2({ params }: { params: Promise<{ cameraId: string }> }) {
  const { cameraId } = use(params);
  const [index, setIndex] = useState(0);

  const { data: cameras } = useQuery({ queryKey: ["cameras"], queryFn: () => api.getCameras() });
  const camera = cameras?.find((c) => c.id === cameraId);

  const { data: eventsData, isLoading } = useQuery({
    queryKey: ["events", "camera", cameraId],
    queryFn: () => api.getEvents({ camera_id: cameraId, per_page: "20" }),
  });

  const events = eventsData?.events ?? [];
  const current = events[index];

  if (isLoading) return <Skeleton className="h-96 w-full max-w-[820px] mx-auto mt-12" />;

  if (events.length === 0) {
    return (
      <div className="max-w-[820px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        No events to play back for this camera yet.
      </div>
    );
  }

  return (
    <div className="max-w-[820px] mx-auto px-12 pt-12 pb-20">
      <Link href={`/app/cameras/${cameraId}`} className="text-[13px] text-[oklch(62%_0.01_265)] mb-4 inline-block">
        ← Back
      </Link>
      <div className="flex items-baseline justify-between mb-4">
        <div className="text-2xl font-bold">{camera?.name ?? "Camera"} · Playback</div>
        <div className="text-[13px] text-[oklch(58%_0.01_265)] font-mono">
          {new Date(current.timestamp).toLocaleString()}
        </div>
      </div>

      <div className="h-[400px] rounded-[18px] overflow-hidden mb-4.5 bg-[oklch(11%_0.015_265)]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={current.snapshot_url} alt={current.description} className="w-full h-full object-cover" />
      </div>

      <div className="flex items-center gap-3.5 bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] px-5 py-4 mb-4.5">
        <div className="flex-1 min-w-0">
          <div className="text-[13.5px] text-[oklch(90%_0.005_265)]">{current.description}</div>
          <div className="text-[11.5px] text-[oklch(55%_0.01_265)] mt-0.5">{current.event_type}</div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <button
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          disabled={index === 0}
          className="w-[42px] h-[42px] rounded-full bg-[oklch(15%_0.015_265)] border border-[oklch(26%_0.015_265)] flex items-center justify-center flex-shrink-0 disabled:opacity-30"
        >
          ←
        </button>
        <div className="flex-1 flex items-center justify-center gap-2 overflow-x-auto px-1">
          {events.map((ev, i) => (
            <button
              key={ev.id}
              onClick={() => setIndex(i)}
              className={`w-2 h-2 rounded-full flex-shrink-0 ${i === index ? "bg-[oklch(85%_0.16_84)]" : "bg-[oklch(30%_0.02_265)]"}`}
            />
          ))}
        </div>
        <button
          onClick={() => setIndex((i) => Math.min(events.length - 1, i + 1))}
          disabled={index === events.length - 1}
          className="w-[42px] h-[42px] rounded-full bg-[oklch(15%_0.015_265)] border border-[oklch(26%_0.015_265)] flex items-center justify-center flex-shrink-0 disabled:opacity-30"
        >
          →
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Visit `/app/playback/{cameraId}` for a camera with events, step through with arrows and dots, confirm the timestamp/snapshot update correctly.

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/playback
git commit -m "frontend: V2 Playback view"
```

---

### Task 7: Activity view

**Files:**
- Create: `frontend/src/app/app/activity/page.tsx`

**Interfaces:**
- Consumes: `ActivityRow` (Task 2), `api.getEvents()` with filters.

- [ ] **Step 1: Implement**

```tsx
// frontend/src/app/app/activity/page.tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { ActivityRow } from "@/components/v2/ActivityRow";

const FILTERS = ["all", "low", "medium", "high", "critical"] as const;

export default function ActivityPageV2() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");

  const { data: cameras } = useQuery({ queryKey: ["cameras"], queryFn: () => api.getCameras() });
  const { data: eventsData, isLoading } = useQuery({
    queryKey: ["events", "activity", filter],
    queryFn: () => api.getEvents({ per_page: "50", ...(filter !== "all" && { severity: filter }) }),
  });

  const cameraName = (id: string) => cameras?.find((c) => c.id === id)?.name ?? "Unknown camera";

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">Activity</div>
      <div className="flex gap-2 mb-6">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-[12px] font-semibold px-3 py-1.5 rounded-full ${
              filter === f
                ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]"
                : "bg-[oklch(15%_0.015_265)] text-[oklch(72%_0.01_265)]"
            }`}
          >
            {f}
          </button>
        ))}
      </div>
      {isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <div className="flex flex-col border border-[oklch(22%_0.015_265)] rounded-[14px] overflow-hidden">
          {(eventsData?.events ?? []).length > 0 ? (
            eventsData!.events.map((ev) => <ActivityRow key={ev.id} event={ev} cameraName={cameraName(ev.camera_id)} />)
          ) : (
            <div className="p-6 text-sm text-[oklch(55%_0.01_265)] text-center">No events match this filter.</div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Visit `/app/activity`, confirm filtering by severity actually changes the results (check network tab for `severity=` query param).

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/activity/page.tsx
git commit -m "frontend: V2 Activity view with severity filters"
```

---

### Task 8: Digests view

**Files:**
- Create: `frontend/src/app/app/digests/page.tsx`

**Interfaces:**
- Consumes: `api.getDigests()`, `api.getDigestPreferences()`, `api.updateDigestPreferences()` (all existing).

- [ ] **Step 1: Implement**

```tsx
// frontend/src/app/app/digests/page.tsx
"use client";

import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function DigestsPageV2() {
  const queryClient = useQueryClient();

  const { data: digestsData, isLoading } = useQuery({
    queryKey: ["digests"],
    queryFn: () => api.getDigests(),
  });

  const { data: prefs } = useQuery({
    queryKey: ["digest-preferences"],
    queryFn: () => api.getDigestPreferences(),
  });

  const updatePrefs = useMutation({
    mutationFn: (body: Parameters<typeof api.updateDigestPreferences>[0]) =>
      api.updateDigestPreferences(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["digest-preferences"] }),
  });

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">Digests</div>

      {prefs && (
        <div className="flex gap-6 mb-8 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={prefs.morning_enabled}
              onChange={(e) => updatePrefs.mutate({ ...prefs, morning_enabled: e.target.checked })}
            />
            Morning digest ({prefs.morning_local_time})
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={prefs.evening_enabled}
              onChange={(e) => updatePrefs.mutate({ ...prefs, evening_enabled: e.target.checked })}
            />
            Evening digest ({prefs.evening_local_time})
          </label>
        </div>
      )}

      {isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : (
        <div className="flex flex-col gap-3">
          {(digestsData?.items ?? []).length > 0 ? (
            digestsData!.items.map((d) => (
              <Link
                key={d.id}
                href={`/app/digests/${d.id}`}
                className="block bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] px-5 py-4"
              >
                <div className="text-sm font-semibold mb-1">{d.payload.headline}</div>
                <div className="text-xs text-[oklch(58%_0.01_265)]">
                  {new Date(d.range_start).toLocaleDateString()} · {d.event_count} events
                </div>
              </Link>
            ))
          ) : (
            <div className="text-sm text-[oklch(55%_0.01_265)]">No digests yet.</div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Visit `/app/digests`, toggle a preference checkbox, confirm it persists (refetch and check state), confirm digest list renders real data.

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/digests/page.tsx
git commit -m "frontend: V2 Digests view"
```

---

### Task 9: Settings view (trimmed)

**Files:**
- Create: `frontend/src/app/app/settings/page.tsx`

**Interfaces:**
- Consumes: `api.getMyOrg`, `api.getTeam`, `api.getWhatsAppAlertContacts`/`addWhatsAppAlertContact`/`deleteWhatsAppAlertContact` (all existing).

- [ ] **Step 1: Implement**

Trimmed per spec — team management, WhatsApp contacts, digest preferences link only. No quiet hours, no generic contacts, no integrations list.

```tsx
// frontend/src/app/app/settings/page.tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";

export default function SettingsPageV2() {
  const queryClient = useQueryClient();
  const [newNumber, setNewNumber] = useState("");

  const { data: org, isLoading: orgLoading } = useQuery({
    queryKey: ["my-org"],
    queryFn: () => api.getMyOrg(),
  });

  const { data: team, isLoading: teamLoading } = useQuery({
    queryKey: ["team"],
    queryFn: () => api.getTeam(),
  });

  const { data: contacts } = useQuery({
    queryKey: ["whatsapp-contacts"],
    queryFn: () => api.getWhatsAppAlertContacts(),
  });

  const addContact = useMutation({
    mutationFn: (number: string) => api.addWhatsAppAlertContact(number),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["whatsapp-contacts"] });
      setNewNumber("");
    },
  });

  if (orgLoading || teamLoading) {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12">
        <Skeleton className="h-8 w-48 mb-6" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">Settings</div>

      <div className="text-base font-bold mb-3">Organization</div>
      <div className="text-sm text-[oklch(72%_0.01_265)] mb-8">{org?.name}</div>

      <div className="text-base font-bold mb-3">Team</div>
      <div className="flex flex-col gap-2 mb-8">
        {(team ?? []).map((member) => (
          <div key={member.id} className="text-sm text-[oklch(80%_0.005_265)]">
            {member.name} ({member.role})
          </div>
        ))}
        {(team ?? []).length === 0 && (
          <div className="text-sm text-[oklch(55%_0.01_265)]">No team members yet.</div>
        )}
      </div>

      <div className="text-base font-bold mb-3">WhatsApp alert contacts</div>
      <div className="flex flex-col gap-2 mb-3">
        {(contacts ?? []).map((c) => (
          <div key={c.id} className="text-sm text-[oklch(80%_0.005_265)]">
            {c.number} {c.enabled ? "" : "(disabled)"}
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={newNumber}
          onChange={(e) => setNewNumber(e.target.value)}
          placeholder="+91..."
          className="bg-[oklch(17%_0.015_265)] border border-[oklch(30%_0.02_265)] rounded-lg px-3 py-2 text-sm text-[oklch(95%_0.005_265)] outline-none"
        />
        <button
          onClick={() => newNumber && addContact.mutate(newNumber)}
          className="text-sm font-semibold px-4 py-2 rounded-lg bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]"
        >
          Add
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Visit `/app/settings`, confirm org/team/WhatsApp contacts render real data, add a test contact and confirm it persists.

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/settings/page.tsx
git commit -m "frontend: V2 Settings view (trimmed to real fields)"
```

---

### Task 10: Admin Overview + Accounts view

**Files:**
- Create: `frontend/src/app/app/admin/page.tsx`

**Interfaces:**
- Consumes: `api.adminGetOrgs`, `api.adminGetUsers` (existing, super_admin-gated by the backend routes themselves).

- [ ] **Step 1: Implement**

```tsx
// frontend/src/app/app/admin/page.tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuthStore } from "@/lib/store";

export default function AdminPageV2() {
  const { user } = useAuthStore();
  const [tab, setTab] = useState<"users" | "orgs">("users");

  const { data: orgs, isLoading: orgsLoading } = useQuery({
    queryKey: ["admin", "orgs"],
    queryFn: () => api.adminGetOrgs(),
    enabled: user?.role === "super_admin",
  });

  const { data: users, isLoading: usersLoading } = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => api.adminGetUsers(),
    enabled: user?.role === "super_admin",
  });

  if (user?.role !== "super_admin") {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        Not authorized.
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">Admin</div>
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setTab("users")}
          className={`text-sm font-semibold px-4 py-2 rounded-lg ${
            tab === "users" ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]" : "text-[oklch(72%_0.01_265)]"
          }`}
        >
          Users
        </button>
        <button
          onClick={() => setTab("orgs")}
          className={`text-sm font-semibold px-4 py-2 rounded-lg ${
            tab === "orgs" ? "bg-[oklch(85%_0.16_84)] text-[oklch(18%_0.02_84)]" : "text-[oklch(72%_0.01_265)]"
          }`}
        >
          Orgs
        </button>
      </div>

      {tab === "users" &&
        (usersLoading ? (
          <Skeleton className="h-96 w-full" />
        ) : (
          <div className="flex flex-col gap-2">
            {(users ?? []).map((u) => (
              <div key={u.id} className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-lg px-4 py-3 text-sm">
                {u.username} · {u.role}
              </div>
            ))}
          </div>
        ))}

      {tab === "orgs" &&
        (orgsLoading ? (
          <Skeleton className="h-96 w-full" />
        ) : (
          <div className="flex flex-col gap-2">
            {(orgs ?? []).map((o: { id: string; name: string }) => (
              <div key={o.id} className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-lg px-4 py-3 text-sm">
                {o.name}
              </div>
            ))}
          </div>
        ))}
    </div>
  );
}
```

- [ ] **Step 2: Manual verification**

Log in as a `super_admin` user, visit `/app/admin`, confirm both tabs render real data. Log in as a non-super_admin, confirm the "Not authorized" state shows instead.

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/admin/page.tsx
git commit -m "frontend: V2 Admin Overview + Accounts view"
```

---

### Task 11: Admin AI usage — backend route + frontend view

**Files:**
- Modify: `backend/app/api/admin.py`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/app/app/admin/ai/page.tsx`

**Interfaces:**
- Produces: `GET /api/admin/ai-usage?org_id=&days=&limit=` (backend), `api.adminGetAiUsage(orgId, days?, limit?)` (frontend).

- [ ] **Step 1: Backend route**

In `backend/app/api/admin.py`, add a cross-org variant of the existing org-scoped `/api/settings/ai-usage` route (`backend/app/api/settings.py:173-267`), reusing the exact same query logic but scoped by an `org_id` query param instead of `user.org_id`, gated by `_require_super_admin` (the pattern already used by every other route in this file):

```python
# add near the top of admin.py, alongside existing imports
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, desc
from app.models.ai_usage import AIUsage

# add as a new route in admin.py
@router.get("/ai-usage")
async def admin_ai_usage(
    org_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
):
    """Cross-org AI usage report — super_admin only. Same shape as
    /api/settings/ai-usage, but scoped by an explicit org_id param
    instead of the caller's own org."""
    _require_super_admin(user)

    since = datetime.now(timezone.utc) - timedelta(days=days)

    agg_q = select(
        func.count(AIUsage.id).label("calls"),
        func.coalesce(func.sum(AIUsage.prompt_tokens), 0).label("prompt_tokens"),
        func.coalesce(func.sum(AIUsage.output_tokens), 0).label("output_tokens"),
        func.coalesce(func.sum(AIUsage.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(AIUsage.cost_usd), 0.0).label("cost_usd"),
        func.coalesce(func.avg(AIUsage.latency_ms), 0).label("avg_latency_ms"),
    ).where(AIUsage.org_id == org_id, AIUsage.timestamp >= since)
    agg_row = (await db.execute(agg_q)).one()

    recent_q = (
        select(AIUsage, User.username)
        .join(User, User.id == AIUsage.user_id)
        .where(AIUsage.org_id == org_id, AIUsage.timestamp >= since)
        .order_by(desc(AIUsage.timestamp))
        .limit(limit)
    )
    recent_rows = (await db.execute(recent_q)).all()
    recent = [
        {
            "id": str(row.AIUsage.id),
            "timestamp": row.AIUsage.timestamp.isoformat(),
            "username": row.username,
            "model": row.AIUsage.model,
            "operation": row.AIUsage.operation,
            "total_tokens": row.AIUsage.total_tokens,
            "cost_usd": row.AIUsage.cost_usd,
        }
        for row in recent_rows
    ]

    return {
        "period_days": days,
        "aggregate": {
            "calls": agg_row.calls or 0,
            "prompt_tokens": int(agg_row.prompt_tokens or 0),
            "output_tokens": int(agg_row.output_tokens or 0),
            "total_tokens": int(agg_row.total_tokens or 0),
            "cost_usd": float(agg_row.cost_usd or 0.0),
            "avg_latency_ms": int(agg_row.avg_latency_ms or 0),
        },
        "recent": recent,
    }
```

Note: this deliberately omits the `by_user` breakdown present in the org-scoped version — keep the first cut minimal; add it later if actually needed, following the exact same per-user query pattern from `settings.py:198-229` if so.

- [ ] **Step 2: Verify backend**

Run: `cd backend && uv run python3 -c "from app.main import app"`
Expected: imports cleanly.

- [ ] **Step 3: Frontend API method**

```ts
// frontend/src/lib/api.ts — add near the other admin methods
async adminGetAiUsage(orgId: string, days = 30, limit = 100) {
  return this.request<{
    period_days: number;
    aggregate: { calls: number; prompt_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number; avg_latency_ms: number };
    recent: { id: string; timestamp: string; username: string; model: string; operation: string; total_tokens: number; cost_usd: number }[];
  }>(`/api/admin/ai-usage?org_id=${orgId}&days=${days}&limit=${limit}`);
}
```

- [ ] **Step 4: Frontend view**

```tsx
// frontend/src/app/app/admin/ai/page.tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuthStore } from "@/lib/store";

export default function AdminAiPageV2() {
  const { user } = useAuthStore();
  const [orgId, setOrgId] = useState("");

  const { data: orgs } = useQuery({
    queryKey: ["admin", "orgs"],
    queryFn: () => api.adminGetOrgs(),
    enabled: user?.role === "super_admin",
  });

  const { data: usage, isLoading } = useQuery({
    queryKey: ["admin", "ai-usage", orgId],
    queryFn: () => api.adminGetAiUsage(orgId),
    enabled: !!orgId,
  });

  if (user?.role !== "super_admin") {
    return (
      <div className="max-w-[1040px] mx-auto px-12 py-12 text-sm text-[oklch(55%_0.01_265)]">
        Not authorized.
      </div>
    );
  }

  return (
    <div className="max-w-[1040px] mx-auto px-12 pt-12 pb-20">
      <div className="text-[28px] font-bold tracking-tight mb-6">AI usage</div>

      <select
        value={orgId}
        onChange={(e) => setOrgId(e.target.value)}
        className="bg-[oklch(17%_0.015_265)] border border-[oklch(30%_0.02_265)] rounded-lg px-3 py-2 text-sm text-[oklch(95%_0.005_265)] mb-6"
      >
        <option value="">Select an org</option>
        {(orgs ?? []).map((o: { id: string; name: string }) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>

      {isLoading && <Skeleton className="h-40 w-full" />}

      {usage && (
        <>
          <div className="grid grid-cols-3 gap-4 mb-8">
            <div className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] p-4">
              <div className="text-2xl font-bold">{usage.aggregate.calls}</div>
              <div className="text-xs text-[oklch(58%_0.01_265)]">calls (30d)</div>
            </div>
            <div className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] p-4">
              <div className="text-2xl font-bold">${usage.aggregate.cost_usd.toFixed(2)}</div>
              <div className="text-xs text-[oklch(58%_0.01_265)]">cost (30d)</div>
            </div>
            <div className="bg-[oklch(13%_0.015_265)] border border-[oklch(22%_0.015_265)] rounded-[14px] p-4">
              <div className="text-2xl font-bold">{usage.aggregate.avg_latency_ms}ms</div>
              <div className="text-xs text-[oklch(58%_0.01_265)]">avg latency</div>
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {usage.recent.map((r) => (
              <div key={r.id} className="text-sm text-[oklch(80%_0.005_265)] flex justify-between">
                <span>{r.username} · {r.operation}</span>
                <span className="text-[oklch(58%_0.01_265)]">${r.cost_usd.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Manual verification**

Log in as `super_admin`, visit `/app/admin/ai`, select an org with real AI usage, confirm the aggregate numbers and recent calls list match what the existing org-owner-scoped `/settings` usage page shows for the same org.

- [ ] **Step 6: Build check**

Run: `cd frontend && npm run build` — expect zero errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/admin.py frontend/src/lib/api.ts frontend/src/app/app/admin/ai/page.tsx
git commit -m "backend+frontend: V2 Admin AI usage (super_admin-scoped ai-usage route)"
```

---

### Task 12: Map + Agents placeholder pages

**Files:**
- Create: `frontend/src/app/app/map/page.tsx`
- Create: `frontend/src/app/app/agents/page.tsx`

- [ ] **Step 1: Implement both as thin wrappers around `ComingSoon`**

```tsx
// frontend/src/app/app/map/page.tsx
import { ComingSoon } from "@/components/v2/ComingSoon";
export default function MapPageV2() {
  return <ComingSoon title="Camera map" />;
}
```

```tsx
// frontend/src/app/app/agents/page.tsx
import { ComingSoon } from "@/components/v2/ComingSoon";
export default function AgentsPageV2() {
  return <ComingSoon title="Agents" />;
}
```

- [ ] **Step 2: Manual verification**

Visit `/app/map` and `/app/agents`, confirm the "coming soon" placeholder renders (not a 404), sidebar nav links to both work.

- [ ] **Step 3: Build check**

Run: `npm run build` — expect zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/app/map frontend/src/app/app/agents
git commit -m "frontend: V2 Map/Agents coming-soon placeholders"
```

---

## Self-Review

**Spec coverage:** every in-scope view from `2026-08-13-frontend-v2-shell-design.md`'s scope table is covered — Home (Task 2), Cameras/Camera Detail (Tasks 3–4), Chat (Task 5), Playback (Task 6), Activity (Task 7), Digests (Task 8), Settings (Task 9), Admin Overview/Accounts (Task 10), Admin AI (Task 11). Map/Agents placeholders (Task 12) per spec's explicit "coming soon, not 404" requirement. Flag mechanism (Task 1) matches the spec's env-var approach.

**Placeholder scan:** no TBD/TODO; every code step has real, complete code. `ComingSoon` is a legitimate placeholder component per the approved design, not a plan-authoring shortcut.

**Type consistency:** `ActivityRow`'s prop signature (`{event, cameraName}`) is defined once in Task 2 and reused identically in Tasks 4 and 7. `AppShellV2`/`isNewUiEnabled` defined in Task 1, consumed correctly by the `(v2)`→`/app` layout in every subsequent task (no task creates a second competing shell).

**Note on route structure deviation:** the original spec's "Open Questions" flagged the exact route structure as an implementation-plan-level decision — Task 1 resolved it to a real `/app` directory (not a route group) specifically to avoid colliding with the existing public marketing page at `/`. This is a legitimate implementation-plan-level resolution of a spec-flagged open question, not a scope deviation.
