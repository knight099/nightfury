# NIGHTWATCH — Frontend Plan

---

| Field | Value |
|-------|-------|
| **Plan Name** | Web Dashboard Frontend |
| **Version** | 1.0.0 |
| **Parent Plan** | MVP_PLAN.md |
| **Date Generated** | 2026-05-26 |
| **Estimated Effort** | 12 person-days |
| **Tech Stack** | Next.js 14 (App Router), TypeScript, Tailwind CSS, shadcn/ui |
| **Deployment** | GCP Cloud Run (or Vercel) |

---

## Objective

Build the web dashboard where clients manage cameras, view real-time events, configure alert rules, provide feedback on detections, and monitor system health. Dark theme, responsive, real-time via WebSocket.

---

## Design System

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        NIGHTWATCH DESIGN TOKENS                          │
│                                                                           │
│  COLORS                                                                   │
│  ─────────────────────────────────────────────────────────────────────── │
│  Background:                                                              │
│    --bg-base:     #0D0D0D   (page background)                           │
│    --bg-card:     #111111   (card/panel surfaces)                        │
│    --bg-elevated: #1A1A1A   (modals, dropdowns, hover states)           │
│    --bg-input:    #1F1F1F   (form inputs)                               │
│    --border:      #2A2A2A   (subtle borders)                            │
│                                                                           │
│  Text:                                                                    │
│    --text-primary:   #F5F5F5  (headings, primary content)               │
│    --text-secondary: #A3A3A3  (labels, descriptions)                    │
│    --text-muted:     #666666  (disabled, timestamps)                    │
│                                                                           │
│  Accent:                                                                  │
│    --accent:         #1E90FF  (buttons, links, active states)           │
│    --accent-hover:   #3BA0FF  (hover)                                   │
│    --accent-muted:   #1E90FF20 (backgrounds with accent tint)           │
│                                                                           │
│  Severity:                                                                │
│    --severity-low:      #4ADE80  (green)                                │
│    --severity-medium:   #FBBF24  (amber)                                │
│    --severity-high:     #F97316  (orange)                                │
│    --severity-critical: #EF4444  (red)                                  │
│                                                                           │
│  Status:                                                                  │
│    --status-online:  #4ADE80                                             │
│    --status-offline: #666666                                             │
│    --status-error:   #EF4444                                             │
│                                                                           │
│  TYPOGRAPHY                                                               │
│  ─────────────────────────────────────────────────────────────────────── │
│  Font family: "Comic Relief", system-ui, sans-serif                      │
│  Mono: "JetBrains Mono", monospace (timestamps, IDs)                    │
│                                                                           │
│  Scale:                                                                   │
│    H1: 1.875rem / 700   (page titles)                                   │
│    H2: 1.5rem / 600     (section headers)                               │
│    H3: 1.125rem / 600   (card titles)                                   │
│    Body: 0.875rem / 400  (default text)                                 │
│    Small: 0.75rem / 400  (metadata, timestamps)                         │
│                                                                           │
│  SPACING                                                                  │
│  ─────────────────────────────────────────────────────────────────────── │
│  Base unit: 4px                                                           │
│  Page padding: 24px                                                       │
│  Card padding: 16px                                                       │
│  Card gap: 16px                                                           │
│  Section gap: 24px                                                        │
│                                                                           │
│  BORDERS                                                                  │
│  ─────────────────────────────────────────────────────────────────────── │
│  Radius: 8px (cards), 6px (buttons/inputs), 4px (tags/badges)           │
│  Width: 1px (default), 2px (focus rings)                                │
│                                                                           │
│  COMPONENTS (shadcn/ui dark overrides)                                   │
│  ─────────────────────────────────────────────────────────────────────── │
│  Button primary: bg-accent, text-white, hover:bg-accent-hover           │
│  Button secondary: bg-elevated, text-secondary, border                   │
│  Input: bg-input, border, focus:ring-accent                              │
│  Card: bg-card, border, radius-8                                         │
│  Badge: rounded-full, px-2, py-0.5, text-xs                            │
│  Table row hover: bg-elevated                                            │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     FRONTEND ARCHITECTURE                                 │
│                                                                           │
│  Next.js 14 (App Router)                                                 │
│  ├── Server Components (initial page loads, SEO-irrelevant but fast)    │
│  ├── Client Components (interactive: forms, real-time feed, maps)       │
│  └── Route Handlers (proxy to backend if needed)                        │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                     STATE MANAGEMENT                                  ││
│  │                                                                       ││
│  │  Server State: TanStack Query v5                                     ││
│  │  • API data fetching, caching, background refetch                    ││
│  │  • Optimistic updates for feedback                                    ││
│  │  • Infinite scroll pagination for events                             ││
│  │                                                                       ││
│  │  Client State: Zustand (minimal)                                     ││
│  │  • Current site selection                                             ││
│  │  • UI state (sidebar open, active filters)                           ││
│  │  • WebSocket connection state                                         ││
│  │                                                                       ││
│  │  Real-time: WebSocket (native)                                       ││
│  │  • Live event feed                                                    ││
│  │  • Camera status updates                                              ││
│  │  • Alert counters                                                     ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                     KEY LIBRARIES                                     ││
│  │                                                                       ││
│  │  • shadcn/ui — component primitives (dark themed)                    ││
│  │  • Lucide React — icons                                               ││
│  │  • Recharts — analytics charts                                        ││
│  │  • date-fns — date formatting                                         ││
│  │  • react-hook-form + zod — form handling + validation                ││
│  │  • nuqs — URL search params state (filters)                          ││
│  │  • Konva (react-konva) — canvas zone drawing                         ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
frontend/
├── src/
│   ├── app/
│   │   ├── layout.tsx                 # Root layout: sidebar + main content
│   │   ├── page.tsx                   # Redirect to /dashboard
│   │   ├── (auth)/
│   │   │   ├── login/page.tsx
│   │   │   ├── signup/page.tsx
│   │   │   └── layout.tsx            # Auth pages: centered, no sidebar
│   │   ├── (app)/                     # Authenticated routes
│   │   │   ├── layout.tsx            # App shell: sidebar + topbar
│   │   │   ├── dashboard/page.tsx
│   │   │   ├── events/
│   │   │   │   ├── page.tsx          # Event list with filters
│   │   │   │   └── [id]/page.tsx     # Event detail
│   │   │   ├── cameras/
│   │   │   │   ├── page.tsx          # Camera grid
│   │   │   │   ├── new/page.tsx      # Add camera flow
│   │   │   │   └── [id]/page.tsx     # Camera detail + edit
│   │   │   ├── alerts/
│   │   │   │   ├── page.tsx          # Alert rules list
│   │   │   │   ├── new/page.tsx      # Create rule
│   │   │   │   └── history/page.tsx  # Sent alerts history
│   │   │   ├── sites/
│   │   │   │   └── page.tsx
│   │   │   └── settings/
│   │   │       ├── page.tsx          # General settings
│   │   │       └── users/page.tsx    # Team management
│   │   └── globals.css
│   │
│   ├── components/
│   │   ├── ui/                        # shadcn/ui components (generated)
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── input.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── dropdown-menu.tsx
│   │   │   ├── select.tsx
│   │   │   ├── table.tsx
│   │   │   ├── tabs.tsx
│   │   │   └── ...
│   │   ├── layout/
│   │   │   ├── sidebar.tsx            # Navigation sidebar
│   │   │   ├── topbar.tsx             # Site selector + user menu
│   │   │   └── mobile-nav.tsx
│   │   ├── dashboard/
│   │   │   ├── stats-row.tsx          # Summary counters
│   │   │   ├── event-feed.tsx         # Real-time scrolling feed
│   │   │   ├── camera-health-grid.tsx # Camera status cards
│   │   │   └── severity-chart.tsx     # Event distribution chart
│   │   ├── events/
│   │   │   ├── event-card.tsx         # Single event in list
│   │   │   ├── event-filters.tsx      # Filter bar
│   │   │   ├── event-detail.tsx       # Full event view
│   │   │   ├── feedback-buttons.tsx   # Approve/Reject/Reclassify
│   │   │   ├── clip-player.tsx        # Video player for event clips
│   │   │   └── snapshot-viewer.tsx    # Annotated snapshot display
│   │   ├── cameras/
│   │   │   ├── camera-card.tsx        # Camera in grid view
│   │   │   ├── camera-form.tsx        # Add/edit camera form
│   │   │   ├── zone-editor.tsx        # Canvas zone drawing tool
│   │   │   ├── event-type-picker.tsx  # Checkbox grid of event types
│   │   │   └── ingest-mode-picker.tsx # RTSP/RTMP mode selector
│   │   ├── alerts/
│   │   │   ├── rule-card.tsx          # Alert rule display
│   │   │   ├── rule-form.tsx          # Create/edit alert rule
│   │   │   └── contact-picker.tsx     # WhatsApp/email/webhook config
│   │   └── shared/
│   │       ├── severity-badge.tsx     # Color-coded severity tag
│   │       ├── status-indicator.tsx   # Online/offline dot
│   │       ├── timestamp.tsx          # Relative + absolute time
│   │       ├── empty-state.tsx        # No data illustrations
│   │       ├── loading-skeleton.tsx
│   │       └── error-boundary.tsx
│   │
│   ├── lib/
│   │   ├── api.ts                     # API client (fetch wrapper with auth)
│   │   ├── auth.ts                    # Firebase auth helpers
│   │   ├── websocket.ts              # WebSocket connection manager
│   │   ├── utils.ts                   # cn(), formatDate, etc.
│   │   └── constants.ts              # Event types, severities, etc.
│   │
│   ├── hooks/
│   │   ├── use-events.ts             # TanStack Query: events list, detail
│   │   ├── use-cameras.ts            # TanStack Query: cameras CRUD
│   │   ├── use-alerts.ts             # TanStack Query: alert rules
│   │   ├── use-realtime.ts           # WebSocket hook: live events
│   │   ├── use-auth.ts               # Auth state + user info
│   │   └── use-site.ts              # Current site selection
│   │
│   ├── stores/
│   │   └── app-store.ts             # Zustand: UI state
│   │
│   └── types/
│       ├── event.ts                   # Event, DetectedEvent types
│       ├── camera.ts                  # Camera, CameraConfig types
│       ├── alert.ts                   # AlertRule, AlertHistory types
│       └── user.ts                    # User, Org types
│
├── public/
│   ├── logo.svg
│   └── favicon.ico
│
├── next.config.ts
├── tailwind.config.ts
├── tsconfig.json
├── package.json
└── .env.local.example
```

---

## Page Specifications

### 1. Dashboard (`/dashboard`)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ┌───────┐                                                                │
│ │       │  ┌─────────────────────────────────────────────────────────┐  │
│ │  N    │  │ Topbar: [Site: All Sites ▾]        [🔔 3] [User ▾]     │  │
│ │  A    │  └─────────────────────────────────────────────────────────┘  │
│ │  V    │                                                                │
│ │       │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐                        │
│ │  S    │  │  47  │ │   3  │ │   8  │ │  12% │                        │
│ │  I    │  │Events│ │Crit. │ │Online│ │ FP%  │                        │
│ │  D    │  │Today │ │Alerts│ │Cams  │ │Rate  │                        │
│ │  E    │  └──────┘ └──────┘ └──────┘ └──────┘                        │
│ │  B    │                                                                │
│ │  A    │  ┌─────────────────────────────────────────────────────────┐  │
│ │  R    │  │ LIVE EVENT FEED (WebSocket-powered, auto-scroll)        │  │
│ │       │  │                                                           │  │
│ │       │  │ ● 22:15:03  Cam: Loading Dock                           │  │
│ │       │  │   INTRUSION — HIGH — 89%                                │  │
│ │       │  │   "Person entered restricted area"                       │  │
│ │       │  │   [View] [✓] [✗]                                        │  │
│ │       │  │ ─────────────────────────────────────────────────        │  │
│ │       │  │ ● 22:14:51  Cam: Main Entrance                          │  │
│ │       │  │   PERSON — LOW — 72%                                     │  │
│ │       │  │   "Person walking through entrance"                      │  │
│ │       │  │   [View] [✓] [✗]                                        │  │
│ │       │  │ ─────────────────────────────────────────────────        │  │
│ │       │  │ ...                                                       │  │
│ │       │  └─────────────────────────────────────────────────────────┘  │
│ │       │                                                                │
│ │       │  ┌─────────────────────────────────────────────────────────┐  │
│ │       │  │ CAMERAS (mini grid)                                      │  │
│ │       │  │ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐            │  │
│ │       │  │ │●Cam│ │●Cam│ │●Cam│ │○Cam│ │●Cam│ │●Cam│            │  │
│ │       │  │ │ 1  │ │ 2  │ │ 3  │ │ 4  │ │ 5  │ │ 6  │            │  │
│ │       │  │ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘            │  │
│ │       │  └─────────────────────────────────────────────────────────┘  │
│ └───────┘                                                                │
└─────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Stats row refreshes every 30s (TanStack Query refetchInterval)
- Event feed is WebSocket-driven: new events appear at top with animation
- Quick feedback: approve/reject buttons inline without navigating away
- Camera grid shows live status (online/offline dot)
- Click event → navigates to `/events/[id]`
- Click camera → navigates to `/cameras/[id]`

### 2. Event Detail (`/events/[id]`)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ← Back to Events                                                        │
│                                                                           │
│  ┌───────────────────────────────┐  ┌────────────────────────────────┐  │
│  │                               │  │                                │  │
│  │   [ANNOTATED SNAPSHOT]        │  │  Event Type: INTRUSION         │  │
│  │   (bounding boxes overlaid)   │  │  Severity: ●●● HIGH           │  │
│  │   (click to zoom)             │  │  Confidence: 89%               │  │
│  │                               │  │  Camera: Loading Dock Cam 1    │  │
│  │                               │  │  Site: Warehouse Mumbai        │  │
│  │                               │  │  Time: 22:15:03 IST            │  │
│  └───────────────────────────────┘  │  (May 26, 2026)                │  │
│                                      │                                │  │
│  ┌───────────────────────────────┐  │  AI Description:               │  │
│  │  ▶ PLAY CLIP (10 seconds)    │  │  "A person entered the         │  │
│  │  [video player with controls] │  │   restricted loading dock      │  │
│  │                               │  │   area after business hours."  │  │
│  └───────────────────────────────┘  │                                │  │
│                                      │  Zone: Loading Dock Area       │  │
│                                      └────────────────────────────────┘  │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │  FEEDBACK                                                             ││
│  │                                                                       ││
│  │  Was this alert correct?                                             ││
│  │                                                                       ││
│  │  [✓ Approve — Correct detection]                                    ││
│  │  [✗ Reject — False positive]                                        ││
│  │  [↻ Reclassify — Wrong type: [select correct type ▾]]              ││
│  │                                                                       ││
│  │  Status: ● Approved by John (May 26, 22:18)                         ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

### 3. Add Camera (`/cameras/new`)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Add Camera                                                              │
│                                                                           │
│  ┌─── Step 1: Basic Info ─────────────────────────────────────────────┐ │
│  │  Camera Name: [____________________________]                        │ │
│  │  Site: [Select site ▾]                                              │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─── Step 2: How to Connect ─────────────────────────────────────────┐ │
│  │                                                                      │ │
│  │  ┌─────────────────────┐  ┌─────────────────────────────────────┐  │ │
│  │  │ ○ I'll provide URL  │  │ ○ Give me an endpoint to push to   │  │ │
│  │  │                     │  │                                     │  │ │
│  │  │ You have a public   │  │ Your NVR can push RTMP/SRT to a    │  │ │
│  │  │ RTSP URL or have    │  │ remote server. We'll give you the  │  │ │
│  │  │ set up port         │  │ URL and stream key.                 │  │ │
│  │  │ forwarding.         │  │                                     │  │ │
│  │  └─────────────────────┘  └─────────────────────────────────────┘  │ │
│  │                                                                      │ │
│  │  [If RTSP selected:]                                                │ │
│  │  RTSP URL: [rtsp://________________________________]                │ │
│  │  [Test Connection]  ● Connected (720p, 25fps)                       │ │
│  │                                                                      │ │
│  │  [If Push selected:]                                                │ │
│  │  Your ingest endpoint: rtmp://ingest.nightwatch.ai/live             │ │
│  │  Stream key: nw_cam_a8f3k2m9... [Copy]                             │ │
│  │  Status: Waiting for stream...                                       │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─── Step 3: What to Detect ─────────────────────────────────────────┐ │
│  │                                                                      │ │
│  │  Select event types to monitor:                                      │ │
│  │                                                                      │ │
│  │  ☑ Person Detected     ☑ Intrusion (zone entry)                    │ │
│  │  ☑ Vehicle Detected    ☐ Loitering (>2 min)                        │ │
│  │  ☐ Crowd Spike         ☐ Fire / Smoke                              │ │
│  │  ☐ PPE Violation       ☐ Object Left Behind                        │ │
│  │                                                                      │ │
│  │  Sensitivity: [Low ○] [● Medium] [○ High]                          │ │
│  │  Low: fewer alerts, only high confidence                             │ │
│  │  High: more alerts, catches more but may have false positives       │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  ┌─── Step 4: Detection Zones (Optional) ─────────────────────────────┐ │
│  │                                                                      │ │
│  │  ┌──────────────────────────────────┐  Zones:                       │ │
│  │  │                                  │  ┌────────────────────┐       │ │
│  │  │  [Camera frame snapshot]         │  │ + Zone A (drawn)   │       │ │
│  │  │   ┌─── Zone A ───┐              │  │ + Add Zone         │       │ │
│  │  │   │  (polygon     │              │  └────────────────────┘       │ │
│  │  │   │   drawn by    │              │                               │ │
│  │  │   │   user)       │              │  Draw on the frame to         │ │
│  │  │   └───────────────┘              │  define detection zones.      │ │
│  │  │                                  │  Events will include which    │ │
│  │  │                                  │  zone they occurred in.       │ │
│  │  └──────────────────────────────────┘                               │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│                                         [Cancel]  [Save Camera →]        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4. Alert Rules (`/alerts`)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Alert Rules                                          [+ New Rule]       │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ ● After-hours intrusion alert                          [Edit] [⋮]  ││
│  │   Events: intrusion, loitering │ Severity: HIGH+                    ││
│  │   Time: 22:00–06:00 │ Cameras: All                                 ││
│  │   Notify: WhatsApp (+91 987...), Email (sec@co.in)                  ││
│  │   Cooldown: 60s │ Triggered: 12 times this week                     ││
│  └─────────────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ ● All critical events                                  [Edit] [⋮]  ││
│  │   Events: All │ Severity: CRITICAL                                  ││
│  │   Time: 24/7 │ Cameras: All                                         ││
│  │   Notify: WhatsApp, Email, Webhook                                  ││
│  │   Cooldown: 30s │ Triggered: 3 times this week                      ││
│  └─────────────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ ○ Crowd alert (disabled)                               [Edit] [⋮]  ││
│  │   Events: crowd_spike │ Severity: MEDIUM+                           ││
│  │   Notify: WhatsApp                                                   ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                           │
│  ─────────────────────────────────────────────────────────────────────── │
│  Recent Alert History                         [View All →]               │
│                                                                           │
│  │ 22:15 │ WhatsApp → +91 987... │ Intrusion (Loading Dock) │ Sent ✓ │ │
│  │ 21:45 │ Email → sec@co.in     │ Crowd spike (Entrance)   │ Sent ✓ │ │
│  │ 20:30 │ Webhook → https://... │ Critical (Fire detect)   │ Failed ✗││
└─────────────────────────────────────────────────────────────────────────┘
```

