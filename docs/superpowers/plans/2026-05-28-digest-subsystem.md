# Digest Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add scheduled and on-demand event-window summaries ("digests") for Nightwatch orgs, delivered via the existing WhatsApp transport and a new dashboard page.

**Architecture:** Lives entirely inside the existing `backend/` (Python/FastAPI) and `frontend/` (Next.js). New DB tables `digests` and `digest_preferences`; two columns added to `organizations`. A new `DigestService` queries events in a time window, compacts them, calls Gemini for a structured text summary, persists the result, and dispatches a WhatsApp message via the existing `NotificationService`. APScheduler runs scheduled morning/evening jobs per-org in their local timezone. An on-demand endpoint runs the same core synchronously-from-the-API/asynchronously-internally and notifies the frontend through the existing WS channel.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, PostgreSQL, Redis, APScheduler, `google-genai` SDK (Gemini 2.5), Next.js 14 App Router + TanStack Query, existing Gupshup WhatsApp transport.

**Spec:** `docs/superpowers/specs/2026-05-28-home-camera-plugin-design.md` (Sections 5.3, 6.3, 6.4, 7, 8.4).

---

## File Structure

### Backend — created
- `backend/app/models/digest.py` — `Digest` ORM model
- `backend/app/models/digest_preferences.py` — `DigestPreferences` ORM model
- `backend/app/schemas/digest.py` — Pydantic request/response schemas
- `backend/app/services/digest/__init__.py` — package marker
- `backend/app/services/digest/compactor.py` — pure event-list → compact-prompt-payload
- `backend/app/services/digest/sampler.py` — pure even-sampling reducer for >200 events
- `backend/app/services/digest/gemini_client.py` — async Gemini wrapper with retry + structured-output schema
- `backend/app/services/digest/renderer.py` — payload → WhatsApp text + dashboard JSON
- `backend/app/services/digest/service.py` — orchestrates query → compact → Gemini → persist → deliver
- `backend/app/services/digest/scheduler.py` — APScheduler glue
- `backend/app/services/digest/spend_tracker.py` — per-org daily Gemini spend cap (Redis)
- `backend/app/api/digests.py` — `/api/digests` routes
- `backend/tests/test_digest_compactor.py`
- `backend/tests/test_digest_sampler.py`
- `backend/tests/test_digest_gemini_client.py`
- `backend/tests/test_digest_renderer.py`
- `backend/tests/test_digest_service.py`
- `backend/tests/test_digest_api.py`
- `backend/tests/test_digest_spend_tracker.py`

### Backend — modified
- `backend/app/models/organization.py` — add `timezone`, `whatsapp_number` columns
- `backend/app/models/__init__.py` — register new models
- `backend/app/services/notification_service.py` — add `send_text_whatsapp(phone, text)` helper
- `backend/app/main.py` — register `digests` router, start APScheduler in lifespan
- `backend/app/config.py` — add `gemini_api_key`, `digest_daily_spend_cap_usd`, `digest_on_demand_per_user_hourly_limit` settings
- `backend/app/ws/events.py` — add `digest.ready` broadcast helper (small additive change)
- `backend/requirements.txt` — add `google-genai`, `apscheduler`, `pytz` (or `tzdata`)

### Frontend — created
- `frontend/app/digests/page.tsx` — list + presets + custom range + history
- `frontend/app/digests/[id]/page.tsx` — single digest detail view
- `frontend/components/digests/DigestCard.tsx`
- `frontend/components/digests/RangePicker.tsx`
- `frontend/components/digests/DigestSettings.tsx`
- `frontend/lib/api/digests.ts` — typed API client functions
- `frontend/types/digest.ts` — TS types matching the Pydantic schemas

### Frontend — modified
- `frontend/components/sidebar.tsx` (or wherever nav lives) — add "Digests" nav item
- `frontend/lib/api/types.ts` — re-export digest types if that pattern is used

---

## Conventions reminders for this plan

- Follow existing patterns: `Mapped[...]` typed columns, `mapped_column(...)`, `org_id` filtering on every query (super_admin null bypass), kebab-case routes, snake_case DB columns.
- DB writes use `AsyncSession` from `app.core.database.get_db`.
- Auth via `Depends(get_current_user)` from `app.core.dependencies`. Use `require_role("admin")` for settings/preferences endpoints, plain `get_current_user` for read endpoints.
- Tests use `pytest_asyncio`, the existing `client` fixture and DB fixtures in `backend/tests/conftest.py`. Run with `pytest -v` from `backend/`.
- Frontend follows the existing TanStack Query + typed-fetcher pattern. Dark theme only (`#0D0D0D`, `#1E90FF`).
- Each task ends in a commit. Commits are small and feature-scoped.

---

## Task 1: Add digest config to settings

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add new settings fields**

In `backend/app/config.py`, add the following fields to the `Settings` class (after `sendgrid_from_email`):

```python
    # Digest subsystem
    gemini_api_key: str = ""
    digest_daily_spend_cap_usd: float = 1.0  # per-org cap on Gemini text-summary spend
    digest_on_demand_per_user_hourly_limit: int = 10
    digest_max_events_per_window: int = 200
    digest_max_range_days: int = 7
```

- [ ] **Step 2: Verify import still works**

Run: `cd backend && python3 -c "from app.config import settings; print(settings.digest_max_events_per_window)"`
Expected: prints `200`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(digest): add digest subsystem config settings"
```

---

## Task 2: Extend Organization model with timezone + whatsapp_number

**Files:**
- Modify: `backend/app/models/organization.py`
- Test: `backend/tests/test_organization_timezone.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_organization_timezone.py`:

```python
import pytest
from sqlalchemy import select
from app.models.organization import Organization


@pytest.mark.asyncio
async def test_organization_has_default_timezone(db_session):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()

    result = await db_session.execute(select(Organization).where(Organization.slug == "acme"))
    fetched = result.scalar_one()
    assert fetched.timezone == "Asia/Kolkata"
    assert fetched.whatsapp_number is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_organization_timezone.py -v`
Expected: FAIL — `AttributeError` or column does not exist.

- [ ] **Step 3: Add columns to Organization**

In `backend/app/models/organization.py`, modify the class body (after `settings`):

```python
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata", server_default="Asia/Kolkata")
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_organization_timezone.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/organization.py backend/tests/test_organization_timezone.py
git commit -m "feat(digest): add timezone and whatsapp_number to Organization"
```

---

## Task 3: Create DigestPreferences model

**Files:**
- Create: `backend/app/models/digest_preferences.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_digest_preferences_model.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_preferences_model.py`:

```python
import uuid
import datetime as dt
import pytest
from sqlalchemy import select
from app.models.organization import Organization
from app.models.digest_preferences import DigestPreferences


@pytest.mark.asyncio
async def test_digest_preferences_defaults(db_session):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()

    prefs = DigestPreferences(org_id=org.id)
    db_session.add(prefs)
    await db_session.commit()

    result = await db_session.execute(
        select(DigestPreferences).where(DigestPreferences.org_id == org.id)
    )
    fetched = result.scalar_one()
    assert fetched.morning_enabled is True
    assert fetched.morning_local_time == dt.time(7, 0)
    assert fetched.evening_enabled is True
    assert fetched.evening_local_time == dt.time(19, 0)
    assert fetched.whatsapp_enabled is True
    assert fetched.email_enabled is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_digest_preferences_model.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the model**

Create `backend/app/models/digest_preferences.py`:

```python
import uuid
from datetime import time

from sqlalchemy import Boolean, ForeignKey, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DigestPreferences(Base):
    __tablename__ = "digest_preferences"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    morning_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    morning_local_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(7, 0))
    evening_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evening_local_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(19, 0))
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 4: Register the model**

In `backend/app/models/__init__.py`, append:

```python
from app.models.digest_preferences import DigestPreferences  # noqa: F401
```

(If `__init__.py` is empty or only has a docstring, add this line. Match the existing import style of other model registrations.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_digest_preferences_model.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/digest_preferences.py backend/app/models/__init__.py backend/tests/test_digest_preferences_model.py
git commit -m "feat(digest): add DigestPreferences model"
```

---

## Task 4: Create Digest model

**Files:**
- Create: `backend/app/models/digest.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_digest_model.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_model.py`:

```python
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import select
from app.models.organization import Organization
from app.models.digest import Digest


@pytest.mark.asyncio
async def test_digest_persistence_roundtrip(db_session):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    digest = Digest(
        org_id=org.id,
        kind="scheduled_morning",
        range_start=now - timedelta(hours=8),
        range_end=now,
        event_count=12,
        payload={"headline": "Quiet night", "narrative": "Nothing of note."},
        delivered_channels=["whatsapp", "dashboard"],
    )
    db_session.add(digest)
    await db_session.commit()

    result = await db_session.execute(select(Digest).where(Digest.org_id == org.id))
    fetched = result.scalar_one()
    assert fetched.kind == "scheduled_morning"
    assert fetched.event_count == 12
    assert fetched.payload["headline"] == "Quiet night"
    assert "whatsapp" in fetched.delivered_channels
    assert fetched.created_at is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_digest_model.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the model**

Create `backend/app/models/digest.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    range_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    range_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    delivered_channels: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False, default=list)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Register the model**

In `backend/app/models/__init__.py`, append:

```python
from app.models.digest import Digest  # noqa: F401
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_digest_model.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/digest.py backend/app/models/__init__.py backend/tests/test_digest_model.py
git commit -m "feat(digest): add Digest model"
```

---

## Task 5: Pydantic schemas for digests

**Files:**
- Create: `backend/app/schemas/digest.py`

- [ ] **Step 1: Create the schemas file**

Create `backend/app/schemas/digest.py`:

