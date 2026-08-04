# Design-system snapshot package

**Date:** 2026-08-03
**Status:** approved for implementation

## Problem

`frontend/` has no standalone, buildable component library — it's a single Next.js app. `components/ui/` has only 3 files; the rest of the reusable UI lives scattered across `components/shared/`, `components/layout/`, `components/cameras/`, `components/digests/`, tightly coupled to the app (routing, live API client, Zustand stores, WebSocket hooks). This blocks using the `/design-sync` skill, which requires a repo shaped like an independently buildable component package (or one with Storybook) to bundle into Claude Design.

## Goal

Create `design-system/`, a new standalone npm package at the repo root, containing a **snapshot** of Nightwatch's real UI components and design tokens, decoupled enough to build and render outside the Next.js app. It exists specifically to be fed into `/design-sync` afterward (a separate, later step — not part of this work).

This is explicitly a **snapshot, not a source of truth**: `frontend/` keeps its own copies of every component and is not changed to import from this package. The two will drift over time; re-running this extraction is the expected way to refresh the snapshot later, not an ongoing sync.

## Component inventory

All 16 real components in `frontend/src/components/` (confirmed by inventory — `components/dashboard/`, `components/alerts/`, `components/events/` are empty directories and are not part of this work):

| Group | Components |
|---|---|
| `ui/` | Skeleton, button, sonner |
| `shared/` | severity-badge, status-dot, help-widget, chat-panel |
| `layout/` | sidebar, app-shell |
| `cameras/` | CameraTile, SequenceEditor, WebRTCPlayer, ZonesEditor |
| `digests/` | DigestCard, DigestSettings, RangePicker |

Every component is copied byte-for-byte into `design-system/src/components/<group>/` in the same grouping. No edits to component source — imports stay exactly as they are in the original (`@/lib/api`, `@/lib/store`, `next/link`, etc.).

## Decoupling strategy: path-alias shims

10 of the 16 components import app-specific modules that don't exist outside `frontend/`:
- `next/link`, `next/navigation` (`useRouter`, `usePathname`)
- `@/lib/api` — live HTTP client
- `@/lib/store` — Zustand auth store
- `@/lib/tour`, `@/lib/chatPanelState`, `@/lib/chatSeed`, `@/lib/chatContext`
- `@/lib/useEventsSocket` — live WebSocket hook
- `@tanstack/react-query` — real dependency, works standalone, no shim needed

Rather than edit any copied component, `design-system`'s own `tsconfig.json` and `tsup` build alias these import paths to local shim modules under `design-system/src/shims/`:

- `design-system/src/shims/next/link.tsx` — thin wrapper rendering a plain `<a>`
- `design-system/src/shims/next/navigation.ts` — `usePathname()` returns a fixed static path, `useRouter()` returns no-op `push`/`replace`
- `design-system/src/shims/lib/api.ts` — same method names/signatures as the real `ApiClient`, each resolving with small realistic sample data (a handful of cameras, events, a digest) instead of calling `fetch`
- `design-system/src/shims/lib/store.ts` — real Zustand store, same shape as `useAuthStore`, pre-seeded with a sample user instead of reading `localStorage`
- `design-system/src/shims/lib/chatPanelState.ts`, `chatSeed.ts`, `chatContext.ts` — real Zustand stores, same shape, seeded with sample/empty state
- `design-system/src/shims/lib/tour.ts` — no-op `startOnboardingTour`/`shouldShowTour`
- `design-system/src/shims/lib/useEventsSocket.ts` — no-op hook, never fires
- `design-system/src/shims/lib/utils.ts` — the real `cn()` helper (no app coupling, copied verbatim, not stubbed)
- `design-system/src/types/index.ts` — the real `types/index.ts`, copied verbatim (pure interfaces, no coupling)