### 5. Event History (`/events`)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Events                                                                  │
│                                                                           │
│  ┌─── Filters ────────────────────────────────────────────────────────┐ │
│  │ Date: [May 20] → [May 26]  Camera: [All ▾]  Type: [All ▾]       │ │
│  │ Severity: [All ▾]  Feedback: [All ▾]  Search: [___________] 🔍   │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                           │
│  47 events found                                     Sort: [Newest ▾]    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │ [thumb] │ 22:15 │ Loading Dock │ Intrusion │ HIGH │ 89% │ ✓ Appr. ││
│  ├─────────────────────────────────────────────────────────────────────┤│
│  │ [thumb] │ 22:14 │ Entrance     │ Person    │ LOW  │ 72% │ ○ Pend. ││
│  ├─────────────────────────────────────────────────────────────────────┤│
│  │ [thumb] │ 22:12 │ Parking      │ Vehicle   │ LOW  │ 81% │ ✗ Rej.  ││
│  ├─────────────────────────────────────────────────────────────────────┤│
│  │ [thumb] │ 22:10 │ Warehouse    │ Loitering │ MED  │ 76% │ ○ Pend. ││
│  ├─────────────────────────────────────────────────────────────────────┤│
│  │ ...                                                                  ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                           │
│  [← Prev]  Page 1 of 5  [Next →]                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## WebSocket Integration