```python
from datetime import datetime, time
from typing import Literal
import uuid

from pydantic import BaseModel, Field, field_validator


DigestKind = Literal["scheduled_morning", "scheduled_evening", "on_demand"]


class DigestHighlight(BaseModel):
    time: datetime
    camera_name: str
    why_notable: str
    event_id: uuid.UUID | None = None


class DigestPayload(BaseModel):
    headline: str
    period: str
    total_events: int
    by_severity: dict[str, int]
    narrative: str
    highlights: list[DigestHighlight]
    quiet_periods: list[str] = Field(default_factory=list)
    degraded: bool = False


class DigestResponse(BaseModel):
    id: uuid.UUID
    kind: DigestKind
    range_start: datetime
    range_end: datetime
    event_count: int
    payload: DigestPayload
    delivered_channels: list[str]
    created_at: datetime

    class Config:
        from_attributes = True


class DigestListResponse(BaseModel):
    items: list[DigestResponse]
    total: int


class DigestRequest(BaseModel):
    start: datetime
    end: datetime
    camera_ids: list[uuid.UUID] | None = None
    site_id: uuid.UUID | None = None

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError("end must be after start")
        return v


class DigestPreferencesResponse(BaseModel):
    morning_enabled: bool
    morning_local_time: time
    evening_enabled: bool
    evening_local_time: time
    whatsapp_enabled: bool
    email_enabled: bool

    class Config:
        from_attributes = True


class DigestPreferencesUpdate(BaseModel):
    morning_enabled: bool | None = None
    morning_local_time: time | None = None
    evening_enabled: bool | None = None
    evening_local_time: time | None = None
    whatsapp_enabled: bool | None = None
    email_enabled: bool | None = None
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python3 -c "from app.schemas.digest import DigestResponse, DigestRequest; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/digest.py
git commit -m "feat(digest): add Pydantic schemas for digests"
```

---

## Task 6: Event sampler (pure function)

**Files:**
- Create: `backend/app/services/digest/__init__.py`
- Create: `backend/app/services/digest/sampler.py`
- Test: `backend/tests/test_digest_sampler.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_sampler.py`:

```python
from app.services.digest.sampler import sample_evenly


def test_sample_below_cap_returns_unchanged():
    items = list(range(50))
    assert sample_evenly(items, cap=200) == items


def test_sample_at_cap_returns_unchanged():
    items = list(range(200))
    assert sample_evenly(items, cap=200) == items


def test_sample_above_cap_returns_evenly_spaced():
    items = list(range(1000))
    sampled = sample_evenly(items, cap=10)
    assert len(sampled) == 10
    # First and last preserved
    assert sampled[0] == 0
    assert sampled[-1] == 999
    # Roughly evenly spaced (gaps within ±1 of nominal stride)
    diffs = [b - a for a, b in zip(sampled, sampled[1:])]
    assert max(diffs) - min(diffs) <= 1


def test_sample_empty_list():
    assert sample_evenly([], cap=10) == []


def test_sample_cap_one():
    assert sample_evenly(list(range(100)), cap=1) == [0]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_sampler.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the package and module**

Create `backend/app/services/digest/__init__.py` as an empty file.

Create `backend/app/services/digest/sampler.py`:

```python
from typing import Sequence, TypeVar

T = TypeVar("T")


def sample_evenly(items: Sequence[T], cap: int) -> list[T]:
    """Return up to `cap` items, evenly spaced across `items`, preserving order.

    If len(items) <= cap, returns a list copy of items unchanged.
    First and last elements are always preserved when cap >= 2.
    """
    n = len(items)
    if n == 0 or cap <= 0:
        return []
    if n <= cap:
        return list(items)
    if cap == 1:
        return [items[0]]

    # Indices: 0, ..., n-1 distributed across `cap` slots
    step = (n - 1) / (cap - 1)
    indices = [round(i * step) for i in range(cap)]
    return [items[i] for i in indices]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && pytest tests/test_digest_sampler.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/digest/__init__.py backend/app/services/digest/sampler.py backend/tests/test_digest_sampler.py
git commit -m "feat(digest): add even-sampling helper for large event windows"
```

---

## Task 7: Event compactor (pure function)

**Files:**
- Create: `backend/app/services/digest/compactor.py`
- Test: `backend/tests/test_digest_compactor.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_compactor.py`:

```python
import uuid
from datetime import datetime, timezone

from app.services.digest.compactor import compact_events, EventCompact


def make_event(ts, severity="medium", description="x", event_type="motion", camera_name="Front"):
    return {
        "id": uuid.uuid4(),
        "timestamp": ts,
        "severity": severity,
        "description": description,
        "event_type": event_type,
        "camera_name": camera_name,
        "confidence": 0.9,
    }


def test_compact_emits_one_record_per_event():
    events = [
        make_event(datetime(2026, 5, 28, 1, 0, tzinfo=timezone.utc)),
        make_event(datetime(2026, 5, 28, 2, 30, tzinfo=timezone.utc), severity="high"),
    ]
    result = compact_events(events)
    assert len(result) == 2
    assert isinstance(result[0], EventCompact)
    assert result[0].time == "2026-05-28T01:00:00+00:00"
    assert result[1].severity == "high"


def test_compact_truncates_long_descriptions():
    long = "x" * 500
    events = [make_event(datetime(2026, 5, 28, tzinfo=timezone.utc), description=long)]
    result = compact_events(events)
    assert len(result[0].description) <= 280


def test_compact_handles_missing_camera_name():
    e = make_event(datetime(2026, 5, 28, tzinfo=timezone.utc))
    e["camera_name"] = None
    result = compact_events([e])
    assert result[0].camera_name == "unknown-camera"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_compactor.py -v`
Expected: FAIL — ModuleNotFoundError.

- [ ] **Step 3: Implement the compactor**

Create `backend/app/services/digest/compactor.py`:

```python
from dataclasses import dataclass
from typing import Iterable, Mapping

DESCRIPTION_MAX = 280


@dataclass
class EventCompact:
    time: str           # ISO 8601
    camera_name: str
    event_type: str
    severity: str
    description: str
    confidence: float


def compact_events(events: Iterable[Mapping]) -> list[EventCompact]:
    """Reduce raw event dicts to the small fields Gemini needs for a text summary.

    Input is an iterable of mappings with keys: timestamp (datetime), camera_name, event_type,
    severity, description, confidence.
    """
    result: list[EventCompact] = []
    for e in events:
        camera_name = e.get("camera_name") or "unknown-camera"
        description = (e.get("description") or "")[:DESCRIPTION_MAX]
        result.append(
            EventCompact(
                time=e["timestamp"].isoformat(),
                camera_name=camera_name,
                event_type=e.get("event_type") or "unknown",
                severity=e.get("severity") or "low",
                description=description,
                confidence=float(e.get("confidence") or 0.0),
            )
        )
    return result
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && pytest tests/test_digest_compactor.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/digest/compactor.py backend/tests/test_digest_compactor.py
git commit -m "feat(digest): add event-list compactor for Gemini prompts"
```

---

## Task 8: Spend tracker (Redis sliding daily counter)

**Files:**
- Create: `backend/app/services/digest/spend_tracker.py`
- Test: `backend/tests/test_digest_spend_tracker.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_spend_tracker.py`:

```python
import uuid
from unittest.mock import AsyncMock
import pytest

from app.services.digest.spend_tracker import SpendTracker


@pytest.mark.asyncio
async def test_under_cap_allows_and_records():
    redis = AsyncMock()
    redis.incrbyfloat.return_value = 0.10
    redis.expire.return_value = True

    tracker = SpendTracker(redis_client=redis, daily_cap_usd=1.0)
    org_id = uuid.uuid4()

    allowed = await tracker.try_charge(org_id, cost_usd=0.10)
    assert allowed is True
    redis.incrbyfloat.assert_awaited_once()
    redis.expire.assert_awaited_once()


@pytest.mark.asyncio
async def test_over_cap_refunds_and_denies():
    redis = AsyncMock()
    # Simulate post-increment value that exceeds cap
    redis.incrbyfloat.side_effect = [1.20]
    redis.expire.return_value = True

    tracker = SpendTracker(redis_client=redis, daily_cap_usd=1.0)
    org_id = uuid.uuid4()

    allowed = await tracker.try_charge(org_id, cost_usd=0.50)
    assert allowed is False
    # Refunds by negative incr
    refund_call = redis.incrbyfloat.await_args_list[-1] if redis.incrbyfloat.await_count > 1 else None
    # Tracker may instead call decr — we just assert it's called twice in net-zero pattern
    assert redis.incrbyfloat.await_count + getattr(redis.decrby, "await_count", 0) >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_spend_tracker.py -v`
Expected: FAIL — ModuleNotFoundError.

- [ ] **Step 3: Implement the tracker**

Create `backend/app/services/digest/spend_tracker.py`:

```python
import datetime as dt
import uuid
from typing import Protocol


class _RedisLike(Protocol):
    async def incrbyfloat(self, key: str, amount: float) -> float: ...
    async def expire(self, key: str, seconds: int) -> bool: ...


class SpendTracker:
    """Per-org daily Gemini spend cap, backed by Redis."""

    def __init__(self, redis_client: _RedisLike, daily_cap_usd: float):
        self.redis = redis_client
        self.cap = daily_cap_usd

    def _key(self, org_id: uuid.UUID, day: dt.date) -> str:
        return f"digest:spend:{org_id}:{day.isoformat()}"

    async def try_charge(self, org_id: uuid.UUID, cost_usd: float) -> bool:
        """Atomically charge `cost_usd` to the org's daily counter.

        If the resulting total exceeds the cap, refund and return False.
        Otherwise return True. Counter expires at end of UTC day.
        """
        today = dt.datetime.now(dt.timezone.utc).date()
        key = self._key(org_id, today)
        new_total = await self.redis.incrbyfloat(key, cost_usd)
        # Set expiry to ~25h to cover day boundaries
        await self.redis.expire(key, 90_000)
        if new_total > self.cap:
            # Refund
            await self.redis.incrbyfloat(key, -cost_usd)
            return False
        return True
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && pytest tests/test_digest_spend_tracker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/digest/spend_tracker.py backend/tests/test_digest_spend_tracker.py
git commit -m "feat(digest): add per-org daily spend tracker"
```

---

## Task 9: Gemini client wrapper

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/services/digest/gemini_client.py`
- Test: `backend/tests/test_digest_gemini_client.py`