**Known-risk component:** `WebRTCPlayer` opens a real `RTCPeerConnection` against `api`. It's included per scope, but is expected to only get `/design-sync`'s basic functional treatment rather than a rich preview later — no fake WebRTC handshake will be built to make it preview-perfect.

## Tokens and fonts

- `design-system/src/styles/tokens.css` — the `:root`/`.dark` CSS custom properties, severity colors, and `@layer utilities` motion classes (`pulse-live`, `fade-up`, `card-lift`, `event-flash`) extracted from `frontend/src/app/globals.css`.
- Fonts (Inter, Space Grotesk, JetBrains Mono) are loaded today via `next/font/google`, which doesn't work outside Next. Pull them as real font files via `@fontsource/inter`, `@fontsource/space-grotesk`, `@fontsource/jetbrains-mono` and declare `@font-face` in the package's own stylesheet — real shipped font files, not a CDN link or a fallback-stack approximation.

## Styling build

Components use Tailwind utility classes with literal hex arbitrary values (e.g. `bg-[#111111]`), not themed Tailwind config tokens. `design-system` gets its own minimal Tailwind v4 + PostCSS build, content-scanning `src/components/**`, producing `dist/styles.css` which imports `tokens.css`. This reproduces the real rendered output without depending on `frontend/`'s build.

## Package shape

```
design-system/
  package.json           # name "@nightwatch/design-system", private, main/module/types → dist/
  tsconfig.json           # path aliases: @/lib/* -> src/shims/lib/*, @/types -> src/types, next/link -> src/shims/next/link
  tsup.config.ts          # entry src/index.ts, format esm+cjs, dts on, mirrors tsconfig aliases
  postcss.config.mjs
  tailwind.config.ts      # (or v4 CSS-based config) content: src/components/**
  src/
    index.ts              # barrel: export every one of the 16 components
    components/
      ui/            Skeleton.tsx, button.tsx, sonner.tsx
      shared/        severity-badge.tsx, status-dot.tsx, help-widget.tsx, chat-panel.tsx
      layout/        sidebar.tsx, app-shell.tsx
      cameras/       CameraTile.tsx, SequenceEditor.tsx, WebRTCPlayer.tsx, ZonesEditor.tsx
      digests/       DigestCard.tsx, DigestSettings.tsx, RangePicker.tsx
    shims/
      next/          link.tsx, navigation.ts
      lib/            api.ts, store.ts, tour.ts, chatPanelState.ts, chatSeed.ts, chatContext.ts, useEventsSocket.ts, utils.ts
    types/index.ts
    styles/
      tokens.css
      globals.css      # Tailwind entry, imports tokens.css
```

**Dependencies**
- Peers: `react`, `react-dom`
- Real deps (used by copied components, no app coupling): `clsx`, `class-variance-authority`, `tailwind-merge`, `lucide-react`, `zustand`, `@tanstack/react-query`, `date-fns`, `driver.js`
- Dev deps: `tsup`, `typescript`, `tailwindcss`, `@tailwindcss/postcss`, `@fontsource/inter`, `@fontsource/space-grotesk`, `@fontsource/jetbrains-mono`

## Verification / done criteria

- `cd design-system && npm install && npm run build` completes with no errors and produces `dist/index.js`, `dist/index.d.ts`, `dist/styles.css`.
- A minimal smoke test (a throwaway `.tsx` file or a bare Vite/React harness, not committed as a permanent test suite) renders each of the 16 exported components with sample props without throwing — confirms every shim resolves and no component reaches for `window`/`fetch`/router context that isn't stubbed.
- No changes made to `frontend/` — this is purely additive at the repo root.

## Explicitly out of scope

- Running `/design-sync` against `design-system/` — a separate, later, explicitly-invoked step.
- Making `frontend/` import from `design-system/` — snapshot only, per decision above.
- Storybook, visual regression tooling, or a component picker UI — not needed for a design-sync source package.
- Fixing `WebRTCPlayer` to render a meaningful live preview outside a real WebRTC context.