```typescript
// lib/websocket.ts

class NightwatchWebSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnects = 10;
  private listeners: Map<string, Set<(data: any) => void>> = new Map();

  connect(token: string) {
    const url = `${process.env.NEXT_PUBLIC_WS_URL}/ws/events?token=${token}`;
    this.ws = new WebSocket(url);

    this.ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data);
      this.emit(data.type, data.payload);
    };

    this.ws.onclose = () => {
      this.reconnect(token);
    };
  }

  on(event: string, callback: (data: any) => void) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(callback);
    return () => this.listeners.get(event)!.delete(callback);
  }

  private emit(event: string, data: any) {
    this.listeners.get(event)?.forEach((cb) => cb(data));
  }

  private reconnect(token: string) {
    if (this.reconnectAttempts >= this.maxReconnects) return;
    setTimeout(() => {
      this.reconnectAttempts++;
      this.connect(token);
    }, Math.min(1000 * 2 ** this.reconnectAttempts, 30000));
  }
}

// hooks/use-realtime.ts
export function useRealtimeEvents() {
  const queryClient = useQueryClient();
  const { token } = useAuth();

  useEffect(() => {
    const ws = new NightwatchWebSocket();
    ws.connect(token);

    const unsub = ws.on("new_event", (event: Event) => {
      // Add to cache (prepend to events list)
      queryClient.setQueryData(["events"], (old: any) => ({
        ...old,
        events: [event, ...(old?.events || [])].slice(0, 50),
      }));
      // Update stats
      queryClient.invalidateQueries({ queryKey: ["events", "stats"] });
    });

    return () => { unsub(); ws.disconnect(); };
  }, [token]);
}
```

