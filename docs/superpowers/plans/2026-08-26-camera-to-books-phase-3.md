# Camera-to-Books Workflow Layer — Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the ten-module set — shelf stock estimation, low-stock procurement, BOM material verification, the vendor scorecard, and the demand trend feed — and give the whole layer its reporting surface: a reconciliation export and the pilot instrumentation that has to exist before anyone makes a reconciliation claim.

**Architecture:** Phases 1 and 2 were reactive: an event arrives, a workflow compares it against a document. Phase 3 adds the two things that shape does not cover. First, **scheduled observation** — a shelf does not generate motion when it empties, so stock estimation needs a sampler that costs Gemini calls on a timer, which makes AI-budget metering a hard requirement rather than a nicety. Second, **aggregation over time** — the scorecard and trend feed have no camera trigger at all; they read what the other eight modules have already written.

**Tech Stack:** Same as Phases 1 and 2, plus the existing `SpendTracker` (`backend/app/services/digest/spend_tracker.py`) for AI budget enforcement and APScheduler for the rollup sweep.

**Spec:** `docs/superpowers/specs/2026-08-26-camera-to-books-spec.md` — modules 3.4, 3.5, 3.6, 3.9, 3.10, plus Section 8's pilot instrumentation. Read Appendix A.8: this plan was written before Phase 1 shipped, so every threshold in it is a guess and Phase 2's Task 1 abstraction may have moved underneath it.

**Depends on:** Phases 1 and 2, complete and merged.

---

## Global Constraints

Phases 1 and 2's Global Constraints still apply verbatim. In addition:

- **Every scheduled Gemini call is charged against the per-site AI budget before it is made.** Phase 3 is the first thing in this feature that spends money on a timer rather than in response to something happening. `SpendTracker.try_charge` is called *before* the call, and a refused charge degrades to "no estimate" rather than an error. This is not optional and it is not deferred: the codebase already carries one known gap where setup runs bypass metering, and adding a second, continuous one would make per-camera AI spend unarguable.
- **Trend statistics only.** Module 3.10 computes moving averages and simple seasonality flags. No forecasting model, no ML. The spec says so twice and the reason is that a forecast presented to a customer is a commitment.
- **The word "reconciliation" appears in a customer-facing surface for the first time in this plan.** Task 8's export is literally named that. It ships with the caveats embedded in the file, and the Section 9 gate — real Tally export validated by hand — must be green before that export is shown to anyone outside the team.
- **Alembic chain:** Phase 2's head is `d4e5f6a7b8c9`. Phase 3 chains off it in task order.
- **Still no write-back to any external system.** See "Beyond Phase 3" at the end.

---

## File Structure

**Backend — created**

| File | Responsibility |
|---|---|
| `backend/app/models/stock_estimate.py` | `StockEstimate` — one shelf reading at one moment |
| `backend/app/models/demand_trend.py` | `DemandTrend` — materialised nightly rollup |
| `backend/app/services/workflows/shelf_stock.py` | Module 3.5 |
| `backend/app/services/workflows/procurement.py` | Module 3.6 — runs on the rollup sweep, not on an event |
| `backend/app/services/workflows/material_issue.py` | Module 3.4 |
| `backend/app/services/rollups/vendor_scorecard.py` | Module 3.9 — computed on read |
| `backend/app/services/rollups/demand_trend.py` | Module 3.10 — materialised nightly |
| `backend/app/services/rollups/sweep.py` | The scheduled entry point for 3.6 and 3.10 |
| `backend/app/services/reporting/reconciliation.py` | CSV export builder |
| `backend/app/services/reporting/instrumentation.py` | Auto-clear rate, resolution outcomes, time-to-resolve |
| `backend/app/api/reports.py` | Export, scorecard, trends, instrumentation endpoints |

**Backend — modified**