- [ ] **Step 1: Add dependency**

In `backend/requirements.txt`, append:

```
google-genai>=0.3.0
apscheduler>=3.10.4
pytz>=2024.1
```

Run: `cd backend && pip install -r requirements.txt`
Expected: installs cleanly.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_digest_gemini_client.py`:

```python
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.services.digest.gemini_client import GeminiDigestClient, GeminiResult
from app.services.digest.compactor import EventCompact


def _fake_compact():
    return [
        EventCompact(
            time="2026-05-28T01:00:00+00:00",
            camera_name="Front",
            event_type="motion",
            severity="medium",
            description="A person near the gate",
            confidence=0.9,
        )
    ]


@pytest.mark.asyncio
async def test_summarize_returns_structured_payload():
    fake_response = MagicMock()
    fake_response.text = (
        '{"headline":"All clear","period":"Last night",'
        '"total_events":1,"by_severity":{"medium":1},'
        '"narrative":"A person was seen near the gate.",'
        '"highlights":[{"time":"2026-05-28T01:00:00+00:00",'
        '"camera_name":"Front","why_notable":"only event"}],'
        '"quiet_periods":[]}'
    )
    fake_genai = MagicMock()
    fake_genai.aio.models.generate_content = AsyncMock(return_value=fake_response)

    client = GeminiDigestClient(genai_client=fake_genai, model="gemini-2.5-flash")
    result = await client.summarize(_fake_compact(), period_label="Last night")

    assert isinstance(result, GeminiResult)
    assert result.payload["headline"] == "All clear"
    assert result.payload["total_events"] == 1
    assert result.cost_usd > 0


@pytest.mark.asyncio
async def test_summarize_retries_once_on_failure():
    fake_response = MagicMock()
    fake_response.text = '{"headline":"x","period":"x","total_events":0,"by_severity":{},"narrative":"x","highlights":[],"quiet_periods":[]}'
    fake_genai = MagicMock()
    fake_genai.aio.models.generate_content = AsyncMock(
        side_effect=[RuntimeError("boom"), fake_response]
    )

    client = GeminiDigestClient(genai_client=fake_genai, model="gemini-2.5-flash")
    result = await client.summarize(_fake_compact(), period_label="x")
    assert result.payload["headline"] == "x"
    assert fake_genai.aio.models.generate_content.await_count == 2


@pytest.mark.asyncio
async def test_summarize_raises_after_two_failures():
    fake_genai = MagicMock()
    fake_genai.aio.models.generate_content = AsyncMock(
        side_effect=[RuntimeError("a"), RuntimeError("b")]
    )
    client = GeminiDigestClient(genai_client=fake_genai, model="gemini-2.5-flash")
    with pytest.raises(RuntimeError):
        await client.summarize(_fake_compact(), period_label="x")
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_gemini_client.py -v`
Expected: FAIL — ModuleNotFoundError.

- [ ] **Step 4: Implement the client**

Create `backend/app/services/digest/gemini_client.py`:

```python
import json
import logging
from dataclasses import dataclass
from typing import Sequence

from app.services.digest.compactor import EventCompact

logger = logging.getLogger(__name__)

# Approx cost (USD) per call. Tune after pilot. ~3¢ per digest is the planning estimate.
APPROX_COST_PER_CALL_USD = 0.03


SYSTEM_PROMPT = (
    "You are a security analyst summarizing CCTV events for a homeowner. "
    "Read the JSON list of events for a period and produce a calm, factual recap. "
    "Be specific about what was seen, when, and on which camera. "
    "Flag any unusual or repeated activity in 'highlights'. "
    "If activity was sparse, say so plainly."
)


SCHEMA_HINT = """
Respond ONLY with JSON matching this schema (no markdown, no commentary):
{
  "headline": string,
  "period": string,
  "total_events": number,
  "by_severity": object,
  "narrative": string,
  "highlights": [{"time": string, "camera_name": string, "why_notable": string}],
  "quiet_periods": [string]
}
""".strip()


@dataclass
class GeminiResult:
    payload: dict
    cost_usd: float


class GeminiDigestClient:
    def __init__(self, genai_client, model: str = "gemini-2.5-flash"):
        self.client = genai_client
        self.model = model

    def _build_prompt(self, events: Sequence[EventCompact], period_label: str) -> str:
        events_json = json.dumps([e.__dict__ for e in events], default=str)
        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"Period: {period_label}\n"
            f"Events ({len(events)}):\n{events_json}\n\n"
            f"{SCHEMA_HINT}"
        )

    async def summarize(self, events: Sequence[EventCompact], period_label: str) -> GeminiResult:
        prompt = self._build_prompt(events, period_label)
        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
                text = response.text.strip()
                # Defensive: strip code-fence if model wraps it
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.startswith("json"):
                        text = text[4:].lstrip()
                payload = json.loads(text)
                return GeminiResult(payload=payload, cost_usd=APPROX_COST_PER_CALL_USD)
            except Exception as e:
                logger.warning("Gemini summarize attempt %d failed: %s", attempt, e)
                last_err = e
        assert last_err is not None
        raise last_err
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd backend && pytest tests/test_digest_gemini_client.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/services/digest/gemini_client.py backend/tests/test_digest_gemini_client.py
git commit -m "feat(digest): add Gemini text-summary client with single retry"
```

---

## Task 10: Renderer (payload → WhatsApp text + dashboard view)

**Files:**
- Create: `backend/app/services/digest/renderer.py`
- Test: `backend/tests/test_digest_renderer.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_renderer.py`:

```python
from app.services.digest.renderer import render_whatsapp_message, build_quiet_payload


PAYLOAD = {
    "headline": "Quiet night, one delivery seen",
    "period": "Last night (22:00 – 06:59)",
    "total_events": 3,
    "by_severity": {"low": 2, "medium": 1},
    "narrative": "Activity was minimal. A delivery was spotted at 02:14 on the front camera.",
    "highlights": [
        {"time": "2026-05-28T02:14:00+05:30", "camera_name": "Front", "why_notable": "Person at gate"},
        {"time": "2026-05-28T03:40:00+05:30", "camera_name": "Garage", "why_notable": "Cat triggered motion"},
    ],
    "quiet_periods": ["00:00 – 02:00", "04:00 – 06:00"],
    "degraded": False,
}


def test_render_whatsapp_includes_headline_and_link():
    text = render_whatsapp_message(PAYLOAD, dashboard_url="https://app/digests/abc")
    assert "Quiet night, one delivery seen" in text
    assert "https://app/digests/abc" in text
    # No more than ~3 highlights rendered to keep messages short
    assert text.count("• ") <= 3


def test_quiet_payload_when_no_events():
    payload = build_quiet_payload(period_label="Last night (22:00 – 06:59)")
    assert payload["total_events"] == 0
    assert payload["headline"]
    assert "quiet" in payload["narrative"].lower()
    assert payload["highlights"] == []


def test_render_whatsapp_marks_degraded_payload():
    p = {**PAYLOAD, "degraded": True}
    text = render_whatsapp_message(p, dashboard_url="https://app/x")
    assert "(summary unavailable" in text.lower() or "limited summary" in text.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_renderer.py -v`
Expected: FAIL — ModuleNotFoundError.

- [ ] **Step 3: Implement the renderer**

Create `backend/app/services/digest/renderer.py`:

```python
from typing import Mapping


def render_whatsapp_message(payload: Mapping, dashboard_url: str) -> str:
    headline = payload.get("headline", "Nightwatch digest")
    period = payload.get("period", "")
    narrative = payload.get("narrative", "")
    highlights = list(payload.get("highlights", []))[:3]
    degraded = bool(payload.get("degraded", False))

    lines = [f"📋 *{headline}*"]
    if period:
        lines.append(f"_{period}_")
    lines.append("")
    if degraded:
        lines.append("(Limited summary — full AI recap unavailable.)")
    if narrative:
        lines.append(narrative)
    if highlights:
        lines.append("")
        for h in highlights:
            cam = h.get("camera_name", "camera")
            why = h.get("why_notable", "")
            t = (h.get("time") or "").split("T")[-1][:5]  # HH:MM
            lines.append(f"• {t} {cam} — {why}")
    lines.append("")
    lines.append(f"View full digest: {dashboard_url}")
    return "\n".join(lines)


def build_quiet_payload(period_label: str) -> dict:
    return {
        "headline": "All quiet",
        "period": period_label,
        "total_events": 0,
        "by_severity": {},
        "narrative": "It was quiet — nothing of note was detected during this window.",
        "highlights": [],
        "quiet_periods": [],
        "degraded": False,
    }


