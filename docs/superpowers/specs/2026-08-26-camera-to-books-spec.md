# Camera-to-Books Workflow Layer — Spec

**Date:** 2026-08-26
**Status:** accepted, split into three plans
**Plans:** all three written — `2026-08-26-camera-to-books-phase-1.md`, `-phase-2.md`, `-phase-3.md` (in `docs/superpowers/plans/`)

---

## Objective

Add a "Camera-to-Books" workflow/exception layer to NightWatch, absorbing the
agentic-ERP concept (read → decide → execute, human approves exceptions) as an
internal module. Ten modules (Procurement, Inventory, Finance,
Order Management, Freight, Vendor Management, Warehouse, Demand Planning,
Production, Reporting) map onto NightWatch's camera-event architecture — not a
separate product.

---

## Section 0 — Prerequisites

Existing bugs that will corrupt audit-trail integrity once camera events start
driving back-office actions. Fix first.

1. **Commit-before-broadcast ordering bug.** WebSocket broadcast and the worker's
   201 response fire before the Postgres commit (commit happens post-yield in
   `get_db`). Fix: move broadcast + response emission to after confirmed commit;
   on commit failure, do not broadcast, log and return 5xx to the worker for retry.
2. **Synchronous notification dispatch blocking ingestion.** WhatsApp/email/webhook
   calls are awaited inline in the ingestion path. Fix: move to a queue consumed by
   a separate notification worker; the ingestion route only enqueues.
3. **Single-instance WebSocket broadcast.** In-memory pub/sub dict, breaks with more
   than one backend replica. Fix: Redis pub/sub as the broadcast layer before
   scaling backend replicas.
4. **Super admin cascade delete removing real event data.** Fix: soft-delete only
   for event/audit tables; hard delete restricted to explicitly non-audit entities.

**Acceptance:** an event can be traced from camera capture → DB commit → downstream
workflow trigger with no window where a client or workflow sees an event that isn't
durably persisted.

---

## Section 1 — Target architecture (5 layers)

```
[1] Event Layer (existing)
     Camera → Motion Gate → Gemini Vision → Event row in Postgres
        |
[2] Context/Enrichment Layer (new)
     Attach business context to raw event: site_id, camera_role (dock/vault/floor),
     expected_document_refs (PO number, BOM id) where derivable
        |
[3] Workflow/Exception Engine (new — the decision layer)
     Rule-based first, agentic later. Evaluates event + enrichment against
     expected state. Produces: MATCH (auto-clear), EXCEPTION (needs human), or IGNORE.
        |
[4] Connector Layer (new)
     Read-only integrations to external systems of record (Tally first).
     Pulls PO/GRN/invoice/BOM data needed by layer 3. No write-back in phase 1.
        |
[5] Reporting/Rollup Layer (new)
     Exception queue UI, audit log, resolved/pending counts per site,
     exportable reconciliation report
```

**Design constraint:** layers 2–5 must be optional/off by default per tenant.
Existing pure-alerting customers see zero behaviour change.

---

## Section 2 — Data model additions

Additive migration. Do not alter the existing `events` table schema; only add FK
relations.

- `workflow_rules` — `id, tenant_id, site_id, workflow_type (enum: dock_grn_match |
  vendor_overbill_check | backdoor_receiving | material_issue_bom_check |
  low_stock_procurement_trigger | shelf_stock_level_estimate |
  dispatch_order_verification | freight_dock_scheduling | vendor_scorecard_rollup |
  demand_trend_feed), config JSONB, enabled, created_at`
- `expected_documents` — `id, tenant_id, source (enum: tally | manual), doc_type
  (enum: po | grn | invoice | bom), external_ref, payload JSONB, synced_at`.
  Populated by the connector layer on a poll schedule (start: every 15 min).
- `workflow_exceptions` — `id, event_id FK -> events.id, workflow_rule_id FK, status
  (enum: open | approved | rejected | auto_cleared), matched_document_id FK ->
  expected_documents.id nullable, discrepancy JSONB, created_at, resolved_at,
  resolved_by`
- `connector_sync_log` — `id, tenant_id, connector (enum: tally), status,
  records_pulled, error, run_at`

All new tables get `tenant_id` with the same server-derived-from-auth pattern already
used elsewhere — never trust `tenant_id` from a request body.

---

## Section 3 — Workflow engine: all 10 modules

Build and ship one workflow at a time, fully, before starting the next. **Do not
build a generic "workflow DSL" up front.** Hardcode each workflow's logic first;
extract shared patterns into the engine only after several workflows reveal what's
actually common.

