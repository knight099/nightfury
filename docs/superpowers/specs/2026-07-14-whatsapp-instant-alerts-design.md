# WhatsApp Instant Alerts — Settings Tab

## Problem

Configuring WhatsApp delivery for real-time event alerts currently requires the
owner to create a full Alert Rule (event types, severity, cooldown, contacts)
on the Alerts page. There is no quick way to just say "send WhatsApp alerts to
these numbers, right now." The owner wants a dedicated Settings tab where they
can register up to 4 WhatsApp numbers, and toggle each one on/off
independently to control who receives instant alerts.

This is separate from the existing digest feature, which already has its own
`organizations.whatsapp_number` column and `whatsapp_enabled` digest
preference — those are untouched by this work.

## Goals

- Owner can add up to 4 WhatsApp numbers to their org, each with its own
  enable/disable toggle.
- Turning a number's toggle on makes it start receiving real-time event
  alerts; turning it off stops delivery to that number without deleting it.
- Numbers are editable in place (form mode) and deletable.
- Reuse the existing alert engine (severity filtering, cooldown, delivery via
  `notification_service`) rather than building a second notification path.
- Settings page becomes tab-based (Organization / Sites / Team / WhatsApp
  Alerts) instead of stacked sections.

## Non-goals

- Per-user WhatsApp numbers (this is org-wide, owner-managed only).
- Changing digest WhatsApp behavior or the `organizations.whatsapp_number`
  column.
- Custom severity/event-type/camera filtering per WhatsApp number — all
  enabled numbers receive all events (matches "instant alerts", not a
  replacement for the full Alert Rules feature).
- Deleting/rewriting existing Alert Rules functionality.

## Design

### Data model

Add a JSONB column to `Organization`:

```python
whatsapp_alert_contacts: Mapped[list] = mapped_column(JSONB, default=list)
# [{ "id": "<uuid4 str>", "number": "+91XXXXXXXXXX", "enabled": bool }, ...]
```

Max 4 entries, enforced in the API layer (not a DB constraint). One Alembic
migration adds this column with `server_default='[]'`.

Phone numbers are validated server-side as E.164-ish: `^\+\d{8,15}$`.

### Sync to the alert engine

A single auto-provisioned `AlertRule` row per org, identified by a fixed name
(`"WhatsApp Instant Alerts"`), acts as the delivery mechanism:

- `cameras: []`, `event_types: []`, `zones: []`, `min_severity: "low"` — no
  filtering, matches every event (an intentional "instant, no filters"
  rule — see Non-goals).
- `notify_channels: ["whatsapp"]`
- `notify_contacts: [{"type": "whatsapp", "value": <number>}, ...]` — rebuilt
  from whichever `whatsapp_alert_contacts` entries currently have
  `enabled: true`.
- `cooldown_seconds: 60` (existing model default).
- `enabled`: `true` if at least one contact is enabled, else `false`.

A helper, `_sync_whatsapp_alert_rule(org, db)`, runs after every mutation to
`whatsapp_alert_contacts`:

1. Compute `enabled_numbers` from the current contact list.
2. Look up the rule by `(org_id, name="WhatsApp Instant Alerts")`.
3. If `enabled_numbers` is empty: if the rule exists, set `enabled = False`
   (row is kept, not deleted, so history/cooldown state isn't lost and
   re-enabling is instant).
4. Else: upsert the rule (create if missing) with the fields above and
   `enabled = True`.

This means the alert engine's existing severity/cooldown/delivery logic in
`alert_service.py` and `notification_service.py` needs **no changes** — the
new feature only ever produces a normal `AlertRule` row.

### Backend API

All endpoints under `/api/settings`, owner-only (`require_role(user,
"owner")`), following the existing pattern in `app/api/settings.py`:

- `GET /api/settings/whatsapp-alerts` → `list[{id, number, enabled}]`
- `POST /api/settings/whatsapp-alerts` — body `{number: str}`
  - 400 if org already has 4 contacts.
  - 400 if `number` fails format validation.
  - 400 if `number` duplicates an existing contact (exact string match).
  - Creates entry with `enabled: false` (owner must explicitly turn it on).
  - Runs sync helper (no-op in this case since new entry is disabled).
  - Returns updated list.
