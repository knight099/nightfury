# NIGHTWATCH — UI/UX Overhaul Plan

**Goal:** Make the dashboard attractive, friendly for non-technical users (home/
warehouse owners), and fully usable on phones. Dark-only theme stays. No new
backend work required — this is frontend-only.

---

## Audit summary (what's wrong today)

| Problem | Evidence |
|---|---|
| Not mobile-usable at all | Fixed `ml-56` sidebar + `pr-[360px]` chat panel in `app/*/layout.tsx`; only 4 files use any `sm:/md:/lg:` breakpoint |
| Hardcoded hex everywhere | `bg-[#111111]`, `text-[#A3A3A3]` repeated in every component instead of the CSS vars already defined in `globals.css` |
| Tech jargon for consumers | "RTSP pull", "stream key", "sensitivity", "FP rate", "cooldown" shown raw in forms and stats |
| Inconsistent loading/empty states | Skeleton component exists but unevenly applied; empty lists show nothing helpful |
| Flat visual hierarchy | Every card identical; no elevation, motion, or focal points; dashboard reads like a log viewer |
| Comic Relief font | Playful but hurts legibility and credibility for a security product (decision needed — listed as "don't change" in AGENTS.md) |

---

## Phase 1 — Mobile-first layout foundation (highest impact)

### 1.1 Responsive app shell (`components/layout/`)
- **Desktop (≥1024px):** keep fixed left sidebar (current behavior).
- **Tablet (768–1023px):** collapsible icon-rail sidebar (icons only, 64px,
  expand on hover/tap).
- **Mobile (<768px):**
  - Sidebar → **bottom tab bar** with the 4 core destinations
    (Dashboard, Events, Cameras, Alerts) + "More" sheet for the rest
    (Digests, Test AI, Usage, Settings, Admin).
  - Top app bar: logo, page title, hamburger for the "More" sheet.
- New `useMediaQuery` hook + single `AppShell` component replacing the
  copy-pasted layout in every route group (one file to maintain, not 12).

### 1.2 Chat panel + help widget on mobile
- Chat side panel: fixed-width `pr-[360px]` → desktop-only; on mobile it becomes
  a full-screen bottom sheet (slide up), toggled from the tab bar.
- Help widget bubble: shrink + reposition above the tab bar; opens full-screen
  sheet on mobile.

### 1.3 Responsive content per page
- Stats rows: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-4`.
- Camera grid: 1-col mobile → 2 → 3.
- **Tables → card lists on mobile** (Events, Alerts, Admin): each row becomes a
  tappable card with the 3 most important fields; details behind tap.
- Forms: full-width inputs, larger touch targets (min 44px), no side-by-side
  fields below `sm`.
- Tour (driver.js): disable auto-start on mobile (popovers don't fit); show a
  "Watch quick intro" card instead.

### 1.4 Plumbing
- Add `viewport` export in root layout (`width=device-width, initial-scale=1`).
- Replace all hardcoded hex classes with the semantic tokens already in
  `globals.css` (`bg-card`, `text-muted-foreground`, `border-border`, …) —
  mechanical sweep, enables future theming and shrinks class noise.

**Exit criteria:** every page usable at 375px width; `npm run build` clean;
no horizontal scroll anywhere.

---

## Phase 2 — Non-technical friendliness

### 2.1 Plain-language copy pass
- "RTSP pull" → "Camera connects automatically" (advanced details collapsed
  behind "Advanced setup").
- "Sensitivity" → visual 3-step selector: "Fewer alerts / Balanced / Catch
  everything" with one-line explanations.
- "FP rate" → "Accuracy"; "cooldown" → "Quiet time between alerts".
- Severity badges get labels + icons, not just colors (color-blind safe).

### 2.2 Guided empty states
Every list gets an illustrated empty state with ONE primary action:
- No cameras → "Add your first camera" (big button → connect wizard).
- No events → "All quiet. Events appear here when your cameras spot something."
- No alert rules → "Get notified on WhatsApp when something happens" + 1-click
  starter templates ("Person at night", "Vehicle in driveway").

### 2.3 Friendlier flows
- Add-camera: surface the existing `/onboard` wizard as the default path;
  raw RTSP form becomes the "Advanced" tab.
- Alert rule creation: template gallery first, custom form second.
- Destructive actions (delete camera/rule): confirmation dialog with plain
  consequence text ("You'll stop receiving alerts from this camera").
- Toast feedback (sonner, already installed) after every mutation.

### 2.4 Status at a glance
- Dashboard hero: single big "System status" strip — "✓ All 4 cameras watching"
  or "⚠ Garage camera offline since 2:14 PM" — before any numbers.
- Camera tiles: human status text ("Watching", "Offline — check power/Wi-Fi"),
  not just a colored dot.

---

## Phase 3 — Visual polish ("cool & attractive")

- **Typography (decision needed):** replace Comic Relief with Inter or Geist for
  body + keep a distinctive display font for the logo/headings only. Comic
  Relief undermines trust for a security product. *Flagged because AGENTS.md
  lists the font as a fixed decision — needs explicit sign-off.*
- Depth & hierarchy: subtle card elevation (`shadow` + 1px lighter inner
  border), hover lift on interactive cards, `#1E90FF` glow on primary actions.
- Micro-interactions (tw-animate-css already imported): fade/slide-in for list
  items, animated count-up on stat numbers, pulsing live-dot on the event feed,
  skeleton shimmer.
- Live feel: "LIVE" badge with pulse on dashboard feed; new event rows slide in
  and briefly highlight.
- Severity color system applied consistently: left border accent on event
  cards, tinted badge backgrounds.
- Login page: split layout with product visual/tagline; first impression
  matters most for non-tech users.
- Consistent iconography pass (lucide, already used) + 8px spacing grid.

---

## Phase 4 — Mobile-native niceties (optional, after 1–3)

- PWA: manifest + icons → "Add to Home Screen" gives an app-like experience.
- Pull-to-refresh on events feed.
- Web Push notifications (pairs with existing alert engine; needs one backend
  endpoint for push subscriptions — only item touching backend).
- Swipe gestures: swipe event card → approve/reject feedback.

---

## Order of work & estimates

| Phase | Effort | Value |
|---|---|---|
| 1 — Responsive shell + pages | ~2–3 days | Unblocks all mobile use |
| 2 — Plain language + empty states | ~1–2 days | Non-tech usability |
| 3 — Visual polish | ~1–2 days | "Cool & attractive" |
| 4 — PWA extras | ~1 day | App-like feel |

Each phase ends with `npm run build` + manual check at 375px / 768px / 1280px.

## Decisions needed before starting
1. **Font:** keep Comic Relief or switch to Inter/Geist (recommended: switch,
   keep Comic Relief only in the logo)?
2. **Mobile nav:** bottom tab bar (recommended, consumer-app feel) vs hamburger
   drawer only?
3. Is Phase 4 (PWA/push) in scope now or later?