---

## API Client

```typescript
// lib/api.ts

const BASE_URL = process.env.NEXT_PUBLIC_API_URL;

class ApiClient {
  private token: string | null = null;

  setToken(token: string) { this.token = token; }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(this.token && { Authorization: `Bearer ${this.token}` }),
        ...options?.headers,
      },
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new ApiError(res.status, error.detail || "Request failed");
    }
    return res.json();
  }

  // Cameras
  getCameras(params?: { site_id?: string }) {
    const qs = new URLSearchParams(params as any).toString();
    return this.request<{ cameras: Camera[] }>(`/api/cameras?${qs}`);
  }
  createCamera(data: CreateCameraInput) {
    return this.request<{ camera: Camera; ingest_endpoint?: string; stream_key?: string }>(
      "/api/cameras", { method: "POST", body: JSON.stringify(data) }
    );
  }

  // Events
  getEvents(params: EventFilters) {
    const qs = new URLSearchParams(params as any).toString();
    return this.request<{ events: Event[]; total: number; pages: number }>(`/api/events?${qs}`);
  }
  getEvent(id: string) {
    return this.request<{ event: Event }>(`/api/events/${id}`);
  }
  submitFeedback(id: string, data: FeedbackInput) {
    return this.request(`/api/events/${id}/feedback`, { method: "POST", body: JSON.stringify(data) });
  }

  // Alert Rules
  getAlertRules() {
    return this.request<{ rules: AlertRule[] }>("/api/alerts/rules");
  }
  createAlertRule(data: CreateAlertRuleInput) {
    return this.request<AlertRule>("/api/alerts/rules", { method: "POST", body: JSON.stringify(data) });
  }

  // Stats
  getEventStats(params: { period: string; site_id?: string }) {
    const qs = new URLSearchParams(params as any).toString();
    return this.request<EventStats>(`/api/events/stats?${qs}`);
  }
}

export const api = new ApiClient();
```

