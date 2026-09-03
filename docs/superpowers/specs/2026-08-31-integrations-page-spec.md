# Integrations Page — Spec

**Date:** 2026-08-31
**Status:** proposed

---

## Objective

Add an `/app/integrations` page: a category-grouped directory of external
systems a customer's site may already run — access control, ERP, POS, HR,
etc. — with a generic, per-org "connection" record for each. This is a
**registry/directory**, not a batch of new sync engines: on ship day exactly
one category (ERP) has real sync logic behind it (Tally, from the
Camera-to-Books work), and every other category is connectable in the sense
that a customer can record "we use Verkada for ACS" and see it listed as
Connected, with no data actually flowing yet.

This mirrors the same anti-premature-abstraction rule Camera-to-Books itself
follows (spec `2026-08-26-camera-to-books-spec.md`, Section 7/8: don't
generalize a connector framework before a second real connector exists). The
generic part being built here is the **registry and UI**, not 9 connectors —
those get built one at a time, later, each as its own scoped task, reusing
this page as their home.

---

## Section 0 — Relationship to Camera-to-Books

This is a separate initiative, not a phase of Camera-to-Books, but the two
share one seam:

- Camera-to-Books' `expected_documents` / `connector_sync_log` /
  `ConnectorSyncLog.connector` (currently a closed enum of `('tally',)`) stay
  exactly as that spec defines them. They are the **sync mechanics** for one
  connector.
- This spec adds `integrations` / `integration_connections` as the **registry
  layer** above that: the thing a user sees and clicks "Connect" on. Tally
  becomes one row in `integrations` (category `erp`), and its
  `integration_connections` row is what the Tally sync job reads its
  per-org base URL from, instead of a one-off org setting.
- If Camera-to-Books Phase 1 ships first, Task order in this plan includes a
  migration step that backfills the Tally connector's existing per-org config
  into `integration_connections`. If this ships first, Camera-to-Books picks
  up `integration_connections` as its config source instead of inventing its
  own.

No other Camera-to-Books table changes.

---

## Section 1 — Categories

Nine categories in four groups, seeded as a closed enum (adding a tenth later
is a migration, which is the right cost for a list a customer-facing page
renders by name):

| Group | Category | What it is | Example vendors |
|---|---|---|---|
| Security & Access | `acs` | Access Control System — keyless/membership-based entry, live membership check, tailgating detection | Brivo, Verkada |
| Security & Access | `pacs` | Physical Access Control System — enterprise door controllers, credential readers, on-prem servers, managed per site | Genetec, Avigilon, Brivo |
| Security & Access | `vms` | Visitor Management System — sign-in kiosks, expected-visitor lists | — |
| Enterprise Systems of Record | `erp` | Purchase/inventory/finance system of record | Tally, SAP B1, Zoho Books |
| Enterprise Systems of Record | `iwms` | Space/asset/facilities management | — |
| Retail & Food Service | `pos` | Point of sale, transaction data | — |
| Retail & Food Service | `kds` | Kitchen display system, order/prep timing | — |
| People & Relationships | `crm` | Customer/lead records | — |
| People & Relationships | `hris` | Employee roster, shift schedules | — |

`acs` and `pacs` are deliberately distinct categories, not a naming
duplicate — confirmed with the site owner: ACS is membership/keyless entry
with tailgating detection (a check against a *live membership feed*), PACS is
enterprise on-prem door-controller infrastructure (a check against a
*credential database*). A site can run both.

---

## Section 2 — Data model

Additive migration, chains off Camera-to-Books' migrations if those exist by
the time this is implemented, else off `80f8c57dc838` directly — resolve the
actual head at implementation time per Global Constraints in the plan.

- **`integrations`** — the catalog. Not per-org.
  `id, category (enum, 9 values above), name, vendor (nullable), status (enum: available | coming_soon), description, created_at`.
  Seeded via a data migration, not an admin UI, in Phase 1 — see Section 7.
  `status=coming_soon` rows render in the UI but are not clickable to
  connect; `status=available` rows are (Tally is the only `available` row on
  ship day).

- **`integration_connections`** — per-org state. The only table a customer
  action writes to.
  `id, org_id, site_id (nullable — some integrations, e.g. an org-wide CRM,
  aren't site-scoped), integration_id FK, status (enum: not_connected |
  pending | connected | error), config JSONB, error_message (nullable),
  connected_at, connected_by FK -> users.id, created_at, updated_at`.
  `unique(org_id, site_id, integration_id)` — one connection record per
  integration per site (or per org, when `site_id IS NULL`).
  `config` is opaque to this layer — the shape is whatever the eventual
  connector for that integration needs (a base URL for Tally, an API key for
  a CRM, nothing at all for a not-yet-built one). No column here is ever read
  by generic registry code; only a specific connector's code reads its own
  `config` shape.

