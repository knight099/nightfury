"""Journeys: correlate events across physically adjacent cameras.

Given a seed event on camera A, walk the operator-drawn adjacency graph and
collect events on connected cameras that happened shortly afterwards. The
result reads like a path through the building.

**What this is not.** It is not person re-identification. There are no
appearance embeddings, no biometrics, no visual matching of any kind — only
"these two cameras are joined by a hallway, and something happened on one and
then the other within a few minutes". That is a *probabilistic correlation*,
never an identity claim, and every string this module produces is written to
say so. A separate design (`2026-08-01-remind-reid-integration-design.md`)
scoped true re-identification as a harder, GPU-dependent, more
privacy-sensitive problem and deliberately left it undone.

Computed on demand — no background job, no materialised table. Revisit only
if this becomes a measured performance problem, not a suspected one.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.camera import Camera
from app.models.camera_connection import CameraConnection
from app.models.event import Event

# How long after an event on camera A we still consider an event on an
# adjacent camera B to plausibly be the same visitor. Roughly the time to walk
# across a building. A starting guess, not a validated constant — worth tuning
# against real pilot data.
DEFAULT_WINDOW = timedelta(minutes=10)

# Bounds the traversal so one seed cannot walk an entire mall.
MAX_CHAIN = 5


@dataclass
class JourneyStep:
    camera_id: uuid.UUID
    camera_name: str
    event_id: uuid.UUID
    timestamp: datetime
    event_type: str
    severity: str
    # The operator's label for the connection walked to reach this step
    # ("Back hallway"), when they gave it one.
    via: str | None = None


@dataclass
class Journey:
    seed_event_id: uuid.UUID
    steps: list[JourneyStep] = field(default_factory=list)
    summary: str = ""

    @property
    def has_journey(self) -> bool:
        # One step is just the seed event — not a journey. Most events will
        # correlate with nothing, and that is a normal outcome, not an error.
        return len(self.steps) > 1


async def _adjacency(db: AsyncSession, site_id: uuid.UUID) -> dict[uuid.UUID, list[tuple[uuid.UUID, str | None]]]:
    """Undirected adjacency map for one site: camera -> [(neighbour, label)]."""
    rows = (
        (
            await db.execute(
                select(CameraConnection).where(CameraConnection.site_id == site_id)
            )
        )
        .scalars()
        .all()
    )
    graph: dict[uuid.UUID, list[tuple[uuid.UUID, str | None]]] = {}
    for conn in rows:
        graph.setdefault(conn.camera_a_id, []).append((conn.camera_b_id, conn.label))
        graph.setdefault(conn.camera_b_id, []).append((conn.camera_a_id, conn.label))
    return graph


def _summarise(steps: list[JourneyStep]) -> str:
    """A templated sentence — deliberately not LLM-generated.

    The wording carries the epistemic status of the whole feature, so it is
    fixed text rather than something a model could restate as a certainty.
    """
    if len(steps) < 2:
        return ""
    first, last = steps[0], steps[-1]
    minutes = max(0, int((last.timestamp - first.timestamp).total_seconds() // 60))
    names = " → ".join(s.camera_name for s in steps)
    return (
        f"Activity on {len(steps)} connected cameras over {minutes} min: {names}. "
        "These events are linked by camera adjacency and timing — this may or "
        "may not be the same person."
    )


async def build_journey(
    db: AsyncSession,
    seed: Event,
    window: timedelta = DEFAULT_WINDOW,
    max_chain: int = MAX_CHAIN,
) -> Journey:
    """Walk forward from ``seed`` across adjacent cameras."""
    graph = await _adjacency(db, seed.site_id)

    names = dict(
        (
            await db.execute(
                select(Camera.id, Camera.name).where(Camera.site_id == seed.site_id)
            )
        ).all()
    )

    journey = Journey(seed_event_id=seed.id)
    journey.steps.append(
        JourneyStep(
            camera_id=seed.camera_id,
            camera_name=names.get(seed.camera_id, "Unknown camera"),
            event_id=seed.id,
            timestamp=seed.timestamp,
            event_type=seed.event_type,
            severity=seed.severity,
        )
    )
    if not graph:
        return journey

    current_camera = seed.camera_id
    current_time = seed.timestamp
    # A camera is only visited once per journey: without this, two adjacent
    # cameras with steady traffic would bounce the walk back and forth and
    # manufacture a long "path" out of one person standing still.
    visited: set[uuid.UUID] = {seed.camera_id}
    seen_events: set[uuid.UUID] = {seed.id}

    for _ in range(max_chain - 1):
        neighbours = [
            (cam_id, label)
            for cam_id, label in graph.get(current_camera, [])
            if cam_id not in visited
        ]
        if not neighbours:
            break

        by_id = {cam_id: label for cam_id, label in neighbours}
        candidate = (
            await db.execute(
                select(Event)
                .where(
                    Event.camera_id.in_(list(by_id)),
                    Event.id.notin_(seen_events),
                    Event.timestamp > current_time,
                    Event.timestamp <= current_time + window,
                )
                .order_by(Event.timestamp)
                .limit(1)
            )
        ).scalar_one_or_none()
        if candidate is None:
            break

        journey.steps.append(
            JourneyStep(
                camera_id=candidate.camera_id,
                camera_name=names.get(candidate.camera_id, "Unknown camera"),
                event_id=candidate.id,
                timestamp=candidate.timestamp,
                event_type=candidate.event_type,
                severity=candidate.severity,
                via=by_id.get(candidate.camera_id),
            )
        )
        visited.add(candidate.camera_id)
        seen_events.add(candidate.id)
        current_camera = candidate.camera_id
        # Chain from the step just found, so the window measures gap between
        # consecutive sightings rather than total elapsed time from the seed.
        current_time = candidate.timestamp

    journey.summary = _summarise(journey.steps)
    return journey


def normalise_pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Order a camera pair so (A,B) and (B,A) store as the same row."""
    return (a, b) if str(a) < str(b) else (b, a)


async def connections_for_site(db: AsyncSession, site_id: uuid.UUID) -> list[CameraConnection]:
    return list(
        (
            await db.execute(
                select(CameraConnection)
                .where(CameraConnection.site_id == site_id)
                .order_by(CameraConnection.created_at)
            )
        )
        .scalars()
        .all()
    )