---

## Zone Editor Component

```typescript
// components/cameras/zone-editor.tsx
// Uses react-konva for canvas polygon drawing

interface ZoneEditorProps {
  snapshotUrl: string;  // Camera frame to draw on
  zones: Zone[];
  onChange: (zones: Zone[]) => void;
}

// User interaction:
// 1. Click "Add Zone" → enter zone name
// 2. Click points on camera frame to draw polygon vertices
// 3. Double-click to close polygon
// 4. Polygon displayed as semi-transparent overlay with name label
// 5. Click existing zone to select → drag vertices to adjust → delete button
// 6. Zones stored as array of {name, points: [[x,y]...]} in camera config
```

---

## Key UX Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Navigation | Left sidebar (collapsible) | Standard SaaS pattern, works on desktop |
| Event feed | Auto-scroll with pause on hover | Users need to see new events but also read current ones |
| Feedback | Inline buttons (no modal) | Reduce friction — one click to approve/reject |
| Filters | URL params (nuqs) | Shareable URLs, browser back button works |
| Loading | Skeleton screens | Better perceived performance than spinners |
| Errors | Toast notifications | Non-blocking, auto-dismiss after 5s |
| Mobile | Responsive (not separate app for MVP) | Ship faster, mobile app is post-MVP |
| Theme | Dark only (no light mode for MVP) | Matches surveillance context, ship faster |
| Auth | Firebase Auth (email + Google) | Fast to implement, handles edge cases |