No FK from `integration_connections` to anything Camera-to-Books-specific.
The seam described in Section 0 is Tally's sync job optionally reading this
table — this spec does not modify Camera-to-Books code.

---

## Section 3 — API surface

```
GET  /api/integrations                          # full catalog, all categories, grouped
GET  /api/integrations/connections?site_id=      # this org's connection state, scoped
POST /api/integrations/{integration_id}/connect  # body: {site_id?, config}
                                                  # creates/updates integration_connections,
                                                  # status=connected (no real handshake in Phase 1
                                                  # except where a real connector exists)
POST /api/integrations/{integration_id}/disconnect
```

Same auth/tenant-scoping pattern as every other endpoint —
`org_id` derived from `get_current_user`, `scope_to_sites` applied wherever
`site_id` is present, super-admin bypass keyed off `role`, never off
`org_id is None`. Pattern to copy: `backend/app/api/camera_setup.py:38-58`
(`_load_site`).

`connect` does not validate the vendor's credentials against the vendor's API
in Phase 1 for any category except ERP/Tally (which already has a real
client). For every other category, `connect` is bookkeeping: it records that
the org says it uses this integration and stores whatever config fields the
frontend form collected. This is stated explicitly in the UI (Section 4) so
it's never mistaken for a working sync.

---

## Section 4 — Frontend

- `frontend/src/app/integrations/page.tsx` — new route, added to the sidebar
  nav (`components/layout/sidebar.tsx` and `app-shell.tsx`, next to
  Settings).
- Layout: one section per group (Section 1's four groups), each rendering its
  categories as cards in a grid — matches the existing Settings-page visual
  pattern (dark-only, shadcn/ui, no new component primitives).
- Each card shows: category name, one-line description, vendor logos/names
  from `integrations` rows in that category, and a status pill:
  - **Connected** (green) — an `integration_connections` row exists with
    `status=connected`
  - **Not connected** (neutral) — clickable, opens a connect form
  - **Coming soon** (muted, not clickable) — every `integrations` row with
    `status=coming_soon`
- Connect form: for `available` integrations, a generic key/value config form
  (field labels come from a small per-integration static field list in the
  frontend — no generic JSON-schema renderer, that's over-engineering for one
  real connector). For Tally specifically, reuses whatever config fields
  Camera-to-Books' Tally connector already needs (base URL, credentials).
- Disconnect: confirmation dialog, calls `disconnect`, no cascading delete of
  historical sync data (`connector_sync_log` rows, if any, are untouched).
- `frontend/src/lib/api.ts` — four new client methods matching Section 3.
- `frontend/src/types/index.ts` — `Integration`, `IntegrationConnection`
  types.

---

## Section 5 — Non-goals (explicit)

- Not building real sync/connector logic for `acs`, `pacs`, `vms`, `iwms`,
  `pos`, `kds`, `crm`, `hris` in this pass. Each is a future, separately
  scoped task, the same way Camera-to-Books' Phase 2/3 modules are scoped
  individually.
- Not building a generic JSON-schema-driven config form. Nine categories,
  one with a real connector — a static per-integration field list is
  sufficient and avoids designing a form-schema abstraction against a single
  real example.
- Not validating credentials against any vendor's API at connect time, except
  where Tally's existing client already does so.
- Not exposing this page to non-admin users differently than Settings is
  today — same permission gate, no new role.
- Not letting an org add a *new* vendor row to `integrations` themselves in
  Phase 1 — the catalog is seeded/admin-managed. "+ your own" (mentioned for
  ACS/PACS) is a config field on the connect form (e.g. "Other — describe"),
  not a new catalog row, until a real intake flow is scoped.

---

## Section 6 — Testing / verification

Per the repo owner's standing preference (`memory/feedback_no_tests_direct_code_review.md`),
no automated test suite — direct implementation plus a manual verification
step per task (curl calls, SQL checks) and a self-review checklist, same
format as Camera-to-Books Phase 1.

---

## Section 7 — Open item for the implementation plan

The initial `integrations` catalog needs real seed data (name, vendor
examples, description) for all 9 categories before the page is demoable.
Section 1's table above is enough to seed real rows for Phase 1 — the
implementation plan's first task should turn it directly into the seed
migration data rather than re-deriving it.
