# Agentic Camera Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An operator selects a batch of cameras; the agent on each edge box watches them, proposes a full detection configuration with a plain-English rationale, and a human approves per scene group.

**Architecture:** Backend enqueues one setup job per camera onto that camera's own agent's Redis list (reusing the ONVIF resolve-jobs pattern). The **Python pipeline** — not the Go agent — drains the jobs, because it is the process that holds decoded frames and already calls Gemini through the credential broker. It posts back a structured proposal; the backend validates it, clusters the batch by a closed `scene_type` enum, and serves grouped proposals for review. Approval writes the real camera config.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Redis (backend); Python asyncio + OpenCV + google-genai (pipeline); Next.js App Router + TanStack Query (frontend).

**Spec:** `docs/superpowers/specs/2026-08-18-agentic-camera-setup-design.md`

## Global Constraints

- **No TDD.** Per the user's standing preference, implement directly then self-review for correctness, simplicity, SOLID and flow. Steps below use *verification* rather than write-failing-test-first. Do not add pytest files unless a task explicitly says to.
- **No automated tests are added by this plan.** Verification is by running the code against a throwaway Postgres, as every other task in this codebase has been.
- **Frames never leave the premises.** The pipeline calls Gemini directly using the broker credential. Never send frames to the backend.
- **Nothing takes effect without human approval.** No code path may write a live camera config from a proposal that has not been explicitly approved.
- **A failed proposal is never silently corrected** — it becomes `needs_input` with the failing reason attached.
- **Alert rules are never bulk-approved.** Group approval covers detection config only.
- Backend runs on port 8080. Dark theme only (`#0D0D0D` bg, `#111111` cards, `#1E90FF` accent, `#2A2A2A` border).
- Scene type enum, verbatim: `parking`, `corridor`, `retail_frontage`, `entrance`, `loading_bay`, `atrium`, `perimeter`, `other`.
- Confidence threshold for `needs_input`: `< 0.6`.
- Batch cap: 50 cameras per run. Observation: 10 frames over 180 seconds. Concurrent setup jobs per agent: 2.

**Throwaway Postgres for verification** (used by several tasks):