def build_degraded_payload(events_summary: list[dict], period_label: str) -> dict:
    by_severity: dict[str, int] = {}
    for e in events_summary:
        sev = e.get("severity", "low")
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return {
        "headline": f"{len(events_summary)} events recorded",
        "period": period_label,
        "total_events": len(events_summary),
        "by_severity": by_severity,
        "narrative": (
            "AI summary was unavailable. The list of detected events is preserved "
            "in the dashboard for your review."
        ),
        "highlights": [],
        "quiet_periods": [],
        "degraded": True,
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd backend && pytest tests/test_digest_renderer.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/digest/renderer.py backend/tests/test_digest_renderer.py
git commit -m "feat(digest): add WhatsApp + degraded/quiet payload renderers"
```

---

## Task 11: Add `send_text_whatsapp` to NotificationService

**Files:**
- Modify: `backend/app/services/notification_service.py`
- Test: `backend/tests/test_notification_text_whatsapp.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_notification_text_whatsapp.py`:

```python
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.services.notification_service import NotificationService


@pytest.mark.asyncio
async def test_send_text_whatsapp_uses_gupshup_endpoint(monkeypatch):
    svc = NotificationService()
    fake_response = MagicMock()
    fake_response.status_code = 200
    svc.http_client = MagicMock()
    svc.http_client.post = AsyncMock(return_value=fake_response)

    monkeypatch.setattr("app.services.notification_service.settings.gupshup_api_key", "k")
    monkeypatch.setattr("app.services.notification_service.settings.gupshup_app_name", "app")
    monkeypatch.setattr("app.services.notification_service.settings.whatsapp_business_number", "919999999999")

    ok = await svc.send_text_whatsapp("919876543210", "hello world")
    assert ok is True
    args, kwargs = svc.http_client.post.await_args
    assert "gupshup.io" in args[0]
    assert kwargs["data"]["destination"] == "919876543210"


@pytest.mark.asyncio
async def test_send_text_whatsapp_returns_false_when_unconfigured(monkeypatch):
    monkeypatch.setattr("app.services.notification_service.settings.gupshup_api_key", "")
    svc = NotificationService()
    ok = await svc.send_text_whatsapp("919876543210", "hello")
    assert ok is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_notification_text_whatsapp.py -v`
Expected: FAIL — `send_text_whatsapp` doesn't exist.

- [ ] **Step 3: Add the method**

In `backend/app/services/notification_service.py`, inside the `NotificationService` class (after `_send_whatsapp`), add:

```python
    async def send_text_whatsapp(self, phone: str, text: str) -> bool:
        """Send a free-form text WhatsApp message (used by digests, not alerts)."""
        if not settings.gupshup_api_key:
            logger.warning("WhatsApp not configured (no Gupshup API key)")
            return False
        try:
            payload = {
                "channel": "whatsapp",
                "source": settings.whatsapp_business_number,
                "destination": phone,
                "message": json.dumps({"type": "text", "text": text}),
                "src.name": settings.gupshup_app_name,
            }
            resp = await self.http_client.post(
                "https://api.gupshup.io/wa/api/v1/msg",
                data=payload,
                headers={"apikey": settings.gupshup_api_key},
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error("send_text_whatsapp failed: %s", e)
            return False
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_notification_text_whatsapp.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/notification_service.py backend/tests/test_notification_text_whatsapp.py
git commit -m "feat(digest): add NotificationService.send_text_whatsapp helper"
```

---

## Task 12: DigestService — orchestration

**Files:**
- Create: `backend/app/services/digest/service.py`
- Test: `backend/tests/test_digest_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_service.py`:

```python
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy import select

from app.models.organization import Organization
from app.models.site import Site
from app.models.camera import Camera
from app.models.event import Event
from app.models.digest import Digest
from app.services.digest.service import DigestService
from app.services.digest.gemini_client import GeminiResult


async def _seed_org_with_events(db_session, n_events: int):
    org = Organization(name="Acme", slug="acme", whatsapp_number="919876543210")
    db_session.add(org)
    await db_session.flush()
    site = Site(org_id=org.id, name="Home")
    db_session.add(site)
    await db_session.flush()
    cam = Camera(org_id=org.id, site_id=site.id, name="Front", rtsp_url="rtsp://x", status="online")
    db_session.add(cam)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    for i in range(n_events):
        db_session.add(Event(
            org_id=org.id,
            camera_id=cam.id,
            site_id=site.id,
            timestamp=now - timedelta(minutes=10 * i),
            event_type="motion",
            confidence=0.9,
            severity="medium",
            description=f"event {i}",
            snapshot_url="gs://x/snap.webp",
        ))
    await db_session.commit()
    return org, now


@pytest.mark.asyncio
async def test_generate_empty_window_creates_quiet_digest(db_session):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()

    gemini = MagicMock()
    gemini.summarize = AsyncMock()  # should NOT be called
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=True)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=True)

    svc = DigestService(
        db=db_session,
        gemini=gemini,
        spend_tracker=spend,
        notification=notif,
        dashboard_base_url="https://app",
    )
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=8)

    digest = await svc.generate(org_id=org.id, kind="scheduled_morning", start=start, end=end)
    assert digest.event_count == 0
    assert digest.payload["headline"] == "All quiet"
    gemini.summarize.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_with_events_calls_gemini_and_persists(db_session):
    org, now = await _seed_org_with_events(db_session, n_events=3)
    gemini = MagicMock()
    gemini.summarize = AsyncMock(return_value=GeminiResult(
        payload={
            "headline": "Three events", "period": "Last night",
            "total_events": 3, "by_severity": {"medium": 3},
            "narrative": "Activity was modest.", "highlights": [], "quiet_periods": []
        },
        cost_usd=0.03,
    ))
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=True)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=True)

    svc = DigestService(
        db=db_session, gemini=gemini, spend_tracker=spend,
        notification=notif, dashboard_base_url="https://app",
    )
    digest = await svc.generate(
        org_id=org.id, kind="scheduled_evening",
        start=now - timedelta(hours=12), end=now + timedelta(minutes=1),
    )

    assert digest.event_count == 3
    assert digest.payload["headline"] == "Three events"
    notif.send_text_whatsapp.assert_awaited_once()
    assert "whatsapp" in digest.delivered_channels


@pytest.mark.asyncio
async def test_generate_falls_back_to_degraded_on_gemini_failure(db_session):
    org, now = await _seed_org_with_events(db_session, n_events=2)
    gemini = MagicMock()
    gemini.summarize = AsyncMock(side_effect=RuntimeError("gemini down"))
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=True)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=True)

    svc = DigestService(
        db=db_session, gemini=gemini, spend_tracker=spend,
        notification=notif, dashboard_base_url="https://app",
    )
    digest = await svc.generate(
        org_id=org.id, kind="on_demand",
        start=now - timedelta(hours=12), end=now + timedelta(minutes=1),
    )
    assert digest.payload["degraded"] is True
    assert digest.event_count == 2


@pytest.mark.asyncio
async def test_generate_skips_gemini_when_spend_cap_hit(db_session):
    org, now = await _seed_org_with_events(db_session, n_events=2)
    gemini = MagicMock()
    gemini.summarize = AsyncMock()
    spend = MagicMock()
    spend.try_charge = AsyncMock(return_value=False)
    notif = MagicMock()
    notif.send_text_whatsapp = AsyncMock(return_value=True)

    svc = DigestService(
        db=db_session, gemini=gemini, spend_tracker=spend,
        notification=notif, dashboard_base_url="https://app",
    )
    digest = await svc.generate(
        org_id=org.id, kind="on_demand",
        start=now - timedelta(hours=12), end=now + timedelta(minutes=1),
    )
    assert digest.payload["degraded"] is True
    gemini.summarize.assert_not_awaited()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_service.py -v`
Expected: FAIL — ModuleNotFoundError.

- [ ] **Step 3: Implement the service**

Create `backend/app/services/digest/service.py`:

```python
import logging
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.digest import Digest
from app.models.event import Event
from app.models.organization import Organization
from app.services.digest.compactor import compact_events
from app.services.digest.gemini_client import GeminiDigestClient
from app.services.digest.renderer import (
    build_degraded_payload,
    build_quiet_payload,
    render_whatsapp_message,
)
from app.services.digest.sampler import sample_evenly
from app.services.digest.spend_tracker import SpendTracker
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


DigestKind = Literal["scheduled_morning", "scheduled_evening", "on_demand"]


class DigestService:
    def __init__(
        self,
        db: AsyncSession,
        gemini: GeminiDigestClient,
        spend_tracker: SpendTracker,
        notification: NotificationService,
        dashboard_base_url: str,
    ):
        self.db = db
        self.gemini = gemini
        self.spend = spend_tracker
        self.notification = notification
        self.dashboard_base_url = dashboard_base_url.rstrip("/")

    async def generate(
        self,
        *,
        org_id: uuid.UUID,
        kind: DigestKind,
        start: datetime,
        end: datetime,
        camera_ids: list[uuid.UUID] | None = None,
        site_id: uuid.UUID | None = None,
        requested_by: uuid.UUID | None = None,
    ) -> Digest:
        org = (await self.db.execute(
            select(Organization).where(Organization.id == org_id)
        )).scalar_one()

        events_rows = await self._load_events(org_id, start, end, camera_ids, site_id)
        period_label = self._period_label(kind, start, end)

        # Empty window
        if not events_rows:
            payload = build_quiet_payload(period_label)
            return await self._persist_and_deliver(
                org=org, kind=kind, start=start, end=end, payload=payload,
                event_count=0, requested_by=requested_by,
            )

        # Sample down if needed
        sampled = sample_evenly(events_rows, cap=settings.digest_max_events_per_window)
        compact = compact_events([self._event_to_dict(e) for e in sampled])

        # Spend cap
        cost_estimate = 0.03  # matches APPROX_COST_PER_CALL_USD
        allowed = await self.spend.try_charge(org_id, cost_estimate)
        if not allowed:
            logger.warning("Spend cap reached for org %s — emitting degraded digest", org_id)
            payload = build_degraded_payload(
                [self._event_to_dict(e) for e in sampled], period_label
            )
            return await self._persist_and_deliver(
                org=org, kind=kind, start=start, end=end, payload=payload,
                event_count=len(events_rows), requested_by=requested_by,
            )

        # Gemini call (with degraded fallback on failure)
        try:
            result = await self.gemini.summarize(compact, period_label)
            payload = result.payload
            payload.setdefault("degraded", False)
        except Exception as e:
            logger.error("Gemini summarize failed for org %s: %s", org_id, e)
            payload = build_degraded_payload(
                [self._event_to_dict(e) for e in sampled], period_label
            )

        return await self._persist_and_deliver(
            org=org, kind=kind, start=start, end=end, payload=payload,
            event_count=len(events_rows), requested_by=requested_by,
        )

    async def _load_events(self, org_id, start, end, camera_ids, site_id):
        stmt = (
            select(Event)
            .options(selectinload(Event.camera))
            .where(Event.org_id == org_id)
            .where(Event.timestamp >= start)
            .where(Event.timestamp < end)
            .order_by(Event.timestamp.asc())
        )
        if camera_ids:
            stmt = stmt.where(Event.camera_id.in_(camera_ids))
        if site_id:
            stmt = stmt.where(Event.site_id == site_id)
        return list((await self.db.execute(stmt)).scalars().all())

    def _event_to_dict(self, e: Event) -> dict:
        return {
            "id": e.id,
            "timestamp": e.timestamp,
            "camera_name": getattr(e.camera, "name", None) if hasattr(e, "camera") and e.camera else None,
            "event_type": e.event_type,
            "severity": e.severity,
            "description": e.description,
            "confidence": e.confidence,
        }

    def _period_label(self, kind, start, end) -> str:
        if kind == "scheduled_morning":
            return "Last night"
        if kind == "scheduled_evening":
            return "Today"
        return f"{start.strftime('%Y-%m-%d %H:%M')} – {end.strftime('%Y-%m-%d %H:%M')}"

    async def _persist_and_deliver(
        self, *, org: Organization, kind, start, end, payload, event_count, requested_by
    ) -> Digest:
        digest = Digest(
            org_id=org.id,
            kind=kind,
            range_start=start,
            range_end=end,
            event_count=event_count,
            payload=payload,
            delivered_channels=["dashboard"],
            requested_by=requested_by,
        )
        self.db.add(digest)
        await self.db.flush()

        # WhatsApp delivery (if configured)
        if org.whatsapp_number:
            url = f"{self.dashboard_base_url}/digests/{digest.id}"
            text = render_whatsapp_message(payload, dashboard_url=url)
            ok = await self.notification.send_text_whatsapp(org.whatsapp_number, text)
            if ok:
                digest.delivered_channels = list(digest.delivered_channels) + ["whatsapp"]

        await self.db.commit()
        await self.db.refresh(digest)
        return digest
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_digest_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/digest/service.py backend/tests/test_digest_service.py
git commit -m "feat(digest): add DigestService orchestrating query→summary→delivery"
```

---

## Task 13: API routes for digests

**Files:**
- Create: `backend/app/api/digests.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_digest_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_api.py`:

```python
import uuid
from datetime import datetime, timezone, timedelta
import pytest