| File | Change |
|---|---|
| `backend/app/services/workflows/dock_grn.py` | Moves to session keying (Phase 2 limitation #3) |
| `backend/app/models/workflow.py` | `WORKFLOW_TYPES` unchanged — Phase 1 declared all ten |
| `backend/app/api/internal.py` | Accepts shelf-sample events; charges the budget |
| `backend/app/main.py` | Rollup sweep job |

**Edge pipeline — modified**

| File | Change |
|---|---|
| `agent/pipeline/prompt_builder.py` | Shelf and material addenda |
| `agent/pipeline/gemini_client.py` | Parses shelf and material blocks |
| `agent/pipeline/supervisor.py` | Scheduled sampler for `shelf`/`bin` cameras |

**Frontend — created / modified**

| File | Change |
|---|---|
| `frontend/src/app/reports/page.tsx` | Create — scorecard, trends, export, instrumentation |
| `frontend/src/components/layout/sidebar.tsx` | "Reports" nav entry |
| `frontend/src/lib/api.ts`, `frontend/src/types/index.ts` | New methods and types |

---

### Task 1: Move `dock_grn` to session keying

**Files:**
- Modify: `backend/app/services/workflows/dock_grn.py`

**Interfaces:**
- Consumes: Phase 2's `DeliverySession` and `WorkflowOutcome.subject_key`.
- Produces: no new interface. `dock_grn` now emits one exception per delivery instead of one per event.

**Why first, and why its own task.** Phase 2 deliberately left this alone so each task changed one module's behaviour at a time. The result is an inconsistency a customer can see: one delivery produces forty `dock_grn_match` rows and one `vendor_overbill_check` row. Fixing it is small, it touches a module every later task builds on, and doing it first means Phase 3's verification runs against a consistent queue.

- [ ] **Step 1: Compare against the session, not the event**

In `backend/app/services/workflows/dock_grn.py`, take the observed quantity from the session where one exists:

```python
    if session is not None and session.direction == "inbound":
        subject_key = f"session:{session.id}"
        session_id = session.id
        carton_count = session.totals.get("carton_count_max", carton_count)
        pallet_count = session.totals.get("pallet_count_max", pallet_count)
        refs = set(session.totals.get("refs") or [])
    else:
        # A dock camera whose events carry goods but which produced no session
        # — only reachable if `assign_session` changes. Falling back to the
        # single event keeps the module working rather than silently going
        # quiet, which is the failure mode that is hardest to notice.
        subject_key = None
        session_id = None
        refs = {r for r in (goods.get("visible_refs") or []) if r}
```

Pass `subject_key=subject_key` and `delivery_session_id=session_id` on every `WorkflowOutcome` this module returns, including the two failure outcomes returned from `DocumentMatcher` (set the attributes on `result.failure` before returning it, as `dispatch_verification` does).

Change every message string that reports the observed count to say "counted at most", matching Phase 2's wording rule — the number is now a session maximum, and the old wording described a single frame.

- [ ] **Step 2: Verify the row count collapses**

Post five dock events two minutes apart against a seeded `PO-4471` for 20 cartons, with counts 8, 12, 20, 12, 9.

```bash
psql "$POSTGRES_URL" -c "select count(*), max(status), max(subject_key) from workflow_exceptions where workflow_type='dock_grn_match' and created_at > now() - interval '10 minutes';"
```

Expected: exactly **one** row, `subject_key` starting `session:`, status `auto_cleared` (the session max is 20, which matches). Before this task the same input produced five rows.

Then re-run every case from Phase 1 Task 8 Step 4 and confirm the verdicts are unchanged — only the keying and the wording moved.

- [ ] **Step 3: Self-review**

- Do old event-keyed rows still exist and still render? (They do, with `subject_key` like `event:…` from Phase 2's backfill. Confirm the API and UI handle both — there is no migration of historical rows and there should not be one, because rewriting an audit record to a new grouping is not a refactor.)
- Are the two `DocumentMatcher` failure outcomes given the session key? (If not, one delivery produces one match row and forty no-match rows — the exact bug this task fixes, surviving in the failure path.)
- Does the fallback branch ever fire in practice? (Add a `logger.warning` in it so if it does, it is visible rather than silent.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/workflows/dock_grn.py
git commit -m "refactor(workflows): key dock GRN exceptions on the delivery session"
```

---

### Task 2: Scheduled shelf sampling, with AI budget enforcement

**Files:**
- Modify: `agent/pipeline/prompt_builder.py`, `agent/pipeline/gemini_client.py`, `agent/pipeline/supervisor.py`
- Modify: `backend/app/api/internal.py`
- Modify: `backend/app/schemas/assignment.py`, `backend/app/models/camera.py` + migration

**Interfaces:**
- Consumes: Phase 2's role-addendum map.
- Produces:
  - `metadata_extra["shelf"]` on events from `shelf` and `bin` cameras:

```json
{"shelf": {"fill_pct": 35, "estimated_units": 14, "sku_hint": "Blue crates, top two rows", "shelf_confidence": 0.7}}
```

  - `Camera.sample_interval_minutes: int | None` — when set on a `shelf`/`bin` camera, the pipeline samples on that timer regardless of motion
  - `/internal/events` charges the per-site AI budget for `event_type == "shelf_sample"` and returns `429` when the budget is exhausted

**The problem this task exists to solve.** Every other module in this feature is triggered by something happening. A shelf emptying is the absence of something happening: no motion, no event, no Gemini call, no data. Stock estimation therefore needs a sampler on a timer.

**Which makes it the first continuously-spending thing in the feature, and that changes the rules.** Ten shelf cameras at fifteen-minute intervals is 960 Gemini Vision calls a day, per site, forever. The codebase already carries one known metering gap — agentic setup runs are not charged against the per-site AI budget — and that one is bounded by a 50-camera batch cap and a human pressing a button. This one is unbounded and automatic. So:

- The budget charge happens **on the backend, at ingestion**, not on the edge box. The edge box holds no spend state and cannot be trusted to enforce a cap it could be reconfigured past.
- A refused charge returns `429`, and the pipeline treats `429` on a shelf sample as "skip this cycle", not as an error to retry. Retrying a call that was refused for cost reasons is how a budget cap becomes a budget suggestion.
- **The charge is an estimate, because `gemini_client._call_gemini` discards `response.usage_metadata` — a known gap recorded in the project's own status notes.** A fixed per-call cost constant is used, and it is wrong. Fixing token accounting is a prerequisite for arguing about vision cost at all, and it is called out again in this task's self-review because Phase 3 is the point where it stops being theoretical.

- [ ] **Step 1: Add the shelf addendum**

In `agent/pipeline/prompt_builder.py`:

```python
SHELF_ADDENDUM = """

This camera watches a shelf, rack, or storage bin. In ADDITION to the schema
above, include a top-level "shelf" object:

  "shelf": {{
    "fill_pct": <int 0-100, or null>,
    "estimated_units": <int or null>,
    "sku_hint": "<what the stock visibly is, or null>",
    "shelf_confidence": <float 0.0-1.0>
  }}

Rules for "shelf":
- "fill_pct" is how much of the visible shelf space is occupied, not how full
  the shelf is relative to some target you cannot see
- "estimated_units" only when individual items are actually countable. A dense
  stack where you can see the front row and infer the rest is NOT countable —
  use null
- "sku_hint" describes what you see. Never name a product you are inferring
  from context rather than reading"""
```

Add `"shelf": (SHELF_ADDENDUM,)` and `"bin": (SHELF_ADDENDUM,)` to `ROLE_ADDENDA`.

Parse it in `gemini_client.py` alongside the goods and vehicle blocks, clamping `fill_pct` to `0..100` and dropping anything non-numeric.

- [ ] **Step 2: Add the sampler**

Add `sample_interval_minutes: int | None = None` to `CameraConfig` (and to `Assignment`, `Camera` + `backend/alembic/versions/e5f6a7b8c9d0_sample_interval.py` chaining off Phase 2's head `d4e5f6a7b8c9`, and the assignment construction in `internal.py` — the same five-place thread as Phase 1 Task 4).

In `agent/pipeline/supervisor.py`, for cameras where `camera_role in ("shelf", "bin")` and `sample_interval_minutes` is set, run a sampling loop independent of the motion gate:

```python
# A shelf emptying produces no motion, so the motion gate — which is what
# keeps Gemini costs down everywhere else — is exactly what makes stock
# estimation impossible. Sampling on a timer is the trade, and it is why the
# backend charges these against the AI budget before accepting them.
async def _sample_loop(self, camera_config, stop_event) -> None:
    interval = max(5, int(camera_config.sample_interval_minutes)) * 60
    while not stop_event.is_set():
        try:
            frame = await self._latest_frame(camera_config.camera_id)
            if frame is not None:
                events = await self._gemini.analyze(frame, camera_config)
                for event in events:
                    event.event_type = "shelf_sample"
                    await self._packager.package(event, camera_config, frame)
        except Exception:
            logger.exception("[%s] shelf sample failed", camera_config.name)
        await asyncio.wait([stop_event.wait()], timeout=interval)
```

Adapt the method names to whatever the supervisor actually exposes for "give me the current frame" and "package and post this event" — read the file first; the shape above is the intent, not the exact call sites.

The `max(5, ...)` floor is deliberate: a one-minute interval on ten cameras is 14,400 calls a day and a misconfiguration, not a use case.

- [ ] **Step 3: Charge the budget at ingestion**

In `backend/app/api/internal.py`, before the `Event` is constructed:

```python
    # Shelf samples are the only event type this system generates on a timer
    # rather than in response to something happening, so they are the only
    # ones that can run up an unbounded bill. Charge before accepting.
    #
    # The cost here is a FIXED ESTIMATE, not a measurement: the pipeline's
    # Gemini client discards `response.usage_metadata`, so nothing in this
    # codebase knows what a vision call actually cost. Until that is fixed,
    # this cap is approximate in a direction nobody has measured.
    if body.event_type == "shelf_sample":
        tracker = SpendTracker(
            await get_redis(),
            daily_cap_usd=settings.digest_daily_spend_cap_usd,
            site_daily_cap_usd=settings.digest_site_daily_spend_cap_usd or None,
        )
        if not await tracker.try_charge(
            camera.org_id, SHELF_SAMPLE_COST_USD, site_id=camera.site_id
        ):
            raise HTTPException(
                status_code=429,
                detail="Daily AI budget for this site is exhausted; shelf sample skipped",
            )
```

with `SHELF_SAMPLE_COST_USD = 0.002` defined at module level next to a comment saying it is a placeholder pending real token accounting.

On the pipeline side, in `agent/pipeline/api_client.py`'s `post_event`, treat a `429` on a `shelf_sample` as a successful skip — log at info and do **not** enqueue it for offline retry. Retrying a call refused for cost is how a cap becomes a suggestion.

- [ ] **Step 4: Verify the sampler and the cap**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

```bash
cd agent/pipeline && python3 -c "
from models import CameraConfig
from prompt_builder import PromptBuilder
p = PromptBuilder().build(CameraConfig(camera_id='x', org_id='y', name='Rack 3', ingest_mode='rtsp_pull', camera_role='shelf'))
assert 'fill_pct' in p and 'goods' not in p and 'vehicle' not in p
print('ok')
"
```

Set a shelf camera to `sample_interval_minutes = 5` against the local RTSP stand-in and confirm events with `event_type='shelf_sample'` arrive on a timer with no motion in frame:

```bash
psql "$POSTGRES_URL" -c "select timestamp, metadata_extra->'shelf' from events where event_type='shelf_sample' order by timestamp desc limit 5;"
```

Then exhaust the site budget deliberately (set `DIGEST_SITE_DAILY_SPEND_CAP_USD` to something tiny and restart) and confirm:
- the backend returns `429`,
- the pipeline logs a skip and does **not** queue a retry,
- no `shelf_sample` row is written,
- ordinary motion-triggered events are still accepted, because they are not charged here.

That last check matters: a budget cap that silently stops security alerting would be a far worse failure than one that stops stock estimation.

- [ ] **Step 5: Self-review**

- Is `SHELF_SAMPLE_COST_USD` honest about being a guess, in both the code comment and anywhere it surfaces to a user? (It is a placeholder for a measurement the codebase cannot currently make. Do not let it be presented as a cost figure.)
- **Should this task also fix `_call_gemini` discarding `usage_metadata`?** It is a small change (`response.usage_metadata` → the existing `AIUsage` row) and it turns every cost number in this feature from inferred to measured. Argument against: it is a separate concern touching a shared client. Argument for: this is the task that makes the gap expensive. Decide explicitly and record the decision — do not leave it undecided.
- Can a customer configure a sample interval that outruns their budget silently? (They can. The cap will refuse the calls, but the only signal is a `429` in an edge log. Consider surfacing "shelf sampling stopped: budget exhausted" in the UI — Task 9 is where that would live.)
- Does the sampler keep running when the camera is offline? (`_latest_frame` returning `None` should skip without a Gemini call. Confirm — sampling a dead camera should cost nothing.)
- Does `shelf_sample` leak into the alerting path? (`alert_service.evaluate_event` runs on every event. A rule with no `event_types` filter matches everything, so shelf samples would page someone. **Check this and exclude `shelf_sample` from alert evaluation** — it is not a security event.)

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline/ backend/app/api/internal.py backend/app/schemas/assignment.py backend/app/models/camera.py backend/alembic/versions/
git commit -m "feat(pipeline): scheduled shelf sampling with AI budget enforcement"
```

---

### Task 3: Module 3.5 — Shelf stock level estimation

**Files:**
- Create: `backend/app/models/stock_estimate.py`
- Create: `backend/app/services/workflows/shelf_stock.py`
- Create: `backend/alembic/versions/f6a7b8c9d0e1_stock_estimates.py`, chaining off Task 2's `e5f6a7b8c9d0`
- Modify: `backend/app/services/workflows/__init__.py`, `backend/app/models/__init__.py`

**Interfaces:**
- Consumes: Task 2's `metadata_extra["shelf"]`; Phase 1's `ExpectedDocument` with `doc_type="stock_on_hand"`.
- Produces:
  - `StockEstimate`: `id, org_id, site_id, camera_id, observed_at, fill_pct, estimated_units, sku_hint, confidence, matched_document_id, book_quantity`
  - a module registered under `"shelf_stock_level_estimate"`. Config keys:
    - `variance_tolerance_pct: float` (default `20.0`) — deliberately loose; see below
    - `min_shelf_confidence: float` (default `0.6`)
    - `reorder_threshold_pct: float` (default `20.0`) — read by module 3.6, stored here because it is a property of the shelf

**Why the tolerance default is 20% and not 5%.** A fill percentage read off an image is a much weaker signal than a carton count at a dock: it depends on shelf depth the camera cannot see, on stacking, and on lighting. Comparing it against a book quantity in units requires a units-per-full-shelf constant nobody has. So this module compares **only when the document carries `units_per_full_shelf`**, and otherwise records the estimate without raising anything. A loose default plus an explicit "no comparison possible" state is honest; a tight default on a weak signal produces a queue of noise.

- [ ] **Step 1: Write the model**

`backend/app/models/stock_estimate.py` — follow Phase 1 Task 6's model conventions exactly (UUID pk, `org_id` + `site_id` FKs, `CheckConstraint`s, explicit `Index`es). Columns:

```python
    # The reading's provenance. Non-nullable: module 3.6 writes a
    # WorkflowException from a StockEstimate and has no event of its own, and
    # WorkflowException.event_id is NOT NULL by design — a verdict with no
    # traceable observation behind it is not an audit record.
    event_id: Mapped[uuid.UUID]              # FK events.id, not null
    observed_at: Mapped[datetime]            # from the event
    fill_pct: Mapped[int | None]
    estimated_units: Mapped[int | None]
    sku_hint: Mapped[str | None]             # Text
    confidence: Mapped[float]
    matched_document_id: Mapped[uuid.UUID | None]  # FK expected_documents
    book_quantity: Mapped[float | None]      # what the books said at that moment
```

with `Index("ix_stock_estimates_camera_time", "camera_id", "observed_at")` — module 3.6 reads "the latest estimate per camera", and that is the query.

Docstring, verbatim:

```python
"""One reading of one shelf at one moment.

Kept as its own table rather than derived from events because module 3.6 asks
"what is the level now?" on a schedule, and answering that by scanning event
JSON would get slower every day the system runs.

`fill_pct` is a camera's estimate of visible occupancy. It is not a stock
count, it cannot see shelf depth, and it should never be rendered as one.
"""
```

- [ ] **Step 2: Write the module**

`backend/app/services/workflows/shelf_stock.py`, registered as `"shelf_stock_level_estimate"`. Module-level constants:

```python
DEFAULT_VARIANCE_TOLERANCE_PCT = 20.0
DEFAULT_MIN_SHELF_CONFIDENCE = 0.6
# A week. Stock-on-hand is a running balance rather than a dated document, so
# the nearest sync is the right figure even if it is days old.
DEFAULT_MATCH_WINDOW_HOURS = 168
```

Body:

```python
@register("shelf_stock_level_estimate")
async def evaluate(event, camera, rule, session, db) -> WorkflowOutcome:
    if camera.camera_role not in ("shelf", "bin"):
        return WorkflowOutcome.ignore()

    shelf = (event.metadata_extra or {}).get("shelf")
    if not isinstance(shelf, dict):
        return WorkflowOutcome.ignore()

    config = rule.config or {}
    min_confidence = float(config.get("min_shelf_confidence", DEFAULT_MIN_SHELF_CONFIDENCE))
    tolerance_pct = float(config.get("variance_tolerance_pct", DEFAULT_VARIANCE_TOLERANCE_PCT))

    if float(shelf.get("shelf_confidence") or 0.0) < min_confidence:
        return WorkflowOutcome.ignore()

    fill_pct = shelf.get("fill_pct")
    estimated_units = shelf.get("estimated_units")
    if fill_pct is None and estimated_units is None:
        return WorkflowOutcome.ignore()

    # Match a stock-on-hand figure for this shelf's SKU, if the org syncs one.
    # A wide window: stock figures are a running balance, not a dated document.
    result = await DocumentMatcher(db).find(
        org_id=event.org_id,
        site_id=event.site_id,
        doc_types=("stock_on_hand",),
        at=event.timestamp,
        window_hours=int(config.get("match_window_hours", 168)),
        refs={shelf["sku_hint"]} if shelf.get("sku_hint") else set(),
        observed={"fill_pct": fill_pct, "estimated_units": estimated_units},
    )
    document = result.document  # may be None; a failure here is not an exception

    book_quantity = None
    units_per_full = None
    if document is not None:
        book_quantity = document.payload.get("expected_quantity")
        units_per_full = document.payload.get("units_per_full_shelf")

    # ALWAYS record the reading, even when nothing can be compared. Module 3.6
    # needs the level regardless of whether a book figure exists, and a
    # customer with no Tally stock sync still gets low-stock alerts.
    db.add(
        StockEstimate(
            org_id=event.org_id,
            site_id=event.site_id,
            camera_id=camera.id,
            event_id=event.id,
            observed_at=event.timestamp,
            fill_pct=fill_pct,
            estimated_units=estimated_units,
            sku_hint=shelf.get("sku_hint"),
            confidence=float(shelf.get("shelf_confidence") or 0.0),
            matched_document_id=document.id if document else None,
            book_quantity=float(book_quantity) if book_quantity is not None else None,
        )
    )

    # Comparison needs three things at once: a book figure, a way to convert a
    # fill percentage into units, and a countable reading. Missing any of them
    # means the reading is recorded and nothing is claimed — which is the
    # common case and must not produce a queue item.
    observed_units = estimated_units
    if observed_units is None and fill_pct is not None and units_per_full:
        observed_units = float(fill_pct) / 100.0 * float(units_per_full)

    if book_quantity is None or observed_units is None:
        return WorkflowOutcome.ignore()

    book_quantity = float(book_quantity)
    if book_quantity <= 0:
        return WorkflowOutcome.ignore()

    variance_pct = abs(observed_units - book_quantity) / book_quantity * 100.0
    if variance_pct <= tolerance_pct:
        return WorkflowOutcome(verdict="match", matched_document_id=document.id)

    return WorkflowOutcome(
        verdict="exception",
        matched_document_id=document.id,
        discrepancy={
            "reason": "stock_variance",
            "book_quantity": book_quantity,
            "observed_units": round(observed_units, 1),
            "fill_pct": fill_pct,
            "units_per_full_shelf": units_per_full,
            "variance_pct": round(variance_pct, 2),
            "tolerance_pct": tolerance_pct,
            "sku_hint": shelf.get("sku_hint"),
            "external_ref": document.external_ref,
            "message": (
                f"Books show {book_quantity:g} of {document.external_ref}; the camera "
                f"estimates about {round(observed_units)} from {fill_pct}% shelf fill. "
                f"A fill estimate cannot see shelf depth, so treat this as a prompt to "
                f"count, not as a count."
            ),
        },
    )
```

Imports follow `dock_grn.py`'s exactly, plus `from app.models.stock_estimate import StockEstimate`. Add `await db.flush()` after the `db.add(...)` so the row has an id before the engine commits.

- [ ] **Step 3: Verify**

| Case | Setup | Expected |
|---|---|---|
| Reading recorded, nothing claimed | No `stock_on_hand` document | `StockEstimate` row written, **no** exception |
| No conversion available | Document with `expected_quantity` but no `units_per_full_shelf`, and `estimated_units: null` | `StockEstimate` written, no exception |
| Agreement | `expected_quantity: 100`, `units_per_full_shelf: 200`, `fill_pct: 50` | `auto_cleared` |
| Variance | Same document, `fill_pct: 20` (→ 40 units vs 100) | `open`, `variance_pct = 60` |

```bash
psql "$POSTGRES_URL" -c "select observed_at, event_id, fill_pct, estimated_units, book_quantity from stock_estimates order by observed_at desc limit 5;"
```

The first two cases matter most: they are the common configuration, and each must write a reading without adding to the queue.

- [ ] **Step 4: Self-review**

- Does an org with no Tally stock sync get anything useful? (Yes — `StockEstimate` rows, which 3.6 uses. Confirm the module does not early-return before the `db.add`.)
- Is `fill_pct → units` conversion ever done without `units_per_full_shelf`? (It must not be. There is no defensible default for it.)
- Does the module write a `StockEstimate` for every sample, forever? (Yes — ten cameras at fifteen-minute intervals is ~350k rows a year. Check whether `retention.py`'s nightly purge covers this table; if not, add it, or the table grows without bound.)
- Is `sku_hint` used as a matching reference safely? (It is free text from a vision model, passed to `DocumentMatcher` as a ref. `normalise_ref` uppercases and strips it; a hint like "BLUE CRATES" will match nothing, which is the right failure. Confirm it cannot match something wrong.)
- Every user-facing string calls this an estimate. Read them.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/stock_estimate.py backend/app/services/workflows/shelf_stock.py backend/app/services/workflows/__init__.py backend/app/models/__init__.py backend/alembic/versions/
git commit -m "feat(workflows): add shelf stock level estimation module"
```

---

### Task 4: Rollup sweep and Module 3.6 — Low-stock procurement trigger

**Files:**
- Create: `backend/app/services/rollups/__init__.py`, `backend/app/services/rollups/sweep.py`
- Create: `backend/app/services/workflows/procurement.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: Task 3's `StockEstimate`.
- Produces:
  - `run_rollup_sweep() -> None` — scheduled hourly; runs the modules that have no camera trigger
  - a procurement evaluator registered **outside** `MODULES`, because it is not event-driven. Config keys read from the `low_stock_procurement_trigger` `WorkflowRule`:
    - `reorder_fill_pct: float` (default `20.0`)
    - `reorder_cooldown_hours: int` (default `24`)

**Why this module does not live in the event registry.** Spec Section 3.6 says it consumes the output of 3.5. Running it on every shelf event would re-evaluate the threshold on every sample and, without a cooldown, draft a requisition every fifteen minutes for as long as the shelf stays low. It belongs on a timer with a cooldown, which makes it structurally a rollup, not a workflow module — even though it produces a `workflow_exceptions` row like one.

**The exception it writes is `open` with a draft, never `auto_cleared`.** A purchase requisition is an action, and the spec is explicit that nothing is auto-sent to a vendor. The draft sits in the queue exactly like a draft GRN.

- [ ] **Step 1: Write the sweep**

`backend/app/services/rollups/sweep.py`:

```python
"""Scheduled evaluation for the modules with no camera trigger.

Two of the ten modules answer questions about accumulated state rather than
about an event: "is this shelf low enough to reorder?" and "what has demand
done this month?". Running those on every incoming event would re-answer them
hundreds of times an hour and, for procurement, draft a requisition on every
answer.

Hourly. Both questions change on the scale of hours at fastest, and a sweep
that runs more often than its inputs change is just load.
"""
import logging

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.organization import Organization
from app.services.rollups.demand_trend import build_demand_trends
from app.services.workflows.procurement import evaluate_low_stock

logger = logging.getLogger(__name__)


async def run_rollup_sweep() -> None:
    async with async_session_factory() as db:
        orgs = (
            await db.execute(
                select(Organization).where(Organization.deleted_at.is_(None))
            )
        ).scalars().all()

    for org in orgs:
        # One session per org: a failure in one org's rollup must not roll back
        # another's, and a long-running org must not hold one transaction open
        # across the whole fleet.
        async with async_session_factory() as db:
            try:
                await evaluate_low_stock(org, db)
            except Exception:  # noqa: BLE001
                logger.exception("low-stock rollup failed for org %s", org.id)
        async with async_session_factory() as db:
            try:
                await build_demand_trends(org, db)
            except Exception:  # noqa: BLE001
                logger.exception("demand trend rollup failed for org %s", org.id)
```

Register it in `backend/app/main.py` alongside the other sweeps, `"interval", minutes=60, id="workflow_rollup_sweep"`.

- [ ] **Step 2: Write the procurement module**

`backend/app/services/workflows/procurement.py`:

```python
"""Module 3.6 — draft a purchase requisition when a shelf runs low.

Not in the event-driven registry, deliberately. Running on every shelf sample
would re-answer "is this low?" every fifteen minutes and, without a cooldown,
draft a requisition every time the answer stayed yes.

Nothing is sent to a vendor. The draft sits in the exception queue for a human,
exactly like a draft GRN — the spec is explicit about this, and it is the whole
difference between a useful prompt and an automated purchasing system nobody
asked for.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.organization import Organization
from app.models.stock_estimate import StockEstimate
from app.models.workflow import WorkflowException, WorkflowRule

logger = logging.getLogger(__name__)

WORKFLOW_TYPE = "low_stock_procurement_trigger"
DEFAULT_REORDER_FILL_PCT = 20.0
DEFAULT_COOLDOWN_HOURS = 24
# A reading older than this is not evidence about the shelf now — a camera
# that went offline while a shelf was low must not keep drafting requisitions.
MAX_READING_AGE_HOURS = 6


async def evaluate_low_stock(org: Organization, db: AsyncSession) -> int:
    rules = (
        await db.execute(
            select(WorkflowRule).where(
                WorkflowRule.org_id == org.id,
                WorkflowRule.workflow_type == WORKFLOW_TYPE,
                WorkflowRule.enabled.is_(True),
            )
        )
    ).scalars().all()
    if not rules:
        return 0

    now = datetime.now(timezone.utc)
    written = 0

    for rule in rules:
        config = rule.config or {}
        threshold = float(config.get("reorder_fill_pct", DEFAULT_REORDER_FILL_PCT))
        cooldown = timedelta(
            hours=int(config.get("reorder_cooldown_hours", DEFAULT_COOLDOWN_HOURS))
        )

        cameras = (
            await db.execute(
                select(Camera).where(
                    Camera.site_id == rule.site_id,
                    Camera.camera_role.in_(("shelf", "bin")),
                    Camera.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        for camera in cameras:
            latest = (
                await db.execute(
                    select(StockEstimate)
                    .where(StockEstimate.camera_id == camera.id)
                    .order_by(StockEstimate.observed_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if latest is None or latest.fill_pct is None:
                continue
            if now - latest.observed_at > timedelta(hours=MAX_READING_AGE_HOURS):
                continue
            if float(latest.fill_pct) > threshold:
                continue

            # The cooldown is per camera, not per exception: a shelf that stays
            # low for a week should produce one requisition, not seven.
            subject_key = f"camera:{camera.id}:low_stock"
            existing = (
                await db.execute(
                    select(WorkflowException).where(
                        WorkflowException.subject_key == subject_key,
                        WorkflowException.workflow_type == WORKFLOW_TYPE,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                if now - existing.created_at < cooldown:
                    continue
                # Past the cooldown and still low: refresh the same row rather
                # than accumulating one per cycle. `created_at` stays as the
                # first observation; the draft carries the current reading.
                existing.status = "open"
                existing.resolved_at = None
                existing.resolved_by = None
                existing.draft = _draft(camera, latest, threshold)
                existing.discrepancy = _discrepancy(camera, latest, threshold)
                written += 1
                continue

            db.add(
                WorkflowException(
                    org_id=org.id,
                    site_id=rule.site_id,
                    # Procurement has no triggering event of its own; the
                    # reading's event is the closest true answer to "what made
                    # this appear", so the UI can still show a snapshot.
                    event_id=latest.event_id,
                    workflow_rule_id=rule.id,
                    workflow_type=WORKFLOW_TYPE,
                    subject_key=subject_key,
                    status="open",
                    discrepancy=_discrepancy(camera, latest, threshold),
                    draft=_draft(camera, latest, threshold),
                )
            )
            written += 1

    await db.commit()
    return written
```

`WorkflowException.event_id` is `NOT NULL` (Phase 1 Task 6) and this module has no event of its own — which is why Task 3's `StockEstimate` carries `event_id`. Use it, as above. Do **not** make `WorkflowException.event_id` nullable to avoid the problem: a nullable column would let every future module skip providing provenance, and provenance is what makes an exception an audit record rather than an assertion.

Write `_discrepancy` and `_draft` as small module-level helpers:

```python
def _discrepancy(camera: Camera, latest: StockEstimate, threshold: float) -> dict:
    return {
        "reason": "stock_below_reorder_point",
        "camera_name": camera.name,
        "fill_pct": latest.fill_pct,
        "reorder_fill_pct": threshold,
        "sku_hint": latest.sku_hint,
        "observed_at": latest.observed_at.isoformat(),
        "message": (
            f"{camera.name} looks about {latest.fill_pct}% full, below the "
            f"{threshold:g}% reorder point. A fill estimate cannot see shelf depth — "
            f"check before ordering."
        ),
    }


def _draft(camera: Camera, latest: StockEstimate, threshold: float) -> dict:
    return {
        "doc_type": "purchase_requisition",
        "sku_hint": latest.sku_hint,
        "camera_id": str(camera.id),
        "observed_fill_pct": latest.fill_pct,
        "observed_at": latest.observed_at.isoformat(),
        # No quantity. Deciding how much to order needs lead times, minimum
        # order quantities, and a real stock figure — none of which a camera
        # knows. Suggesting a number here would be inventing one.
        "suggested_quantity": None,
        "note": "Draft prepared from a camera estimate. Nothing has been ordered.",
    }
```

- [ ] **Step 3: Verify**

Enable the rule, write a `StockEstimate` at 15% fill, and trigger the sweep manually:

```bash
cd backend && uv run python3 -c "
import asyncio
from app.services.rollups.sweep import run_rollup_sweep
asyncio.run(run_rollup_sweep())
print('swept')
"
```

| Case | Expected |
|---|---|
| Fill 15%, threshold 20% | one `open` row with a draft |
| Sweep again immediately | still one row, unchanged (cooldown) |
| Backdate `created_at` past the cooldown, sweep | same row refreshed, still one |
| Fill 60% | no new row |
| Reading 8 hours old | no row (stale) |
| Rule disabled | no row |

```bash
psql "$POSTGRES_URL" -c "select count(*), max(created_at), max(draft->>'observed_fill_pct') from workflow_exceptions where workflow_type='low_stock_procurement_trigger';"
```

- [ ] **Step 4: Self-review**

- Does a shelf low for a week produce one row or seven? (One. Verify by backdating and sweeping repeatedly.)
- Does refreshing an already-`approved` row silently reopen it? (It does, as written — past the cooldown, status is set back to `open`. Decide: a human who approved a requisition last week and whose shelf is still low probably *does* want a new prompt. But silently clearing `resolved_by` erases who acted. Consider keeping the resolution history in `note` before overwriting, or use a fresh `subject_key` per cooldown period. **Pick one and write down why.**)
- Does the sweep scale? (It is O(orgs × rules × shelf cameras) queries per hour. At ten orgs with ten shelf cameras each that is 100 queries an hour — fine. At 800 cameras it is not. Note the number where it stops being fine.)
- Does `suggested_quantity: None` render sensibly in the UI, or as an empty field that looks broken? (Task 9.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rollups/ backend/app/services/workflows/procurement.py backend/app/main.py
git commit -m "feat(workflows): add low-stock procurement trigger on an hourly rollup"
```

---

### Task 5: Module 3.4 — Material issue verification against BOM

**Files:**
- Modify: `agent/pipeline/prompt_builder.py`, `agent/pipeline/gemini_client.py`
- Create: `backend/app/services/workflows/material_issue.py`
- Modify: `backend/app/services/workflows/__init__.py`

**Interfaces:**
- Consumes: Phase 2's role-addendum map, Phase 1's `ExpectedDocument` with `doc_type="bom"`.
- Produces:
  - `metadata_extra["material"]` on `floor` cameras:

```json
{"material": {"movement": "inbound", "container_count": 3, "material_hint": "Steel coils on a pallet", "material_confidence": 0.7}}
```

  - a module registered under `"material_issue_bom_check"`. Config keys:
    - `quantity_tolerance_pct: float` (default `10.0`)
    - `match_window_hours: int` (default `8`) — a shift, roughly
    - `min_material_confidence: float` (default `0.6`)

**This is the weakest module in the set, and the plan should say so up front.** A BOM specifies materials by part number and quantity. A camera on a factory floor sees containers moving. Bridging those requires the BOM to carry a `containers_per_issue` figure the way Task 3's shelf comparison requires `units_per_full_shelf` — and most BOMs will not. So the module follows Task 3's pattern exactly: record what was seen, compare **only** when the document makes comparison possible, and stay silent otherwise.

Expect this to produce nothing for most customers. That is the correct behaviour, not a bug, and the settings copy in Task 9 says so before anyone enables it.

- [ ] **Step 1: Add the material addendum**

In `agent/pipeline/prompt_builder.py`:

```python
MATERIAL_ADDENDUM = """

This camera watches a production floor. In ADDITION to the schema above,
include a top-level "material" object:

  "material": {{
    "movement": "<inbound | outbound | null>",
    "container_count": <int or null>,
    "material_hint": "<what the material visibly is, or null>",
    "material_confidence": <float 0.0-1.0>
  }}

Rules for "material":
- "inbound" means material moving INTO the production area; "outbound" means
  finished or scrap material leaving it
- Count containers, pallets, or bins — not individual parts inside them
- "material_hint" describes what you can see. Never name a part number"""
```

Add `"floor": (MATERIAL_ADDENDUM,)` to `ROLE_ADDENDA` and parse it in `gemini_client.py` alongside the others, clamping `movement` to the two-value enum or `None`.

The "never name a part number" rule matters: a model that guesses `"SKU-4471-B"` from context produces a `material_hint` that matches a real BOM by coincidence, and a coincidental match is worse than no match.

- [ ] **Step 2: Write the module**

`backend/app/services/workflows/material_issue.py`, registered as `"material_issue_bom_check"`:

```python
"""Module 3.4 — material issued to the floor against what the BOM calls for.

The weakest comparison in the set, and written to fail quietly rather than
loudly. A BOM specifies parts and quantities; a camera sees containers. The
bridge between them is a `containers_per_issue` figure the BOM has to carry,
and most will not.

So: record nothing, claim nothing, unless the document makes the comparison
possible. Producing no findings for most customers is the correct behaviour
here.
"""
```

Body follows Task 3's structure precisely:

1. `if camera.camera_role != "floor": return ignore()`
2. Read `metadata_extra["material"]`; ignore if absent, if `movement != "inbound"`, if `material_confidence` below threshold, or if `container_count is None`.
3. `DocumentMatcher(db).find(org_id=..., site_id=..., doc_types=("bom",), at=event.timestamp, window_hours=window_hours, refs={material_hint} if material_hint else set(), observed={"container_count": n})`.
4. On `result.failure`: **return `ignore()`, not the failure.** Material moving on a factory floor with no open BOM nearby is ordinary — every shift has movement the BOM does not describe. Raising it would fill the queue.
5. `containers_per_issue = document.payload.get("containers_per_issue")`; if absent, `return ignore()`.
6. `expected_containers = float(document.payload["expected_quantity"]) / float(containers_per_issue)`; guard `containers_per_issue > 0`.
7. Compare against `container_count` with `variance_pct`; within tolerance → `match`; outside → `exception` with:

```python
        discrepancy={
            "reason": "material_issue_variance",
            "expected_containers": round(expected_containers, 1),
            "observed_containers": container_count,
            "variance_pct": round(variance_pct, 2),
            "tolerance_pct": tolerance_pct,
            "bom_ref": document.external_ref,
            "material_hint": material_hint,
            "containers_per_issue": containers_per_issue,
            "message": (
                f"{document.external_ref} calls for about "
                f"{round(expected_containers, 1)} containers; the camera counted "
                f"{container_count}. Container counts say nothing about what is "
                f"inside them — check the issue slip."
            ),
        }
```

- [ ] **Step 3: Verify, including the silent cases**

| Case | Setup | Expected |
|---|---|---|
| No BOM in window | material event, no `bom` document | **nothing** — no row |
| BOM without `containers_per_issue` | `expected_quantity: 500` only | **nothing** — no row |
| Agreement | `expected_quantity: 500`, `containers_per_issue: 100`, observed 5 | `auto_cleared` |
| Variance | same, observed 2 | `open`, `variance_pct = 60` |
| Outbound movement | `movement: "outbound"` | **nothing** |

The first two are the ones to check hardest. They are the common configuration, and a module that raises an exception in either of them is unusable on a real factory floor.

- [ ] **Step 4: Self-review**

- Does this module ever produce a finding without a `containers_per_issue` figure? (It must not. There is no defensible default.)
- Does `material_hint` reach `DocumentMatcher` as a ref? (Yes, same as `sku_hint` in Task 3. Confirm a descriptive hint like "STEEL COILS" cannot match a real BOM reference by accident — `normalise_ref` keeps punctuation, so it will not.)
- Does the message avoid claiming to know what is in a container? (Read it. "Container counts say nothing about what is inside them" is doing real work.)
- Is the "return ignore, not failure" choice in step 4 written down in the code, not just here? (A future reader will otherwise "fix" it to match `dispatch_verification`, which returns the failure — and the two are different for a reason.)

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline/prompt_builder.py agent/pipeline/gemini_client.py backend/app/services/workflows/material_issue.py backend/app/services/workflows/__init__.py
git commit -m "feat(workflows): add material issue BOM verification module"
```

---

### Task 6: Module 3.9 — Vendor scorecard

**Files:**
- Create: `backend/app/services/rollups/vendor_scorecard.py`

**Interfaces:**
- Consumes: `WorkflowException` history from modules 3.1, 3.2, 3.3; `ExpectedDocument.payload["vendor"]`.
- Produces: `build_vendor_scorecard(org_id, site_id, start, end, db) -> list[VendorScore]`, where `VendorScore` is a pydantic model:

```python
class VendorScore(BaseModel):
    vendor: str
    deliveries_observed: int
    on_time_pct: float | None
    short_delivery_pct: float | None
    overbilled_pct: float | None
    unexpected_receiving_count: int
    # None when the denominator is too small to mean anything. The UI renders
    # "not enough data", never 0% or 100%.
    sample_too_small: bool
```

**Computed on read, not materialised.** The scorecard is an aggregate over `workflow_exceptions`, which is already indexed by `(site_id, status, created_at)`. A date-bounded query over one org's exceptions is small — the alternative, a nightly materialised table, adds a staleness window to a number people will act on. Task 7's demand trend goes the other way, and the reason for the difference is written into both files.

**A scorecard is the most consequential output in this entire feature.** Everything else says "these two numbers disagree, go look". This says "this vendor short-delivers 30% of the time", and someone will take that into a contract negotiation. Three rules follow:

1. **Small denominators produce `None`, not a percentage.** Three deliveries and one discrepancy is not a 33% short-delivery rate. `MIN_SAMPLE = 10` and `sample_too_small` is on the response so the UI cannot render around it.
2. **Every percentage is of *observations*, not of deliveries.** The denominator is deliveries where the camera produced a usable count, not all deliveries — and the response says which.
3. **The word "short-delivery" describes the finding, never the vendor.** The metric is "deliveries where the camera counted fewer than the paperwork", which is what was actually measured. Under-counting is a known property of the measurement (Phase 2 limitation #2), so the scorecard carries that caveat as a field, not as a footnote someone can crop out.

- [ ] **Step 1: Write the builder**

```python
"""Module 3.9 — per-vendor rollup of what the other modules found.

Computed on read rather than materialised: the query is date-bounded over one
org's exceptions and the index already exists, and a nightly table would add a
staleness window to a number people take into vendor conversations.
(Module 3.10 goes the other way, for reasons written in that file.)

This is the most consequential output in the feature. Everything else says
"these numbers disagree, go look". This says something about a company. So:
small samples return None rather than a percentage, denominators are stated,
and the known under-counting of camera-based quantities travels with the
result as a field rather than as a footnote.
"""
```

Implementation shape:

- One query pulling `WorkflowException` joined to `ExpectedDocument`, filtered by `org_id`, optional `site_id`, `created_at` between `start` and `end`, and `workflow_type` in the three contributing modules. Apply `scope_to_sites` at the API layer (Task 8), not here — this function takes an already-authorised scope.
- Group in Python by `payload["vendor"]`, skipping rows with no vendor. Rows from `backdoor_receiving` have no document and therefore no vendor: count those into a site-level `unexpected_receiving_count` returned separately, **not** attributed to a vendor. Attributing an unexplained delivery to whichever vendor was nearest in time would be a guess with a company's name on it.
- `short_delivery_pct` = `dock_grn_match` exceptions with `reason == "quantity_mismatch"` and `observed < expected`, over all `dock_grn_match` verdicts for that vendor.
- `overbilled_pct` = `vendor_overbill_check` exceptions with `reason == "invoiced_above_observed"`, over all `vendor_overbill_check` verdicts for that vendor.
- `on_time_pct` = from `freight_dock_scheduling` where a vendor is on the matched document; `None` when that module is not enabled.
- Any metric whose denominator is below `MIN_SAMPLE = 10` returns `None` and sets `sample_too_small = True`.

Add to the returned payload a constant caveat string the API passes through verbatim:

```python
QUANTITY_CAVEAT = (
    "Quantities come from camera estimates that under-report deliveries "
    "unloaded in waves. Treat these figures as a prompt to review footage, not "
    "as a measurement of what a vendor delivered."
)
```

- [ ] **Step 2: Verify the small-sample rule first**

Seed exactly three `dock_grn_match` verdicts for one vendor, one of them a shortfall.

Expected: `short_delivery_pct is None`, `sample_too_small is True`. **Not** `33.3`.

Then seed twelve, four of them shortfalls. Expected: `33.33`, `sample_too_small: False`.

Then seed a `backdoor_receiving` exception and confirm it appears in the site-level count and is attributed to **no** vendor.

- [ ] **Step 3: Self-review**

- Can any vendor percentage be rendered from fewer than ten observations? (Trace every return path.)
- Is a `backdoor_receiving` finding ever attributed to a vendor? (It must not be.)
- Does the caveat string travel with the data through the API and into the UI, or does it stop at the service? (It must reach the rendered page and any export.)
- Does the query filter `org_id`? Read the line.
- Should `rejected` exceptions count against a vendor? (They should not — a human looked and said it was not a real finding. Confirm `status == "rejected"` rows are excluded from numerators, and decide whether they stay in denominators. Argument for keeping them: they were observations. Write down the choice.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/rollups/vendor_scorecard.py
git commit -m "feat(rollups): add vendor scorecard aggregation"
```

---

### Task 7: Module 3.10 — Demand trend feed

**Files:**
- Create: `backend/app/models/demand_trend.py`
- Create: `backend/app/services/rollups/demand_trend.py`
- Create: `backend/alembic/versions/a7b8c9d0e1f2_demand_trends.py`, chaining off Task 3's `f6a7b8c9d0e1` — Task 4 adds no schema, so this is the next link, not a fourth head
- Modify: `backend/app/services/rollups/sweep.py` (already calls it — verify the import)

**Interfaces:**
- Consumes: `DeliverySession` (inbound and outbound), `StockEstimate`.
- Produces:
  - `DemandTrend`: `id, org_id, site_id, bucket_date, direction, sessions, observed_units_max_sum, avg_fill_pct, computed_at` — unique on `(site_id, bucket_date, direction)`
  - `build_demand_trends(org, db) -> int`

**Materialised, unlike Task 6, and here is why.** The scorecard aggregates exceptions — hundreds of rows over a month. This aggregates delivery sessions and shelf readings over *months*, and shelf readings arrive every fifteen minutes per camera. Computing a twelve-month trend on every page load would scan hundreds of thousands of rows. Daily buckets computed once and kept are the right shape, and a day-old bucket is not a staleness problem for a trend line the way it would be for a vendor percentage.

**Trend statistics only. No forecast.** The spec says this twice and this task honours it literally: the module writes daily buckets, and the API (Task 8) computes a 7-day and 28-day moving average plus a same-weekday-comparison flag over them. There is no model, nothing is predicted, and nothing in the response is called a forecast. A number presented to a customer as next week's demand is a commitment, and this feature has no basis for making one.

- [ ] **Step 1: Write the model and migration**

`DemandTrend` following Phase 1 Task 6's conventions. `bucket_date` is a `Date` in the **org's timezone**, not UTC — a trend line a customer reads is in their own days. Take the timezone from `Organization.timezone`, which every org already has.

Unique constraint `uq_demand_trend_bucket` on `(site_id, bucket_date, direction)` so the sweep can upsert idempotently — it runs hourly and recomputes the current and previous day every time.

- [ ] **Step 2: Write the builder**

```python
"""Module 3.10 — daily activity buckets, from which trends are drawn.

Materialised, unlike the vendor scorecard: this aggregates months of delivery
sessions and shelf readings, and shelf readings arrive every fifteen minutes
per camera. A twelve-month trend computed on page load would scan hundreds of
thousands of rows; a day-old bucket costs a trend line nothing.

Buckets only. The moving averages live in the API and are arithmetic. There is
no model here and nothing is predicted — the spec says trend statistics only,
twice, and a number a customer reads as next week's demand is a commitment
this feature cannot back.
"""

# Recompute today and yesterday on every hourly sweep: today because it is
# still filling, yesterday because a late-arriving event from an edge box that
# was offline can land in it.
RECOMPUTE_DAYS = 2
```

For each site in the org, for each of the last `RECOMPUTE_DAYS` local days, for each direction: count sessions, sum `totals["carton_count_max"]`, and average `fill_pct` across `StockEstimate` rows in that day. Upsert with `pg_insert(...).on_conflict_do_update(constraint="uq_demand_trend_bucket", ...)`, exactly as Phase 1's Tally sync upserts `expected_documents`.

Name the summed column `observed_units_max_sum` and not `total_units`. It is a sum of per-session maxima — every consumer needs to see that in the name, because "total units received" is precisely what it is not.

- [ ] **Step 3: Verify idempotency and the timezone**

Run the sweep twice in a row:

```bash
psql "$POSTGRES_URL" -c "select bucket_date, direction, sessions, observed_units_max_sum from demand_trends order by bucket_date desc limit 6;"
```

Expected: identical rows both times, no duplicates.

```bash
cd backend && uv run alembic heads
```

Expected: one head, `a7b8c9d0e1f2 (head)`. Four migrations across this plan, in a single chain: `e5f6a7b8c9d0` → `f6a7b8c9d0e1` → `a7b8c9d0e1f2`, off Phase 2's `d4e5f6a7b8c9`.

Then set an org's timezone to `Asia/Kolkata`, post a session at 19:00 UTC (00:30 next day local), sweep, and confirm the session lands in the **local** day's bucket. This is the check most likely to fail silently and least likely to be noticed for months.

- [ ] **Step 4: Self-review**

- Is the bucket boundary in the org's timezone everywhere, or does one query use UTC? (Read every date expression.)
- Does the upsert constraint name match the migration exactly? (A typo here fails at runtime, not at import.)
- Does `RECOMPUTE_DAYS = 2` cover the offline-queue replay window? (An edge box offline for three days replays events into a bucket the sweep no longer recomputes. Either widen it, or accept and document that trends can under-count after a long outage. **Decide and write it down.**)
- Is anything in the output called a forecast, a prediction, or an expectation? (Grep for those words.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/demand_trend.py backend/app/services/rollups/demand_trend.py backend/app/services/rollups/sweep.py backend/alembic/versions/
git commit -m "feat(rollups): add daily demand trend buckets"
```

---

### Task 8: Reporting API — export, scorecard, trends, instrumentation

**Files:**
- Create: `backend/app/services/reporting/reconciliation.py`
- Create: `backend/app/services/reporting/instrumentation.py`
- Create: `backend/app/api/reports.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: Tasks 6 and 7's builders, Phase 1's `WorkflowException`.
- Produces:

```
GET /api/reports/vendor-scorecard?site_id=&start=&end=
GET /api/reports/demand-trends?site_id=&direction=&days=
GET /api/reports/instrumentation?site_id=&days=
GET /api/reports/reconciliation.csv?site_id=&start=&end=
```

  - `InstrumentationResponse`: `total_verdicts, auto_cleared, open, approved, rejected, auto_clear_rate, rejection_rate, median_time_to_resolve_minutes, by_workflow_type`

**Instrumentation is spec Section 8, and it is the thing that makes every other number in this feature arguable.** Auto-clear rate says how much work the layer is actually saving. Rejection rate is the closest available proxy for false-positive rate — a human looked and said no. Time-to-resolve says whether the queue is being worked or ignored. Without these, "our system reconciles your books" is an unfalsifiable claim, which is the state the spec's Section 9 exists to prevent.

**`rejection_rate` is a proxy, not a false-positive rate, and the response says so in a field.** An operator rejects for reasons that are not "the system was wrong" — a real discrepancy already settled with the vendor, a duplicate, a shift ending. Labelling it "false positive rate" in an API would put a number nobody measured into a slide deck.

- [ ] **Step 1: Write the instrumentation service**

Aggregate `workflow_exceptions` over the window, grouped by `workflow_type`:

- `auto_clear_rate` = `auto_cleared / total_verdicts`
- `rejection_rate` = `rejected / (approved + rejected)`, `None` when the denominator is under `MIN_RESOLVED = 10`
- `median_time_to_resolve_minutes` from `resolved_at - created_at` over resolved rows, `None` under the same floor

Include the literal field:

```python
    rejection_rate_is_proxy: bool = True
    rejection_rate_note: str = (
        "Rejections are the closest available proxy for false positives. "
        "Operators also reject findings that were correct but already handled, "
        "so this over-states the error rate by an unmeasured amount."
    )
```

- [ ] **Step 2: Write the CSV export**

`reconciliation.py` builds a CSV streamed via `StreamingResponse` with `text/csv`. Columns: `exception_id, created_at, site, camera, workflow_type, status, reason, expected, observed, variance_pct, document_ref, vendor, resolved_at, resolved_by, note`.

**Three header rows precede the column header**, and they are not decoration:

```
# NightWatch camera-to-books reconciliation export
# Quantities are CAMERA ESTIMATES. They under-report deliveries unloaded in waves and cannot see shelf depth or container contents.
# This is a review aid, not an audited record, and nothing here was posted to any accounting system.
```

A CSV leaves the product and gets forwarded, pasted into a spreadsheet, and attached to an email. Caveats that live only in the web UI do not survive that trip. Anyone stripping these lines is making a deliberate choice, which is the point.

Cap the export at 10,000 rows and return `400` with a message naming the fix (narrow the date range) above it — a streaming export of an unbounded query is a way to take the database down from an authenticated endpoint.

- [ ] **Step 3: Write the API**

`backend/app/api/reports.py`, `prefix="/api/reports"`. Every endpoint:

- resolves `org_id` from `get_current_user`, never from a parameter
- applies `scope_to_sites(q, <Model>.site_id, user)` before calling any builder
- validates `site_id` with `user_may_access_site` when supplied, returning `404` when not permitted
- caps `days` at 400 and the `start`/`end` span at 400 days

Register the router in `main.py`.

- [ ] **Step 4: Verify**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

```bash
curl -s "localhost:8080/api/reports/instrumentation?days=30" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: rates present, `rejection_rate_is_proxy: true`, and `null` rates on a fresh install rather than `0.0`.

```bash
curl -s "localhost:8080/api/reports/reconciliation.csv?start=2026-08-01&end=2026-08-31" -H "Authorization: Bearer $TOKEN" | head -6
```

Expected: the three caveat lines, then the column header, then data.

Repeat every check from Phase 1 Task 10 Step 6 against all four endpoints — another org's token, and a site-restricted user in the same org. Expected: `404` or empty, never another org's vendor names. A vendor scorecard leaking across orgs would expose one customer's supplier relationships to another, which is a materially worse failure than leaking an event.

- [ ] **Step 5: Self-review**

- Does the CSV keep its caveat lines under every filter combination, including an empty result set? (An empty export must still carry them.)
- Is `rejection_rate` ever labelled "false positive" in code, response, or docs? (Grep.)
- Are the row and range caps enforced before the query runs, not after? (After is not a cap.)
- Does `scope_to_sites` reach every one of the four endpoints? Tick them off individually.
- Does the scorecard endpoint pass `QUANTITY_CAVEAT` through to the response? (Task 6 Step 3 asked for this — verify it actually arrives here.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/reporting/ backend/app/api/reports.py backend/app/main.py
git commit -m "feat(reports): add scorecard, trends, instrumentation, and reconciliation export"
```

---

### Task 9: Reports page and settings for the final three modules

**Files:**
- Create: `frontend/src/app/reports/page.tsx`
- Modify: `frontend/src/lib/api.ts`, `frontend/src/types/index.ts`
- Modify: `frontend/src/app/settings/page.tsx` (three more catalogue entries)
- Modify: `frontend/src/components/layout/sidebar.tsx`, `app-shell.tsx`
- Modify: `frontend/src/components/exceptions/exception-detail.tsx` (stock and material panes)

**Interfaces:**
- Consumes: Task 8's four endpoints; Phase 2's `WORKFLOW_CATALOGUE`.
- Produces: `/reports` with four sections, and settings entries for the last three modules.

**Charts:** before writing any chart code, load the `dataviz` skill. The demand trend is the first chart in this feature and it should read as part of a system rather than as a one-off.

- [ ] **Step 1: Extend the workflow catalogue**

Add three entries to `WORKFLOW_CATALOGUE` in the shared module Phase 2 created. Copy, verbatim — this text is the only warning a customer gets before enabling something that may do nothing or may cost money:

```ts
  {
    type: "shelf_stock_level_estimate",
    title: "Shelf stock estimate",
    description:
      "Samples shelf and bin cameras on a timer and estimates how full they look. Unlike every other workflow, this makes AI calls on a schedule rather than when something happens — it will consume your daily AI budget continuously. Fill estimates cannot see shelf depth.",
    fields: [
      { key: "variance_tolerance_pct", label: "Tolerance", type: "number", min: 0, max: 100, step: 1, suffix: "%", help: "Loose by default: a fill estimate is a much weaker signal than a carton count." },
      { key: "min_shelf_confidence", label: "Min. confidence", type: "number", min: 0, max: 1, step: 0.05, help: "" },
    ],
  },
  {
    type: "low_stock_procurement_trigger",
    title: "Low-stock requisition draft",
    description:
      "Drafts a purchase requisition when a shelf looks low. Requires shelf stock estimate to be on. Nothing is ordered and no quantity is suggested — a camera cannot know lead times or minimum order quantities.",
    fields: [
      { key: "reorder_fill_pct", label: "Reorder point", type: "number", min: 0, max: 100, step: 5, suffix: "%", help: "" },
      { key: "reorder_cooldown_hours", label: "Cooldown", type: "number", min: 1, max: 336, step: 1, suffix: "h", help: "How long before a shelf that stays low prompts again." },
    ],
  },
  {
    type: "material_issue_bom_check",
    title: "Material issue check",
    description:
      "Compares containers moving onto the production floor against the BOM. Only produces findings when your BOM carries a containers-per-issue figure — for most setups it will correctly produce nothing.",
    fields: [
      { key: "quantity_tolerance_pct", label: "Tolerance", type: "number", min: 0, max: 100, step: 1, suffix: "%", help: "" },
      { key: "min_material_confidence", label: "Min. confidence", type: "number", min: 0, max: 1, step: 0.05, help: "" },
    ],
  },
```

Add a dependency note under the requisition card: when `shelf_stock_level_estimate` is disabled for the site, render "Turn on shelf stock estimate first — this has nothing to read without it" and disable the toggle. A module that can be enabled but cannot work is a support ticket.

- [ ] **Step 2: Build the reports page**

Four sections on `/reports`, site-selectable, matching the exceptions page's visual language:

1. **How the layer is performing** — instrumentation. Auto-clear rate as the headline. Render the rejection rate with its proxy note visible next to it, not in a tooltip. Show "not enough resolved items yet" where the API returned `null`.
2. **Vendors** — a table from the scorecard. Render `null` metrics as "not enough data", never as `0%` or a dash that reads as zero. Print `QUANTITY_CAVEAT` above the table, not below it.
3. **Activity trend** — a line chart of `sessions` and `observed_units_max_sum` per day with a 7-day moving average, using the `dataviz` palette. Axis label: "Sessions observed", never "Deliveries received". No projection line, no shaded future region.
4. **Export** — date range plus a download button hitting the CSV endpoint. Show the three caveat lines in the UI above the button so nobody is surprised by them in the file.

- [ ] **Step 3: Add stock and material detail panes**

In `exception-detail.tsx`, handle the new reasons: `stock_variance` renders fill percentage, book quantity, and the units-per-shelf figure used for conversion; `stock_below_reorder_point` renders the fill percentage against the reorder point and the draft with its empty `suggested_quantity` shown explicitly as "not suggested — a camera cannot know your lead times" rather than as a blank field; `material_issue_variance` renders expected and observed container counts with the containers-per-issue divisor.

- [ ] **Step 4: Build and verify**

```bash
cd frontend && npm run build
```

Then, against seeded data:

1. `/settings` shows eight cards; the requisition card is disabled with its explanation when shelf estimate is off.
2. `/reports` renders all four sections; a fresh install shows "not enough data" everywhere rather than a wall of zeros.
3. The scorecard caveat is visible above the table without scrolling.
4. The exported CSV's first three lines are the caveats.
5. The trend chart has no projection and its axis says "Sessions observed".
6. A site-restricted user sees only their sites in every section.

- [ ] **Step 5: Self-review**

- Does any surface render a `null` metric as `0%`? (This is the single most likely way this page misleads someone. Check every metric.)
- Does the chart imply a forecast in any way — a dashed continuation, a shaded band, a label like "projected"? (It must not.)
- Is the scorecard caveat above the fold, or below a long table? (Below is the same as absent.)
- Does the settings copy for shelf stock mention the continuous AI cost *before* the toggle? (It is the only warning a customer gets.)
- Dark mode only. No light-mode classes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/reports/ frontend/src/lib/api.ts frontend/src/types/index.ts frontend/src/app/settings/page.tsx frontend/src/components/layout/ frontend/src/components/exceptions/
git commit -m "feat(frontend): add reports page and settings for stock, procurement, and BOM modules"
```

---

## Phase 3 acceptance

All ten modules exist and the layer has a reporting surface. Checked by hand:

- [ ] One delivery produces exactly one `dock_grn_match` exception, keyed on the session.
- [ ] A `shelf` camera produces `shelf_sample` events on a timer with no motion in frame, and produces none when the site's AI budget is exhausted — while ordinary motion-triggered events continue to be accepted.
- [ ] `shelf_sample` events do not trigger alert rules.
- [ ] Shelf estimation with no `stock_on_hand` document writes a `StockEstimate` and no exception.
- [ ] A shelf low for a week produces one requisition draft, not seven, and the draft suggests no quantity.
- [ ] Material issue produces nothing when the BOM carries no `containers_per_issue`.
- [ ] A vendor with three observations shows "not enough data", not `33%`.
- [ ] `backdoor_receiving` findings appear in the site-level count and are attributed to no vendor.
- [ ] Demand trend buckets are idempotent across repeated sweeps and land in the org's local day, verified with a non-UTC timezone.
- [ ] The reconciliation CSV carries its three caveat lines even when empty, and refuses ranges over 10,000 rows with a message naming the fix.
- [ ] `rejection_rate` is never labelled a false-positive rate anywhere in code, API, or UI.
- [ ] Cross-org and site-restricted checks pass on all four report endpoints — in particular, no org can see another's vendor names.
- [ ] Real-Tally validation is green for every report the connector pulls (spec Section 9). **Until this is done, no "audit-ready" or "reconciliation" claim to any prospect, regardless of the export being named reconciliation.csv.**
- [ ] `cd backend && uv run python3 -c "from app.main import app"`, `cd agent && go build ./...`, and `cd frontend && npm run build` all pass.

## What is still true after all three phases

Carry these into any pilot conversation:

1. **Every quantity in this feature is a camera estimate.** Session totals are per-frame maxima that under-report; shelf fill cannot see depth; container counts say nothing about contents. Three phases of work did not change that, and no amount of further work on this architecture will — it needs either a different sensor or object identity across frames.
2. **No unit reconciliation.** Cartons compared against a document in pieces still produces a meaningless variance in every module. Nothing detects it.
3. **The control plane is still single-replica** (Phase 2 limitation #1). This caps the backend at one replica for any customer using the agent Tally transport, which is a scaling ceiling, not a rough edge.
4. **Gemini token accounting may still be unmeasured.** If Phase 3 Task 2's self-review decided against fixing `_call_gemini`'s discarded `usage_metadata`, then every cost figure in this feature — including the shelf sampling cap that gates a continuously-spending loop — is a fixed guess.
5. **Every threshold is still a guess** unless a pilot moved it. They are all config keys; check what a real customer's values ended up being before shipping new defaults.

## Beyond Phase 3

Deliberately not planned, in the order they are most likely to be wanted:

- **Write-back to Tally with maker-checker.** Spec Section 8. The whole feature is currently read-only, and every draft waits for a human to key it in. Making it write is a different risk posture and needs its own design — an approval that posts to a customer's books cannot be a button someone clicks by accident, and a bug in it corrupts accounting data rather than producing a bad suggestion. Do not start this until the instrumentation from Task 8 shows a real auto-clear rate against real data.
- **A second connector.** The `Transport` seam and the `expected_documents` shape were built to make this cheap. Which system comes second should be decided by customers, not by us.
- **Cross-frame object identity for quantities.** The one change that would turn "counted at most" into a count. Deliberately unplanned: it needs a decision about tracking and retention that resembles the re-identification question this codebase has already answered "no" to once, and reopening it should be a product decision, not an implementation detail of a stock counter.