```bash
docker run -d --name nw-setup -e POSTGRES_PASSWORD=test -e POSTGRES_DB=nw_main -p 55450:5432 postgres:15
export DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:55450/nw_main"
export PYTHONPATH=$PWD   # from backend/
```

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/models/camera_setup.py` | `SetupRun` + `CameraSetupProposal` ORM models |
| `backend/alembic/versions/<rev>_camera_setup.py` | Tables |
| `backend/app/schemas/camera_setup.py` | Wire shapes: the proposal payload, job, responses |
| `backend/app/services/camera_setup/validator.py` | Pure validation of a returned proposal |
| `backend/app/services/camera_setup/grouping.py` | Pure clustering of a batch into review groups |
| `backend/app/api/camera_setup.py` | Operator endpoints: start run, list groups, approve |
| `backend/app/api/agents.py` (modify) | Agent endpoints: drain setup jobs, post result |
| `agent/pipeline/scene_analyzer.py` | Sample frames, one structured Gemini call, return proposal |
| `agent/pipeline/supervisor.py` (modify) | Poll for setup jobs, run analyzer, post result |
| `frontend/src/app/setup/` | Grouped review UI |
| `frontend/src/lib/api.ts`, `types/index.ts` (modify) | Client methods and types |

---

### Task 1: Data model and migration

**Files:**
- Create: `backend/app/models/camera_setup.py`
- Create: `backend/alembic/versions/b4c8e1a90d37_camera_setup.py`
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `SetupRun`, `CameraSetupProposal` ORM classes; statuses `pending | proposed | needs_input | failed | approved | rejected`.

- [ ] **Step 1: Create the models**

```python
# backend/app/models/camera_setup.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SetupRun(Base):
    """One operator-initiated batch of camera setup proposals."""

    __tablename__ = "setup_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False, index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")  # running|complete|cancelled
    camera_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CameraSetupProposal(Base):
    """The agent's proposed configuration for one camera.

    The row is created `pending` at dispatch time and is the source of truth
    for the job: the Redis queue is only a dispatch hint, so an agent dying
    mid-job leaves a visible pending row the operator can retry rather than a
    silently lost job.
    """

    __tablename__ = "camera_setup_proposals"
    __table_args__ = (
        Index("ix_setup_proposals_run", "run_id"),
        Index("ix_setup_proposals_camera", "camera_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"), nullable=False)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cameras.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("setup_runs.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    scene_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scene_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The full returned object, stored verbatim. Kept after approval as the
    # record of what was proposed and who accepted it.
    proposal: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Register the models**

In `backend/app/models/__init__.py`, after the `from app.models.camera_connection import CameraConnection` line, add:

```python
from app.models.camera_setup import CameraSetupProposal, SetupRun
```

If the file has an `__all__` list, add `"CameraSetupProposal"` and `"SetupRun"` to it.

- [ ] **Step 3: Write the migration**

Find the current head with `cd backend && uv run alembic heads`. Use it as `down_revision` below (at time of writing: `a8b3d6f20c94`).

```python
# backend/alembic/versions/b4c8e1a90d37_camera_setup.py
"""camera setup runs and proposals

Revision ID: b4c8e1a90d37
Revises: a8b3d6f20c94
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4c8e1a90d37"
down_revision: Union[str, None] = "a8b3d6f20c94"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "setup_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("camera_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_setup_runs_site", "setup_runs", ["site_id"])

    op.create_table(
        "camera_setup_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("setup_runs.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("scene_type", sa.String(32), nullable=True),
        sa.Column("scene_description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("proposal", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_setup_proposals_run", "camera_setup_proposals", ["run_id"])
    op.create_index("ix_setup_proposals_camera", "camera_setup_proposals", ["camera_id"])


def downgrade() -> None:
    op.drop_table("camera_setup_proposals")
    op.drop_index("ix_setup_runs_site", table_name="setup_runs")
    op.drop_table("setup_runs")
```

- [ ] **Step 4: Verify the migration applies and reverses**

```bash
cd backend
docker run -d --name nw-setup -e POSTGRES_PASSWORD=test -e POSTGRES_DB=nw_main -p 55450:5432 postgres:15
sleep 5
export DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:55450/nw_main"
export PYTHONPATH=$PWD
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
uv run alembic heads      # must print exactly one head
```

Expected: no errors, single head. **`MIN(uuid)` does not exist in Postgres** — if you add any backfill SQL, do not use `MIN()` on a uuid column; use `(array_agg(id))[1]`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/camera_setup.py backend/app/models/__init__.py backend/alembic/versions/b4c8e1a90d37_camera_setup.py
git commit -m "Add camera setup run and proposal models"
```

---

### Task 2: Proposal validation

**Files:**
- Create: `backend/app/services/camera_setup/__init__.py` (empty)
- Create: `backend/app/services/camera_setup/validator.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `SCENE_TYPES: set[str]`, `MIN_CONFIDENCE: float`, `validate_proposal(proposal: dict, frame_width: int, frame_height: int) -> list[str]` returning a list of human-readable failure reasons (empty list = valid).

- [ ] **Step 1: Write the validator**

```python
# backend/app/services/camera_setup/validator.py
"""Validation of an agent-returned setup proposal.

A proposal that fails validation is marked `needs_input` with the reasons
attached. It is NEVER silently corrected: a corrected proposal is no longer
the thing the model justified in its rationale, so approving it would mean a
human accepting something nobody explained.
"""

SCENE_TYPES = {
    "parking",
    "corridor",
    "retail_frontage",
    "entrance",
    "loading_bay",
    "atrium",
    "perimeter",
    "other",
}

VALID_SENSITIVITIES = {"low", "medium", "high"}

# Below this, the proposal goes to the "Needs your input" group and can never
# be bulk-approved.
MIN_CONFIDENCE = 0.6

# Matches the camera model's existing vocabulary.
KNOWN_EVENT_TYPES = {
    "person",
    "vehicle",
    "animal",
    "intrusion",
    "loitering",
    "crowd_spike",
}


def validate_proposal(proposal: dict, frame_width: int, frame_height: int) -> list[str]:
    """Return a list of failure reasons. Empty list means the proposal is usable."""
    reasons: list[str] = []

    scene_type = proposal.get("scene_type")
    if scene_type not in SCENE_TYPES:
        reasons.append(f"unknown scene_type {scene_type!r}")

    confidence = proposal.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        reasons.append("confidence missing or out of range")

    events = proposal.get("enabled_events")
    if not isinstance(events, list) or not events:
        reasons.append("enabled_events is empty")
    else:
        unknown = [e for e in events if e not in KNOWN_EVENT_TYPES]
        if unknown:
            reasons.append(f"unknown event types: {', '.join(map(str, unknown))}")

    if proposal.get("sensitivity") not in VALID_SENSITIVITIES:
        reasons.append("sensitivity must be low, medium or high")

    for zone in proposal.get("zones") or []:
        name = zone.get("name")
        polygon = zone.get("polygon")
        if not name:
            reasons.append("a zone has no name")
        if not isinstance(polygon, list) or len(polygon) < 3:
            reasons.append(f"zone {name!r} needs at least 3 points")
            continue
        for point in polygon:
            if (
                not isinstance(point, (list, tuple))
                or len(point) != 2
                or not (0 <= point[0] <= frame_width)
                or not (0 <= point[1] <= frame_height)
            ):
                reasons.append(f"zone {name!r} has a point outside the frame")
                break

    for line in proposal.get("counting_lines") or []:
        name = line.get("name")
        if not name:
            reasons.append("a counting line has no name")
        try:
            x1, y1, x2, y2 = int(line["x1"]), int(line["y1"]), int(line["x2"]), int(line["y2"])
        except (KeyError, TypeError, ValueError):
            reasons.append(f"counting line {name!r} is missing coordinates")
            continue
        if (x1, y1) == (x2, y2):
            reasons.append(f"counting line {name!r} has zero length")
        for x, y in ((x1, y1), (x2, y2)):
            if not (0 <= x <= frame_width and 0 <= y <= frame_height):
                reasons.append(f"counting line {name!r} extends outside the frame")
                break

    if not proposal.get("rationale"):
        # The rationale is what an operator reads before approving twelve
        # cameras at once. A proposal without one cannot be reviewed.
        reasons.append("no rationale given")

    return reasons
```

- [ ] **Step 2: Verify against valid and invalid proposals**

```bash
cd backend && uv run python - <<'PY'
from app.services.camera_setup.validator import validate_proposal

good = {
    "scene_type": "corridor", "confidence": 0.8,
    "enabled_events": ["person", "loitering"], "sensitivity": "medium",
    "zones": [{"name": "Corridor", "polygon": [[0,0],[100,0],[100,100]]}],
    "counting_lines": [{"name": "Door", "x1": 10, "y1": 10, "x2": 10, "y2": 200}],
    "rationale": "Indoor corridor, foot traffic only.",
}
assert validate_proposal(good, 1280, 720) == []
print("valid proposal passes                       OK")

cases = [
    ({**good, "scene_type": "hallway"}, "unknown scene_type"),
    ({**good, "confidence": 1.5}, "confidence"),
    ({**good, "enabled_events": []}, "enabled_events is empty"),
    ({**good, "enabled_events": ["teleport"]}, "unknown event types"),
    ({**good, "sensitivity": "extreme"}, "sensitivity"),
    ({**good, "zones": [{"name": "Z", "polygon": [[0,0],[1,1]]}]}, "at least 3 points"),
    ({**good, "zones": [{"name": "Z", "polygon": [[0,0],[9999,0],[5,5]]}]}, "outside the frame"),
    ({**good, "counting_lines": [{"name": "L", "x1":1,"y1":1,"x2":1,"y2":1}]}, "zero length"),
    ({**good, "rationale": ""}, "no rationale"),
]
for bad, expect in cases:
    reasons = validate_proposal(bad, 1280, 720)
    assert any(expect in r for r in reasons), (expect, reasons)
    print(f"rejected: {expect:<28} OK")
print("\nVALIDATOR OK")
PY
```

Expected: every line prints OK.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/camera_setup/
git commit -m "Add setup proposal validation"
```

---

### Task 3: Grouping proposals into review cards

**Files:**
- Create: `backend/app/services/camera_setup/grouping.py`

**Interfaces:**
- Consumes: `SCENE_TYPES`, `MIN_CONFIDENCE` from Task 2.
- Produces: `group_proposals(rows: list[ProposalLike]) -> list[ReviewGroup]` where `ProposalLike` is any object with `.id`, `.camera_id`, `.status`, `.scene_type`, `.confidence`, `.proposal` (dict); `ReviewGroup` is a dataclass with `.scene_type: str`, `.label: str`, `.bulk_approvable: bool`, `.shared_config: dict`, `.proposal_ids: list[uuid.UUID]`, `.differing_proposal_ids: list[uuid.UUID]`.

- [ ] **Step 1: Write the grouper**

```python
# backend/app/services/camera_setup/grouping.py
"""Cluster a batch of proposals into reviewable groups.

Clustering is on a closed scene_type enum, so it is exact rather than fuzzy
string matching. A camera whose config differs from its group's is split out
into its own card rather than silently averaged in — averaging would present
the operator with a config that no camera actually got proposed.
"""

import uuid
from dataclasses import dataclass, field

from app.services.camera_setup.validator import MIN_CONFIDENCE

# The fields a group must agree on to be bulk-approvable. Alert rules are
# deliberately excluded: who gets woken at 2am is confirmed per camera.
SHARED_FIELDS = ("enabled_events", "sensitivity", "suggest_pose")

NEEDS_INPUT = "needs_input"

LABELS = {
    "parking": "Parking",
    "corridor": "Corridors",
    "retail_frontage": "Retail frontage",
    "entrance": "Entrances",
    "loading_bay": "Loading bays",
    "atrium": "Atrium & open areas",
    "perimeter": "Perimeter",
    "other": "Needs your input",
    NEEDS_INPUT: "Needs your input",
}


@dataclass
class ReviewGroup:
    scene_type: str
    label: str
    bulk_approvable: bool
    shared_config: dict = field(default_factory=dict)
    proposal_ids: list[uuid.UUID] = field(default_factory=list)
    differing_proposal_ids: list[uuid.UUID] = field(default_factory=list)


def _signature(proposal: dict) -> tuple:
    events = proposal.get("enabled_events") or []
    return (
        tuple(sorted(str(e) for e in events)),
        proposal.get("sensitivity"),
        bool(proposal.get("suggest_pose")),
    )


def group_proposals(rows) -> list[ReviewGroup]:
    """Group proposals by scene type; split outliers into their own cards."""
    buckets: dict[str, list] = {}
    for row in rows:
        needs_input = (
            row.status in ("needs_input", "failed", "pending")
            or row.scene_type in (None, "other")
            or (row.confidence or 0.0) < MIN_CONFIDENCE
        )
        key = NEEDS_INPUT if needs_input else row.scene_type
        buckets.setdefault(key, []).append(row)

    groups: list[ReviewGroup] = []
    for key, members in sorted(buckets.items()):
        if key == NEEDS_INPUT:
            groups.append(
                ReviewGroup(
                    scene_type=NEEDS_INPUT,
                    label=LABELS[NEEDS_INPUT],
                    bulk_approvable=False,
                    proposal_ids=[m.id for m in members],
                )
            )
            continue

        # The majority signature defines the group; everything else is an
        # outlier the operator reviews individually.
        counts: dict[tuple, int] = {}
        for m in members:
            counts[_signature(m.proposal)] = counts.get(_signature(m.proposal), 0) + 1
        majority = max(counts, key=lambda s: (counts[s], str(s)))

        agreeing = [m for m in members if _signature(m.proposal) == majority]
        differing = [m for m in members if _signature(m.proposal) != majority]
        template = agreeing[0].proposal

        groups.append(
            ReviewGroup(
                scene_type=key,
                label=LABELS.get(key, key),
                # A group of one is not a bulk action; review it directly.
                bulk_approvable=len(agreeing) > 1,
                shared_config={f: template.get(f) for f in SHARED_FIELDS},
                proposal_ids=[m.id for m in agreeing],
                differing_proposal_ids=[m.id for m in differing],
            )
        )
    return groups
```

- [ ] **Step 2: Verify grouping and outlier splitting**

```bash
cd backend && uv run python - <<'PY'
import uuid
from types import SimpleNamespace as NS
from app.services.camera_setup.grouping import group_proposals, NEEDS_INPUT

def p(scene, events, sens="medium", conf=0.9, status="proposed", pose=False):
    return NS(id=uuid.uuid4(), camera_id=uuid.uuid4(), status=status,
              scene_type=scene, confidence=conf,
              proposal={"enabled_events": events, "sensitivity": sens, "suggest_pose": pose})

rows = [p("corridor", ["person"]) for _ in range(3)] \
     + [p("parking", ["person","vehicle"]) for _ in range(2)] \
     + [p("corridor", ["person","vehicle"])] \
     + [p("corridor", ["person"], conf=0.3)] \
     + [p(None, ["person"], status="failed")]

groups = {g.scene_type: g for g in group_proposals(rows)}
assert set(groups) == {"corridor", "parking", NEEDS_INPUT}, list(groups)
print("groups:", sorted(groups))

assert len(groups["corridor"].proposal_ids) == 3
assert len(groups["corridor"].differing_proposal_ids) == 1
print("majority of 3 grouped, 1 outlier split out       OK")

assert groups["parking"].bulk_approvable is True
assert groups[NEEDS_INPUT].bulk_approvable is False
print("needs_input is never bulk-approvable             OK")

assert len(groups[NEEDS_INPUT].proposal_ids) == 2   # low confidence + failed
print("low confidence and failed both routed to it     OK")

single = group_proposals([p("atrium", ["person"])])
assert single[0].bulk_approvable is False
print("a group of one is not a bulk action              OK")
print("\nGROUPING OK")
PY
```

Expected: every line prints OK.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/camera_setup/grouping.py
git commit -m "Add setup proposal grouping"
```

---

### Task 4: Wire shapes

**Files:**
- Create: `backend/app/schemas/camera_setup.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SetupJob`, `SetupJobsResponse`, `SetupResultRequest`, `ProposalResponse`, `ReviewGroupResponse`, `SetupRunResponse`, `StartRunRequest`, `ApproveGroupRequest`.

- [ ] **Step 1: Write the schemas**

```python
# backend/app/schemas/camera_setup.py
"""Wire shapes for agentic camera setup."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SetupJob(BaseModel):
    """One camera for the pipeline to observe and propose a config for."""

    camera_id: uuid.UUID
    camera_name: str
    rtsp_url: str | None = None
    # Observation parameters travel with the job so they can be tuned
    # server-side without shipping a new agent build.
    frame_count: int = 10
    observe_seconds: int = 180


class SetupJobsResponse(BaseModel):
    jobs: list[SetupJob] = []


class SetupResultRequest(BaseModel):
    """The pipeline's answer for one camera: a proposal, or why not."""

    proposal: dict | None = None
    error: str | None = None
    frame_width: int = 1280
    frame_height: int = 720


class ProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    camera_id: uuid.UUID
    status: str
    scene_type: str | None = None
    scene_description: str | None = None
    confidence: float | None = None
    proposal: dict = {}
    rationale: str | None = None
    error: str | None = None
    approved_at: datetime | None = None


class ReviewGroupResponse(BaseModel):
    scene_type: str
    label: str
    bulk_approvable: bool
    shared_config: dict = {}
    proposals: list[ProposalResponse] = []
    differing: list[ProposalResponse] = []


class SetupRunResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    status: str
    camera_count: int
    pending: int = 0
    groups: list[ReviewGroupResponse] = []


class StartRunRequest(BaseModel):
    # Explicit camera list, never "the whole site" — the operator chooses the
    # batch so they can learn from the first one.
    camera_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=50)


class ApproveGroupRequest(BaseModel):
    scene_type: str
```

- [ ] **Step 2: Verify the schemas import and enforce the batch cap**

```bash
cd backend && uv run python - <<'PY'
import uuid, pydantic
from app.schemas.camera_setup import StartRunRequest, SetupJob
StartRunRequest(camera_ids=[uuid.uuid4()])
try:
    StartRunRequest(camera_ids=[uuid.uuid4() for _ in range(51)])
    raise SystemExit("FAIL: batch cap not enforced")
except pydantic.ValidationError:
    print("batch cap of 50 enforced        OK")
j = SetupJob(camera_id=uuid.uuid4(), camera_name="c")
assert (j.frame_count, j.observe_seconds) == (10, 180)
print("observation defaults 10 / 180s  OK")
PY
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/camera_setup.py
git commit -m "Add camera setup wire schemas"
```

---

### Task 5: Agent-facing job endpoints

**Files:**
- Modify: `backend/app/api/agents.py`

**Interfaces:**
- Consumes: `SetupJob`, `SetupJobsResponse`, `SetupResultRequest` (Task 4); `CameraSetupProposal` (Task 1); `validate_proposal` (Task 2).
- Produces: `GET /api/agents/me/setup-jobs`, `POST /api/agents/me/setup-jobs/{camera_id}`, and the helper `enqueue_setup_job(agent_id, job)` used by Task 6.

- [ ] **Step 1: Add the queue helper and endpoints**

Add near the existing `_resolve_queue_key` / `_enqueue_resolve_job` helpers in `backend/app/api/agents.py`:

```python
SETUP_QUEUE_TTL_SECONDS = 3600


def _setup_queue_key(agent_id: uuid.UUID) -> str:
    return f"agent:{agent_id}:setup-jobs"


async def enqueue_setup_job(agent_id: uuid.UUID, job: SetupJob) -> None:
    r = await get_redis()
    key = _setup_queue_key(agent_id)
    await r.rpush(key, job.model_dump_json())
    await r.expire(key, SETUP_QUEUE_TTL_SECONDS)
```

Then append these endpoints to the same file:

```python
@router.get("/me/setup-jobs", response_model=SetupJobsResponse)
async def get_setup_jobs(
    agent: Agent = Depends(get_agent_from_token),
) -> SetupJobsResponse:
    """Drain pending camera-setup jobs for this agent.

    Polled by the PYTHON PIPELINE, not the Go agent: the pipeline is the
    process that holds decoded frames and can call Gemini. It authenticates
    with the same device token.

    Jobs are popped. The camera_setup_proposals row — not this queue — is the
    source of truth, so a lost job leaves a visible `pending` proposal the
    operator can retry.
    """
    r = await get_redis()
    key = _setup_queue_key(agent.id)
    jobs: list[SetupJob] = []
    while True:
        raw = await r.lpop(key)
        if raw is None:
            break
        jobs.append(SetupJob.model_validate_json(raw))
    return SetupJobsResponse(jobs=jobs)


@router.post("/me/setup-jobs/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def post_setup_result(
    camera_id: uuid.UUID,
    payload: SetupResultRequest,
    agent: Agent = Depends(get_agent_from_token),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Record the pipeline's proposal for one camera.

    Never writes camera config — only the proposal row. Approval is a separate,
    human action.
    """
    stmt = (
        select(CameraSetupProposal)
        .join(Camera, Camera.id == CameraSetupProposal.camera_id)
        .where(
            CameraSetupProposal.camera_id == camera_id,
            CameraSetupProposal.status == "pending",
            Camera.agent_id == agent.id,
        )
        .order_by(CameraSetupProposal.created_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no pending proposal")

    if payload.error or not payload.proposal:
        row.status = "failed"
        row.error = payload.error or "no proposal returned"
        await db.flush()
        return

    reasons = validate_proposal(payload.proposal, payload.frame_width, payload.frame_height)
    row.proposal = payload.proposal
    row.scene_type = payload.proposal.get("scene_type")
    row.scene_description = payload.proposal.get("scene_description")
    row.confidence = payload.proposal.get("confidence")
    row.rationale = payload.proposal.get("rationale")

    if reasons:
        # Never corrected — a corrected proposal is no longer the thing the
        # model justified in its rationale.
        row.status = "needs_input"
        row.error = "; ".join(reasons)
    else:
        row.status = "proposed"
        row.error = None
    await db.flush()
```

- [ ] **Step 2: Add the imports**

At the top of `backend/app/api/agents.py`, add to the existing import block:

```python
from app.models.camera_setup import CameraSetupProposal
from app.schemas.camera_setup import SetupJob, SetupJobsResponse, SetupResultRequest
from app.services.camera_setup.validator import validate_proposal
```

- [ ] **Step 3: Verify the routes register**

```bash
cd backend && uv run python -c "
from app.main import app
s = app.openapi()['paths']
got = sorted(p for p in s if 'setup-jobs' in p)
print(got)
assert got == ['/api/agents/me/setup-jobs', '/api/agents/me/setup-jobs/{camera_id}'], got
print('setup job routes registered  OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/agents.py
git commit -m "Add agent-facing camera setup job endpoints"
```

---

### Task 6: Operator API — start a run, review groups, approve

**Files:**
- Create: `backend/app/api/camera_setup.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `enqueue_setup_job` (Task 5); `group_proposals`, `ReviewGroup` (Task 3); all schemas (Task 4); models (Task 1).
- Produces: `POST /api/sites/{site_id}/setup-runs`, `GET /api/setup-runs/{run_id}`, `POST /api/setup-proposals/{proposal_id}/approve`, `POST /api/setup-runs/{run_id}/approve-group`.

- [ ] **Step 1: Write the router**

```python
# backend/app/api/camera_setup.py
"""Operator-facing endpoints for agentic camera setup.

Approval is the only path that writes camera configuration. A proposal on its
own changes nothing.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agents import enqueue_setup_job
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role, scope_to_sites
from app.models.camera import Camera
from app.models.camera_setup import CameraSetupProposal, SetupRun
from app.models.site import Site
from app.models.user import User
from app.schemas.camera_setup import (
    ApproveGroupRequest,
    ProposalResponse,
    ReviewGroupResponse,
    SetupJob,
    SetupRunResponse,
    StartRunRequest,
)
from app.services.camera_setup.grouping import group_proposals

router = APIRouter(prefix="/api", tags=["camera-setup"])


async def _load_site(site_id: uuid.UUID, user: User, db: AsyncSession) -> Site:
    q = select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Site.org_id == user.org_id)
    q = scope_to_sites(q, Site.id, user)
    site = (await db.execute(q)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


async def _load_run(run_id: uuid.UUID, user: User, db: AsyncSession) -> SetupRun:
    q = select(SetupRun).where(SetupRun.id == run_id)
    if user.role != "super_admin":
        q = q.where(SetupRun.org_id == user.org_id)
    q = scope_to_sites(q, SetupRun.site_id, user)
    run = (await db.execute(q)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Setup run not found")
    return run


@router.post("/sites/{site_id}/setup-runs", response_model=SetupRunResponse, status_code=201)
async def start_setup_run(
    site_id: uuid.UUID,
    body: StartRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start a setup run over an operator-selected batch of cameras."""
    require_role(user, "admin")
    site = await _load_site(site_id, user, db)

    cameras = list(
        (
            await db.execute(
                select(Camera).where(
                    Camera.id.in_(body.camera_ids),
                    Camera.site_id == site.id,
                    Camera.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not cameras:
        raise HTTPException(status_code=404, detail="No cameras found at this site")

    unplaced = [c.name for c in cameras if c.agent_id is None]
    if unplaced:
        # Without an agent there is nothing to observe the camera. Say so
        # rather than creating proposals that can never be fulfilled.
        raise HTTPException(
            status_code=400,
            detail=f"These cameras are not assigned to an appliance yet: {', '.join(unplaced)}",
        )

    run = SetupRun(
        org_id=site.org_id,
        site_id=site.id,
        requested_by=user.id,
        status="running",
        camera_count=len(cameras),
    )
    db.add(run)
    await db.flush()

    for camera in cameras:
        db.add(
            CameraSetupProposal(
                org_id=site.org_id,
                site_id=site.id,
                camera_id=camera.id,
                run_id=run.id,
                status="pending",
            )
        )
        await enqueue_setup_job(
            camera.agent_id,
            SetupJob(
                camera_id=camera.id,
                camera_name=camera.name,
                rtsp_url=camera.rtsp_url,
            ),
        )
    await db.flush()
    return await _run_response(run, db)


async def _run_response(run: SetupRun, db: AsyncSession) -> SetupRunResponse:
    rows = list(
        (
            await db.execute(
                select(CameraSetupProposal).where(CameraSetupProposal.run_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    by_id = {r.id: r for r in rows}
    groups = [
        ReviewGroupResponse(
            scene_type=g.scene_type,
            label=g.label,
            bulk_approvable=g.bulk_approvable,
            shared_config=g.shared_config,
            proposals=[ProposalResponse.model_validate(by_id[i]) for i in g.proposal_ids],
            differing=[ProposalResponse.model_validate(by_id[i]) for i in g.differing_proposal_ids],
        )
        for g in group_proposals(rows)
    ]
    return SetupRunResponse(
        id=run.id,
        site_id=run.site_id,
        status=run.status,
        camera_count=run.camera_count,
        pending=sum(1 for r in rows if r.status == "pending"),
        groups=groups,
    )


@router.get("/setup-runs/{run_id}", response_model=SetupRunResponse)
async def get_setup_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = await _load_run(run_id, user, db)
    return await _run_response(run, db)


def _apply(camera: Camera, proposal: dict) -> None:
    """Write an approved proposal onto the camera.

    Only ever called from an approve endpoint, and only for a proposal whose
    status is `proposed` — never `needs_input` or `failed`.
    """
    camera.enabled_events = list(proposal.get("enabled_events") or [])
    camera.sensitivity = proposal.get("sensitivity") or "medium"
    camera.detection_zones = list(proposal.get("zones") or [])
    camera.counting_lines = list(proposal.get("counting_lines") or [])


@router.post("/setup-proposals/{proposal_id}/approve", response_model=ProposalResponse)
async def approve_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve one camera's proposal and write its configuration."""
    require_role(user, "admin")

    q = select(CameraSetupProposal).where(CameraSetupProposal.id == proposal_id)
    if user.role != "super_admin":
        q = q.where(CameraSetupProposal.org_id == user.org_id)
    q = scope_to_sites(q, CameraSetupProposal.site_id, user)
    row = (await db.execute(q)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if row.status != "proposed":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve a proposal in state '{row.status}'",
        )

    camera = (
        await db.execute(select(Camera).where(Camera.id == row.camera_id))
    ).scalar_one_or_none()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    _apply(camera, row.proposal)
    row.status = "approved"
    row.approved_by = user.id
    row.approved_at = datetime.now(timezone.utc)
    await db.flush()
    return ProposalResponse.model_validate(row)


@router.post("/setup-runs/{run_id}/approve-group", response_model=SetupRunResponse)
async def approve_group(
    run_id: uuid.UUID,
    body: ApproveGroupRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Approve every agreeing proposal in one scene group.

    Detection configuration only. Alert rules are confirmed per camera, and
    a non-bulk-approvable group (needs_input, or a group of one) is refused.
    """
    require_role(user, "admin")
    run = await _load_run(run_id, user, db)

    rows = list(
        (
            await db.execute(
                select(CameraSetupProposal).where(CameraSetupProposal.run_id == run.id)
            )
        )
        .scalars()
        .all()
    )
    target = next((g for g in group_proposals(rows) if g.scene_type == body.scene_type), None)
    if target is None:
        raise HTTPException(status_code=404, detail="No such group in this run")
    if not target.bulk_approvable:
        raise HTTPException(
            status_code=400, detail="This group must be reviewed one camera at a time"
        )

    by_id = {r.id: r for r in rows}
    camera_ids = [by_id[i].camera_id for i in target.proposal_ids]
    cameras = {
        c.id: c
        for c in (
            await db.execute(select(Camera).where(Camera.id.in_(camera_ids)))
        ).scalars().all()
    }

    now = datetime.now(timezone.utc)
    for pid in target.proposal_ids:
        row = by_id[pid]
        if row.status != "proposed":
            continue
        camera = cameras.get(row.camera_id)
        if camera is None:
            continue
        _apply(camera, row.proposal)
        row.status = "approved"
        row.approved_by = user.id
        row.approved_at = now

    if all(r.status in ("approved", "rejected") for r in rows):
        run.status = "complete"
    await db.flush()
    return await _run_response(run, db)
```

- [ ] **Step 2: Register the router**

In `backend/app/main.py`, add the import next to the other API routers:

```python
from app.api.camera_setup import router as camera_setup_router
```

and register it after `app.include_router(camera_connections_router)`:

```python
app.include_router(camera_setup_router)
```

- [ ] **Step 3: Verify routes and the guard rails**

```bash
cd backend && uv run python -c "
from app.main import app
s = app.openapi()['paths']
got = sorted(p for p in s if 'setup-run' in p or 'setup-proposal' in p)
for p in got: print(' ', p, sorted(s[p]))
assert '/api/sites/{site_id}/setup-runs' in got
assert '/api/setup-runs/{run_id}/approve-group' in got
assert '/api/setup-proposals/{proposal_id}/approve' in got
print('operator routes registered  OK')"
```

- [ ] **Step 4: End-to-end verification against Postgres**

Create `backend/tests/test_setup_verify.py` **temporarily** (delete it in Step 5):

```python
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.agent import Agent
from app.models.camera import Camera
from app.models.camera_setup import CameraSetupProposal
from app.models.site import Site


@pytest.mark.asyncio
async def test_setup_run_flow(auth_client, db_session, test_org):
    site = Site(org_id=test_org.id, name="Mall", timezone="Asia/Kolkata")
    db_session.add(site); await db_session.flush()
    agent = Agent(org_id=test_org.id, site_id=site.id, machine_id="box",
                  pubkey="k", device_token_hash="h", status="online",
                  capacity_cameras=12, last_seen_at=datetime.now(timezone.utc))
    db_session.add(agent); await db_session.flush()
    cams = []
    for i in range(3):
        c = Camera(org_id=test_org.id, site_id=site.id, agent_id=agent.id,
                   name=f"cam{i}", ingest_mode="rtsp_pull", rtsp_url="rtsp://x",
                   enabled_events=["person"], detection_zones=[], sensitivity="medium",
                   status="online", idle_fps=1, active_fps=5)
        db_session.add(c); cams.append(c)
    # one camera with no appliance
    orphan = Camera(org_id=test_org.id, site_id=site.id, agent_id=None, name="orphan",
                    ingest_mode="rtsp_pull", rtsp_url="rtsp://x", enabled_events=["person"],
                    detection_zones=[], sensitivity="medium", status="online",
                    idle_fps=1, active_fps=5)
    db_session.add(orphan); await db_session.flush()

    base = f"/api/sites/{site.id}/setup-runs"

    r = await auth_client.post(base, json={"camera_ids": [str(orphan.id)]})
    assert r.status_code == 400 and "not assigned" in r.text
    print("\n  unplaced camera refused with a reason        OK")

    r = await auth_client.post(base, json={"camera_ids": [str(c.id) for c in cams]})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["camera_count"] == 3 and run["pending"] == 3
    print("  run created, 3 proposals pending             OK")

    rows = (await db_session.execute(
        select(CameraSetupProposal).where(CameraSetupProposal.run_id == uuid.UUID(run["id"]))
    )).scalars().all()

    good = {"scene_type": "corridor", "scene_description": "Indoor corridor",
            "confidence": 0.9, "enabled_events": ["person"], "sensitivity": "medium",
            "zones": [], "counting_lines": [], "suggest_pose": False,
            "rationale": "Foot traffic only; no vehicles seen."}
    for row in rows[:2]:
        row.status = "proposed"; row.proposal = good
        row.scene_type = "corridor"; row.confidence = 0.9; row.rationale = good["rationale"]
    rows[2].status = "needs_input"; rows[2].error = "no rationale given"
    await db_session.flush()

    r = await auth_client.get(f"/api/setup-runs/{run['id']}")
    groups = {g["scene_type"]: g for g in r.json()["groups"]}
    assert "corridor" in groups and "needs_input" in groups
    assert groups["corridor"]["bulk_approvable"] is True
    assert groups["needs_input"]["bulk_approvable"] is False
    print("  grouped: corridor bulk-approvable, other not  OK")

    r = await auth_client.post(f"/api/setup-runs/{run['id']}/approve-group",
                               json={"scene_type": "needs_input"})
    assert r.status_code == 400
    print("  needs_input group refuses bulk approval      OK")

    r = await auth_client.post(f"/api/setup-runs/{run['id']}/approve-group",
                               json={"scene_type": "corridor"})
    assert r.status_code == 200, r.text
    await db_session.refresh(cams[0])
    assert cams[0].enabled_events == ["person"]
    approved = (await db_session.execute(
        select(CameraSetupProposal).where(CameraSetupProposal.status == "approved")
    )).scalars().all()
    assert len(approved) == 2 and all(a.approved_at is not None for a in approved)
    print("  approval wrote config and recorded approver  OK")

    r = await auth_client.post(f"/api/setup-proposals/{rows[2].id}/approve")
    assert r.status_code == 400 and "needs_input" in r.text
    print("  needs_input proposal cannot be approved      OK")
```

Run it:

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:55450/nw_main"
docker exec nw-setup psql -U postgres -q -c "CREATE DATABASE nw_suite;" postgres
export TEST_DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:55450/nw_suite"
export PYTHONPATH=$PWD
uv run pytest tests/test_setup_verify.py -q -s
```

Expected: `1 passed`, with every OK line printed.

- [ ] **Step 5: Delete the temporary test and commit**

```bash
cd backend && rm tests/test_setup_verify.py
export TEST_DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:55450/nw_suite"
export PYTHONPATH=$PWD
uv run pytest tests/ -q       # expect 133 passed + the 5 known pre-existing failures
cd .. && git add backend/app/api/camera_setup.py backend/app/main.py
git commit -m "Add operator API for camera setup runs and approval"
```

---

### Task 7: Pipeline scene analyzer

**Files:**
- Create: `agent/pipeline/scene_analyzer.py`

**Interfaces:**
- Consumes: `GeminiClient` from `agent/pipeline/gemini_client.py`.
- Produces: `SETUP_PROMPT: str`, `async analyze_scene(gemini, frames: list[bytes], camera_name: str) -> dict` returning the proposal dict, raising `SceneAnalysisError` on failure.

- [ ] **Step 1: Write the analyzer**

```python
# agent/pipeline/scene_analyzer.py
"""Look at a camera and propose how it should be configured.

Runs in the pipeline because that is the process holding decoded frames and
the brokered Gemini credential. Frames go pipeline → Gemini directly; they
never reach the backend.
"""

import json
import logging

logger = logging.getLogger(__name__)


class SceneAnalysisError(Exception):
    """The camera could not be analysed. Carries an operator-readable reason."""


SCENE_TYPES = [
    "parking", "corridor", "retail_frontage", "entrance",
    "loading_bay", "atrium", "perimeter", "other",
]

EVENT_TYPES = ["person", "vehicle", "animal", "intrusion", "loitering", "crowd_spike"]

SETUP_PROMPT = f"""You are configuring a CCTV camera for a security platform.

You are shown several frames sampled over a few minutes from ONE fixed camera
called "{{camera_name}}". Frames are {{width}}x{{height}} pixels.

Decide how this camera should be configured. Reply with ONLY a JSON object:

{{{{
  "scene_type": one of {SCENE_TYPES},
  "scene_description": "one sentence describing what this camera watches",
  "confidence": 0.0-1.0,
  "enabled_events": subset of {EVENT_TYPES},
  "sensitivity": "low" | "medium" | "high",
  "zones": [{{{{"name": "...", "polygon": [[x,y],[x,y],[x,y]]}}}}],
  "counting_lines": [{{{{"name": "...", "x1": 0, "y1": 0, "x2": 0, "y2": 0}}}}],
  "suggest_pose": true | false,
  "suggested_alert": null or {{{{"event_types": [...], "min_severity": "low|medium|high|critical"}}}},
  "rationale": "why you chose the above, in plain English for a security manager"
}}}}

Rules:
- Only enable an event type you actually saw evidence for. Enabling vehicle
  detection on an indoor corridor produces false alerts and erodes trust.
- Zone polygons and counting-line coordinates must lie within the frame.
- Only propose a counting line where there is a clear single crossing point
  such as a doorway or gate. If there is no natural crossing, return [].
- suggest_pose only if this scene involves a repeatable procedure worth
  tracking posture for. It is expensive; default to false.
- If you cannot tell what this camera is looking at, set scene_type "other"
  and confidence below 0.5 rather than guessing.
- The rationale is read by a person approving this for many cameras at once.
  Say what you saw and what you deliberately left off.
"""


def _extract_json(text: str) -> dict:
    """Parse the model's reply, tolerating a ```json fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise SceneAnalysisError("model did not return JSON")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SceneAnalysisError(f"model returned unparseable JSON: {exc}") from exc


async def analyze_scene(gemini, frames: list[bytes], camera_name: str,
                        width: int = 1280, height: int = 720) -> dict:
    """Ask Gemini to propose a configuration from sampled frames.

    Raises SceneAnalysisError with an operator-readable reason. One corrective
    re-prompt is attempted on unparseable output, matching the sequence
    compiler's behaviour.
    """
    if not frames:
        raise SceneAnalysisError("could not observe this camera long enough")

    prompt = SETUP_PROMPT.format(camera_name=camera_name, width=width, height=height)
    try:
        text = await gemini.generate_text_with_images(prompt, frames)
    except Exception as exc:  # noqa: BLE001
        raise SceneAnalysisError(f"scene analysis unavailable: {exc}") from exc

    try:
        return _extract_json(text)
    except SceneAnalysisError:
        logger.warning("[%s] unparseable setup reply; re-prompting once", camera_name)
        retry_prompt = prompt + "\n\nYour previous reply was not valid JSON. Reply with ONLY the JSON object."
        try:
            text = await gemini.generate_text_with_images(retry_prompt, frames)
        except Exception as exc:  # noqa: BLE001
            raise SceneAnalysisError(f"scene analysis unavailable: {exc}") from exc
        return _extract_json(text)
```

- [ ] **Step 2: Add the multi-image helper to the Gemini client**

`agent/pipeline/gemini_client.py` currently only exposes `analyze_frame`. Add a method to the same class (match the existing client's SDK usage — read `analyze_frame` first and mirror how it builds `contents` and calls the model):

```python
    async def generate_text_with_images(self, prompt: str, images: list[bytes]) -> str:
        """One text reply grounded in several JPEG frames.

        Used by scene analysis at setup time, not on the detection hot path,
        so it deliberately does not go through the circuit breaker that guards
        per-frame calls — a setup run failing must not open the breaker that
        detection depends on.
        """
        parts = [{"inline_data": {"mime_type": "image/jpeg", "data": img}} for img in images]
        parts.append({"text": prompt})
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=[{"role": "user", "parts": parts}],
        )
        return response.text or ""
```

- [ ] **Step 3: Verify JSON extraction and error paths**

```bash
cd agent/pipeline && .venv/bin/python - <<'PY'
import asyncio
from scene_analyzer import _extract_json, analyze_scene, SceneAnalysisError

assert _extract_json('{"a": 1}') == {"a": 1}
assert _extract_json('```json\n{"a": 2}\n```') == {"a": 2}
assert _extract_json('Here you go:\n{"a": 3}\nhope that helps') == {"a": 3}
print("json extraction handles fences and prose   OK")

for bad in ("no json here", "{broken"):
    try:
        _extract_json(bad); raise SystemExit(f"FAIL: accepted {bad!r}")
    except SceneAnalysisError:
        pass
print("unparseable replies raise SceneAnalysisError OK")

class Boom:
    async def generate_text_with_images(self, *a, **k):
        raise RuntimeError("circuit open")

async def main():
    try:
        await analyze_scene(Boom(), [b"x"], "cam")
        raise SystemExit("FAIL: should have raised")
    except SceneAnalysisError as e:
        assert "unavailable" in str(e)
    try:
        await analyze_scene(Boom(), [], "cam")
        raise SystemExit("FAIL: should have raised")
    except SceneAnalysisError as e:
        assert "observe this camera long enough" in str(e)
    print("no frames and provider failure both report reasons OK")

asyncio.run(main())
PY
```

- [ ] **Step 4: Commit**

```bash
git add agent/pipeline/scene_analyzer.py agent/pipeline/gemini_client.py
git commit -m "Add pipeline scene analyzer for camera setup"
```

---

### Task 8: Pipeline polls and answers setup jobs

**Files:**
- Modify: `agent/pipeline/supervisor.py`
- Modify: `agent/pipeline/api_client.py`

**Interfaces:**
- Consumes: `analyze_scene`, `SceneAnalysisError` (Task 7); the endpoints from Task 5.
- Produces: `ApiClient.get_setup_jobs()`, `ApiClient.post_setup_result(camera_id, payload)`; `WorkerSupervisor._setup_loop()`.

- [ ] **Step 1: Add the client methods**

Append to `ApiClient` in `agent/pipeline/api_client.py`:

```python
    async def get_setup_jobs(self) -> list[dict]:
        """Drain camera-setup jobs for this box. Empty list on any failure."""
        try:
            resp = await self.client.get("/api/agents/me/setup-jobs")
            if resp.status_code != 200:
                return []
            return resp.json().get("jobs", [])
        except Exception as e:
            logger.debug(f"setup jobs fetch failed: {e}")
            return []

    async def post_setup_result(self, camera_id: str, payload: dict) -> bool:
        try:
            resp = await self.client.post(
                f"/api/agents/me/setup-jobs/{camera_id}", json=payload
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"setup result post failed for {camera_id}: {e}")
            return False
```

- [ ] **Step 2: Add the setup loop to the supervisor**

Add the constant near `DEGRADED_LOAD_FACTOR` in `agent/pipeline/supervisor.py`:

```python
# Setup analysis is not urgent; detection is. Bounding concurrency keeps an
# onboarding run from competing with the pipeline this box exists to run.
MAX_CONCURRENT_SETUP_JOBS = 2
SETUP_POLL_INTERVAL = 30
```

Add these methods to `WorkerSupervisor`:

```python
    async def _setup_loop(self):
        """Poll for camera-setup jobs and answer them."""
        while True:
            try:
                await asyncio.sleep(SETUP_POLL_INTERVAL)
                jobs = await self.api_client.get_setup_jobs()
                if not jobs:
                    continue
                semaphore = asyncio.Semaphore(MAX_CONCURRENT_SETUP_JOBS)

                async def run(job):
                    async with semaphore:
                        await self._run_setup_job(job)

                await asyncio.gather(*(run(j) for j in jobs), return_exceptions=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"setup loop error: {e}")

    async def _run_setup_job(self, job: dict):
        """Observe one camera and post a proposal (or the reason there isn't one)."""
        import cv2
        from scene_analyzer import SceneAnalysisError, analyze_scene

        camera_id = job.get("camera_id")
        name = job.get("camera_name", camera_id)
        frame_count = int(job.get("frame_count", 10))
        observe_seconds = int(job.get("observe_seconds", 180))

        worker = self.workers.get(camera_id)
        if worker is None:
            await self.api_client.post_setup_result(
                camera_id, {"error": "this camera is not running on this appliance"}
            )
            return

        interval = max(1.0, observe_seconds / max(1, frame_count))
        frames: list[bytes] = []
        height, width = 720, 1280
        for _ in range(frame_count):
            frame = worker.last_frame
            if frame is not None:
                height, width = frame.shape[0], frame.shape[1]
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    frames.append(buf.tobytes())
            await asyncio.sleep(interval)

        try:
            proposal = await analyze_scene(self.gemini, frames, name, width, height)
        except SceneAnalysisError as exc:
            await self.api_client.post_setup_result(camera_id, {"error": str(exc)})
            return

        await self.api_client.post_setup_result(
            camera_id,
            {"proposal": proposal, "frame_width": width, "frame_height": height},
        )
        logger.info(f"[{name}] setup proposal submitted")
```

- [ ] **Step 3: Start the loop**

In `WorkerSupervisor.run`, alongside the existing `reconcile_task = asyncio.create_task(self._reconcile_loop())`, add:

```python
        setup_task = asyncio.create_task(self._setup_loop())
```

and in the `except asyncio.CancelledError:` shutdown block, cancel it next to `reconcile_task`:

```python
            setup_task.cancel()
            try:
                await setup_task
            except (asyncio.CancelledError, Exception):
                pass
```

- [ ] **Step 4: Verify the supervisor still constructs and the interfaces exist**

```bash
cd agent/pipeline && .venv/bin/python -c "
import supervisor, scene_analyzer
from supervisor import WorkerSupervisor, MAX_CONCURRENT_SETUP_JOBS
s = WorkerSupervisor()
assert hasattr(s, '_setup_loop') and hasattr(s, '_run_setup_job')
assert hasattr(s.api_client, 'get_setup_jobs') and hasattr(s.api_client, 'post_setup_result')
assert MAX_CONCURRENT_SETUP_JOBS == 2
print('supervisor wired for setup jobs  OK')" 2>&1 | tail -2
```

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline/supervisor.py agent/pipeline/api_client.py
git commit -m "Pipeline polls and answers camera setup jobs"
```

---

### Task 9: Review UI

**Files:**
- Create: `frontend/src/app/setup/layout.tsx`
- Create: `frontend/src/app/setup/page.tsx`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/components/layout/sidebar.tsx`

**Interfaces:**
- Consumes: the operator endpoints from Task 6.
- Produces: a `/setup` route.

- [ ] **Step 1: Add types**

Append to `frontend/src/types/index.ts`:

```ts
// ─── Agentic camera setup ───────────────────────────────────────────────────

export interface SetupProposal {
  id: string;
  camera_id: string;
  status: "pending" | "proposed" | "needs_input" | "failed" | "approved" | "rejected";
  scene_type: string | null;
  scene_description: string | null;
  confidence: number | null;
  proposal: Record<string, unknown>;
  /** Why the agent chose this. Shown verbatim — never summarised. */
  rationale: string | null;
  error: string | null;
  approved_at: string | null;
}

export interface SetupReviewGroup {
  scene_type: string;
  label: string;
  /** False for "needs your input" and for a group of one. */
  bulk_approvable: boolean;
  shared_config: Record<string, unknown>;
  proposals: SetupProposal[];
  differing: SetupProposal[];
}

export interface SetupRun {
  id: string;
  site_id: string;
  status: string;
  camera_count: number;
  pending: number;
  groups: SetupReviewGroup[];
}
```

- [ ] **Step 2: Add API methods**

Add to the `ApiClient` class in `frontend/src/lib/api.ts` (and add `SetupRun` to the `@/types` import list at the top):

```ts
  // ─── Agentic camera setup ────────────────────────────────────────────────

  async startSetupRun(siteId: string, cameraIds: string[]) {
    return this.request<SetupRun>(`/api/sites/${siteId}/setup-runs`, {
      method: "POST",
      body: JSON.stringify({ camera_ids: cameraIds }),
    });
  }

  async getSetupRun(runId: string) {
    return this.request<SetupRun>(`/api/setup-runs/${runId}`);
  }

  async approveSetupProposal(proposalId: string) {
    return this.request<unknown>(`/api/setup-proposals/${proposalId}/approve`, {
      method: "POST",
    });
  }

  async approveSetupGroup(runId: string, sceneType: string) {
    return this.request<SetupRun>(`/api/setup-runs/${runId}/approve-group`, {
      method: "POST",
      body: JSON.stringify({ scene_type: sceneType }),
    });
  }
```

- [ ] **Step 3: Create the page**

```tsx
// frontend/src/app/setup/layout.tsx
import { AppShell } from "@/components/layout/app-shell";

export default function PageLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
```

```tsx
// frontend/src/app/setup/page.tsx
"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { StatusDot } from "@/components/shared/status-dot";
import { Skeleton } from "@/components/ui/Skeleton";
import type { SetupProposal, SetupReviewGroup } from "@/types";

const BATCH_CAP = 50;

/**
 * Agentic camera setup — pick a batch, let the agent propose, review by group.
 *
 * The rationale is shown in full on every card: an operator approving twelve
 * cameras at once needs to know WHY vehicle detection was left off, and a
 * proposal they cannot interrogate is one they will rubber-stamp or ignore.
 */
export default function SetupPage() {
  const qc = useQueryClient();
  const [siteId, setSiteId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [runId, setRunId] = useState<string | null>(null);

  const { data: sites } = useQuery({ queryKey: ["sites"], queryFn: () => api.getSites() });
  const activeSiteId = siteId ?? sites?.[0]?.id ?? null;

  const { data: cameras } = useQuery({
    queryKey: ["cameras", activeSiteId],
    queryFn: () => api.getCameras({ site_id: activeSiteId as string }),
    enabled: !!activeSiteId,
  });

  const { data: run } = useQuery({
    queryKey: ["setup-run", runId],
    queryFn: () => api.getSetupRun(runId as string),
    enabled: !!runId,
    // Proposals arrive as each box finishes observing, over a few minutes.
    refetchInterval: (q) => ((q.state.data?.pending ?? 0) > 0 ? 10_000 : false),
  });

  const start = useMutation({
    mutationFn: () => api.startSetupRun(activeSiteId as string, [...selected]),
    onSuccess: (r) => { setRunId(r.id); setSelected(new Set()); },
  });

  const approveGroup = useMutation({
    mutationFn: (sceneType: string) => api.approveSetupGroup(runId as string, sceneType),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["setup-run", runId] }),
  });

  const approveOne = useMutation({
    mutationFn: (id: string) => api.approveSetupProposal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["setup-run", runId] }),
  });

  const cameraName = (id: string) =>
    (cameras ?? []).find((c) => c.id === id)?.name ?? "Unknown camera";

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < BATCH_CAP) next.add(id);
      return next;
    });
  }

  if (!sites?.length) {
    return <p className="text-sm text-[#A3A3A3]">No sites yet.</p>;
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#F5F5F5]">Camera setup</h1>
          <p className="mt-1 max-w-2xl text-sm text-[#A3A3A3]">
            Pick a batch of cameras. Each appliance watches its own cameras for
            a few minutes and proposes what they should detect. Nothing changes
            until you approve it.
          </p>
        </div>
        <select
          value={activeSiteId ?? ""}
          onChange={(e) => { setSiteId(e.target.value); setRunId(null); }}
          className="rounded-md border border-[#2A2A2A] bg-[#1F1F1F] px-3 py-2 text-sm text-[#F5F5F5] transition-colors focus:border-[#1E90FF] focus:outline-none"
        >
          {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </header>

      {!runId && (
        <section className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-[#A3A3A3]">
              {selected.size} of {BATCH_CAP} selected
            </span>
            <button
              disabled={selected.size === 0 || start.isPending}
              onClick={() => start.mutate()}
              className="rounded-md bg-[#1E90FF] px-3 py-2 text-sm text-white transition-colors hover:bg-[#3BA0FF] disabled:opacity-40"
            >
              {start.isPending ? "Starting…" : "Propose setup"}
            </button>
            {start.isError && (
              <span className="text-sm text-amber-400">
                {(start.error as Error).message}
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {(cameras ?? []).map((c) => (
              <button
                key={c.id}
                onClick={() => toggle(c.id)}
                className={`flex items-center gap-2 rounded-lg border p-3 text-left text-sm transition-colors ${
                  selected.has(c.id)
                    ? "border-[#1E90FF] bg-[#1E90FF]/10 text-[#F5F5F5]"
                    : "border-[#2A2A2A] bg-[#111111] text-[#A3A3A3] hover:bg-[#1A1A1A]"
                }`}
              >
                <StatusDot status={c.status} />
                <span className="truncate">{c.name}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {runId && !run && <Skeleton className="h-64 w-full" />}

      {run && (
        <section className="space-y-4">
          {run.pending > 0 && (
            <p className="rounded-md border border-[#2A2A2A] bg-[#111111] px-3 py-2 text-sm text-[#A3A3A3]">
              Watching {run.pending} of {run.camera_count} cameras… proposals
              appear as each appliance finishes.
            </p>
          )}

          {run.groups.map((g: SetupReviewGroup) => (
            <article key={g.scene_type} className="rounded-lg border border-[#2A2A2A] bg-[#111111] p-4">
              <header className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-heading text-lg font-semibold text-[#F5F5F5]">
                  {g.label}
                  <span className="ml-2 text-sm font-normal text-[#666666]">
                    {g.proposals.length} camera{g.proposals.length === 1 ? "" : "s"}
                  </span>
                </h2>
                {g.bulk_approvable && (
                  <button
                    onClick={() => approveGroup.mutate(g.scene_type)}
                    disabled={approveGroup.isPending}
                    className="rounded-md bg-[#1E90FF] px-3 py-1.5 text-sm text-white transition-colors hover:bg-[#3BA0FF] disabled:opacity-40"
                  >
                    Approve all {g.proposals.length}
                  </button>
                )}
              </header>

              {g.bulk_approvable && (
                <p className="mt-1 font-mono text-xs text-[#666666]">
                  {String((g.shared_config.enabled_events as string[])?.join(", ") ?? "")}
                  {" · "}
                  {String(g.shared_config.sensitivity ?? "")}
                </p>
              )}

              <ul className="mt-3 space-y-2">
                {[...g.proposals, ...g.differing].map((p: SetupProposal) => (
                  <li key={p.id} className="rounded-md border border-[#2A2A2A] bg-[#0D0D0D] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm text-[#F5F5F5]">{cameraName(p.camera_id)}</span>
                      {p.status === "proposed" ? (
                        <button
                          onClick={() => approveOne.mutate(p.id)}
                          className="rounded border border-[#1E90FF]/50 px-2 py-1 text-xs text-[#1E90FF] transition-colors hover:bg-[#1E90FF]/10"
                        >
                          Approve
                        </button>
                      ) : (
                        <span className="text-xs text-[#666666]">{p.status}</span>
                      )}
                    </div>
                    {p.scene_description && (
                      <p className="mt-1 text-xs text-[#A3A3A3]">{p.scene_description}</p>
                    )}
                    {p.rationale && (
                      <p className="mt-1 text-xs text-[#666666]">{p.rationale}</p>
                    )}
                    {p.error && <p className="mt-1 text-xs text-amber-400">{p.error}</p>}
                  </li>
                ))}
              </ul>
            </article>
          ))}

          {run.pending === 0 && (
            <p className="rounded-md border border-[#2A2A2A] bg-[#111111] px-3 py-3 text-sm text-[#A3A3A3]">
              Next: tell Nightwatch which of these cameras are physically
              connected, so it can follow activity between them.{" "}
              <Link href="/map" className="text-[#1E90FF] hover:underline">
                Open the camera map
              </Link>
            </p>
          )}
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Add the nav entry**

In `frontend/src/components/layout/sidebar.tsx`, add `Wand2` to the `lucide-react` import list and add this entry directly above the `/fleet` entry:

```tsx
  { href: "/setup", label: "Camera setup", icon: Wand2, tourId: "nav-setup" },
```

- [ ] **Step 5: Verify the build**

```bash
cd frontend && npm run build
```

Expected: `✓ Compiled successfully`, and `/setup` listed among the routes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/setup frontend/src/types/index.ts frontend/src/lib/api.ts frontend/src/components/layout/sidebar.tsx
git commit -m "Add camera setup review UI"
```

---

### Task 10: Documentation and cleanup

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code-facing.

- [ ] **Step 1: Document the feature**

Add to the "Current Project Status" section of both `CLAUDE.md` and `AGENTS.md` (they are mirrors — make the same edit in both):

```markdown
### Agentic Camera Setup (COMPLETE)
- Operator selects a batch of cameras (max 50); backend enqueues one setup job
  per camera onto that camera's own agent's Redis list
- The **Python pipeline** (not the Go agent) drains the jobs: samples 10 frames
  over 3 minutes, makes one structured Gemini Vision call, posts back a proposal
- Backend validates the proposal and clusters the batch by a closed `scene_type`
  enum; low-confidence, invalid, or `other` proposals go to "Needs your input"
  and can never be bulk-approved
- Approval is the ONLY path that writes camera config. Alert rules are confirmed
  per camera, never in bulk
- Camera adjacency is deliberately NOT proposed — it is not visible in frames.
  The flow prompts the operator to draw it on `/map` after a batch is approved
- Design: `docs/superpowers/specs/2026-08-18-agentic-camera-setup-design.md`
```

- [ ] **Step 2: Full verification sweep**

```bash
# backend
cd backend
export DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:55450/nw_main"
export TEST_DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:55450/nw_suite"
export PYTHONPATH=$PWD
uv run alembic upgrade head
uv run alembic heads            # exactly one head
uv run pytest tests/ -q         # 133 passed + 5 known pre-existing failures

# frontend
cd ../frontend && npm run build  # ✓ Compiled successfully

# agent
cd ../agent && go build ./...
cd pipeline && .venv/bin/python -c "import supervisor, scene_analyzer; print('pipeline OK')"

# tear down the throwaway database
docker rm -f nw-setup
```

- [ ] **Step 3: Confirm no temporary test files remain**

```bash
cd /Users/vaibhaw/Developer/vision && git status --short | grep -E "test_.*verify" && echo "REMOVE THESE" || echo "clean"
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md AGENTS.md
git commit -m "Document agentic camera setup"
```

---

## Self-Review Notes

**Spec coverage:** Batching (Task 6 + Task 9, cap enforced in Task 4). Grouping (Task 3). Proposal shape (Task 4 + Task 7's prompt). Validation (Task 2). Data model (Task 1). Error handling table (Task 5 result endpoint + Task 8's job runner + Task 7's error paths). Scale — per-agent dispatch (Task 6), concurrency cap (Task 8). Adjacency prompt after approval (Task 9). Non-goal "no auto-apply" is enforced structurally: `_apply` is only reachable from the two approve endpoints, and only for `status == "proposed"`.

**Not covered by any task, deliberately:** `suggested_alert` is stored in the proposal JSON and shown in the UI, but writing an alert rule on approval is **not** implemented. The spec requires alert rules be confirmed per item; building that confirm-and-write flow is a follow-up once the detection path is proven. Task 9's UI shows the suggestion without acting on it. Flagged here so it is a decision, not an omission.

**Known interface dependency:** Task 7 Step 2 adds `generate_text_with_images` to `GeminiClient` by mirroring `analyze_frame`'s SDK usage. The implementer must read that method first — the exact `contents` shape depends on which SDK path the client took (Vertex vs AI Studio), and this plan cannot pin it without that file open.
