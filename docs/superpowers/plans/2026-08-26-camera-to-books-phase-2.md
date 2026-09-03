# Camera-to-Books Workflow Layer — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build out the dock/gate/dispatch family of workflows — vendor over-billing, back-door receiving, dispatch verification, and freight scheduling — on top of a matcher extracted from Phase 1, plus the delivery-session concept all four need and the on-prem Tally bridge real customers will require.

**Architecture:** Phase 1 proved one module end to end with hardcoded matching logic. Phase 2 extracts that logic into a `DocumentMatcher` now that there are four modules to extract it from, adds `delivery_sessions` so a truck unloaded over twenty minutes is one subject rather than forty independent comparisons, teaches the edge pipeline to report goods on more camera roles and vehicles on gate cameras, and replaces the Phase 1 HTTP transport with an agent-relayed one so Tally does not have to be reachable from the cloud.

**Tech Stack:** Same as Phase 1 — FastAPI + SQLAlchemy 2.0 async + Alembic + PostgreSQL + Redis on the backend, Python dataclasses in `agent/pipeline/`, Go in `agent/`, Next.js + TanStack Query on the frontend.

**Spec:** `docs/superpowers/specs/2026-08-26-camera-to-books-spec.md` — modules 3.2, 3.3, 3.7, 3.8, and Section 4's on-prem note. Read Appendix A.8 first: this plan was written before Phase 1 shipped, and Task 1 is the part most likely to need rewriting because of it.

**Depends on:** `2026-08-26-camera-to-books-phase-1.md`, complete and merged. Every task here consumes interfaces Phase 1 produced.

---

## Global Constraints

Everything in Phase 1's Global Constraints section still applies verbatim. In addition:

- **`org_id` filtering is the boundary that matters most in this phase.** Modules now compare quantities across *sessions* and *vendors*, and a missing filter would attribute one customer's short delivery to another customer's vendor. Every candidate query gets read twice.
- **No re-identification, no biometrics.** This holds for vehicles as it does for people. Plate text, where captured at all, is opt-in per rule, stored on the event, and never used to link activity across sites or orgs. See Task 2.
- **Alembic chain:** Phase 1's head is `b2c3d4e5f6a7`. Phase 2 chains off it in task order.
- **Nothing is written back to Tally.** Still. Write-back with maker-checker is deferred past Phase 3 — see that plan's closing section.
- **Every threshold in this plan is a starting guess.** No field data exists behind any window, tolerance, or gap value here. Each is marked where it appears, and each is a `config` key so it can be changed without a deploy.

---

## File Structure

**Backend — created**

| File | Responsibility |
|---|---|
| `backend/app/services/workflows/matching.py` | `DocumentMatcher` — the candidate query, ref narrowing, and ambiguity handling extracted from `dock_grn` |
| `backend/app/models/delivery_session.py` | `DeliverySession` — many events at one camera aggregated into one delivery |
| `backend/app/services/workflows/sessions.py` | Opens, extends, and closes delivery sessions from incoming events |
| `backend/app/services/workflows/vendor_overbill.py` | Module 3.2 |
| `backend/app/services/workflows/backdoor_receiving.py` | Module 3.3 |
| `backend/app/services/workflows/dispatch_verification.py` | Module 3.7 |
| `backend/app/services/workflows/freight_scheduling.py` | Module 3.8 |
| `backend/app/connectors/tally/agent_transport.py` | Tally over the agent control WebSocket |
| `backend/alembic/versions/b8c9d0e1f2a3_capture_vehicle_refs.py` | Task 2 migration |
| `backend/alembic/versions/c3d4e5f6a7b8_delivery_sessions.py` | Task 3 migration |
| `backend/alembic/versions/d4e5f6a7b8c9_workflow_subject_key.py` | Task 3 migration, second half |

**Backend — modified**

| File | Change |
|---|---|
| `backend/app/services/workflows/dock_grn.py` | Refactored onto `DocumentMatcher`; becomes session-aware |
| `backend/app/services/workflows/engine.py` | Session assignment before dispatch; `subject_key` upsert |
| `backend/app/services/workflows/outcome.py` | `WorkflowOutcome.subject_key` |
| `backend/app/models/workflow.py` | `WorkflowException.subject_key`, `delivery_session_id` |
| `backend/app/api/agent_control.py` | `tally_query` command + response correlation |
| `backend/app/connectors/tally/client.py` | `REPORT_DOC_TYPES` gains Sales Order |
| `backend/app/connectors/tally/sync.py` | Transport selection per org |
| `backend/app/api/workflows.py` | Session detail on the exception response |
| `backend/app/schemas/workflow.py` | Session fields |

**Edge pipeline / agent — modified**

| File | Change |
|---|---|
| `agent/pipeline/prompt_builder.py` | Role → addendum map; vehicle addendum |
| `agent/pipeline/gemini_client.py` | Parses the vehicle block |
| `agent/internal/tally/` | Go: local Tally HTTP proxy driven by control-socket commands |

**Frontend — modified**

| File | Change |
|---|---|
| `frontend/src/app/settings/page.tsx` | All enabled workflows, not just one |
| `frontend/src/components/exceptions/exception-detail.tsx` | Renders session totals and vehicle observations |
| `frontend/src/types/index.ts` | `WorkflowType` union widened; session types |

---

### Task 1: Extract `DocumentMatcher` from `dock_grn`

**Files:**
- Create: `backend/app/services/workflows/matching.py`
- Modify: `backend/app/services/workflows/dock_grn.py`

**Interfaces:**
- Consumes: Phase 1's `ExpectedDocument`, `WorkflowOutcome`.
- Produces:
  - `MatchResult` (dataclass): `document: ExpectedDocument | None`, `failure: WorkflowOutcome | None`. Exactly one is set.
  - `DocumentMatcher(db).find(org_id, site_id, doc_types, at, window_hours, refs, statuses=("open",)) -> MatchResult`

**Read this before writing any code.** This task proposes a shape inferred from one shipped module and three designed ones. Open Phase 1's `dock_grn.py` as it actually landed and compare it against the extraction below. If the pilot changed the matching rule — a different ambiguity policy, a status filter that turned out wrong, site attribution that had to be loosened — the extraction changes with it. Rewriting this task is the expected outcome of having written it early, not a failure of it.

**What is genuinely common across the four modules, and what is not:**

| Step | 3.1 dock | 3.2 overbill | 3.7 dispatch | 3.8 freight | Common? |
|---|---|---|---|---|---|
| Candidate query by org/site/type/date | ✓ | ✓ | ✓ | ✓ | **yes** |
| Narrow by legible reference | ✓ | ✓ | ✓ | ✓ | **yes** |
| No-match / ambiguity outcomes | ✓ | ✓ | ✓ | ✓ | **yes** |
| Quantity comparison | ✓ | ✓ | ✓ | ✗ | no — 3.8 compares times |
| Draft generation | ✓ | ✗ | ✗ | ✗ | no — only 3.1 drafts |

So the matcher covers finding the document and failing well. Comparison and drafting stay in each module, because three of the four compare different things.

- [ ] **Step 1: Write the matcher**

`backend/app/services/workflows/matching.py`:

```python
"""Finding the one document an observation should be compared against.

Extracted from `dock_grn` once four modules needed it. Deliberately does NOT
cover comparison or draft generation: three of the four modules compare
something different (quantities, invoiced amounts, arrival times), and a
matcher that also compared would have to know which — at which point it is not
a matcher.

The failure outcomes live here because they are the part most easily got
wrong. "More than one document could match" must never resolve to a guess, and
having one implementation of that rule is the point of the extraction.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import ExpectedDocument
from app.services.workflows.outcome import WorkflowOutcome

logger = logging.getLogger(__name__)

MAX_LISTED_CANDIDATES = 10


def normalise_ref(value: str) -> str:
    """Collapse whitespace and case so "po 4471" matches "PO-4471"...

    ...but NOT so far that "PO-4471" matches "PO-44710". Punctuation is kept
    for exactly that reason: a reference number is an identifier, and a
    normaliser that makes near-misses collide silently matches the wrong
    document.
    """
    return "".join(str(value).split()).upper()


@dataclass
class MatchResult:
    """Exactly one of these is set."""

    document: ExpectedDocument | None = None
    failure: WorkflowOutcome | None = None


class DocumentMatcher:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def find(
        self,
        *,
        org_id: uuid.UUID,
        site_id: uuid.UUID,
        doc_types: tuple[str, ...],
        at: datetime,
        window_hours: int,
        refs: set[str] | None = None,
        statuses: tuple[str, ...] = ("open",),
        observed: dict | None = None,
    ) -> MatchResult:
        window_start = at - timedelta(hours=window_hours)
        window_end = at + timedelta(hours=window_hours)

        candidates = (
            await self._db.execute(
                select(ExpectedDocument).where(
                    # The tenant boundary for this entire feature. A missing
                    # org filter here compares one customer's delivery against
                    # another customer's purchase order.
                    ExpectedDocument.org_id == org_id,
                    ExpectedDocument.doc_type.in_(doc_types),
                    ExpectedDocument.status.in_(statuses),
                    or_(
                        ExpectedDocument.site_id == site_id,
                        # Tally has no concept of a site, so documents an org
                        # has not mapped are matchable anywhere within it.
                        ExpectedDocument.site_id.is_(None),
                    ),
                    or_(
                        ExpectedDocument.doc_date.is_(None),
                        ExpectedDocument.doc_date.between(window_start, window_end),
                    ),
                )
            )
        ).scalars().all()

        normalised_refs = {normalise_ref(r) for r in (refs or set()) if r}
        if normalised_refs:
            by_ref = [
                d for d in candidates if normalise_ref(d.external_ref) in normalised_refs
            ]
            if by_ref:
                # A legible reference beats every heuristic. If it matched more
                # than one document the source data is inconsistent, and that
                # is worth surfacing rather than resolving quietly.
                candidates = by_ref

        if not candidates:
            return MatchResult(
                failure=WorkflowOutcome(
                    verdict="exception",
                    discrepancy={
                        "reason": "no_matching_document",
                        "observed": observed or {},
                        "doc_types": list(doc_types),
                        "visible_refs": sorted(normalised_refs),
                        "window_hours": window_hours,
                        "message": (
                            "No open "
                            + " or ".join(t.upper() for t in doc_types)
                            + " for this site falls in the matching window."
                        ),
                    },
                )
            )

        if len(candidates) > 1:
            return MatchResult(
                failure=WorkflowOutcome(
                    verdict="exception",
                    discrepancy={
                        "reason": "ambiguous_document",
                        "observed": observed or {},
                        "candidates": [
                            {
                                "id": str(d.id),
                                "external_ref": d.external_ref,
                                "doc_type": d.doc_type,
                                "doc_date": d.doc_date.isoformat() if d.doc_date else None,
                            }
                            for d in candidates[:MAX_LISTED_CANDIDATES]
                        ],
                        "candidate_count": len(candidates),
                        "message": (
                            "More than one open document could match this and no "
                            "reference number was legible. Pick the right one rather "
                            "than letting the system guess."
                        ),
                    },
                )
            )

        return MatchResult(document=candidates[0])
```

- [ ] **Step 2: Refactor `dock_grn` onto it**

