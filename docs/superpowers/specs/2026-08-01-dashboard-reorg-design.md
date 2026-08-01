# Dashboard Reorganization — Design

## Problem

The dashboard (`frontend/src/app/dashboard/page.tsx`) is a flat stack of four stat cards, a raw event table (timestamp/type/severity/camera-id-truncated/confidence/description columns), and a camera status grid. It's functional but reads as a log viewer, not something an operator would actually want to check in on. There's also a global "Ask Gemini" chat capability (`components/shared/chat-panel.tsx`) that lives only in a collapsible side panel, disconnected from the page someone actually lands on.

## Goal

Reorganize the dashboard to be more conversational and more analytical, without duplicating existing infrastructure:
1. A prominent "ask about your cameras" entry point on the dashboard itself, backed by the same Gemini Q&A the side panel already uses.
2. Real trend/breakdown analytics (currently nonexistent anywhere in the app) replacing the four flat stat cards.
3. The event feed reads as short narrative sentences instead of a raw data-grid row.

## Non-goals

- Rebuilding or duplicating the existing chat panel UI — the dashboard gets a lightweight entry point that hands off to it, not a second full chat implementation.
- New Gemini calls to "narrate" events — the narrative feed is a client-side formatting change over data already returned by the events API; no new AI cost.
- A dedicated analytics/charts page — this reorganizes the dashboard itself; a separate analytics page (already listed as a P3 "not yet built" item in the root `CLAUDE.md`) is out of scope here.
- Any change to event ingestion, storage, or the WebSocket live-feed mechanism — this is purely a presentation-layer reorganization of data that already exists.

## Backend

### Extend `GET /api/events/stats` (no new endpoint)

`backend/app/schemas/event.py`'s `EventStatsResponse` gains two fields:

```python
class EventStatsResponse(BaseModel):
    total_events: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    feedback_rate: float
    false_positive_rate: float
    time_series: list[dict]   # new: [{"bucket": "2026-08-01T14:00:00Z", "count": 12, "by_severity": {...}}, ...]
    by_camera: list[dict]     # new: [{"camera_id": "...", "camera_name": "...", "count": 42}, ...], sorted desc
```

`backend/app/api/events.py`'s stats handler buckets by hour when `period=24h`, by day for `7d`/`30d` (matching the existing period options), grouped via SQL `date_trunc` on `events.timestamp`, filtered by the same org-scoping the endpoint already applies. `by_camera` is a `GROUP BY camera_id` count, joined to `cameras.name`, limited to the top 10 (long tail folds into an "Other" row if there are more than 10 cameras — consistent with the dataviz guidance that a 9th+ category never gets its own generated hue).

## Frontend

### 1. Ask entry point

A single input pinned near the top of the dashboard, below the header:

```tsx
const [question, setQuestion] = useState("");
const [answer, setAnswer] = useState<string | null>(null);
const askMutation = useMutation({
  mutationFn: (q: string) => api.chatSend({ message: q }),  // same call chat-panel.tsx's Ask tab already makes
  onSuccess: (data) => setAnswer(data.content),
});
```

Renders as a single-line input ("Ask about your cameras…") + Send. On response, the answer renders inline in a card directly below. A "Continue in chat →" link opens the existing side panel (`useChatPanelStore` or whatever `chatPanelState.ts` exposes) pre-seeded with the same question, so a real back-and-forth continues in the panel that already supports it — this component never re-implements multi-turn chat.

### 2. Analytics section, replacing the 4-stat-card row

Per the dataviz procedure:
- **Trend chart** — job is "change over time" → a single-line area chart of `time_series` counts. One series (total volume) → single accent hue (`#1E90FF`), no legend needed (the chart title names it). If a severity breakdown is shown as a stacked area instead of a flat total, color follows the **existing status palette** (severity already has fixed colors via `SeverityBadge` — green/amber/orange/red) since severity is a status dimension, never a generated categorical hue.
- **Per-camera breakdown** — job is "ranking by magnitude" → a horizontal bar list, single accent hue, sorted descending, direct count labels (small N per org, so direct labels are appropriate per the mark-spec guidance rather than a shared axis every reader has to trace).
- Hover tooltip on the trend line (crosshair + value), matching the skill's interaction defaults.
- Dark-mode is the only mode this app has (Nightwatch is dark-only per its own design system) — the chart is built once, validated against the dark surface, not toggled.
- Before shipping, run `validate_palette.js` against the accent + severity hues actually used, per the skill's mandatory step — this happens at implementation time, not in this doc.

### 3. Narrative event feed

Replaces the current row-per-event table. Each entry becomes one line built entirely from data the page already has:

```tsx
const cameraName = camerasById[event.camera_id]?.name ?? "Unknown camera";
// "{description} — {cameraName} · {relative time}"
```

`event.description` already reads naturally (e.g. "Person detected in Driveway zone", "3 vehicle detected") since it's generated by the worker's event-construction logic (both YOLO fast-path and Gemini escalation already produce human-readable descriptions) — this isn't inventing new text, just presenting the existing field as a leading sentence instead of a table cell, paired with the camera's real name (resolved client-side from the `cameras` query already on this page, since `EventResponse` doesn't include `camera_name` and doesn't need to — no backend change required) instead of a truncated UUID, and a relative timestamp ("2m ago") instead of an absolute clock time.

Severity still renders via the existing `SeverityBadge` component, unchanged — status color stays reserved for status, exactly as it is today.

## Testing

Per standing preference (no TDD ceremony, direct implementation + manual sanity check + self-review):
- Backend: manual check of the extended stats endpoint's `time_series` bucketing at each period value (24h/7d/30d) and `by_camera` grouping/top-10-fold-to-Other behavior against seeded events.
- Frontend: `npm run build` clean; manual click-through of the Ask input (question → inline answer → "Continue in chat" opens the side panel with context preserved); visual check of the chart against the dataviz skill's anti-patterns list; confirm the narrative feed resolves real camera names, not UUIDs.

## Rollout

- No feature flag — this replaces the dashboard's existing sections in place; the underlying data sources (events, stats, cameras) are unchanged, so there's no migration and nothing to roll back beyond the frontend/backend code itself.