- `PATCH /api/settings/whatsapp-alerts/{contact_id}` — body
  `{number?: str, enabled?: bool}`
  - 404 if `contact_id` not found in org's list.
  - Re-validates format if `number` provided; duplicate check excludes self.
  - Runs sync helper.
  - Returns updated list.
- `DELETE /api/settings/whatsapp-alerts/{contact_id}`
  - 404 if not found.
  - Removes entry, runs sync helper.
  - Returns updated list.

New Pydantic schemas in `app/schemas/organization.py` (or a new
`app/schemas/whatsapp_alerts.py`):

```python
class WhatsAppAlertContact(BaseModel):
    id: str
    number: str
    enabled: bool

class CreateWhatsAppAlertContactRequest(BaseModel):
    number: str

class UpdateWhatsAppAlertContactRequest(BaseModel):
    number: str | None = None
    enabled: bool | None = None
```

### Frontend

**Settings page restructure** (`frontend/src/app/settings/page.tsx`): convert
from stacked sections to a shadcn `Tabs` component with four tabs —
Organization, Sites, Team, WhatsApp Alerts. Each existing section
(`OrgSection`, `SiteSection`, `TeamSection`) moves into its tab body
unchanged; no internal changes to those components.

**New `WhatsAppAlertsSection` component:**
- Lists current contacts (0–4 rows). Each row: phone number, a `Switch` for
  enabled/disabled, **Edit** and **Delete** buttons.
- **Edit** turns the row into an inline form (phone input + Save/Cancel),
  mirroring the existing `SiteEditor` edit-in-place pattern.
- **"+ Add Number"** button (hidden/disabled once 4 contacts exist) opens the
  same form in create mode.
- Toggling the `Switch` directly calls `PATCH .../{id}` with
  `{enabled: !current}` — no separate save step.
- Empty state: "No WhatsApp numbers added yet" (matches the empty-state
  copy style used in `SiteSection`).

**New `lib/api.ts` methods:**
```ts
getWhatsAppAlertContacts(): Promise<WhatsAppAlertContact[]>
addWhatsAppAlertContact(number: string): Promise<WhatsAppAlertContact[]>
updateWhatsAppAlertContact(id: string, data: { number?: string; enabled?: boolean }): Promise<WhatsAppAlertContact[]>
deleteWhatsAppAlertContact(id: string): Promise<WhatsAppAlertContact[]>
```

**New type in `types/index.ts`:**
```ts
export interface WhatsAppAlertContact {
  id: string;
  number: string;
  enabled: boolean;
}
```

Data fetching via TanStack Query (`["settings", "whatsapp-alerts"]` query
key), mutations invalidate that key on success — matching the existing
pattern used by `OrgSection`/`SiteSection`/`TeamSection`.

### Error handling

- Client-side: reject empty/malformed numbers before submitting; disable
  "Add" button at 4 contacts; show inline error text on 400 responses (max
  reached, duplicate, invalid format) reusing the `errorMsg` pattern already
  in `SiteSection`.
- Server-side: all validation (format, count, duplicates) enforced in the API
  regardless of client-side checks.
- Delivery failures (e.g. Gupshup misconfigured) are unaffected by this
  feature — `notification_service` already soft-fails per number today.

### Testing

Backend tests (new file, e.g. `backend/tests/test_whatsapp_alert_contacts.py`):
- Add a contact → appears in list with `enabled: false`.
- Add a 5th contact → 400.
- Add a duplicate number → 400.
- Add invalid format → 400.
- Toggle a contact on → catch-all `AlertRule` created/enabled with that
  number in `notify_contacts`.
- Toggle the only enabled contact off → rule's `enabled` becomes `False`.
- Edit a contact's number while enabled → rule's `notify_contacts` reflects
  the new number.
- Delete an enabled contact → rule's `notify_contacts` no longer includes it.
- Non-owner role → 403 on all mutating endpoints.

No worker/relay/agent changes required.
