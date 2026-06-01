# Nightwatch Frontend — Development Rules

## What's Already Built (Current State)

### Completed
- **Project scaffold:** Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui (button, card, badge, input, select, table, tabs, dialog, dropdown-menu, separator, switch, textarea, sonner)
- **Design system:** Full dark theme CSS vars in globals.css (#0D0D0D bg, #1E90FF accent), Comic Relief font, custom severity colors, driver.js tour popover dark styling
- **Auth flow:** Login page (username + password), signup page (username + password + name + org), Zustand persist store (localStorage), API client token management, logout with server-side session revocation
- **Dashboard page:** Stats row (events today, critical count, cameras online, FP rate), real-time event feed (10s refetch), camera health grid with status dots, auto-starts onboarding tour on first login
- **Events page:** Paginated event list with filters (event type, severity), inline approve/reject feedback buttons, pagination controls, timestamp + confidence + description display
- **Cameras page:** Camera grid with status/config display, add camera form (RTSP pull + RTMP push modes), event type checkboxes, sensitivity selector, stream key display for push mode, delete camera
- **Alerts page:** Alert rules list with enable/disable toggle, create rule form (name, severity, channels, contacts, cooldown), delete rule
- **Sidebar:** Navigation with data-tour attributes, super_admin badge, "Quick Tour" replay button, username display, logout button (calls API + clears store)
- **Onboarding tour (driver.js):** 11-step guided walkthrough covering: welcome, how it works, camera connection (RTSP + RTMP explained), detection types, sensitivity, alerts, events feedback, dashboard monitoring. Auto-triggers on first login, localStorage flag prevents re-show
- **Help widget:** Floating chat bubble (bottom-right), 6 quick-action topics (camera not connecting, no events, no alerts, stream dropping, false positives, RTSP URL guide), keyword matching for free-text queries, formatted responses (bold, code blocks), typing indicator, dark themed
- **Shared components:** SeverityBadge (color-coded), StatusDot (green/gray/red), HelpWidget
- **API client (lib/api.ts):** Typed methods for all backend endpoints (auth, cameras, events, alerts, sites), token management, error handling
- **Types (types/index.ts):** Full TypeScript interfaces matching backend schemas (User, Organization, Site, Camera, Event, AlertRule, etc.)
- **Build:** `npm run build` passes with zero type errors, all 6 routes compile

### Not Yet Built (Planned)
- Event detail page (/events/[id]) with full snapshot viewer, clip player, AI reasoning
- Zone drawing tool (canvas on camera frame for defining detection areas)
- Site management page
- Settings/team management page
- Admin page (super_admin: orgs list, users list, change passwords)
- WebSocket real-time connection (currently polling with refetchInterval)
- Loading skeletons (currently shows "Loading..." text)
- Error boundaries and toast notifications
- Mobile responsive layout adjustments
- Analytics/charts page (event trends, heatmaps)
- Search (full-text across events)

## Identity
- **Service:** Web Dashboard
- **Framework:** Next.js 14+ (App Router)
- **Language:** TypeScript (strict)
- **Styling:** Tailwind CSS + shadcn/ui components
- **State:** Zustand (client) + TanStack Query (server)

## Design System

### Theme (Dark Only — No Light Mode)
- Background: `#0D0D0D` (page), `#111111` (cards), `#1A1A1A` (elevated/hover)
- Text: `#F5F5F5` (primary), `#A3A3A3` (secondary), `#666666` (muted)
- Accent: `#1E90FF` (buttons, links, active states), `#3BA0FF` (hover)
- Border: `#2A2A2A`
- Input bg: `#1F1F1F`
- Severity: green `#4ADE80`, amber `#FBBF24`, orange `#F97316`, red `#EF4444`
- Font: "Comic Relief" (Google Fonts), monospace: system default

### Component Rules
- Use shadcn/ui as base — override with Nightwatch colors via CSS variables
- Cards: `bg-[#111111] border border-[#2A2A2A] rounded-lg`
- Buttons primary: `bg-[#1E90FF] text-white hover:bg-[#3BA0FF]`
- Buttons secondary: `bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A]`
- Inputs: `bg-[#1F1F1F] border border-[#2A2A2A] focus:border-[#1E90FF]`
- All interactive elements need `transition-colors` for smooth hover
- Border radius: `rounded-lg` (cards), `rounded-md` (buttons/inputs)

## Architecture Rules

### Routing & Layout
- App Router (not Pages Router)
- Each authenticated route has its own layout with `Sidebar` + `HelpWidget`
- Auth guard in layout: redirect to `/login` if no token in store
- `api.setToken(token)` called in layout `useEffect` before any data fetching

### Auth
- Login with **username + password** (not email)
- Backend returns encrypted opaque token (NOT JWT — can't decode client-side)
- Token stored in Zustand store with `persist` middleware (localStorage)
- On logout: call `POST /api/auth/logout` (server revokes session) THEN clear store
- Never display or log the token value

### Data Fetching
- ALL server data via TanStack Query (`useQuery`, `useMutation`)
- Query keys: `["resource"]` or `["resource", id]` or `["resource", filters...]`
- Mutations invalidate related queries on success
- `refetchInterval` for live data: events feed (10s), stats (30s)
- Optimistic updates for feedback (approve/reject) — revert on failure
- Never fetch in `useEffect` — always via TanStack Query hooks

### API Client (`lib/api.ts`)
- Single `ApiClient` class — singleton exported as `api`
- Token set via `api.setToken()` — included as `Authorization: Bearer <token>` header
- All methods are typed with request/response generics
- Throw on non-2xx (error detail from JSON body)
- Never construct URLs manually — always relative paths from `BASE_URL`

### State Management
- **Server state:** TanStack Query (caching, refetching, optimistic updates)
- **Client state:** Zustand (auth, UI state like sidebar open, current site)
- NEVER duplicate server state in Zustand — let TanStack Query own it
- NEVER use `useState` for data that should survive navigation — use Zustand or URL params

### Components
- `"use client"` directive on all interactive components
- Server components only for static layout shells (if any)
- Shared components in `components/shared/` (SeverityBadge, StatusDot, HelpWidget)
- Page-specific components inline in the page file (unless reused)
- No prop drilling beyond 2 levels — use context or Zustand

### Live View & Camera Pages
- `/cameras` is now a 2x2 / 3x3 grid of camera tiles; click a tile → `/cameras/[id]` single view.
- Single-camera view shows the live snapshot + a filtered feed of events for that camera.
- Live view is **snapshot polling, NOT real video**: fetch `GET /api/cameras/{id}/latest-frame` (returns a signed URL) and render in `<img>`, refreshing every 1–2s. Do NOT add HLS, WebRTC, or RTSP players in the MVP.
- Persistent right-side chat panel mounted in the authenticated layout: tabs **Events** (WebSocket live stream) + **Ask** (Gemini Q&A scoped to camera/event); collapsible; toggle with **Ctrl/Cmd+K**.

### Help & Onboarding
- Tour (driver.js): auto-starts on first login, replay via sidebar "Quick Tour" button
- Help widget: always visible bottom-right on all authenticated pages
- Help widget uses keyword matching against local knowledge base (no API calls)
- Tour completion stored in localStorage (`nightwatch-tour-completed`)

## Code Style
- TypeScript strict mode — no `any` types (use `unknown` + type guards)
- Prefer `interface` over `type` for object shapes
- All types in `types/index.ts` — shared across the app
- Component files: PascalCase (`SeverityBadge.tsx`) — route files: lowercase (`page.tsx`)
- Tailwind classes: use Nightwatch design tokens (hex values) not Tailwind defaults
- No inline styles except `fontFamily` on body (Comic Relief)
- No comments in components — code should be self-explanatory
- Event handlers: inline for simple (1 line), extracted for complex (>3 lines)

## File Layout
```
src/
├── app/
│   ├── layout.tsx          # Root: html, body, Providers, font
│   ├── page.tsx            # Redirect to /dashboard or /login
│   ├── providers.tsx       # QueryClientProvider
│   ├── globals.css         # Tailwind + dark theme vars + tour CSS
│   ├── login/page.tsx      # Username + password form
│   ├── dashboard/          # layout.tsx (sidebar+helpwidget) + page.tsx
│   ├── events/             # layout.tsx + page.tsx
│   ├── cameras/            # layout.tsx + page.tsx
│   └── alerts/             # layout.tsx + page.tsx
├── components/
│   ├── layout/sidebar.tsx
│   ├── shared/             # Reusable: severity-badge, status-dot, help-widget
│   └── ui/                 # shadcn/ui generated components
├── lib/
│   ├── api.ts              # API client (typed, token-managed)
│   ├── store.ts            # Zustand auth store
│   ├── tour.ts             # driver.js onboarding tour config
│   └── utils.ts            # cn() helper
└── types/
    └── index.ts            # All TypeScript interfaces
```

## Running
```bash
npm run dev    # http://localhost:3000
npm run build  # Verify no type errors
```

## Critical Rules
- NEVER use light mode colors — this is a dark-only UI
- NEVER store sensitive data in localStorage except the session token
- NEVER skip the auth guard in layouts — all data routes must be protected
- NEVER make API calls without setting the token first
- ALWAYS show loading skeletons while data is fetching (not blank pages)
- ALWAYS handle error states (show toast or inline error, not blank)
- ALWAYS invalidate queries after mutations (don't rely on stale cache)
- ALWAYS test with `npm run build` before committing (catches type errors)

@AGENTS.md