### Camera-native modules

**3.1 Warehouse — Dock GRN auto-match**
- Trigger: event tagged `camera_role=dock` with a detected pallet/carton count
  (existing Gemini Vision output) and, where OCR is feasible, a visible PO/DC number
- Match against: `expected_documents` where `doc_type=grn` or `po`, same site, open
- Outcome: quantity within tolerance → auto-draft GRN entry
  (`workflow_exceptions.status=auto_cleared`, payload includes draft GRN JSON for
  human review, **not** auto-posted to Tally). Mismatch → `status=open`, discrepancy
  JSON records expected vs. observed qty

**3.2 Finance — Vendor over-billing / short-delivery detection**
- Trigger: same dock events, matched against `invoice` documents pulled from Tally
- Outcome: flags if invoiced qty > camera-observed received qty

**3.3 Warehouse — Back-door receiving + shrinkage attribution (retail/QSR)**
- Trigger: event on a non-designated-entry camera with inbound-goods-like activity
  outside scheduled delivery windows (windows come from `expected_documents` PO
  delivery dates)
- Outcome: exception flagged for review; no auto-clear path — detection-only

**3.4 Production — Material-issue verification against BOM**
- Trigger: event tagged `camera_role=floor` showing material movement into the
  production area
- Match against: `expected_documents.doc_type=bom` for the active work order
- Outcome: flags issue quantities inconsistent with BOM requirement

**3.5 Inventory — Shelf/bin stock-level estimation**
- Trigger: scheduled or motion-triggered snapshot of `camera_role=shelf` or
  `camera_role=bin`; Gemini Vision estimates fill level / unit count
- Match against: `expected_documents` stock-on-hand figures synced from Tally
- Outcome: flags variance beyond tolerance as a stock-discrepancy exception; feeds
  current stock level into Procurement (3.6)

**3.6 Procurement — Low-stock trigger**
- Trigger: consumes output of 3.5; when estimated stock crosses a configured reorder
  threshold
- Outcome: drafts a purchase requisition record (not auto-sent to vendor) surfaced in
  the exception queue for human approval

**3.7 Order Management — Dispatch verification**
- Trigger: event tagged `camera_role=dispatch` or `camera_role=packing` showing
  picked/packed items leaving for an order
- Match against: `expected_documents.doc_type=po` or a new `sales_order` doc_type
  pulled from Tally
- Outcome: flags mismatch between what's picked and what the order specifies before
  dispatch

**3.8 Freight — Dock/vehicle scheduling verification**
- Trigger: event on a yard/gate camera detecting vehicle arrival/departure
- Match against: expected delivery/pickup windows in `expected_documents`
- Outcome: flags early/late/unscheduled vehicle activity; timestamps feed freight
  turnaround reporting

### Rollup / derived modules (no direct camera trigger)

**3.9 Vendor Management — Vendor scorecard**
- Source: aggregates `workflow_exceptions` history from 3.1, 3.2, 3.3 grouped by
  vendor (vendor identity resolved via `expected_documents` payload)
- Outcome: per-vendor on-time %, short-delivery %, over-billing % — surfaced as a
  report, not an exception

**3.10 Demand Planning — Trend feed**
- Source: aggregates historical dispatch (3.7), stock-level (3.5), and receiving
  (3.1) data over time
- Outcome: basic trend output (moving averages, seasonality flags) consumed by
  Reporting. Explicitly data-only — no camera trigger of its own, and no forecasting
  model beyond simple trend statistics in the initial build

Reporting is not a separate workflow — it is Layer 5, and every module above writes
into it via `workflow_exceptions` and the rollup tables in 3.9/3.10.

---

## Section 4 — Connector: Tally (read-only, first integration)

- Tally exposes an XML-over-HTTP interface on the local network (typically
  `localhost:9000` on the machine running Tally)
- Build a `connectors/tally/` module:
  - `client.py` — XML request builder + response parser for PO, GRN,
    Sales/Purchase Invoice, Stock Item (BOM proxy) reports
  - `sync.py` — scheduled job that pulls deltas and upserts into
    `expected_documents`, writes to `connector_sync_log`
- Since Tally typically runs on-prem, this connector likely needs a lightweight
  on-site agent/bridge (similar to the existing edge device pattern) rather than a
  direct cloud-to-Tally connection — **confirm network topology with a pilot customer
  before finalizing; do not assume cloud can reach Tally directly**