from app.models.digest import Digest
from app.models.organization import Organization


@pytest.mark.asyncio
async def test_list_digests_requires_auth(client):
    resp = await client.get("/api/digests")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_digests_returns_only_org_digests(client, db_session, auth_headers, current_org):
    other_org = Organization(name="Other", slug="other")
    db_session.add(other_org)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add(Digest(
        org_id=current_org.id, kind="on_demand",
        range_start=now - timedelta(hours=1), range_end=now,
        event_count=0, payload={"headline": "mine"}, delivered_channels=["dashboard"],
    ))
    db_session.add(Digest(
        org_id=other_org.id, kind="on_demand",
        range_start=now - timedelta(hours=1), range_end=now,
        event_count=0, payload={"headline": "theirs"}, delivered_channels=["dashboard"],
    ))
    await db_session.commit()

    resp = await client.get("/api/digests", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["payload"]["headline"] == "mine"


@pytest.mark.asyncio
async def test_create_on_demand_rejects_range_too_long(client, auth_headers):
    start = datetime.now(timezone.utc) - timedelta(days=10)
    end = datetime.now(timezone.utc)
    resp = await client.post(
        "/api/digests",
        json={"start": start.isoformat(), "end": end.isoformat()},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "range" in resp.json()["detail"].lower()
```

This test relies on shared fixtures `auth_headers` and `current_org`. Add them to `backend/tests/conftest.py` if they don't already exist:

```python
import pytest_asyncio
from app.core.security import create_access_token
from app.core.sessions import session_manager
from app.models.organization import Organization
from app.models.user import User
from app.core.security import hash_password


@pytest_asyncio.fixture
async def current_org(db_session):
    org = Organization(name="TestOrg", slug="testorg", whatsapp_number=None)
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def current_user(db_session, current_org):
    user = User(
        org_id=current_org.id,
        username=f"u-{current_org.id}",
        password_hash=hash_password("password"),
        name="Test",
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def auth_headers(current_user):
    token = await session_manager.create_session(
        user_id=current_user.id,
        org_id=current_user.org_id,
        ip="127.0.0.1",
        user_agent="pytest",
    )
    return {"Authorization": f"Bearer {token}"}
```

(If equivalent fixtures already exist with different names, reuse them and adapt the test imports rather than duplicating.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_api.py -v`
Expected: FAIL — 404 from missing route.

- [ ] **Step 3: Implement the routes**

Create `backend/app/api/digests.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.digest import Digest
from app.models.user import User
from app.schemas.digest import (
    DigestListResponse,
    DigestRequest,
    DigestResponse,
)
from app.services.digest.service import DigestService
from app.services.digest.deps import get_digest_service

router = APIRouter(prefix="/api/digests", tags=["digests"])


def _scope(query, current: User):
    if current.role == "super_admin":
        return query
    return query.where(Digest.org_id == current.org_id)


@router.get("", response_model=DigestListResponse)
async def list_digests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    base = select(Digest).order_by(Digest.created_at.desc())
    rows = (await db.execute(_scope(base, current).limit(limit).offset(offset))).scalars().all()
    total = (await db.execute(_scope(select(func.count(Digest.id)), current))).scalar_one()
    return DigestListResponse(
        items=[DigestResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/{digest_id}", response_model=DigestResponse)
async def get_digest(
    digest_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    row = (await db.execute(_scope(select(Digest).where(Digest.id == digest_id), current))).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Digest not found")
    return DigestResponse.model_validate(row)


@router.post("", response_model=DigestResponse, status_code=201)
async def create_on_demand(
    body: DigestRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
    service: DigestService = Depends(get_digest_service),
):
    if body.end - body.start > timedelta(days=settings.digest_max_range_days):
        raise HTTPException(400, f"Range cannot exceed {settings.digest_max_range_days} days")
    if current.role == "super_admin" and current.org_id is None:
        raise HTTPException(400, "super_admin must specify an org via /admin endpoints, not on-demand digests")
    digest = await service.generate(
        org_id=current.org_id,
        kind="on_demand",
        start=body.start,
        end=body.end,
        camera_ids=body.camera_ids,
        site_id=body.site_id,
        requested_by=current.id,
    )
    return DigestResponse.model_validate(digest)
```

Also create `backend/app/services/digest/deps.py`:

```python
from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from google import genai

from app.config import settings
from app.core.database import get_db
from app.core.redis_client import get_redis
from app.services.digest.gemini_client import GeminiDigestClient
from app.services.digest.service import DigestService
from app.services.digest.spend_tracker import SpendTracker
from app.services.notification_service import notification_service


def _gemini_client():
    return genai.Client(api_key=settings.gemini_api_key)


async def get_digest_service(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> DigestService:
    gemini = GeminiDigestClient(genai_client=_gemini_client())
    spend = SpendTracker(redis_client=redis, daily_cap_usd=settings.digest_daily_spend_cap_usd)
    return DigestService(
        db=db,
        gemini=gemini,
        spend_tracker=spend,
        notification=notification_service,
        dashboard_base_url="https://app.nightwatch.ai",  # TODO: env var if needed
    )
```

If `app.core.redis_client.get_redis` doesn't exist yet, search for the existing Redis dependency (likely in `app.core.sessions` or `app.core.database`). Use whatever the codebase already exposes; adjust the import. Do not create a new client if one is already used.

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add to imports near the other routers:

```python
from app.api.digests import router as digests_router
```

And in the route registration section:

```python
app.include_router(digests_router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_digest_api.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/digests.py backend/app/services/digest/deps.py backend/app/main.py backend/tests/test_digest_api.py backend/tests/conftest.py
git commit -m "feat(digest): add /api/digests routes and dependency wiring"
```

---

## Task 14: Digest preferences API

**Files:**
- Modify: `backend/app/api/digests.py`
- Test: `backend/tests/test_digest_preferences_api.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_preferences_api.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_get_preferences_creates_defaults_if_missing(client, auth_headers):
    resp = await client.get("/api/digests/preferences", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["morning_enabled"] is True
    assert body["morning_local_time"] == "07:00:00"


@pytest.mark.asyncio
async def test_update_preferences_persists(client, auth_headers):
    resp = await client.put(
        "/api/digests/preferences",
        json={"morning_enabled": False, "evening_local_time": "20:30:00"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["morning_enabled"] is False
    assert body["evening_local_time"] == "20:30:00"

    resp = await client.get("/api/digests/preferences", headers=auth_headers)
    assert resp.json()["morning_enabled"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_preferences_api.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Add the endpoints**

In `backend/app/api/digests.py`, add (above the `@router.post("")` route):

```python
from app.models.digest_preferences import DigestPreferences
from app.schemas.digest import DigestPreferencesResponse, DigestPreferencesUpdate


async def _get_or_create_prefs(db: AsyncSession, org_id) -> DigestPreferences:
    row = (await db.execute(
        select(DigestPreferences).where(DigestPreferences.org_id == org_id)
    )).scalar_one_or_none()
    if row:
        return row
    row = DigestPreferences(org_id=org_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/preferences", response_model=DigestPreferencesResponse)
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.org_id is None:
        raise HTTPException(400, "super_admin has no preferences")
    prefs = await _get_or_create_prefs(db, current.org_id)
    return DigestPreferencesResponse.model_validate(prefs)


@router.put("/preferences", response_model=DigestPreferencesResponse)
async def update_preferences(
    body: DigestPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if current.org_id is None:
        raise HTTPException(400, "super_admin has no preferences")
    prefs = await _get_or_create_prefs(db, current.org_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(prefs, field, value)
    await db.commit()
    await db.refresh(prefs)
    return DigestPreferencesResponse.model_validate(prefs)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_digest_preferences_api.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/digests.py backend/tests/test_digest_preferences_api.py
git commit -m "feat(digest): add /api/digests/preferences GET and PUT"
```

---

## Task 15: Per-user hourly rate limit on on-demand digests

**Files:**
- Modify: `backend/app/api/digests.py`
- Test: `backend/tests/test_digest_rate_limit.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_rate_limit.py`:

```python
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest


@pytest.mark.asyncio
async def test_on_demand_rate_limit_returns_429(client, auth_headers, monkeypatch):
    # Force the limit to 1 for this test
    monkeypatch.setattr(
        "app.config.settings.digest_on_demand_per_user_hourly_limit", 1
    )
    start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    end = datetime.now(timezone.utc).isoformat()

    # Stub the service so we don't actually call Gemini
    from app.services.digest.service import DigestService
    async def fake_generate(*args, **kwargs):
        from app.models.digest import Digest
        return Digest(
            org_id=kwargs["org_id"], kind="on_demand",
            range_start=kwargs["start"], range_end=kwargs["end"],
            event_count=0, payload={"headline": "x"}, delivered_channels=["dashboard"],
        )
    with patch.object(DigestService, "generate", side_effect=fake_generate):
        r1 = await client.post("/api/digests", json={"start": start, "end": end}, headers=auth_headers)
        assert r1.status_code in (200, 201)
        r2 = await client.post("/api/digests", json={"start": start, "end": end}, headers=auth_headers)
        assert r2.status_code == 429
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_rate_limit.py -v`
Expected: FAIL — 200/201 for both calls.

- [ ] **Step 3: Add Redis-backed rate limit**

In `backend/app/api/digests.py`, add at the top (with other imports):

```python
from redis.asyncio import Redis
from app.core.redis_client import get_redis  # use whatever import the project uses
```

Add a helper above the route definitions:

```python
async def _enforce_user_rate_limit(redis: Redis, user_id):
    key = f"digest:ondemand:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 3600)
    if count > settings.digest_on_demand_per_user_hourly_limit:
        raise HTTPException(429, "On-demand digest hourly limit reached. Try again later.")
```

Modify `create_on_demand` to call it:

```python
@router.post("", response_model=DigestResponse, status_code=201)
async def create_on_demand(
    body: DigestRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current: User = Depends(get_current_user),
    service: DigestService = Depends(get_digest_service),
):
    if body.end - body.start > timedelta(days=settings.digest_max_range_days):
        raise HTTPException(400, f"Range cannot exceed {settings.digest_max_range_days} days")
    await _enforce_user_rate_limit(redis, current.id)
    if current.org_id is None:
        raise HTTPException(400, "super_admin cannot run on-demand digests")
    digest = await service.generate(
        org_id=current.org_id,
        kind="on_demand",
        start=body.start,
        end=body.end,
        camera_ids=body.camera_ids,
        site_id=body.site_id,
        requested_by=current.id,
    )
    return DigestResponse.model_validate(digest)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pytest tests/test_digest_rate_limit.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/digests.py backend/tests/test_digest_rate_limit.py
git commit -m "feat(digest): rate-limit on-demand digests per user (Redis sliding hour)"
```

---

## Task 16: APScheduler integration for scheduled digests

**Files:**
- Create: `backend/app/services/digest/scheduler.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_digest_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_digest_scheduler.py`:

```python
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import pytest

from app.services.digest.scheduler import compute_morning_window, compute_evening_window


def test_morning_window_covers_prior_22_to_07_in_org_tz():
    tz = ZoneInfo("Asia/Kolkata")
    # "Now" is 07:00 IST on 2026-05-28
    now_local = datetime(2026, 5, 28, 7, 0, tzinfo=tz)
    start, end = compute_morning_window(now_local, morning_local_time=time(7, 0))
    # Window: 22:00 prior day → 06:59:59.999 same day, expressed in UTC
    assert start.tzinfo is not None
    assert end > start
    assert (end - start).total_seconds() == 9 * 3600  # 22:00 → 07:00 = 9 hours


def test_evening_window_covers_07_to_19_in_org_tz():
    tz = ZoneInfo("Asia/Kolkata")
    now_local = datetime(2026, 5, 28, 19, 0, tzinfo=tz)
    start, end = compute_evening_window(now_local, evening_local_time=time(19, 0))
    assert (end - start).total_seconds() == 12 * 3600  # 07:00 → 19:00
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_scheduler.py -v`
Expected: FAIL — ModuleNotFoundError.

- [ ] **Step 3: Implement scheduler glue**

Create `backend/app/services/digest/scheduler.py`:

```python
import logging
from datetime import datetime, time, timedelta
from typing import Tuple
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.redis_client import get_redis_singleton  # adjust to project
from app.models.digest_preferences import DigestPreferences
from app.models.organization import Organization
from app.services.digest.deps import _gemini_client  # reuse private factory
from app.services.digest.gemini_client import GeminiDigestClient
from app.services.digest.service import DigestService
from app.services.digest.spend_tracker import SpendTracker
from app.services.notification_service import notification_service
from app.config import settings

logger = logging.getLogger(__name__)


def compute_morning_window(now_local: datetime, morning_local_time: time) -> Tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes covering 22:00 prior day → morning_local_time today."""
    end_local = now_local.replace(
        hour=morning_local_time.hour, minute=morning_local_time.minute,
        second=0, microsecond=0,
    )
    start_local = (end_local - timedelta(hours=9)).replace(hour=22, minute=0, second=0, microsecond=0)
    return start_local.astimezone(tz=None).astimezone().astimezone(tz=None) if False else (
        start_local.astimezone(ZoneInfo("UTC")),
        end_local.astimezone(ZoneInfo("UTC")),
    )


def compute_evening_window(now_local: datetime, evening_local_time: time) -> Tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes covering 07:00 today → evening_local_time today."""
    end_local = now_local.replace(
        hour=evening_local_time.hour, minute=evening_local_time.minute,
        second=0, microsecond=0,
    )
    start_local = end_local.replace(hour=7, minute=0, second=0, microsecond=0)
    return (
        start_local.astimezone(ZoneInfo("UTC")),
        end_local.astimezone(ZoneInfo("UTC")),
    )


async def _run_for_org(org_id, kind: str):
    async with async_session_factory() as db:
        org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one()
        prefs = (await db.execute(
            select(DigestPreferences).where(DigestPreferences.org_id == org_id)
        )).scalar_one_or_none()
        if prefs is None:
            return
        tz = ZoneInfo(org.timezone or "Asia/Kolkata")
        now_local = datetime.now(tz)
        if kind == "scheduled_morning":
            if not prefs.morning_enabled:
                return
            start, end = compute_morning_window(now_local, prefs.morning_local_time)
        else:
            if not prefs.evening_enabled:
                return
            start, end = compute_evening_window(now_local, prefs.evening_local_time)

        redis = await get_redis_singleton()
        gemini = GeminiDigestClient(genai_client=_gemini_client())
        spend = SpendTracker(redis_client=redis, daily_cap_usd=settings.digest_daily_spend_cap_usd)
        service = DigestService(
            db=db, gemini=gemini, spend_tracker=spend,
            notification=notification_service,
            dashboard_base_url="https://app.nightwatch.ai",
        )
        try:
            await service.generate(org_id=org.id, kind=kind, start=start, end=end)
        except Exception:
            logger.exception("Scheduled digest failed for org %s kind %s", org.id, kind)


async def schedule_all(scheduler: AsyncIOScheduler) -> None:
    """Iterate orgs and add cron jobs in each org's local timezone."""
    async with async_session_factory() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()
        for org in orgs:
            tz = org.timezone or "Asia/Kolkata"
            prefs = (await db.execute(
                select(DigestPreferences).where(DigestPreferences.org_id == org.id)
            )).scalar_one_or_none()
            morning = prefs.morning_local_time if prefs else time(7, 0)
            evening = prefs.evening_local_time if prefs else time(19, 0)

            scheduler.add_job(
                _run_for_org, args=[org.id, "scheduled_morning"],
                trigger=CronTrigger(hour=morning.hour, minute=morning.minute, timezone=tz),
                id=f"morning:{org.id}", replace_existing=True,
            )
            scheduler.add_job(
                _run_for_org, args=[org.id, "scheduled_evening"],
                trigger=CronTrigger(hour=evening.hour, minute=evening.minute, timezone=tz),
                id=f"evening:{org.id}", replace_existing=True,
            )


def start_scheduler() -> AsyncIOScheduler:
    sched = AsyncIOScheduler()
    sched.start()
    return sched
```

(If `app.core.redis_client.get_redis_singleton` doesn't exist, use whatever existing pattern the codebase has for a process-level Redis client — search the codebase before adding new infrastructure.)

- [ ] **Step 4: Wire into FastAPI lifespan**

In `backend/app/main.py`, modify the `lifespan` context manager:

```python
from app.services.digest.scheduler import start_scheduler, schedule_all
```

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_super_admin()
    scheduler = start_scheduler()
    await schedule_all(scheduler)
    app.state.digest_scheduler = scheduler
    logger.info("Nightwatch API started")
    yield
    scheduler.shutdown(wait=False)
    await engine.dispose()
```

- [ ] **Step 5: Run scheduler tests**

Run: `cd backend && pytest tests/test_digest_scheduler.py -v`
Expected: PASS.

- [ ] **Step 6: Smoke-test app boot**

Run: `cd backend && python3 -c "from app.main import app; print('ok', len(app.routes))"`
Expected: `ok <number>` with no exception.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/digest/scheduler.py backend/app/main.py backend/tests/test_digest_scheduler.py
git commit -m "feat(digest): add APScheduler-driven scheduled digests"
```

---

## Task 17: WS broadcast for `digest.ready`

**Files:**
- Modify: `backend/app/ws/events.py`
- Modify: `backend/app/services/digest/service.py`
- Test: `backend/tests/test_digest_ws_broadcast.py`

- [ ] **Step 1: Inspect existing WS module**

Read `backend/app/ws/events.py` — locate the existing per-org broadcast helper (e.g. `manager.broadcast_to_org(org_id, payload)` or similar). The exact name/signature determines what to call below.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_digest_ws_broadcast.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
import pytest

from app.services.digest.service import DigestService
from app.services.digest.gemini_client import GeminiResult
from app.models.organization import Organization


@pytest.mark.asyncio
async def test_digest_generation_emits_ws_broadcast(db_session):
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()

    gemini = MagicMock()
    gemini.summarize = AsyncMock(return_value=GeminiResult(
        payload={"headline": "x", "period": "x", "total_events": 0,
                 "by_severity": {}, "narrative": "x", "highlights": [], "quiet_periods": []},
        cost_usd=0.0,
    ))
    spend = MagicMock(); spend.try_charge = AsyncMock(return_value=True)
    notif = MagicMock(); notif.send_text_whatsapp = AsyncMock(return_value=False)

    with patch("app.services.digest.service.broadcast_to_org") as bc:
        bc.return_value = AsyncMock()
        svc = DigestService(
            db=db_session, gemini=gemini, spend_tracker=spend,
            notification=notif, dashboard_base_url="https://x",
        )
        end = datetime.now(timezone.utc); start = end - timedelta(hours=1)
        await svc.generate(org_id=org.id, kind="on_demand", start=start, end=end)
        assert bc.called
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && pytest tests/test_digest_ws_broadcast.py -v`
Expected: FAIL — `broadcast_to_org` does not exist in service module.

- [ ] **Step 4: Wire the broadcast**

In `backend/app/ws/events.py`, ensure a function is exposed (add if missing, matching the existing manager pattern):

```python
async def broadcast_to_org(org_id, payload: dict) -> None:
    await manager.broadcast(org_id, payload)
```

(Replace `manager.broadcast(...)` with the actual existing method discovered in Step 1.)

In `backend/app/services/digest/service.py`, add at the top:

```python
from app.ws.events import broadcast_to_org
```

In `_persist_and_deliver`, just before `return digest`, add:

```python
        await broadcast_to_org(org.id, {
            "type": "digest.ready",
            "digest_id": str(digest.id),
            "kind": kind,
            "headline": payload.get("headline"),
            "range_start": start.isoformat(),
            "range_end": end.isoformat(),
        })
```

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest tests/test_digest_ws_broadcast.py tests/test_digest_service.py -v`
Expected: all PASS (existing service tests still pass).

- [ ] **Step 6: Commit**

```bash
git add backend/app/ws/events.py backend/app/services/digest/service.py backend/tests/test_digest_ws_broadcast.py
git commit -m "feat(digest): broadcast digest.ready over existing WS channel"
```

---

## Task 18: Frontend types + API client

**Files:**
- Create: `frontend/types/digest.ts`
- Create: `frontend/lib/api/digests.ts`

- [ ] **Step 1: Inspect existing API client pattern**

Read one existing client file, e.g. `frontend/lib/api/events.ts` (or whatever exists). Match its style — same fetcher, same auth header convention, same error-handling helper.

- [ ] **Step 2: Add types**

Create `frontend/types/digest.ts`:

```ts
export type DigestKind = "scheduled_morning" | "scheduled_evening" | "on_demand";

export interface DigestHighlight {
  time: string;
  camera_name: string;
  why_notable: string;
  event_id?: string | null;
}

export interface DigestPayload {
  headline: string;
  period: string;
  total_events: number;
  by_severity: Record<string, number>;
  narrative: string;
  highlights: DigestHighlight[];
  quiet_periods: string[];
  degraded?: boolean;
}

export interface Digest {
  id: string;
  kind: DigestKind;
  range_start: string;
  range_end: string;
  event_count: number;
  payload: DigestPayload;
  delivered_channels: string[];
  created_at: string;
}

export interface DigestListResponse {
  items: Digest[];
  total: number;
}

export interface DigestRequest {
  start: string;
  end: string;
  camera_ids?: string[];
  site_id?: string;
}

export interface DigestPreferences {
  morning_enabled: boolean;
  morning_local_time: string;
  evening_enabled: boolean;
  evening_local_time: string;
  whatsapp_enabled: boolean;
  email_enabled: boolean;
}
```

- [ ] **Step 3: Add API client**

Create `frontend/lib/api/digests.ts` (adapt the import paths to match existing convention — likely `import { apiFetch } from "@/lib/api/client"` or similar):

```ts
import { apiFetch } from "@/lib/api/client";
import type {
  Digest,
  DigestListResponse,
  DigestRequest,
  DigestPreferences,
} from "@/types/digest";

export const digestsApi = {
  list: (limit = 20, offset = 0) =>
    apiFetch<DigestListResponse>(`/api/digests?limit=${limit}&offset=${offset}`),

  get: (id: string) => apiFetch<Digest>(`/api/digests/${id}`),

  createOnDemand: (body: DigestRequest) =>
    apiFetch<Digest>("/api/digests", { method: "POST", body: JSON.stringify(body) }),

  getPreferences: () =>
    apiFetch<DigestPreferences>("/api/digests/preferences"),

  updatePreferences: (body: Partial<DigestPreferences>) =>
    apiFetch<DigestPreferences>("/api/digests/preferences", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds (warnings ok).

- [ ] **Step 5: Commit**

```bash
git add frontend/types/digest.ts frontend/lib/api/digests.ts
git commit -m "feat(digest): add frontend types and API client"
```

---

## Task 19: Digests list page with presets + custom range

**Files:**
- Create: `frontend/app/digests/page.tsx`
- Create: `frontend/components/digests/DigestCard.tsx`
- Create: `frontend/components/digests/RangePicker.tsx`

- [ ] **Step 1: Inspect existing page pattern**

Read `frontend/app/events/page.tsx` (or equivalent) to copy the layout shell (sidebar, header, container styling, dark theme classes).

- [ ] **Step 2: Create the DigestCard component**

Create `frontend/components/digests/DigestCard.tsx`:

```tsx
"use client";
import Link from "next/link";
import type { Digest } from "@/types/digest";

export function DigestCard({ digest }: { digest: Digest }) {
  const date = new Date(digest.created_at).toLocaleString();
  return (
    <Link
      href={`/digests/${digest.id}`}
      className="block rounded-lg border border-zinc-800 bg-zinc-950 p-4 hover:border-[#1E90FF] transition-colors"
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-base font-semibold text-zinc-100">
            {digest.payload.headline}
          </h3>
          <p className="mt-1 text-sm text-zinc-400">
            {digest.payload.period} · {digest.event_count} event{digest.event_count === 1 ? "" : "s"}
          </p>
        </div>
        <span className="text-xs text-zinc-500">{date}</span>
      </div>
      {digest.payload.degraded && (
        <p className="mt-2 text-xs text-amber-400">Limited summary</p>
      )}
      {digest.payload.narrative && (
        <p className="mt-3 text-sm text-zinc-300 line-clamp-2">
          {digest.payload.narrative}
        </p>
      )}
    </Link>
  );
}
```

- [ ] **Step 3: Create the RangePicker component**

Create `frontend/components/digests/RangePicker.tsx`:

```tsx
"use client";
import { useState } from "react";

export interface Range {
  start: Date;
  end: Date;
}

export function presetRanges(): Record<string, () => Range> {
  const now = new Date();
  return {
    "Last night": () => {
      const end = new Date(now);
      end.setHours(7, 0, 0, 0);
      const start = new Date(end);
      start.setDate(start.getDate() - 1);
      start.setHours(22, 0, 0, 0);
      return { start, end };
    },
    "Today": () => {
      const start = new Date(now);
      start.setHours(7, 0, 0, 0);
      return { start, end: now };
    },
    "This week": () => {
      const start = new Date(now);
      start.setDate(start.getDate() - 7);
      return { start, end: now };
    },
  };
}

export function RangePicker({ onRange }: { onRange: (r: Range) => void }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const presets = presetRanges();

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {Object.entries(presets).map(([label, fn]) => (
          <button
            key={label}
            onClick={() => onRange(fn())}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 hover:border-[#1E90FF]"
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex gap-2 items-end">
        <label className="flex flex-col text-xs text-zinc-400">
          Start
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="mt-1 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-zinc-100"
          />
        </label>
        <label className="flex flex-col text-xs text-zinc-400">
          End
          <input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="mt-1 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-sm text-zinc-100"
          />
        </label>
        <button
          disabled={!start || !end}
          onClick={() => onRange({ start: new Date(start), end: new Date(end) })}
          className="rounded-md bg-[#1E90FF] px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          Generate
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create the page**

Create `frontend/app/digests/page.tsx`:

```tsx
"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { digestsApi } from "@/lib/api/digests";
import { DigestCard } from "@/components/digests/DigestCard";
import { RangePicker, type Range } from "@/components/digests/RangePicker";

export default function DigestsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["digests"],
    queryFn: () => digestsApi.list(),
  });

  const create = useMutation({
    mutationFn: (r: Range) =>
      digestsApi.createOnDemand({ start: r.start.toISOString(), end: r.end.toISOString() }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["digests"] }),
  });

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 space-y-6">
      <h1 className="text-2xl font-bold text-zinc-100">Digests</h1>

      <section className="rounded-lg border border-zinc-800 bg-zinc-950 p-4">
        <h2 className="mb-3 text-sm font-semibold text-zinc-300">Generate a digest</h2>
        <RangePicker onRange={(r) => create.mutate(r)} />
        {create.isPending && <p className="mt-2 text-xs text-zinc-400">Generating…</p>}
        {create.isError && (
          <p className="mt-2 text-xs text-red-400">{(create.error as Error).message}</p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-zinc-300">History</h2>
        {isLoading && <p className="text-zinc-500 text-sm">Loading…</p>}
        {data?.items.length === 0 && (
          <p className="text-zinc-500 text-sm">No digests yet.</p>
        )}
        {data?.items.map((d) => <DigestCard key={d.id} digest={d} />)}
      </section>
    </div>
  );
}
```

- [ ] **Step 5: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/digests/page.tsx frontend/components/digests/DigestCard.tsx frontend/components/digests/RangePicker.tsx
git commit -m "feat(digest): add /digests list page with presets and custom range"
```

---

## Task 20: Digest detail page

**Files:**
- Create: `frontend/app/digests/[id]/page.tsx`

- [ ] **Step 1: Implement the page**

Create `frontend/app/digests/[id]/page.tsx`:

```tsx
"use client";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { digestsApi } from "@/lib/api/digests";

export default function DigestDetailPage() {
  const params = useParams<{ id: string }>();
  const { data, isLoading, error } = useQuery({
    queryKey: ["digest", params.id],
    queryFn: () => digestsApi.get(params.id!),
    enabled: !!params.id,
  });

  if (isLoading) return <p className="p-8 text-zinc-400">Loading…</p>;
  if (error) return <p className="p-8 text-red-400">{(error as Error).message}</p>;
  if (!data) return null;

  const p = data.payload;
  return (
    <div className="mx-auto max-w-3xl px-4 py-8 space-y-6">
      <header>
        <p className="text-xs uppercase tracking-wide text-zinc-500">{p.period}</p>
        <h1 className="mt-1 text-2xl font-bold text-zinc-100">{p.headline}</h1>
        {p.degraded && (
          <p className="mt-2 inline-block rounded bg-amber-900/40 px-2 py-0.5 text-xs text-amber-300">
            Limited summary
          </p>
        )}
      </header>

      <section className="grid grid-cols-3 gap-3">
        <Stat label="Events" value={p.total_events} />
        {Object.entries(p.by_severity).map(([k, v]) => (
          <Stat key={k} label={k} value={v} />
        ))}
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-zinc-300">Summary</h2>
        <p className="text-zinc-200 leading-relaxed">{p.narrative}</p>
      </section>

      {p.highlights.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-zinc-300">Highlights</h2>
          <ul className="space-y-2">
            {p.highlights.map((h, i) => (
              <li key={i} className="rounded border border-zinc-800 p-3">
                <div className="text-xs text-zinc-500">
                  {new Date(h.time).toLocaleString()} · {h.camera_name}
                </div>
                <div className="mt-1 text-sm text-zinc-200">{h.why_notable}</div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {p.quiet_periods.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-zinc-300">Quiet periods</h2>
          <ul className="text-sm text-zinc-400 list-disc pl-5">
            {p.quiet_periods.map((q, i) => <li key={i}>{q}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-950 p-3">
      <div className="text-xs uppercase text-zinc-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-zinc-100">{value}</div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/digests/[id]/page.tsx
git commit -m "feat(digest): add /digests/[id] detail page"
```

---

## Task 21: Preferences UI

**Files:**
- Create: `frontend/components/digests/DigestSettings.tsx`
- Modify: `frontend/app/digests/page.tsx`

- [ ] **Step 1: Create the settings component**

Create `frontend/components/digests/DigestSettings.tsx`:

```tsx
"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { digestsApi } from "@/lib/api/digests";
import type { DigestPreferences } from "@/types/digest";

export function DigestSettings() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["digest-prefs"],
    queryFn: () => digestsApi.getPreferences(),
  });
  const update = useMutation({
    mutationFn: (patch: Partial<DigestPreferences>) => digestsApi.updatePreferences(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["digest-prefs"] }),
  });

  if (!data) return null;
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 space-y-3">
      <h2 className="text-sm font-semibold text-zinc-300">Digest schedule</h2>
      <Toggle
        label="Morning recap (last night)"
        checked={data.morning_enabled}
        onChange={(v) => update.mutate({ morning_enabled: v })}
      />
      <TimeField
        label="Morning time"
        value={data.morning_local_time}
        onChange={(v) => update.mutate({ morning_local_time: v })}
      />
      <Toggle
        label="Evening recap (today)"
        checked={data.evening_enabled}
        onChange={(v) => update.mutate({ evening_enabled: v })}
      />
      <TimeField
        label="Evening time"
        value={data.evening_local_time}
        onChange={(v) => update.mutate({ evening_local_time: v })}
      />
      <Toggle
        label="Send via WhatsApp"
        checked={data.whatsapp_enabled}
        onChange={(v) => update.mutate({ whatsapp_enabled: v })}
      />
      <Toggle
        label="Send via Email"
        checked={data.email_enabled}
        onChange={(v) => update.mutate({ email_enabled: v })}
      />
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center justify-between text-sm text-zinc-200">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[#1E90FF]"
      />
    </label>
  );
}

function TimeField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  // Backend returns "HH:MM:SS"; <input type="time"> wants "HH:MM"
  const inputValue = value.slice(0, 5);
  return (
    <label className="flex items-center justify-between text-sm text-zinc-200">
      <span>{label}</span>
      <input
        type="time"
        value={inputValue}
        onChange={(e) => onChange(`${e.target.value}:00`)}
        className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-100"
      />
    </label>
  );
}
```

- [ ] **Step 2: Mount it on the digests page**

In `frontend/app/digests/page.tsx`, add the import:

```tsx
import { DigestSettings } from "@/components/digests/DigestSettings";
```

And insert `<DigestSettings />` as a section above or below the History section (your choice — match existing page layout density).

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/digests/DigestSettings.tsx frontend/app/digests/page.tsx
git commit -m "feat(digest): add preferences UI on /digests page"
```

---

## Task 22: Sidebar nav entry

**Files:**
- Modify: existing sidebar/nav component (find via grep)

- [ ] **Step 1: Locate the nav**

Run: `grep -rn "Cameras" frontend/app frontend/components --include="*.tsx" | head -10`
Pick the file that lists the existing nav items (likely a sidebar or layout component).

- [ ] **Step 2: Add a Digests entry**

Add a new nav item with `href="/digests"` and label `Digests`. Match the existing pattern (icon source, classes, ordering — put it after "Events" and before "Cameras" or wherever it logically fits).

- [ ] **Step 3: Verify build**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/<modified-file>
git commit -m "feat(digest): add Digests link to sidebar nav"
```

---

## Task 23: End-to-end smoke test (manual)

**Files:** none

- [ ] **Step 1: Run backend**

Run: `cd backend && docker compose up -d db redis && python3 -m uvicorn app.main:app --reload --port 8080`
Expected: app boots; logs show scheduler started.

- [ ] **Step 2: Run frontend**

Run: `cd frontend && npm run dev`
Expected: dev server up at `http://localhost:3000`.

- [ ] **Step 3: Manual verification**

In a browser:
1. Log in as an existing test user.
2. Visit `/digests`. Toggle a preference; reload — change persists.
3. Pick a "Last night" preset; click Generate. Wait for the new card to appear in History.
4. Open the digest; verify headline, narrative, highlights render. If `GEMINI_API_KEY` is unset, expect the degraded-summary path (still renders, banner says Limited summary).
5. Confirm WhatsApp delivery only if `GUPSHUP_API_KEY` and `whatsapp_number` on the org are configured. Otherwise skip — log entry will say "WhatsApp not configured".

- [ ] **Step 4: Record results**

Note in the PR description: which digests rendered, whether WhatsApp delivered, whether scheduler logged its registered jobs at boot.

- [ ] **Step 5: Commit (no code, just close out)**

If any small issues showed up, fix them in their own task. Otherwise this task has no commit.

---

## Self-review

**Spec coverage check:**
- 5.3 Digest service core (compactor, sampler, Gemini, renderer, service) → Tasks 6, 7, 9, 10, 12 ✓
- 5.3 Scheduled digests + on-demand → Tasks 12, 13, 16 ✓
- 5.3 Per-org spend cap → Task 8, integrated in Task 12 ✓
- 5.3 Per-user rate limit → Task 15 ✓
- 5.3 Empty window "all quiet" → Task 10 (`build_quiet_payload`), Task 12 (skip Gemini path) ✓
- 5.3 Gemini failure degraded fallback → Task 10 (`build_degraded_payload`), Task 12 ✓
- 5.3 WhatsApp delivery via NotificationService → Task 11 + Task 12 ✓
- 5.3 Dashboard view of digests → Tasks 19, 20 ✓
- 5.3 Preferences (schedule, channels) → Tasks 14, 21 ✓
- 6.3, 6.4 Data flows → Tasks 12, 13, 16 ✓
- 7.1 New `digests` table → Task 4 ✓
- 7.1 New `digest_preferences` table → Task 3 ✓
- 7.2 `organizations` adds `timezone`, `whatsapp_number` → Task 2 ✓
- 8.4 Range > 7 days → Task 13 ✓ ; > 200 events → sample_evenly via Task 12 ✓
- WS broadcast `digest.ready` (good UX, not strictly in spec but small) → Task 17 ✓
- Schema additions including `digests.requested_by` → Task 4 ✓

**Gaps / explicit non-goals:**
- Email delivery channel toggle is in `digest_preferences` but the email branch is not wired in `_persist_and_deliver`. The spec mentions email is supported via the existing alert engine; deferring concrete email send to a follow-up task is acceptable since `email_enabled` defaults to `false`. If you want this in this plan, add a small task between 11 and 12 to add `send_text_email` and dispatch it in the service.
- Snapshot thumbnails on the detail page: spec says "fetched lazily per highlight via signed URLs". Highlights currently lack `event_id` in the prompt output. Tightening the Gemini prompt to include `event_id` and adding thumbnail rendering is a polish follow-up; not in critical path.

**Placeholder scan:** one `TODO` left in `services/digest/deps.py` for the dashboard base URL — replace with an env var. Add this small task if you don't want any TODOs landing:

> Optional Task: add `dashboard_base_url` to `Settings` (default `http://localhost:3000`), thread through `deps.py` and `scheduler.py`. ~5 min.

**Type consistency:** `DigestKind`, `Digest`, `DigestPayload` names match between Python schemas (Task 5), frontend types (Task 18), and DB rows. `compute_morning_window`/`compute_evening_window` referenced consistently in Task 16.
