<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# Nightwatch Frontend — Agent Rules

## What's Already Built
- 6 pages: login, dashboard, events, cameras, alerts + root redirect
- Auth: username/password login + signup, Zustand persist, server-side logout
- Dashboard: stats row + event feed (10s poll) + camera grid + auto-starts tour on first login
- Events: paginated list, type/severity filters, inline approve/reject feedback
- Cameras: grid view, add form (RTSP pull + RTMP push), event type picker, sensitivity, delete
- Alerts: rules list with toggle, create form (severity, channels, contacts, cooldown), delete
- Onboarding tour: 11-step driver.js walkthrough (auto on first login, replay via sidebar)
- Help widget: floating chat (bottom-right), 6 troubleshooting topics, keyword matching, dark themed
- Full TypeScript types matching backend, typed API client, Zustand auth store
- Build passes with zero errors (`npm run build` verified)
- NOT yet done: event detail page, zone editor, WebSocket live feed, admin page, settings, mobile responsive, loading skeletons

## What This Service Does
Web dashboard for managing cameras, viewing events, configuring alerts, and providing feedback on AI detections. Dark-themed, real-time via WebSocket.

## Tech Stack
- Next.js 14+ (App Router), TypeScript (strict), Tailwind CSS, shadcn/ui
- State: TanStack Query v5 (server), Zustand (client/auth)
- Tour: driver.js, Help: custom chat widget with local knowledge base

## Key Decisions Already Made — Don't Change
- Dark mode ONLY (no light mode toggle)
- Username-based login (not email)
- Token is opaque (can't decode client-side — don't try to extract user info from it)
- Font: Comic Relief from Google Fonts
- Sidebar navigation (fixed left, 224px wide)
- Help widget always visible (bottom-right floating button)
- Tour auto-triggers on first login only (localStorage flag)

## Color Reference (Use These, Not Tailwind Defaults)
```
Page bg:      #0D0D0D
Card bg:      #111111
Elevated:     #1A1A1A
Input bg:     #1F1F1F
Border:       #2A2A2A
Text primary: #F5F5F5
Text secondary: #A3A3A3
Text muted:   #666666
Accent:       #1E90FF
Accent hover: #3BA0FF
Severity low:      #4ADE80
Severity medium:   #FBBF24
Severity high:     #F97316
Severity critical: #EF4444
```

## How to Add a New Page
1. Create `src/app/<route>/layout.tsx` — copy from events/layout.tsx (includes Sidebar + HelpWidget + auth guard)
2. Create `src/app/<route>/page.tsx` — "use client", fetch with TanStack Query
3. Add nav item in `components/layout/sidebar.tsx` (with `data-tour` attribute)
4. Add tour step in `lib/tour.ts` if relevant

## How to Add a New API Call
1. Add typed method to `lib/api.ts`
2. Add response type to `types/index.ts`
3. Use via `useQuery` or `useMutation` in the page component

## Auth Flow
```
Login page → POST /api/auth/login (username, password)
  → Receive { token, user }
  → api.setToken(token)
  → useAuthStore.setAuth(token, user)
  → redirect to /dashboard
  → Each layout checks token, calls api.setToken(token), renders page

Logout:
  → api.logout() (revokes server session)
  → useAuthStore.logout() (clears localStorage)
  → redirect to /login
```

## Data Fetching Pattern
```tsx
const { data, isLoading } = useQuery({
  queryKey: ["events", filters],
  queryFn: () => api.getEvents(filters),
  refetchInterval: 10000, // optional: live data
});
```

## Common Mistakes to Avoid
- Using Tailwind color utilities (like `bg-gray-900`) instead of hex values
- Fetching data in useEffect instead of useQuery
- Forgetting auth guard in new page layouts
- Not invalidating queries after mutations
- Using `"use server"` or Server Actions (we don't use them — all data via API client)
- Adding light mode styles or white backgrounds
- Storing server data in Zustand (use TanStack Query for that)