- No write-back to Tally in phase 1. All drafted GRN/match records stay inside
  NightWatch for human export or manual entry.

---

## Section 5 — API surface

```
GET  /api/workflows/exceptions?site_id=&status=   # exception queue
POST /api/workflows/exceptions/{id}/resolve       # approve/reject, body: {action, note}
GET  /api/workflows/rules?site_id=                # list configured workflows per site
POST /api/workflows/rules                         # enable/configure a workflow for a site
GET  /api/connectors/tally/status                 # last sync time, error state
POST /api/connectors/tally/sync                   # manual trigger (rate-limited)
```

All endpoints follow existing auth/tenant-scoping middleware — no new auth pattern.

---

## Section 6 — Frontend additions

- New "Exceptions" tab in dashboard (TanStack Query, matches existing patterns)
  - List view: open exceptions, filter by site / workflow type
  - Detail view: side-by-side camera snapshot + expected document data + discrepancy diff
  - Approve/Reject actions call the resolve endpoint
- Site settings: toggle which workflows are enabled per site, per-workflow config
  (tolerance %, delivery-window hours, etc.)
- Connector status widget: Tally sync health, last run, error banner if stale >X hours

---

## Section 7 — Non-goals (explicit, to prevent scope creep)

- Not building a generic ERP or replacing Tally/SAP — all 10 modules are
  exception/verification layers on top of Tally, not a system of record
- Not auto-writing to external systems initially — every auto-cleared item is a draft
  awaiting human export/entry until write-back is explicitly built (Section 8)
- Not building a new auth/tenant system — reuse existing
- Not building a generalized workflow config UI until enough modules are in
  production to reveal the real shared shape
- Demand Planning (3.10) is not building a forecasting/ML model initially — trend
  statistics only

---

## Section 8 — Deferred / later iteration

Build only after core workflows are stable.

- Optional write-back to Tally with maker-checker approval flow
- Second connector beyond Tally
- Generalized workflow config UI
- Pilot instrumentation: auto-clear rate, false-positive rate, time-to-resolve per
  exception — needed once reconciliation claims are made to prospects

---

## Section 9 — Testing requirements before any pilot claim

- Integration test: full event → enrichment → workflow → exception path, including
  forced-commit-failure case (must NOT produce an exception from an uncommitted event
  — validates the Section 0 fix)
- Load test: connector sync must not block event ingestion under concurrent load
- Data integrity test: tenant isolation on all new tables (attempt cross-tenant read,
  must fail)
- Per-module test: each of the 10 modules needs its own match/mismatch/no-data test
  case before being marked done
- No claim of "audit-ready" or "reconciliation" to any prospect until the discrepancy
  math has been validated against at least one real Tally export

---

# Appendix A — Codebase grounding (added 2026-08-26)

Findings from reading the repo before planning. These override or qualify the spec
above where they conflict.

### A.1 Section 0 status against the actual code

| Item | Status | Evidence |
|---|---|---|
| 1. Commit-before-broadcast | **Confirmed real** | `app/core/database.py:44` — `get_db` yields, *then* commits. `app/api/internal.py:58-71` — `db.flush()`, then `broadcast_to_org`, then `return`, all inside that pre-commit window. |
| 2. Synchronous notification dispatch | **Confirmed real** | `app/services/alert_service.py:38-45` — `await notification_service.send(...)` inline per contact, inside the ingestion request. |
| 3. Single-instance WebSocket broadcast | **Confirmed real** | `app/ws/events.py:44` — `ConnectionManager.connections` is a plain in-process `dict`. |
| 4. Super-admin cascade delete | **Already fixed — no work needed** | `app/services/soft_delete_service.py` replaced the ORM `delete-orphan` cascade with an explicit reversible `deleted_at` sweep. `app/api/admin.py:172-201` calls `soft_delete_service.delete_organization` / `restore_organization`. Events are never hard-deleted by this path. |

### A.2 Naming: `tenant_id` → `org_id`

This codebase has no `tenant_id`. Multi-tenancy is `organizations.id`, carried as
`org_id` on every scoped table, with an additional per-user site restriction applied
via `scope_to_sites(query, <Model>.site_id, user)` (`app/core/dependencies.py:175`).
**Both halves are required on every query.** All new tables in Section 2 use
`org_id` + `site_id`, not `tenant_id`.

### A.3 The exception queue already has a precedent — reuse it

`CameraSetupProposal` (`app/models/camera_setup.py`) is structurally the same object
Section 2 asks for: a DB row created at dispatch as the source of truth, a Redis list
used only as a dispatch *hint*, and approval as the only code path that writes real
configuration. `workflow_exceptions` follows that pattern rather than inventing a
second one.