In `backend/app/services/workflows/dock_grn.py`, delete `_normalise_ref`, `MAX_LISTED_CANDIDATES`, the candidate query, the ref narrowing, and both failure branches. Replace them with:

```python
    result = await DocumentMatcher(db).find(
        org_id=event.org_id,
        site_id=event.site_id,
        doc_types=("po", "grn"),
        at=event.timestamp,
        window_hours=window_hours,
        refs={r for r in (goods.get("visible_refs") or []) if r},
        observed={"carton_count": carton_count, "pallet_count": pallet_count},
    )
    if result.failure is not None:
        return result.failure
    document = result.document
```

and update the imports:

```python
from app.services.workflows.matching import DocumentMatcher
```

Everything from `expected_qty = document.payload.get("expected_quantity")` onward stays exactly as it was — the comparison and the draft are this module's own.

- [ ] **Step 3: Verify the refactor changed no behaviour**

Re-run every case from Phase 1 Task 8 Step 4 — match, mismatch, no-match, ambiguous — and confirm identical `discrepancy` JSON, field for field. This is a pure refactor; any difference is a regression.

```bash
psql "$POSTGRES_URL" -c "select status, discrepancy from workflow_exceptions order by created_at desc limit 4;"
```

The one intentional difference: `no_matching_document`'s `message` is now generated from `doc_types` rather than hardcoded, so it reads "No open PO or GRN for this site falls in the matching window." Confirm that is the only change.

- [ ] **Step 4: Self-review**

- Is `org_id` filtered in the extracted query? Read the line. It is the only thing standing between two customers' books.
- Did the extraction change the ambiguity policy in any way? (It must not — one document wins only when it is the only candidate, or the only ref match.)
- Does `normalise_ref` still reject near-misses? (`PO-4471` vs `PO-44710` — check by hand.)
- Is `MatchResult`'s "exactly one is set" invariant actually enforced, or merely documented? (It is documented. Decide whether that is enough for two callers; it will have five by the end of this plan.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflows/matching.py backend/app/services/workflows/dock_grn.py
git commit -m "refactor(workflows): extract DocumentMatcher from dock GRN module"
```

---

### Task 2: Role-driven prompt addenda and vehicle observation

**Files:**
- Modify: `agent/pipeline/prompt_builder.py`
- Modify: `agent/pipeline/gemini_client.py`

**Interfaces:**
- Consumes: Phase 1 Task 5's `DOCK_ADDENDUM` and `DetectedEvent.metadata`.
- Produces:
  - `metadata_extra["goods"]` on events from **any** camera whose role is `dock`, `gate`, `dispatch`, `packing`, or `other` — previously `dock` only. Same four keys.
  - `metadata_extra["vehicle"]` on `gate` cameras, shaped:

```json
{"vehicle": {"action": "arrival", "vehicle_type": "truck", "plate_text": null, "vehicle_confidence": 0.8}}
```

`action` is `"arrival"`, `"departure"`, or `null`. `plate_text` is `null` unless plate capture is explicitly turned on for the camera.

**Why goods on more roles:** module 3.3 detects goods arriving at a camera that is *not* the designated dock. That only works if non-dock cameras report goods at all. Restricting the addendum to `dock` in Phase 1 was correct then and is the blocker now.

**Plate text is off by default, and here is why.** This codebase deliberately avoids identity claims — cross-camera journeys carry a "may or may not be the same person" caveat precisely so a correlation cannot drift into an identification, and re-identification was scoped out rather than deferred. A plate number is not biometric, but it identifies a vehicle and, in practice, a driver. Reading one on every gate event and storing it forever is a different privacy posture from anything currently shipped. So: `capture_vehicle_refs` defaults to `false`, the prompt omits the plate field entirely when it is off, and 3.8 matches on delivery windows rather than plates. Turning it on is a customer decision made once, in settings, not a side effect of enabling freight scheduling.

- [ ] **Step 1: Replace the single addendum with a role map**

In `agent/pipeline/prompt_builder.py`, keep `DOCK_ADDENDUM` exactly as Phase 1 wrote it, rename it `GOODS_ADDENDUM`, and add below it:

```python
VEHICLE_ADDENDUM = """

This camera watches a gate or yard. In ADDITION to the schema above, include a
top-level "vehicle" object:

  "vehicle": {{
    "action": "<arrival | departure | null>",
    "vehicle_type": "<truck | van | car | other | null>",
    "vehicle_confidence": <float 0.0-1.0>
  }}

Rules for "vehicle":
- "arrival" means moving toward or stopping at the premises; "departure" means
  moving away. Use null when direction is genuinely unclear
- A parked vehicle that has not moved is neither an arrival nor a departure
- Never guess the direction from the vehicle's orientation alone"""

PLATE_FIELD_ADDENDUM = """
- Also include "plate_text": the registration number if it is clearly legible,
  otherwise null. Never infer or complete a partially visible plate"""

# Which roles get which addendum. Goods reporting is deliberately wider than
# the dock: module 3.3 exists to catch goods arriving somewhere that is NOT the
# designated dock, and it cannot see what the prompt never asks about.
ROLE_ADDENDA = {
    "dock": (GOODS_ADDENDUM,),
    "gate": (GOODS_ADDENDUM, VEHICLE_ADDENDUM),
    "dispatch": (GOODS_ADDENDUM,),
    "packing": (GOODS_ADDENDUM,),
    "other": (GOODS_ADDENDUM,),
}
```

and replace the Phase 1 tail of `build`:

```python
        for addendum in ROLE_ADDENDA.get(camera_config.camera_role or "", ()):
            prompt += addendum
        if (
            camera_config.camera_role == "gate"
            and camera_config.capture_vehicle_refs
        ):
            prompt += PLATE_FIELD_ADDENDUM
        return prompt
```

Add `capture_vehicle_refs: bool = False` to `CameraConfig` in `agent/pipeline/models.py`, read it in `from_assignment` as `bool(a.get("capture_vehicle_refs", False))`, add the field to `Assignment` in `backend/app/schemas/assignment.py`, add a nullable `capture_vehicle_refs` boolean column to `Camera` (default `false`) via `backend/alembic/versions/b8c9d0e1f2a3_capture_vehicle_refs.py` chaining off Phase 1's head `b2c3d4e5f6a7` and following Phase 1 Task 4's migration shape exactly, and include it in the assignment construction in `backend/app/api/internal.py`.

**Watch the alembic chain.** This is the first Phase 2 migration, so it takes `b2c3d4e5f6a7` as its parent; Task 3's two migrations then chain off *this* one, not off Phase 1's head. Two migrations sharing a parent is two heads, and `alembic upgrade head` fails on it. Verify with `uv run alembic heads` before committing.

- [ ] **Step 2: Parse the vehicle block**

In `agent/pipeline/gemini_client.py`, next to the Phase 1 goods parse:

```python
        vehicle = data.get("vehicle")
        if isinstance(vehicle, dict):
            action = vehicle.get("action")
            plate = vehicle.get("plate_text")
            metadata["vehicle"] = {
                # Anything the model invented outside the enum is dropped
                # rather than stored — a bogus direction is worse than none.
                "action": action if action in ("arrival", "departure") else None,
                "vehicle_type": vehicle.get("vehicle_type"),
                # Only present when the prompt asked for it. Belt and braces:
                # if a model volunteers a plate we did not request, drop it.
                "plate_text": (
                    str(plate)[:16]
                    if plate and camera_config.capture_vehicle_refs
                    else None
                ),
                "vehicle_confidence": float(vehicle.get("vehicle_confidence") or 0.0),
            }
```

- [ ] **Step 3: Verify the prompt matrix**

```bash
cd agent/pipeline && python3 -c "
from models import CameraConfig
from prompt_builder import PromptBuilder
b = PromptBuilder()
def p(role, plates=False):
    return b.build(CameraConfig(camera_id='x', org_id='y', name='c', ingest_mode='rtsp_pull', camera_role=role, capture_vehicle_refs=plates))
assert 'goods' in p('dock') and 'vehicle' not in p('dock')
assert 'goods' in p('gate') and 'vehicle' in p('gate')
assert 'plate_text' not in p('gate'), 'plate asked for without opt-in'
assert 'plate_text' in p('gate', True)
assert 'goods' not in p(None) and 'vehicle' not in p(None)
assert 'goods' in p('other')
print('ok')
"
```

Expected: `ok`. The third assertion is the privacy one — it must hold.

```bash
cd backend && uv run alembic upgrade head && uv run alembic heads
```

Expected: one head, `b8c9d0e1f2a3 (head)`.

- [ ] **Step 4: Verify against a real stream**

Same setup as Phase 1 Task 5 Step 6. Set a camera to `gate`, run the pipeline, and confirm `metadata_extra` carries a `vehicle` object with `plate_text: null`. Then set `capture_vehicle_refs = true` and confirm the field is populated only when a plate is actually legible.

- [ ] **Step 5: Self-review**

- Does a camera with no role still produce a byte-identical payload to Phase 1? (It must — most cameras have no role.)
- Can a plate reach the database when `capture_vehicle_refs` is false? (Two independent guards: the prompt omits the field, and the parser drops it. Confirm both.)
- Does `_load_camera_configs()` in `agent/pipeline/supervisor.py` pass `camera_role` and `capture_vehicle_refs`? (This fallback has silently dropped config fields twice now. Check it again.)
- Is `plate_text` truncated and typed before storage? (`str(...)[:16]` — confirm; a model returning a paragraph must not become a database row.)

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline/prompt_builder.py agent/pipeline/gemini_client.py agent/pipeline/models.py agent/pipeline/supervisor.py backend/app/schemas/assignment.py backend/app/models/camera.py backend/app/api/internal.py backend/alembic/versions/
git commit -m "feat(pipeline): role-driven prompt addenda and opt-in vehicle observation"
```

---

### Task 3: Delivery sessions

**Files:**
- Create: `backend/app/models/delivery_session.py`
- Create: `backend/app/services/workflows/sessions.py`
- Create: `backend/alembic/versions/c3d4e5f6a7b8_delivery_sessions.py`
- Create: `backend/alembic/versions/d4e5f6a7b8c9_workflow_subject_key.py`
- Modify: `backend/app/models/workflow.py`, `backend/app/services/workflows/engine.py`, `backend/app/services/workflows/outcome.py`, `backend/app/models/__init__.py`

**Interfaces:**
- Consumes: Phase 1's engine and exception model.
- Produces:
  - `DeliverySession`: `id, org_id, site_id, camera_id, direction, started_at, last_event_at, closed_at, event_count, totals, matched_document_id, status`
  - `assign_session(event, camera, db) -> DeliverySession | None`
  - `WorkflowOutcome.subject_key: str | None` — when a module sets it, the exception is keyed on that instead of the event
  - `WorkflowException.subject_key` (unique with `workflow_type`) and `delivery_session_id`

**The problem this solves.** Phase 1's known limitation #2: a truck unloaded over twenty minutes produces many events, each independently compared against the same purchase order. Forty events against a 20-carton PO produce forty exceptions, most of them nonsense, and the one real finding is buried. A session is the unit a human actually reasons about — "this delivery" — so it is the unit a comparison should use.

