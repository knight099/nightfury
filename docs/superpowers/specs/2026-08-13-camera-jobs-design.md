# Single-Camera "Agents" / Jobs — Design (Project C of 3)

*Date: 2026-08-13*

## Context

This is Project C of the three-project frontend-v2 decomposition (see [Project A](2026-08-13-frontend-v2-shell-design.md), [Project B](2026-08-13-camera-map-journeys-design.md)). The mockup's "Agents" view is a per-camera list of natural-language "jobs" ("call me if a package is left at the door") — the single-camera half of it (as opposed to the "Multi-camera" badged items, which depend on Project B's camera-connection graph and are explicitly out of scope here).

**This is light assembly work, not new AI capability.** The pieces already exist:
- `POST /api/cameras/{id}/compile-sequence` already turns natural language into a draft `AlertRule` scoped to exactly one camera (`alert_rule.cameras = [camera_id]`), including conversational follow-up questions and validation warnings.
- `AlertRule` already has everything a "job" needs: `name`, `enabled`, `cameras`, `notify_channels`, `notify_contacts`.
- `AlertHistory` already links a rule to the events it notified on.

What's missing is a single frontend flow that glues "compile" → "save" together (today they're two separate, unconnected API calls with no UI joining them), a per-camera filter on the rules list, and honest framing of two real gaps: no phone-call channel exists, and "recent matches" is really "recent sent notifications" (cooldown-skipped or contact-less matches don't appear in `AlertHistory`).

## Goal

A per-camera "jobs" list (mockup's single-camera "Agents" section) where a user can: create a job via natural language, see it listed with its status/channel, toggle it on/off, rename it, remove it, and view its recent notification history — entirely on top of existing `AlertRule`/`compile-sequence`/`AlertHistory` capability.

## Architecture

```
backend/app/api/alerts.py          # MODIFY: add camera_id filter to list_rules
frontend/src/components/v2/JobsList.tsx       # new — per-camera job list
frontend/src/components/v2/JobCreateFlow.tsx  # new — wraps compile-sequence +
                                                  save-as-rule into one flow
frontend/src/components/v2/AgentDetail.tsx    # new — job detail + notification
                                                  history (mockup's "Agent Detail")
```

**Backend change — the only one in this project:**
```python
# backend/app/api/alerts.py — list_rules
async def list_rules(
    ...,
    camera_id: uuid.UUID | None = Query(None),   # NEW
):
    # existing org-scoping/include_deleted logic, plus:
    if camera_id is not None:
        query = query.where(AlertRule.cameras.contains([camera_id]))
```
Everything else in this project is frontend work over already-existing endpoints.

## Data flow

**Create a job:**
1. User on Camera Detail types a description (e.g. "call me if a package is left at the door") → `POST /api/cameras/{id}/compile-sequence {message, conversation_id?}`.
2. If `type: "question"` — show the model's follow-up question, loop back to step 1 with the same `conversation_id`.
3. If `type: "draft"` — show the proposed rule (name, trigger description, any `warnings`). Block the "Save" action until every warning is resolved (e.g. user must add a WhatsApp contact if the draft's `notify_channels` includes `"whatsapp"` and none exists — reuse the existing WhatsApp-contact-add flow from Settings, don't build a second one).
4. User confirms → `POST /api/alerts/rules` with the draft's `alert_rule` payload (already shaped as `CreateAlertRuleRequest` per the compile-sequence route's existing behavior) → job now exists as a real, enabled `AlertRule`.

**List jobs for a camera:** `GET /api/alerts/rules?camera_id={id}` → render as the mockup's job rows (name, toggle, channel badge, rename, remove).

**Toggle / rename / remove:** `PATCH /api/alerts/rules/{id} {enabled}` / `{name}`, `DELETE /api/alerts/rules/{id}` — direct reuse of the existing alert-rules CRUD, already used by the current (non-v2) Alerts page.

**Agent Detail — notification history:** `GET /api/alerts/history?rule_id={id}` → for each row, fetch/join the corresponding `Event` (via `getEvent(event_id)`) to render snapshot + description, matching the mockup's `agentDetail.recentEvents` shape. **UI copy says "Recent notifications," not "Recent matches"** — accurate to what's actually shown (successfully sent notifications only; see Non-goals).

## Channel handling

Mockup's channel-cycling UI (`ag.channel`, cycling "Text message" → "Phone call" → "Log only") is trimmed to what's real:
- Cyclable options: **WhatsApp**, **Email**, **Webhook** (maps to `notify_channels: ["whatsapp"]` / `["email"]` / `["webhook"]`).
- No "Phone call" — doesn't exist, not fabricated in the UI.
- No "Log only" as a distinct channel state — a job with an empty `notify_channels` is just a rule that doesn't notify anywhere; if useful, represent this as an explicit "no channel selected" state rather than pretending it's a fourth toggle-through option like the mockup's UI implies.

## Error handling

- `compile-sequence` warnings (missing contact/email/webhook URL) block save, surfaced inline — this validation already exists server-side, this project just makes sure the frontend actually shows and respects it (today nothing calls this route from a real UI flow).
- Deleting/toggling a job reuses the existing alert-rules page's error handling pattern (optimistic update, revert + toast on failure).

## Testing

No automated tests for this project (standing preference, consistent with Projects A and B) — manual: create a job end-to-end via natural language on a real camera, confirm it's a real queryable `AlertRule`, confirm it actually fires (generates an `AlertHistory` row) when a matching event occurs, confirm toggle/rename/remove all behave identically to the existing (non-v2) Alerts page since they're the same underlying calls.

## Non-goals

- No new notification channel (no phone calls) — would require a new telephony integration (e.g. Twilio), out of scope.
- No multi-camera jobs — the "Multi-camera" badged items in the mockup depend on Project B's `camera_connections` data and are not built here.
- No change to alert-engine matching/cooldown/dispatch logic — this project only adds a UI layer and one query filter over what already exists.
- "Recent matches" is not built as "all rule evaluations, including skipped ones" — that would require either a new logging path in the alert engine (out of scope) or accepting the existing `AlertHistory`-only view's honest limitation (chosen approach). If a future need arises to see cooldown-skipped matches too, that's a separate, explicitly-scoped follow-up.

## Open questions

- Whether `compile-sequence`'s draft `steps` (the step_sequence, separate from the `alert_rule` dict) need to persist anywhere once a job is saved — the explorer's research flagged this as unclear from the compile-sequence route alone. Worth checking the current (non-v2) camera-detail save handler's exact behavior before implementation, since Project C's save flow should match whatever the existing UI already does here, not invent a second persistence path.
- Exact wording for the "no channel selected" state — implementation-plan-level UI copy decision.