---

## Configuration

```typescript
// next.config.ts
const nextConfig = {
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: 'storage.googleapis.com' },  // GCS snapshots
    ],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL,
    NEXT_PUBLIC_FIREBASE_CONFIG: process.env.NEXT_PUBLIC_FIREBASE_CONFIG,
  },
};
```

```typescript
// tailwind.config.ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#0D0D0D",
        card: "#111111",
        elevated: "#1A1A1A",
        input: "#1F1F1F",
        border: "#2A2A2A",
        foreground: "#F5F5F5",
        muted: "#A3A3A3",
        accent: {
          DEFAULT: "#1E90FF",
          hover: "#3BA0FF",
          muted: "rgba(30, 144, 255, 0.12)",
        },
        severity: {
          low: "#4ADE80",
          medium: "#FBBF24",
          high: "#F97316",
          critical: "#EF4444",
        },
        status: {
          online: "#4ADE80",
          offline: "#666666",
          error: "#EF4444",
        },
      },
      fontFamily: {
        sans: ['"Comic Relief"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
```

---

## Implementation Order

| Day | Task |
|-----|------|
| 1 | Next.js project setup, Tailwind config, shadcn/ui init, design tokens, font setup |
| 2 | Layout: sidebar, topbar, routing structure, auth context |
| 3 | Firebase Auth: login page, signup page, auth guards, token management |
| 4 | API client + TanStack Query setup + types |
| 5 | Dashboard: stats row + camera health grid (static data first) |
| 6 | Dashboard: real-time event feed (WebSocket integration) |
| 7 | Events list page: filters, pagination, event cards |
| 8 | Event detail page: snapshot viewer, clip player, feedback buttons |
| 9 | Camera pages: list grid + add camera form (both ingest modes) |
| 10 | Camera: zone editor (react-konva polygon drawing on snapshot) |
| 11 | Alert rules: list + create/edit form (time window, contacts, channels) |
| 12 | Polish: loading states, error boundaries, empty states, responsive tweaks, deploy |