**Session boundaries:** one open session per (camera, direction). An event joins the open session if the gap since `last_event_at` is under `SESSION_GAP_MINUTES`; otherwise the old one closes and a new one opens. `totals` holds `{"carton_count_max": n, "pallet_count_max": n, "refs": [...]}`.

**Why max and not sum.** Summing carton counts across frames would count the same pallet forty times. The tracker in `agent/pipeline/` has no cross-frame identity for cartons — deliberately, since re-identification is out of scope — so the honest aggregate is the largest single-frame count, which under-counts a delivery unloaded in waves. That is the same trade footfall counting already makes and documents. **`totals` therefore records `carton_count_max`, and every module and every UI string says "counted at most", never "received".** Getting a true per-delivery total needs cross-frame object identity, which is a Phase 3+ decision with real privacy and cost implications, not a tweak here.

- [ ] **Step 1: Write the model**

`backend/app/models/delivery_session.py`:

```python
"""Many events at one camera, aggregated into one delivery.

A truck unloaded over twenty minutes is one thing a human reasons about, not
forty. Comparing each event independently against the same purchase order
produces forty exceptions and buries the one that matters.

`totals` holds MAXIMA, not sums — see the plan. There is no cross-frame
identity for cartons, so summing would count the same pallet once per frame.
Every reader of this table must say "counted at most".
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DeliverySession(Base):
    __tablename__ = "delivery_sessions"
    __table_args__ = (
        CheckConstraint("direction IN ('inbound','outbound')", name="ck_delivery_sessions_direction"),
        CheckConstraint("status IN ('open','closed')", name="ck_delivery_sessions_status"),
        # The hot query: "is there an open session for this camera and
        # direction?", run once per event on a role-tagged camera.
        Index("ix_delivery_sessions_open", "camera_id", "direction", "status"),
        Index("ix_delivery_sessions_site", "site_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False
    )
    # Derived from camera_role: dock/gate/other are inbound, dispatch/packing
    # outbound. Kept as a column rather than recomputed so a role change does
    # not retroactively rewrite history.
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # {"carton_count_max": 12, "pallet_count_max": 2, "refs": ["PO-4471"]}
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    matched_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("expected_documents.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
```

Register it in `backend/app/models/__init__.py` alongside the Phase 1 workflow models.

- [ ] **Step 2: Write the session assigner**

`backend/app/services/workflows/sessions.py`:

```python
"""Opens, extends, and closes delivery sessions."""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.delivery_session import DeliverySession
from app.models.event import Event

logger = logging.getLogger(__name__)

# A starting guess with no field data behind it. Long enough to span a pause
# while a forklift repositions, short enough that two deliveries an hour apart
# are two sessions. Tune against a real dock before any pilot claim.
SESSION_GAP_MINUTES = 15

DIRECTION_BY_ROLE = {
    "dock": "inbound",
    "gate": "inbound",
    "other": "inbound",
    "dispatch": "outbound",
    "packing": "outbound",
}


async def assign_session(
    event: Event, camera: Camera, db: AsyncSession
) -> DeliverySession | None:
    """Attach this event to a delivery session, opening one if needed.

    Returns None for cameras with no direction — a shelf or floor camera is not
    part of a delivery, and giving it a session would make "how many deliveries
    today" a meaningless number.
    """
    direction = DIRECTION_BY_ROLE.get(camera.camera_role or "")
    if direction is None:
        return None

    goods = (event.metadata_extra or {}).get("goods")
    if not isinstance(goods, dict):
        return None

    session = (
        await db.execute(
            select(DeliverySession)
            .where(
                DeliverySession.camera_id == camera.id,
                DeliverySession.direction == direction,
                DeliverySession.status == "open",
            )
            .order_by(DeliverySession.last_event_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if session is not None:
        gap = event.timestamp - session.last_event_at
        if gap > timedelta(minutes=SESSION_GAP_MINUTES):
            session.closed_at = session.last_event_at
            session.status = "closed"
            session = None
        elif gap < timedelta(0):
            # An out-of-order event, from a backlogged edge box replaying its
            # offline queue. Fold it in rather than opening a session in the
            # past, which would leave two overlapping open sessions.
            logger.info("out-of-order event %s folded into session %s", event.id, session.id)

    if session is None:
        session = DeliverySession(
            org_id=event.org_id,
            site_id=event.site_id,
            camera_id=camera.id,
            direction=direction,
            started_at=event.timestamp,
            last_event_at=event.timestamp,
            totals={},
        )
        db.add(session)

    _fold(session, goods, event)
    await db.flush()
    return session


def _fold(session: DeliverySession, goods: dict, event: Event) -> None:
    """Merge one observation into the session's running totals.

    MAXIMA, not sums. There is no cross-frame identity for cartons, so adding
    frame counts would count one pallet once per frame. The maximum
    under-counts a delivery unloaded in waves, and that is the honest error
    direction: under-reporting what a camera saw produces a missed exception,
    over-reporting produces a false accusation against a vendor.
    """
    totals = dict(session.totals or {})
    for key, field in (("carton_count_max", "carton_count"), ("pallet_count_max", "pallet_count")):
        value = goods.get(field)
        if value is not None:
            totals[key] = max(int(value), int(totals.get(key) or 0))

    refs = set(totals.get("refs") or [])
    refs.update(str(r) for r in (goods.get("visible_refs") or []) if r)
    totals["refs"] = sorted(refs)[:20]

    session.totals = totals
    session.last_event_at = max(session.last_event_at, event.timestamp)
    session.event_count += 1
```

- [ ] **Step 3: Add `subject_key` to exceptions**

In `backend/app/models/workflow.py`, on `WorkflowException` add:

```python
    # What this verdict is ABOUT. "event:<uuid>" for per-event modules,
    # "session:<uuid>" for modules that reason about a whole delivery. The
    # uniqueness constraint moves here from event_id, so forty events in one
    # delivery produce one exception rather than forty.
    subject_key: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_sessions.id"), nullable=True
    )
```

and replace the `uq_workflow_exception_event_type` constraint in `__table_args__` with:

```python
        UniqueConstraint("subject_key", "workflow_type", name="uq_workflow_exception_subject_type"),
```

`event_id` stays non-nullable and now means "the event that most recently triggered this verdict" — update its comment to say so.

In `backend/app/services/workflows/outcome.py`, add to `WorkflowOutcome`:

```python
    # Set by modules that reason about a session rather than a single event.
    # None means the engine keys the exception on the event.
    subject_key: str | None = None
    delivery_session_id: uuid.UUID | None = None
```

- [ ] **Step 4: Write both migrations**