### A.4 Gap the spec does not mention: the vision pipeline emits no goods data

Module 3.1 assumes "a detected pallet/carton count (existing Gemini Vision output)".
That output **does not exist**:

- `agent/pipeline/prompt_builder.py:16-27` — the response schema Gemini is given has
  `event_type`, `confidence`, `severity`, `description`, `bounding_boxes`, `zone`,
  `person_count`, `scene_summary`. No goods, carton, pallet, or document-reference field.
- `agent/pipeline/event_packager.py:59-71` — the payload POSTed to `/internal/events`
  never sets `metadata_extra` at all, even though `CreateEventRequest` accepts it
  (`app/schemas/event.py:19`).

So 3.1 requires a pipeline-side change (a dock-specific prompt addendum plus
`metadata_extra` plumbing), not just backend work. This is Task 5 of Phase 1.

### A.5 Tally topology — assumption recorded

Section 4 says to confirm topology with a pilot customer. Phase 1 implements the
connector as a backend-side puller against a per-org configured base URL, which works
for a Tally instance reachable from the backend (VPN, port-forward, or a cloud-hosted
Tally). The on-prem bridge over the existing agent control WebSocket is **deferred to
Phase 2** and is expected to be the production path. Nothing in Phase 1's connector
interface assumes the puller runs in the cloud — `TallyClient` takes a transport, so
swapping in an agent-relayed transport later does not change `sync.py`.

### A.6 Testing deviation from Section 9

The repo owner's standing preference is direct implementation plus structured
self-review rather than a test suite (`memory/feedback_no_tests_direct_code_review.md`),
and that preference was reaffirmed for this work on 2026-08-26. Phase 1 therefore
replaces Section 9's automated tests with per-task **manual verification steps**
(explicit `curl` calls, SQL checks, and a written self-review checklist covering
correctness, org+site scoping, and failure ordering).

**This weakens Section 9's gate, and the gate still stands:** no "audit-ready" or
"reconciliation" claim to any prospect until the discrepancy math has been checked by
hand against a real Tally export. Phase 1 Task 9 ends with that manual validation
step recorded in the connector sync log.

### A.7 Phase split

| Phase | Scope | Plan | Modules |
|---|---|---|---|
| 1 | Section 0 prereqs (items 1–3), Layer 2 enrichment, Layers 3/4/5 skeleton, first module end-to-end, Tally connector, API + Exceptions UI | `2026-08-26-camera-to-books-phase-1.md` | 3.1 |
| 2 | The dock/gate/dispatch family — all reuse Phase 1's document matching — plus the delivery-session concept they all need, the engine extraction, and the Tally on-prem bridge | `2026-08-26-camera-to-books-phase-2.md` | 3.2, 3.3, 3.7, 3.8 |
| 3 | The modules needing new vision capability (shelf fill estimation, BOM material tracking), the two rollups, and the reconciliation export | `2026-08-26-camera-to-books-phase-3.md` | 3.4, 3.5, 3.6, 3.9, 3.10 |

The split follows Section 3's own rule about not building a generic engine up front:
Phase 1 hardcodes exactly one module, and the shared shape is extracted in Phase 2
Task 1 — after four modules exist to extract it from, not before.

### A.8 Plans 2 and 3 were written ahead of Phase 1 shipping

Requested on 2026-08-27. Section 3 says to ship one workflow fully before starting
the next, and the reason is that the first module in production is what tells you
what the engine actually needs. Writing all three plans up front trades that
information for a complete roadmap on paper.

The cost is concentrated in two places, and both are marked in the plans themselves:

1. **Phase 2 Task 1 (engine extraction)** proposes a specific shared shape —
   `DocumentMatcher` — inferred from one implemented module plus three designed
   ones. If Phase 1's pilot shows the matching rule is wrong in a way that changes
   the abstraction, that task is the one to rewrite, and rewriting it is expected
   rather than a failure.
2. **Every quantity, threshold, and window in Phases 2 and 3** is a starting guess
   with no field data behind it. Each is called out as such where it appears.

Everything else — the data model, the API surface, the tenant-scoping pattern, the
verification steps — is derived from code that already exists and does not depend on
Phase 1's pilot outcome.

**Before starting Phase 2, re-read its Task 1 against what Phase 1 actually shipped.**
That is the checkpoint this ordering removed, reinstated as an explicit step.