---

## Deployment

```dockerfile
# Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

Deploy to Cloud Run:
- Region: asia-south1
- CPU: 1, Memory: 512Mi
- Min instances: 1 (avoid cold starts)
- Custom domain: app.nightwatch.ai

Alternative: Vercel (simpler, auto-scaling, edge functions) — evaluate based on latency from India.

---

## Test Strategy

| Type | What | Tool |
|------|------|------|
| Component | Individual UI components render correctly | Vitest + React Testing Library |
| Integration | Pages render with mocked API data | Vitest + MSW (mock service worker) |
| E2E | Full user flows (login → add camera → view event → give feedback) | Playwright |
| Visual | Design consistency, responsive layouts | Playwright screenshots + manual review |

---

## Definition of Done

- [ ] Auth flow working: signup → login → protected dashboard
- [ ] Dashboard shows live event feed via WebSocket
- [ ] Events page: filterable, paginated, clickable to detail
- [ ] Event detail: snapshot, clip player, feedback buttons functional
- [ ] Camera add flow: both RTSP and push mode, event type selection
- [ ] Zone editor: draw polygons on camera snapshot, save to API
- [ ] Alert rules: create, edit, delete, toggle enabled/disabled
- [ ] Dark theme consistent across all pages (design tokens applied)
- [ ] Responsive: usable on tablet (1024px+), graceful on mobile
- [ ] Loading/error/empty states for all data-driven views
- [ ] Deployed and accessible via HTTPS
- [ ] Core flows tested with Playwright (login, view event, feedback)