`c3d4e5f6a7b8_delivery_sessions.py` creates `delivery_sessions` (chain off Task 2's `b8c9d0e1f2a3`, **not** off Phase 1's head — see Task 2 Step 1; follow Phase 1 Task 6's migration shape — `postgresql.UUID(as_uuid=True)` columns, explicit `create_check_constraint` and `create_index` calls, a `downgrade` that drops the table).

`d4e5f6a7b8c9_workflow_subject_key.py` chains off it and does the constraint move. It must backfill before adding `NOT NULL`, because existing rows have no `subject_key`:

```python
def upgrade() -> None:
    op.add_column("workflow_exceptions", sa.Column("subject_key", sa.Text(), nullable=True))
    op.add_column(
        "workflow_exceptions",
        sa.Column(
            "delivery_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("delivery_sessions.id"),
            nullable=True,
        ),
    )
    # Every existing row was keyed on its event, so that is its subject.
    op.execute("UPDATE workflow_exceptions SET subject_key = 'event:' || event_id::text")
    op.alter_column("workflow_exceptions", "subject_key", nullable=False)
    op.drop_constraint("uq_workflow_exception_event_type", "workflow_exceptions", type_="unique")
    op.create_unique_constraint(
        "uq_workflow_exception_subject_type", "workflow_exceptions", ["subject_key", "workflow_type"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_workflow_exception_subject_type", "workflow_exceptions", type_="unique")
    op.create_unique_constraint(
        "uq_workflow_exception_event_type", "workflow_exceptions", ["event_id", "workflow_type"]
    )
    op.drop_column("workflow_exceptions", "delivery_session_id")
    op.drop_column("workflow_exceptions", "subject_key")
```

**The downgrade can fail, and that is correct.** If session-keyed exceptions exist, recreating the old constraint may violate it. A downgrade that silently deleted rows to fit the old shape would destroy audit records. Add that as a comment in the migration.

- [ ] **Step 5: Teach the engine about sessions**

In `backend/app/services/workflows/engine.py`, after loading the camera and before the module loop:

```python
    session = await assign_session(event, camera, db)
```

Pass it into each module call — widen the `WorkflowModule` signature in `services/workflows/__init__.py` to take a fifth argument:

```python
WorkflowModule = Callable[
    [Event, Camera, WorkflowRule, "DeliverySession | None", AsyncSession],
    Awaitable[WorkflowOutcome],
]
```

and update every existing module's signature (`dock_grn.evaluate` gains `session: DeliverySession | None` before `db`). `dock_grn` ignores it for now — Task 4 is where a module first uses it.

In `_upsert_exception`, replace the lookup key:

```python
    subject_key = outcome.subject_key or f"event:{event.id}"
    existing = (
        await db.execute(
            select(WorkflowException).where(
                WorkflowException.subject_key == subject_key,
                WorkflowException.workflow_type == rule.workflow_type,
            )
        )
    ).scalar_one_or_none()
```

and set `subject_key=subject_key`, `delivery_session_id=outcome.delivery_session_id`, and `event_id=event.id` on both the insert and the update path. Updating `event_id` on an existing row is intentional: it points at the latest event that contributed to the verdict.

- [ ] **Step 6: Apply and verify**

```bash
cd backend && uv run alembic upgrade head && uv run alembic heads && uv run python3 -c "from app.main import app; print('ok')"
```

Expected: one head, `d4e5f6a7b8c9 (head)`, and `ok`.

Confirm existing exceptions were backfilled:

```bash
psql "$POSTGRES_URL" -c "select count(*) filter (where subject_key is null) as unbackfilled, count(*) from workflow_exceptions;"
```

Expected: `unbackfilled = 0`.

Then post five dock events two minutes apart with carton counts 8, 12, 10, 12, 9:

```bash
psql "$POSTGRES_URL" -c "select event_count, totals, status from delivery_sessions order by started_at desc limit 1;"
```

Expected: one session, `event_count = 5`, `totals->>'carton_count_max' = '12'`. Post a sixth event twenty minutes later and confirm the first session closes and a second opens.

- [ ] **Step 7: Self-review**

- Can two open sessions exist for one camera and direction? (The query takes the most recent; the close-then-open path sets `status='closed'` before adding. Trace a concurrent double-delivery — the workflow consumer is serial, so no. Confirm it is still serial.)
- Does the out-of-order branch corrupt `started_at`? (`_fold` only ever moves `last_event_at` forward via `max`. Confirm `started_at` is never rewritten.)
- Does a session ever cross a site or an org? (It is keyed on `camera_id`, and a camera belongs to one site. Confirm `org_id`/`site_id` come from the event, not from a lookup that could drift.)
- Do sessions ever get closed if the camera goes quiet forever? (No — nothing closes an idle session until the next event arrives. Decide whether that matters: an open session is only read by modules evaluating new events, so a permanently open one is inert. Note it, and add a sweep only if a module ever needs "closed" to mean something.)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/delivery_session.py backend/app/services/workflows/sessions.py backend/app/services/workflows/engine.py backend/app/services/workflows/outcome.py backend/app/services/workflows/__init__.py backend/app/services/workflows/dock_grn.py backend/app/models/workflow.py backend/app/models/__init__.py backend/alembic/versions/
git commit -m "feat(workflows): aggregate events into delivery sessions"
```

---

### Task 4: Module 3.2 — Vendor over-billing / short-delivery detection

**Files:**
- Create: `backend/app/services/workflows/vendor_overbill.py`
- Modify: `backend/app/services/workflows/__init__.py` (registry import)

**Interfaces:**
- Consumes: Task 1's `DocumentMatcher`, Task 3's `DeliverySession`.
- Produces: a module registered under `"vendor_overbill_check"`. Config keys:
  - `shortfall_tolerance_pct: float` (default `5.0`)
  - `match_window_hours: int` (default `72`) — wider than 3.1's 24, because an invoice is raised after the delivery, sometimes days after
  - `min_goods_confidence: float` (default `0.6`) — higher than 3.1's 0.5, because this one accuses a vendor

**The comparison:** invoiced quantity against the session's `carton_count_max`. A shortfall beyond tolerance is an exception. **Over-delivery is not** — a vendor sending more than they billed for is not a billing dispute, and flagging it would train operators to dismiss this queue.

**Read this before implementing.** This module produces a finding with a named counterparty attached, off a vision estimate that under-counts by construction (Task 3, `_fold`). That combination deserves specific care:

- The threshold is asymmetric on purpose. `carton_count_max` under-counts deliveries unloaded in waves, so a *false* shortfall is the expected failure mode. The default tolerance is therefore a floor, not a target, and the discrepancy message must say the count is a camera estimate.
- Every string this module writes says "camera counted at most N" — never "vendor delivered N", never "short-delivered". The finding is that the numbers disagree; who is at fault is the human's call after they look at the snapshot.
- The spec's Section 9 gate applies with full force here. Do not let anyone describe this as over-billing detection to a customer until the arithmetic has been checked against real invoices and real deliveries.

- [ ] **Step 1: Write the module**

`backend/app/services/workflows/vendor_overbill.py`:

```python
"""Module 3.2 — invoiced quantity against what the camera counted.

Produces a finding with a vendor's name on it, from a count that under-reports
by construction. Every string here is written accordingly: the camera "counted
at most" N, the numbers "disagree", and a human decides what that means.

Over-delivery is deliberately not flagged. A vendor shipping more than they
billed is not a billing dispute, and surfacing it would fill the queue with
items nobody acts on — which is how a review queue becomes a rubber stamp.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.delivery_session import DeliverySession
from app.models.event import Event
from app.models.workflow import WorkflowRule
from app.services.workflows import register
from app.services.workflows.matching import DocumentMatcher
from app.services.workflows.outcome import WorkflowOutcome

logger = logging.getLogger(__name__)

DEFAULT_SHORTFALL_TOLERANCE_PCT = 5.0
DEFAULT_WINDOW_HOURS = 72
DEFAULT_MIN_GOODS_CONFIDENCE = 0.6


@register("vendor_overbill_check")
async def evaluate(
    event: Event,
    camera: Camera,
    rule: WorkflowRule,
    session: DeliverySession | None,
    db: AsyncSession,
) -> WorkflowOutcome:
    if camera.camera_role != "dock":
        return WorkflowOutcome.ignore()
    if session is None or session.direction != "inbound":
        return WorkflowOutcome.ignore()

    config = rule.config or {}
    tolerance_pct = float(
        config.get("shortfall_tolerance_pct", DEFAULT_SHORTFALL_TOLERANCE_PCT)
    )
    window_hours = int(config.get("match_window_hours", DEFAULT_WINDOW_HOURS))
    min_confidence = float(
        config.get("min_goods_confidence", DEFAULT_MIN_GOODS_CONFIDENCE)
    )

    goods = (event.metadata_extra or {}).get("goods") or {}
    if float(goods.get("goods_confidence") or 0.0) < min_confidence:
        return WorkflowOutcome.ignore()

    observed = session.totals.get("carton_count_max")
    if observed is None:
        return WorkflowOutcome.ignore()

    subject_key = f"session:{session.id}"

    result = await DocumentMatcher(db).find(
        org_id=event.org_id,
        site_id=event.site_id,
        doc_types=("invoice",),
        at=session.started_at,
        window_hours=window_hours,
        refs=set(session.totals.get("refs") or []),
        observed={"carton_count_max": observed, "event_count": session.event_count},
    )
    if result.failure is not None:
        # An unmatched delivery is 3.1's and 3.3's business, not this module's.
        # Raising "no invoice yet" as a billing exception would fire on every
        # delivery that is simply newer than its paperwork.
        return WorkflowOutcome.ignore()

    document = result.document
    invoiced = document.payload.get("expected_quantity")
    if invoiced is None:
        return WorkflowOutcome.ignore()

    invoiced = float(invoiced)
    vendor = document.payload.get("vendor")

    if invoiced <= 0:
        return WorkflowOutcome.ignore()

    shortfall = invoiced - float(observed)
    shortfall_pct = shortfall / invoiced * 100.0

    if shortfall_pct <= tolerance_pct:
        # Covers both agreement and over-delivery — a negative shortfall is
        # comfortably under tolerance and is not a finding.
        return WorkflowOutcome(
            verdict="match",
            subject_key=subject_key,
            delivery_session_id=session.id,
            matched_document_id=document.id,
        )

    return WorkflowOutcome(
        verdict="exception",
        subject_key=subject_key,
        delivery_session_id=session.id,
        matched_document_id=document.id,
        discrepancy={
            "reason": "invoiced_above_observed",
            "field": "quantity",
            "invoiced": invoiced,
            "observed_max": observed,
            "shortfall": shortfall,
            "shortfall_pct": round(shortfall_pct, 2),
            "tolerance_pct": tolerance_pct,
            "vendor": vendor,
            "external_ref": document.external_ref,
            "observed_over_events": session.event_count,
            "message": (
                f"{document.external_ref} invoices {invoiced:g} but the camera counted "
                f"at most {observed:g} across {session.event_count} frames of this "
                f"delivery — a {round(shortfall_pct, 1)}% gap. Camera counts under-report "
                f"deliveries unloaded in waves, so check the footage before raising this "
                f"with the vendor."
            ),
        },
    )
```

Add the import to `backend/app/services/workflows/__init__.py`'s registration block.

- [ ] **Step 2: Verify all four branches**

Seed an invoice and drive sessions through. Replace UUIDs with real ones.

```bash
psql "$POSTGRES_URL" <<'SQL'
insert into workflow_rules (id, org_id, site_id, workflow_type, config, enabled)
select gen_random_uuid(), org_id, id, 'vendor_overbill_check',
       '{"shortfall_tolerance_pct": 5, "match_window_hours": 72, "min_goods_confidence": 0.6}'::jsonb, true
from sites limit 1;

insert into expected_documents (id, org_id, site_id, source, doc_type, external_ref, payload, doc_date, status)
select gen_random_uuid(), org_id, id, 'manual', 'invoice', 'INV-9012',
       '{"expected_quantity": 20, "vendor": "Acme Supplies"}'::jsonb, now(), 'open'
from sites limit 1;
SQL
```

| Case | Session `carton_count_max` | Expected |
|---|---|---|
| Agreement | 20 | `auto_cleared` |
| Over-delivery | 24 | `auto_cleared` — **not** an exception |
| Within tolerance | 19 | `auto_cleared` (5% of 20 is 1) |
| Shortfall | 12 | `open`, `shortfall_pct = 40` |

Drive each by posting dock events with `visible_refs: ["INV-9012"]` and the given carton count, waiting out `SESSION_GAP_MINUTES` between cases so each is its own session.

```bash
psql "$POSTGRES_URL" -c "select we.status, we.subject_key, we.discrepancy->>'shortfall_pct' from workflow_exceptions we where we.workflow_type='vendor_overbill_check' order by we.created_at desc limit 5;"
```

Then post three more events into the shortfall session and confirm **one** exception row still exists, with its `event_id` updated — this is the session-keying paying off.

- [ ] **Step 3: Self-review**

- Does over-delivery ever produce an exception? (Negative shortfall → negative percentage → under tolerance. Trace it and confirm.)
- Does the module fire when no invoice exists yet? (It must not — `result.failure` returns `ignore`, not the failure. Confirm, and confirm you agree: an invoice arriving days later is normal.)
- Is a vendor name ever asserted as being at fault in any string? (Read every message. "invoices X but the camera counted at most Y" states two facts. "Vendor short-delivered" would not.)
- Does `subject_key` match 3.1's? (No — 3.1 keys on the event, this keys on the session, and the unique constraint is per `(subject_key, workflow_type)`, so they coexist. Confirm both rows appear for one delivery.)
- Should 3.1 also move to session keying? (Probably yes, and it is deliberately not done here: this task changes one module's behaviour at a time. Note it for Phase 3.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/workflows/vendor_overbill.py backend/app/services/workflows/__init__.py
git commit -m "feat(workflows): add vendor over-billing detection module"
```

---

### Task 5: Module 3.3 — Back-door receiving

**Files:**
- Create: `backend/app/services/workflows/backdoor_receiving.py`
- Modify: `backend/app/services/workflows/__init__.py`

**Interfaces:**
- Consumes: Task 2's goods-on-more-roles, Task 3's sessions, Phase 1's `ExpectedDocument`.
- Produces: a module registered under `"backdoor_receiving"`. Config keys:
  - `designated_roles: list[str]` (default `["dock"]`) — where receiving is *supposed* to happen
  - `delivery_window_hours: int` (default `4`) — how far either side of a document's `doc_date` counts as "during a scheduled delivery"
  - `min_goods_confidence: float` (default `0.6`)

**The rule:** goods observed inbound at a camera whose role is **not** in `designated_roles`, **or** at a designated camera with no open document anywhere near in time. Either way: exception, no auto-clear path. Spec Section 3.3 says detection-only, and that is right — there is nothing to draft.

**This module accuses people, not paperwork.** 3.1 and 3.2 compare numbers; this one says "goods came in somewhere they shouldn't have". Two consequences for how it is written:

- It never names a person and never uses the word "theft", "shrinkage", or "unauthorised". The finding is *goods observed at a non-receiving entrance outside a scheduled delivery*. What that means is the human's call, and there are innocent explanations — a returns pickup, a contractor, a mis-set camera role.
- A camera with the wrong role produces a constant stream of these. The message therefore names the camera's current role and says how to change it, so the first response to a false positive is a settings fix rather than an investigation.

- [ ] **Step 1: Write the module**

`backend/app/services/workflows/backdoor_receiving.py`:

```python
"""Module 3.3 — goods arriving somewhere, or somewhen, they were not expected.

Detection only. There is nothing to draft and no auto-clear path: the finding
is that goods appeared at a non-receiving entrance, or at the dock with no
document near it in time.

This module deliberately does not use the words theft, shrinkage, or
unauthorised, and never refers to a person. There are innocent explanations for
every one of these — a returns pickup, a contractor, a camera whose role was
set wrong — and a queue that opens by asserting wrongdoing is one operators
learn to dismiss.
"""
import logging
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.delivery_session import DeliverySession
from app.models.event import Event
from app.models.workflow import ExpectedDocument, WorkflowRule
from app.services.workflows import register
from app.services.workflows.outcome import WorkflowOutcome

logger = logging.getLogger(__name__)

DEFAULT_DESIGNATED_ROLES = ["dock"]
DEFAULT_DELIVERY_WINDOW_HOURS = 4
DEFAULT_MIN_GOODS_CONFIDENCE = 0.6


@register("backdoor_receiving")
async def evaluate(
    event: Event,
    camera: Camera,
    rule: WorkflowRule,
    session: DeliverySession | None,
    db: AsyncSession,
) -> WorkflowOutcome:
    if session is None or session.direction != "inbound":
        return WorkflowOutcome.ignore()

    config = rule.config or {}
    designated = list(config.get("designated_roles") or DEFAULT_DESIGNATED_ROLES)
    window_hours = int(
        config.get("delivery_window_hours", DEFAULT_DELIVERY_WINDOW_HOURS)
    )
    min_confidence = float(
        config.get("min_goods_confidence", DEFAULT_MIN_GOODS_CONFIDENCE)
    )

    goods = (event.metadata_extra or {}).get("goods") or {}
    if float(goods.get("goods_confidence") or 0.0) < min_confidence:
        return WorkflowOutcome.ignore()
    if goods.get("carton_count") is None and goods.get("pallet_count") is None:
        return WorkflowOutcome.ignore()

    subject_key = f"session:{session.id}"
    role = camera.camera_role or "unset"
    wrong_place = role not in designated

    window_start = session.started_at - timedelta(hours=window_hours)
    window_end = session.started_at + timedelta(hours=window_hours)
    scheduled_count = (
        await db.execute(
            select(func.count())
            .select_from(ExpectedDocument)
            .where(
                ExpectedDocument.org_id == event.org_id,
                ExpectedDocument.doc_type.in_(("po", "grn")),
                ExpectedDocument.status == "open",
                or_(
                    ExpectedDocument.site_id == event.site_id,
                    ExpectedDocument.site_id.is_(None),
                ),
                ExpectedDocument.doc_date.between(window_start, window_end),
            )
        )
    ).scalar_one()

    wrong_time = scheduled_count == 0

    if not wrong_place and not wrong_time:
        return WorkflowOutcome(
            verdict="match", subject_key=subject_key, delivery_session_id=session.id
        )

    if wrong_place:
        message = (
            f"Goods were observed arriving at {camera.name}, whose role is "
            f'"{role}" — receiving is expected at '
            + " or ".join(f'"{r}"' for r in designated)
            + ". If this camera does watch a receiving point, change its role in "
            "Settings and this will stop firing."
        )
    else:
        message = (
            f"Goods were observed arriving at {camera.name} with no scheduled "
            f"delivery within {window_hours}h either side. There may be a "
            f"legitimate reason — a return, a contractor, paperwork not yet "
            f"synced from Tally."
        )

    return WorkflowOutcome(
        verdict="exception",
        subject_key=subject_key,
        delivery_session_id=session.id,
        discrepancy={
            "reason": "unexpected_receiving_point" if wrong_place else "outside_delivery_window",
            "camera_name": camera.name,
            "camera_role": role,
            "designated_roles": designated,
            "scheduled_documents_in_window": scheduled_count,
            "delivery_window_hours": window_hours,
            "observed": {
                "carton_count_max": session.totals.get("carton_count_max"),
                "pallet_count_max": session.totals.get("pallet_count_max"),
            },
            "observed_at": session.started_at.isoformat(),
            "message": message,
        },
    )
```

Register it.

- [ ] **Step 2: Verify all four quadrants**

Enable the rule for a site, then:

| Camera role | Open PO within 4h | Expected |
|---|---|---|
| `dock` | yes | `auto_cleared` |
| `dock` | no | `open`, `outside_delivery_window` |
| `other` | yes | `open`, `unexpected_receiving_point` |
| `other` | no | `open`, `unexpected_receiving_point` (place wins — it is the more specific finding) |

```bash
psql "$POSTGRES_URL" -c "select status, discrepancy->>'reason', discrepancy->>'camera_name' from workflow_exceptions where workflow_type='backdoor_receiving' order by created_at desc limit 6;"
```

- [ ] **Step 3: Verify it does not fire on ordinary sites**

Enable the rule on a site whose cameras all have `camera_role IS NULL`. Post a normal event. Expected: no rows at all — `assign_session` returns `None` for a roleless camera, so the module never runs. Confirm, because a module that fires on every camera in an unconfigured estate is worse than one that never fires.

- [ ] **Step 4: Self-review**

- Does any string here name a person, or use "theft", "shrinkage", "unauthorised", or "suspicious"? (Read all of them.)
- Does the wrong-place message tell the operator how to make a false positive stop? (It should name the camera, its current role, and where to change it.)
- Is `scheduled_count` filtered by `org_id`? (Yes. Read it again — this one counts across a whole org's documents.)
- Does the `doc_date IS NULL` case behave sensibly? (`between` excludes NULL, so documents with no date never count as scheduled, which makes an undated PO look like an unscheduled delivery. Decide: is that right? Argument for — a document with no date genuinely does not schedule anything. Note your decision either way.)
- What happens the first time a customer enables this on an estate where half the cameras have the wrong role? (A flood. Note it, and consider whether Task 9's settings UI should show a preview count before enabling.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/workflows/backdoor_receiving.py backend/app/services/workflows/__init__.py
git commit -m "feat(workflows): add back-door receiving detection module"
```

---

### Task 6: Module 3.8 — Freight dock/vehicle scheduling

**Files:**
- Create: `backend/app/services/workflows/freight_scheduling.py`
- Modify: `backend/app/services/workflows/__init__.py`

**Interfaces:**
- Consumes: Task 2's `metadata_extra["vehicle"]`, Phase 1's `ExpectedDocument`.
- Produces: a module registered under `"freight_dock_scheduling"`. Config keys:
  - `on_time_window_minutes: int` (default `60`)
  - `min_vehicle_confidence: float` (default `0.6`)

**The comparison:** a vehicle arrival at a `gate` camera against the nearest scheduled `doc_date`. Early, late, or unscheduled are the three findings. This is the one module in the family that compares **times, not quantities** — which is exactly why `DocumentMatcher` stops at finding the document.

**Event-keyed, not session-keyed.** A vehicle arrival is an instant, not a delivery. It gets `subject_key = f"event:{event.id}"` (the engine's default) so each arrival is its own row.

**No plate matching.** Even when `capture_vehicle_refs` is on, this module does not match on plate text. Matching a vehicle to a document by registration number is vehicle re-identification by another name, and the honest version of that needs a conversation about retention and consent that has not happened. Timing alone is enough for "was this delivery on schedule".

- [ ] **Step 1: Write the module**

`backend/app/services/workflows/freight_scheduling.py`:

```python
"""Module 3.8 — was the vehicle on schedule?

Compares an observed arrival time at a gate camera against the nearest
scheduled delivery. Times, not quantities — which is why the shared matcher
stops at finding the document and this module does its own comparison.

Deliberately does not match on plate text, even when plate capture is enabled.
Matching a vehicle to a document by registration is vehicle re-identification,
and this codebase does not do re-identification without a deliberate decision
to. Timing answers the question on its own.
"""
import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.delivery_session import DeliverySession
from app.models.event import Event
from app.models.workflow import ExpectedDocument, WorkflowRule
from app.services.workflows import register
from app.services.workflows.outcome import WorkflowOutcome

logger = logging.getLogger(__name__)

DEFAULT_ON_TIME_WINDOW_MINUTES = 60
DEFAULT_MIN_VEHICLE_CONFIDENCE = 0.6
# How far out to look for "the delivery this vehicle is probably for" before
# calling it unscheduled. A starting guess — tune against a real yard.
SEARCH_WINDOW_HOURS = 12


@register("freight_dock_scheduling")
async def evaluate(
    event: Event,
    camera: Camera,
    rule: WorkflowRule,
    session: DeliverySession | None,
    db: AsyncSession,
) -> WorkflowOutcome:
    if camera.camera_role != "gate":
        return WorkflowOutcome.ignore()

    vehicle = (event.metadata_extra or {}).get("vehicle")
    if not isinstance(vehicle, dict):
        return WorkflowOutcome.ignore()
    if vehicle.get("action") != "arrival":
        # Departures are recorded on the event and feed turnaround reporting in
        # Phase 3. They are not a scheduling finding on their own.
        return WorkflowOutcome.ignore()

    config = rule.config or {}
    on_time_minutes = int(
        config.get("on_time_window_minutes", DEFAULT_ON_TIME_WINDOW_MINUTES)
    )
    min_confidence = float(
        config.get("min_vehicle_confidence", DEFAULT_MIN_VEHICLE_CONFIDENCE)
    )

    if float(vehicle.get("vehicle_confidence") or 0.0) < min_confidence:
        return WorkflowOutcome.ignore()

    arrived_at = event.timestamp
    search_start = arrived_at - timedelta(hours=SEARCH_WINDOW_HOURS)
    search_end = arrived_at + timedelta(hours=SEARCH_WINDOW_HOURS)

    candidates = (
        await db.execute(
            select(ExpectedDocument).where(
                ExpectedDocument.org_id == event.org_id,
                ExpectedDocument.doc_type.in_(("po", "sales_order")),
                ExpectedDocument.status == "open",
                or_(
                    ExpectedDocument.site_id == event.site_id,
                    ExpectedDocument.site_id.is_(None),
                ),
                ExpectedDocument.doc_date.between(search_start, search_end),
            )
        )
    ).scalars().all()

    if not candidates:
        return WorkflowOutcome(
            verdict="exception",
            discrepancy={
                "reason": "unscheduled_vehicle",
                "arrived_at": arrived_at.isoformat(),
                "vehicle_type": vehicle.get("vehicle_type"),
                "search_window_hours": SEARCH_WINDOW_HOURS,
                "camera_name": camera.name,
                "message": (
                    f"A {vehicle.get('vehicle_type') or 'vehicle'} arrived at "
                    f"{camera.name} with no scheduled delivery or dispatch within "
                    f"{SEARCH_WINDOW_HOURS}h."
                ),
            },
        )

    # Nearest by absolute time. Unlike quantity matching, "closest" is a
    # defensible answer here: a vehicle arrives at one moment, and the delivery
    # it is nearest to is the one it is most likely for. The finding is the
    # DELTA, so picking a slightly wrong document still surfaces the right
    # question rather than a wrong number.
    document = min(candidates, key=lambda d: abs(d.doc_date - arrived_at))
    delta = arrived_at - document.doc_date
    delta_minutes = delta.total_seconds() / 60.0

    if abs(delta_minutes) <= on_time_minutes:
        return WorkflowOutcome(verdict="match", matched_document_id=document.id)

    early = delta_minutes < 0
    return WorkflowOutcome(
        verdict="exception",
        matched_document_id=document.id,
        discrepancy={
            "reason": "vehicle_early" if early else "vehicle_late",
            "arrived_at": arrived_at.isoformat(),
            "scheduled_for": document.doc_date.isoformat(),
            "delta_minutes": round(delta_minutes, 1),
            "on_time_window_minutes": on_time_minutes,
            "external_ref": document.external_ref,
            "vendor": document.payload.get("vendor"),
            "vehicle_type": vehicle.get("vehicle_type"),
            "message": (
                f"Vehicle arrived {abs(round(delta_minutes))} minutes "
                f"{'early' if early else 'late'} for {document.external_ref}, "
                f"scheduled {document.doc_date.strftime('%d %b %H:%M')}."
            ),
        },
    )
```

Register it.

- [ ] **Step 2: Verify the three findings and the match**

Seed a PO dated at a known time, then post gate events with `metadata_extra` containing a `vehicle` arrival at: on time, 3 hours early, 3 hours late, and with no PO within 12h.

| Case | Expected |
|---|---|
| Within 60 min | `auto_cleared` |
| 180 min early | `open`, `vehicle_early`, `delta_minutes ≈ -180` |
| 180 min late | `open`, `vehicle_late`, `delta_minutes ≈ 180` |
| No document | `open`, `unscheduled_vehicle` |

```bash
psql "$POSTGRES_URL" -c "select status, discrepancy->>'reason', discrepancy->>'delta_minutes' from workflow_exceptions where workflow_type='freight_dock_scheduling' order by created_at desc limit 5;"
```

Also confirm a `departure` event produces nothing, and that a `null` action produces nothing.

- [ ] **Step 3: Self-review**

- Does `min(candidates, ...)` crash on a `doc_date IS NULL` row? (The query filters with `between`, which excludes NULL — so no. Confirm by reading the query, not by assuming.)
- Is the "nearest document" heuristic defensible here when it was rejected for quantities? (Yes, and the reason is in the comment: the output is a delta, so a slightly wrong document still asks the right question. Re-read the comment and decide whether you agree; if not, this should return `ambiguous_document` like the others.)
- Does plate text influence matching anywhere? (It must not. `grep plate` in this file should find nothing.)
- Does the on-time window apply symmetrically? (`abs(delta_minutes)` — yes. Confirm that is intended: a customer may care more about late than early.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/workflows/freight_scheduling.py backend/app/services/workflows/__init__.py
git commit -m "feat(workflows): add freight vehicle scheduling module"
```

---

### Task 7: Module 3.7 — Dispatch order verification

**Files:**
- Create: `backend/app/services/workflows/dispatch_verification.py`
- Modify: `backend/app/services/workflows/__init__.py`
- Modify: `backend/app/connectors/tally/client.py` (`REPORT_DOC_TYPES`)

**Interfaces:**
- Consumes: Task 1's matcher, Task 3's outbound sessions, Task 2's goods on `dispatch`/`packing` roles.
- Produces: a module registered under `"dispatch_order_verification"`, plus `sales_order` documents in the Tally sync. Config keys:
  - `quantity_tolerance_pct: float` (default `2.0`) — tighter than inbound, because sending the wrong quantity to a customer costs more than receiving one
  - `match_window_hours: int` (default `24`)
  - `min_goods_confidence: float` (default `0.6`)

**Direction matters here.** This is the only module in the family that reads an **outbound** session, and it is the only one where over-shipping is as serious as under-shipping — sending 24 when the order says 20 is inventory walking out the door. So unlike 3.2, the comparison is symmetric.

- [ ] **Step 1: Pull sales orders from Tally**

In `backend/app/connectors/tally/client.py`, add to `REPORT_DOC_TYPES`:

```python
    "Sales Order Outstandings": "sales_order",
```

`sales_order` is already in Phase 1's `DOC_TYPES` CHECK constraint, so no migration is needed. Confirm:

```bash
cd backend && grep -n "sales_order" app/models/workflow.py
```

Expected: it appears in `DOC_TYPES`.

- [ ] **Step 2: Write the module**

`backend/app/services/workflows/dispatch_verification.py`:

```python
"""Module 3.7 — did what left match what was ordered?

The only outbound module in the family, and the only one where over-shipping
is as serious as under-shipping: sending 24 against an order for 20 is stock
walking out of the door with a customer's name on it. The comparison is
therefore symmetric, unlike vendor over-billing.

The tolerance default is tighter than inbound for the same reason.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.delivery_session import DeliverySession
from app.models.event import Event
from app.models.workflow import WorkflowRule
from app.services.workflows import register
from app.services.workflows.matching import DocumentMatcher
from app.services.workflows.outcome import WorkflowOutcome

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE_PCT = 2.0
DEFAULT_WINDOW_HOURS = 24
DEFAULT_MIN_GOODS_CONFIDENCE = 0.6


@register("dispatch_order_verification")
async def evaluate(
    event: Event,
    camera: Camera,
    rule: WorkflowRule,
    session: DeliverySession | None,
    db: AsyncSession,
) -> WorkflowOutcome:
    if camera.camera_role not in ("dispatch", "packing"):
        return WorkflowOutcome.ignore()
    if session is None or session.direction != "outbound":
        return WorkflowOutcome.ignore()

    config = rule.config or {}
    tolerance_pct = float(config.get("quantity_tolerance_pct", DEFAULT_TOLERANCE_PCT))
    window_hours = int(config.get("match_window_hours", DEFAULT_WINDOW_HOURS))
    min_confidence = float(
        config.get("min_goods_confidence", DEFAULT_MIN_GOODS_CONFIDENCE)
    )

    goods = (event.metadata_extra or {}).get("goods") or {}
    if float(goods.get("goods_confidence") or 0.0) < min_confidence:
        return WorkflowOutcome.ignore()

    observed = session.totals.get("carton_count_max")
    if observed is None:
        return WorkflowOutcome.ignore()

    subject_key = f"session:{session.id}"

    result = await DocumentMatcher(db).find(
        org_id=event.org_id,
        site_id=event.site_id,
        doc_types=("sales_order", "po"),
        at=session.started_at,
        window_hours=window_hours,
        refs=set(session.totals.get("refs") or []),
        observed={"carton_count_max": observed, "event_count": session.event_count},
    )
    if result.failure is not None:
        failure = result.failure
        failure.subject_key = subject_key
        failure.delivery_session_id = session.id
        # Unlike inbound, an unmatched OUTBOUND movement is itself worth
        # surfacing: goods leaving with no order behind them is the finding,
        # not a paperwork lag.
        return failure

    document = result.document
    ordered = document.payload.get("expected_quantity")
    if ordered is None:
        return WorkflowOutcome(
            verdict="exception",
            subject_key=subject_key,
            delivery_session_id=session.id,
            matched_document_id=document.id,
            discrepancy={
                "reason": "document_has_no_quantity",
                "external_ref": document.external_ref,
                "observed_max": observed,
                "message": (
                    f"Matched {document.external_ref}, which carries no quantity, so "
                    f"there is nothing to compare the dispatch against."
                ),
            },
        )

    ordered = float(ordered)
    if ordered <= 0:
        return WorkflowOutcome.ignore()

    delta = float(observed) - ordered
    variance_pct = abs(delta) / ordered * 100.0

    if variance_pct <= tolerance_pct:
        return WorkflowOutcome(
            verdict="match",
            subject_key=subject_key,
            delivery_session_id=session.id,
            matched_document_id=document.id,
        )

    over = delta > 0
    return WorkflowOutcome(
        verdict="exception",
        subject_key=subject_key,
        delivery_session_id=session.id,
        matched_document_id=document.id,
        discrepancy={
            "reason": "dispatch_over_order" if over else "dispatch_under_order",
            "field": "quantity",
            "ordered": ordered,
            "observed_max": observed,
            "variance_pct": round(variance_pct, 2),
            "tolerance_pct": tolerance_pct,
            "external_ref": document.external_ref,
            "customer": document.payload.get("vendor"),
            "message": (
                f"{document.external_ref} orders {ordered:g}; the camera counted at "
                f"most {observed:g} leaving — "
                f"{round(variance_pct, 1)}% {'over' if over else 'under'}. Check before "
                f"the vehicle leaves."
            ),
        },
    )
```

Register it.

- [ ] **Step 3: Verify**

Seed a `sales_order` for 20 and drive outbound sessions at a `dispatch` camera:

| Session `carton_count_max` | Expected |
|---|---|
| 20 | `auto_cleared` |
| 24 | `open`, `dispatch_over_order`, `variance_pct = 20` |
| 12 | `open`, `dispatch_under_order`, `variance_pct = 40` |
| 20, no matching order | `open`, `no_matching_document` |

The fourth case is the behavioural difference from 3.2 — confirm it produces a row rather than being ignored.

- [ ] **Step 4: Verify against real Tally**

Run a real Sales Order Outstandings export through `TallyClient._parse` and confirm `external_ref` and `expected_quantity` come out right for at least five orders. Same gate as Phase 1 Task 9 Step 6, for the new report.

- [ ] **Step 5: Self-review**

- Is the comparison symmetric? (`abs(delta)` — yes. Confirm you agree that over-dispatch is a finding here while over-delivery is not in 3.2, and that the two comments explain why.)
- Does mutating `result.failure` in place cause aliasing? (`DocumentMatcher` constructs a fresh `WorkflowOutcome` per call, so no. Confirm by reading `find`.)
- Does `doc_types=("sales_order", "po")` risk matching an inbound PO to an outbound movement? (Yes, it can. Decide: is including `po` worth it for customers who raise POs for outbound movements? If not, drop it — the narrower set is safer.)
- Is `customer` read from `payload["vendor"]`? (Tally's party field is the same regardless of direction. Confirm the label in the UI reads "customer" for outbound, or drop the rename and call it "party".)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflows/dispatch_verification.py backend/app/services/workflows/__init__.py backend/app/connectors/tally/client.py
git commit -m "feat(workflows): add dispatch order verification module"
```

---

### Task 8: Tally over the agent control WebSocket

**Files:**
- Create: `backend/app/connectors/tally/agent_transport.py`
- Create: `agent/internal/tally/proxy.go`
- Modify: `backend/app/api/agent_control.py` (generic correlated request)
- Modify: `backend/app/connectors/tally/sync.py` (transport selection)
- Modify: `agent/internal/control/` (command dispatch — exact path per the agent's existing control-socket handler)

**Interfaces:**
- Consumes: Phase 1's `Transport` protocol and `TallyConfig`; the existing `ControlRegistry`.
- Produces:
  - `ControlRegistry.request_response(agent_id, msg, timeout) -> dict` — correlated request/response that does **not** insist on an `answer` field
  - `AgentTransport(agent_id)` implementing `post_xml(base_url, body) -> str`
  - Wire protocol, both directions over the control socket:
    - Backend → agent: `{"type": "tally_query", "request_id": str, "base_url": str, "body": str}`
    - Agent → backend: `{"type": "tally_result", "request_id": str, "xml": str}` or `{"type": "tally_result", "request_id": str, "error": str}`

**Why this exists.** Spec Section 4 says Tally almost always runs on a machine inside the customer's LAN with no inbound route from the internet. Phase 1's `HttpTransport` assumes the backend can reach it, which covers a VPN or a cloud-hosted Tally and nothing else. The edge box is already on that LAN, already holds a device token, and already keeps a persistent socket open to the backend. Relaying an XML request down it is the smallest thing that works, and it is why Phase 1 put a transport seam in `TallyClient` rather than calling `httpx` directly.

**This is the one task in the plan that touches Go.** Keep the Go side deliberately dumb: it takes a URL and a body, POSTs them on the LAN, returns the response text. No parsing, no caching, no retries. Every decision stays on the backend where it can be changed without shipping a new agent binary.

**Two constraints the Go side must enforce, because the backend cannot:**

1. **The `base_url` must be LAN-local.** The backend sends a URL that came from org settings. If an operator (or an attacker with settings access) sets it to an internal cloud address, the *agent* is the thing that would fetch it — from inside the customer's network. The agent validates that the host resolves to a private range and refuses otherwise.
2. **Response size is capped.** A Tally export can be large and the control socket is shared with heartbeat and WebRTC signaling. Cap at 8 MB and return an error above it rather than stalling live view behind a document dump.

- [ ] **Step 1: Add a generic correlated request to the registry**

In `backend/app/api/agent_control.py`, add to `ControlRegistry`:

```python
    async def request_response(
        self, agent_id: uuid.UUID, msg: dict, timeout: float = 30.0
    ) -> dict:
        """Correlated request/response for non-signaling commands.

        `request_signal` insists on an `answer` field because that is what a
        WebRTC round-trip returns. A Tally query returns `xml`, a future
        command will return something else again, so this one returns the
        whole payload and lets the caller decide what it needs.

        The default timeout is longer than signaling's 10s: a Tally export of
        a month of purchase orders is not fast, and a timeout here means a
        failed sync rather than a dropped video call.
        """
        ws = self.get(agent_id)
        if ws is None:
            raise ConnectionError("agent not connected")
        request_id = str(uuid.uuid4())
        msg["request_id"] = request_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        try:
            try:
                await ws.send_json(msg)
            except Exception as e:
                raise ConnectionError(f"agent socket send failed: {e}") from e
            payload = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

        if payload.get("error"):
            raise SignalError(str(payload["error"]))
        return payload
```

In the socket's inbound message loop, route `tally_result` to `registry.resolve(...)` exactly as `signal_answer` is routed today — find that branch and add the message type alongside it.

- [ ] **Step 2: Write the backend transport**

`backend/app/connectors/tally/agent_transport.py`:

```python
"""Tally XML relayed through the customer's own edge box.

The edge box is already on the LAN Tally lives on, already authenticated, and
already holds a persistent socket to us. Relaying the request down it is the
smallest thing that reaches an on-prem Tally without asking a customer to open
a port or run a VPN.

The agent side is deliberately dumb — URL in, response text out. Every parsing
and matching decision stays here, where changing it does not mean shipping a
new agent binary to every customer.
"""
import logging
import uuid

from app.api.agent_control import SignalError, registry

logger = logging.getLogger(__name__)

TALLY_QUERY_TIMEOUT_SECONDS = 45.0


class AgentTransport:
    """Implements Phase 1's `Transport` protocol over the control socket."""

    def __init__(self, agent_id: uuid.UUID):
        self._agent_id = agent_id

    async def post_xml(self, base_url: str, body: str) -> str:
        try:
            payload = await registry.request_response(
                self._agent_id,
                {"type": "tally_query", "base_url": base_url, "body": body},
                timeout=TALLY_QUERY_TIMEOUT_SECONDS,
            )
        except ConnectionError as exc:
            raise ConnectionError(
                f"Edge box for this site is not connected, so Tally cannot be "
                f"reached: {exc}"
            ) from exc
        except SignalError as exc:
            raise ValueError(f"Edge box could not reach Tally: {exc}") from exc

        xml = payload.get("xml")
        if not xml:
            raise ValueError("Edge box returned an empty Tally response")
        return xml
```

- [ ] **Step 3: Select the transport per org**

In `backend/app/connectors/tally/sync.py`, add to `TallyConfig` handling in `sync_org`:

```python
    if config.agent_id is not None:
        transport = AgentTransport(config.agent_id)
    else:
        transport = None  # TallyClient falls back to HttpTransport
    client = TallyClient(config, transport)
```

and add `agent_id: uuid.UUID | None = None` to `TallyConfig`, read in `from_org_settings` from `raw.get("agent_id")`. Settings then look like:

```json
{"tally": {"enabled": true, "base_url": "http://192.168.1.40:9000", "company_name": "Acme Traders", "agent_id": "…", "site_id": null}}
```

**A `base_url` pointing at a LAN address with no `agent_id` set is a misconfiguration that will fail every sync with a connection timeout.** Add an explicit check in `sync_org` that raises a clear error naming the fix, rather than letting it surface as an opaque `httpx.ConnectTimeout` in the sync log:

```python
    if config.agent_id is None and _is_private_host(config.base_url):
        raise ValueError(
            "Tally base_url is a private address but no agent_id is set — the "
            "cloud cannot reach it. Set agent_id to the edge box on that LAN."
        )
```

Write `_is_private_host` using `ipaddress.ip_address(...).is_private`, treating an unresolvable hostname as not-private (the check is a helpful diagnostic, not a security control — the security control is on the agent, Step 4).

- [ ] **Step 4: Write the agent proxy**

`agent/internal/tally/proxy.go` — follow the surrounding package's conventions for logging and error shape:

```go
// Package tally relays Tally XML requests from the backend onto the local LAN.
//
// Deliberately dumb: URL in, response text out. No parsing, no caching, no
// retries — every decision that could need changing lives on the backend,
// where changing it does not mean shipping a new binary to every customer.
package tally

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// The control socket is shared with heartbeat and WebRTC signaling. A large
// export must not stall live view behind it.
const maxResponseBytes = 8 << 20 // 8 MiB
const requestTimeout = 40 * time.Second

// Query POSTs body to rawURL and returns the response text.
//
// The backend sends a URL that came from org settings, and this process sits
// inside the customer's network — so a URL pointing anywhere but the local
// network would make this agent a proxy into its owner's LAN on behalf of
// whoever can edit those settings. Refuse anything that is not private.
func Query(ctx context.Context, rawURL string, body string) (string, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return "", fmt.Errorf("invalid tally url: %w", err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", fmt.Errorf("unsupported tally scheme %q", parsed.Scheme)
	}
	if err := requirePrivateHost(parsed.Hostname()); err != nil {
		return "", err
	}

	ctx, cancel := context.WithTimeout(ctx, requestTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, rawURL, strings.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "text/xml")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("tally unreachable at %s: %w", parsed.Host, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return "", fmt.Errorf("tally returned %d", resp.StatusCode)
	}

	// LimitReader + 1 so a response exactly at the cap is distinguishable
	// from one that was truncated.
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxResponseBytes+1))
	if err != nil {
		return "", err
	}
	if len(data) > maxResponseBytes {
		return "", fmt.Errorf("tally response exceeds %d bytes; narrow the date range", maxResponseBytes)
	}
	return string(data), nil
}

func requirePrivateHost(host string) error {
	ips, err := net.LookupIP(host)
	if err != nil {
		return fmt.Errorf("cannot resolve tally host %q: %w", host, err)
	}
	for _, ip := range ips {
		if !ip.IsPrivate() && !ip.IsLoopback() {
			return fmt.Errorf("tally host %q resolves to non-local address %s; refusing", host, ip)
		}
	}
	return nil
}
```

In the agent's control-socket message handler, add a `tally_query` case that calls `tally.Query` in a goroutine and writes back `{"type":"tally_result","request_id":…,"xml":…}` or `{"type":"tally_result","request_id":…,"error":…}`. Run it off the read loop so a 40-second Tally export does not block heartbeat.

- [ ] **Step 5: Build and verify**

```bash
cd agent && go build ./... && go vet ./...
```

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Run a local Tally stand-in — any HTTP server that echoes fixed XML on port 9000 — plus the agent and backend per CLAUDE.md's local instructions. Configure an org with `agent_id` set and `base_url` pointing at it, then:

```bash
curl -s -X POST localhost:8080/api/connectors/tally/sync -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `last_status: "ok"` with a non-zero `records_pulled`, and a `tally_query` / `tally_result` pair in the agent log.

Then verify both agent-side guards:

```bash
psql "$POSTGRES_URL" -c "update organizations set settings = jsonb_set(settings, '{tally,base_url}', '\"http://93.184.216.34:9000\"') where id = (select id from organizations limit 1);"
```

Expected on the next manual sync: `status='error'` with "refusing" in the message. The agent must refuse; the backend must not have to.

Finally, stop the agent and sync again. Expected: a clear "Edge box for this site is not connected" error in the sync log, not a stack trace.

- [ ] **Step 6: Self-review**

- **Does the scheduled sweep work with more than one backend replica?** It does not, and this is the important finding of this task. `ControlRegistry` is in-process — the same single-instance problem Phase 1 Task 3 fixed for WebSocket broadcast, still unfixed for the control plane. The scheduler tick runs on one replica; the agent's socket may be on another. Make the sweep skip-and-log when `registry.get(agent_id)` is `None`, so the behaviour is visible rather than mysterious, and record this in the limitations section. Routing control-plane commands through Redis is its own piece of work and does not belong inside a connector task.
- Is the private-host check on the agent, the backend, or both? (It must be on the agent — that is the process with LAN access. The backend check is a diagnostic only. Confirm the comment says so.)
- Does a 40s Tally export block the agent's heartbeat? (It must not. Confirm the handler runs off the read loop.)
- Is the device token doing any authorization work here beyond identifying the agent? (The backend picks the `agent_id` from org settings, and the org is resolved from the authenticated caller. Trace that an org cannot name another org's agent — if `agent_id` is taken from settings without checking `Agent.org_id == org.id`, that is a cross-tenant hole. **Add that check.**)
- Does `LookupIP` on every request add latency worth caching? (Measure before optimising.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/connectors/tally/agent_transport.py backend/app/connectors/tally/sync.py backend/app/api/agent_control.py agent/internal/tally/ agent/internal/control/
git commit -m "feat(connectors): relay Tally queries through the edge agent"
```

---

### Task 9: Frontend — all workflows, sessions, and vehicle detail

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/app/settings/page.tsx`
- Modify: `frontend/src/components/exceptions/exception-detail.tsx`
- Modify: `frontend/src/app/exceptions/page.tsx`

**Interfaces:**
- Consumes: Phase 1's API client methods unchanged; new response fields from Tasks 3–7.
- Produces: a settings section that configures all five implemented workflows, and a detail view that renders session totals and vehicle observations.

- [ ] **Step 1: Widen the types**

In `frontend/src/types/index.ts`:

```ts
export type WorkflowType =
  | "dock_grn_match"
  | "vendor_overbill_check"
  | "backdoor_receiving"
  | "dispatch_order_verification"
  | "freight_dock_scheduling";

export interface DeliverySessionSummary {
  id: string;
  direction: "inbound" | "outbound";
  started_at: string;
  last_event_at: string;
  event_count: number;
  totals: {
    carton_count_max?: number;
    pallet_count_max?: number;
    refs?: string[];
  };
}
```

and add to `WorkflowException`:

```ts
  delivery_session_id: string | null;
  session: DeliverySessionSummary | null;
```

Add the matching `session` field to `WorkflowExceptionResponse` in `backend/app/schemas/workflow.py` and populate it in `_to_response` by outer-joining `DeliverySession` on `WorkflowException.delivery_session_id`, following the pattern already there for `ExpectedDocument`.

- [ ] **Step 2: Drive settings from a workflow catalogue**

Replace Phase 1's single hardcoded `WorkflowSettings` component with one driven by a catalogue, so adding a sixth module in Phase 3 is a data change:

```tsx
type ConfigField = {
  key: string;
  label: string;
  type: "number";
  min: number;
  max: number;
  step: number;
  suffix?: string;
  help: string;
};

const WORKFLOW_CATALOGUE: {
  type: WorkflowType;
  title: string;
  description: string;
  fields: ConfigField[];
}[] = [
  {
    type: "dock_grn_match",
    title: "Dock GRN auto-match",
    description:
      "Compares what a dock camera counts arriving against the open purchase order, and drafts a goods-receipt note when they agree. Only runs on cameras whose role is “dock”.",
    fields: [
      { key: "quantity_tolerance_pct", label: "Tolerance", type: "number", min: 0, max: 100, step: 0.5, suffix: "%", help: "How far the counts may differ before it becomes an exception." },
      { key: "match_window_hours", label: "Match window", type: "number", min: 1, max: 168, step: 1, suffix: "h", help: "How far either side of the delivery to look for a document." },
      { key: "min_goods_confidence", label: "Min. confidence", type: "number", min: 0, max: 1, step: 0.05, help: "Below this, the camera's count is treated as unusable rather than wrong." },
    ],
  },
  {
    type: "vendor_overbill_check",
    title: "Vendor billing check",
    description:
      "Flags where an invoice is for more than the camera counted arriving. Camera counts under-report deliveries unloaded in waves, so treat findings as a prompt to check footage, not as proof.",
    fields: [
      { key: "shortfall_tolerance_pct", label: "Shortfall tolerance", type: "number", min: 0, max: 100, step: 0.5, suffix: "%", help: "Over-delivery is never flagged." },
      { key: "match_window_hours", label: "Match window", type: "number", min: 1, max: 336, step: 1, suffix: "h", help: "Invoices often follow a delivery by days." },
      { key: "min_goods_confidence", label: "Min. confidence", type: "number", min: 0, max: 1, step: 0.05, help: "Higher than other workflows: this one names a vendor." },
    ],
  },
  {
    type: "backdoor_receiving",
    title: "Unexpected receiving",
    description:
      "Flags goods arriving at a camera that is not a designated receiving point, or arriving with no scheduled delivery nearby. Detection only — nothing is drafted.",
    fields: [
      { key: "delivery_window_hours", label: "Delivery window", type: "number", min: 1, max: 24, step: 1, suffix: "h", help: "How far either side of a scheduled delivery still counts as on-schedule." },
      { key: "min_goods_confidence", label: "Min. confidence", type: "number", min: 0, max: 1, step: 0.05, help: "" },
    ],
  },
  {
    type: "dispatch_order_verification",
    title: "Dispatch verification",
    description:
      "Compares what leaves a dispatch or packing camera against the sales order. Flags both over- and under-dispatch.",
    fields: [
      { key: "quantity_tolerance_pct", label: "Tolerance", type: "number", min: 0, max: 100, step: 0.5, suffix: "%", help: "Tighter than inbound by default." },
      { key: "match_window_hours", label: "Match window", type: "number", min: 1, max: 168, step: 1, suffix: "h", help: "" },
      { key: "min_goods_confidence", label: "Min. confidence", type: "number", min: 0, max: 1, step: 0.05, help: "" },
    ],
  },
  {
    type: "freight_dock_scheduling",
    title: "Vehicle scheduling",
    description:
      "Flags vehicles arriving at a gate camera early, late, or with nothing scheduled. Matches on timing only — never on registration numbers.",
    fields: [
      { key: "on_time_window_minutes", label: "On-time window", type: "number", min: 5, max: 480, step: 5, suffix: "min", help: "" },
      { key: "min_vehicle_confidence", label: "Min. confidence", type: "number", min: 0, max: 1, step: 0.05, help: "" },
    ],
  },
];
```

Render one card per entry, each with an enable checkbox and its fields, reading the current `WorkflowRule` for that type and calling `api.upsertWorkflowRule` on change. Keep Phase 1's save-on-blur behaviour for number fields. **Send the full config object on every save** — the backend replaces `config` wholesale, so a partial write silently resets the other fields to their module defaults.

`backdoor_receiving`'s `designated_roles` is deliberately not editable here: it is a list, the UI for it is a multi-select, and the default (`["dock"]`) is right for every customer who has set camera roles at all. Add it when a customer asks, not before.

- [ ] **Step 3: Render sessions and vehicles in the detail view**

In `exception-detail.tsx`, in the "What the camera saw" pane, when `exception.session` is present, replace the single-event summary with the session's:

```tsx
{exception.session ? (
  <>
    <Field
      label="Delivery"
      value={`${exception.session.event_count} frames over ${Math.max(
        1,
        Math.round(
          (new Date(exception.session.last_event_at).getTime() -
            new Date(exception.session.started_at).getTime()) /
            60000
        )
      )} min`}
    />
    <Field
      label="Counted at most"
      value={
        exception.session.totals.carton_count_max !== undefined
          ? `${exception.session.totals.carton_count_max} cartons`
          : exception.session.totals.pallet_count_max !== undefined
          ? `${exception.session.totals.pallet_count_max} pallets`
          : "—"
      }
    />
    {exception.session.totals.refs?.length ? (
      <Field label="References seen" value={exception.session.totals.refs.join(", ")} />
    ) : null}
  </>
) : null}
```

**"Counted at most" is not a stylistic choice.** The session total is a maximum across frames and under-reports a delivery unloaded in waves (Task 3). Rendering it as "Received: 12" would present an estimate as a fact, which is the specific failure the footfall feature already documents and avoids. Keep this wording, and keep the tooltip below.

Add, under the counted value:

```tsx
<p className="mt-1 text-xs text-zinc-600">
  Highest count seen in any single frame. Deliveries unloaded in waves will read low.
</p>
```

Add the vehicle block where `exception.discrepancy.reason` starts with `vehicle_` or is `unscheduled_vehicle`, rendering `arrived_at`, `scheduled_for`, and `delta_minutes` as a small three-row table.

- [ ] **Step 4: Add the workflow-type filter to the queue**

Phase 1's page already passes `workflow_type` through to the API but has no control for it. Add a select next to the site select, populated from `WORKFLOW_CATALOGUE` (export it from a shared module so both pages use one list), defaulting to all types. Add `workflowType` to the query key.

- [ ] **Step 5: Build and verify**

```bash
cd frontend && npm run build
```

Then, with all five rules enabled on a test site:

1. `/settings` shows five cards; changing one field on one card does not reset the others (check the DB `config` after each save — this is the wholesale-replace trap).
2. `/exceptions` filter by workflow type returns only that type.
3. A vendor-overbill exception shows "Counted at most 12 cartons" and "5 frames over 8 min", not "Received: 12".
4. A freight exception shows the arrival/scheduled/delta table.
5. Approving a session-keyed exception still moves it out of the open list.

- [ ] **Step 6: Self-review**

- Does any string in the UI present a camera count as a received quantity? (Grep the components for "Received", "Delivered", "Actual". None should survive.)
- Does a partial config save reset sibling fields? (Test it explicitly — read the DB row after changing one field.)
- Is `WORKFLOW_CATALOGUE` the single source of both pages' type lists? (Two copies drift the moment Phase 3 adds a module.)
- Does the settings page handle a rule that exists in the DB but not in the catalogue? (It can happen after a rollback. It should render nothing for it rather than crashing — confirm.)
- Dark mode only, no light-mode classes anywhere in the new markup.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/app/settings/page.tsx frontend/src/components/exceptions/ frontend/src/app/exceptions/page.tsx backend/app/schemas/workflow.py backend/app/api/workflows.py
git commit -m "feat(frontend): configure all workflows and render delivery sessions"
```

---

## Phase 2 acceptance

Checked by hand, all at once:

- [ ] The four Phase 1 `dock_grn` cases produce byte-identical `discrepancy` JSON after the `DocumentMatcher` refactor, apart from the one intended `no_matching_document` message change.
- [ ] A `gate` camera reports vehicles; a `dock` camera does not; a roleless camera's payload is unchanged from Phase 1.
- [ ] `plate_text` is absent from the prompt and `null` in the payload unless `capture_vehicle_refs` is explicitly on.
- [ ] Five dock events two minutes apart produce one session with `carton_count_max` equal to the largest single count — not the sum. A sixth event twenty minutes later opens a second session.
- [ ] Forty events in one delivery produce **one** exception per session-keyed workflow, with `event_id` pointing at the most recent contributor.
- [ ] Over-delivery auto-clears under `vendor_overbill_check` and raises an exception under `dispatch_order_verification`, and the reason each behaves that way is written in its module docstring.
- [ ] `backdoor_receiving` produces nothing on a site whose cameras have no role.
- [ ] `freight_dock_scheduling` produces `vehicle_early`, `vehicle_late`, `unscheduled_vehicle`, and an auto-clear across four seeded cases, and `grep plate` in that module finds nothing.
- [ ] A Tally sync succeeds through the agent transport; the agent refuses a non-private `base_url`; a disconnected agent produces a readable error in `connector_sync_log`.
- [ ] An org cannot name another org's `agent_id` in its Tally settings (Task 8 Step 6).
- [ ] Cross-tenant and site-restricted checks from Phase 1 Task 10 Step 6 still return `404` and `total: 0`, now including session-keyed exceptions.
- [ ] `cd backend && uv run python3 -c "from app.main import app"`, `cd agent && go build ./...`, and `cd frontend && npm run build` all pass.
- [ ] Real-Tally validation done for the Sales Order report (Task 7 Step 4), same gate as Phase 1.

## Known limitations to carry into Phase 3

1. **The control plane is still single-replica.** `ControlRegistry` is an in-process dict, so the scheduled Tally sweep only reaches agents whose socket landed on the replica running the scheduler. Phase 1 Task 3 fixed exactly this for WebSocket broadcast; the control plane needs the same Redis routing treatment. Until then, agent-transport Tally sync is correct on a single replica and lossy above one. **This blocks scaling the backend past one replica for any customer using the agent transport** — it is not merely a degradation.
2. **Session totals under-report.** `carton_count_max` is a per-frame maximum because there is no cross-frame carton identity. Every consumer says "counted at most". A true per-delivery total needs object tracking with identity, which is a Phase 3+ decision with real cost and privacy implications.
3. **3.1 is still event-keyed while 3.2 and 3.7 are session-keyed.** One delivery therefore produces one `dock_grn_match` row per event and one `vendor_overbill_check` row total. Moving 3.1 to session keying is a small change deferred deliberately so Task 4 changed one thing at a time — do it early in Phase 3.
4. **No unit reconciliation.** Still. Cartons compared against a document in pieces produces a meaningless variance in every module here. `counted_unit` records what was counted; nothing detects the mismatch.
5. **Every threshold is a guess.** `SESSION_GAP_MINUTES`, `SEARCH_WINDOW_HOURS`, and all five modules' defaults have no field data behind them. They are config keys precisely so a pilot can move them without a deploy — but nobody has moved them yet.
