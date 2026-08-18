import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.dependencies import scope_to_sites
from app.models.camera import Camera
from app.models.event import Event
from app.models.user import User
from app.schemas.event import (
    EventResponse,
    EventStatsCameraBreakdown,
    EventStatsResponse,
    EventStatsTimeBucket,
    EventStatusRequest,
    FeedbackRequest,
)
from app.services.gcs import fetch_gcs_object, sign_gcs_url

MAX_CAMERA_BREAKDOWN_ROWS = 10

router = APIRouter(prefix="/api/events", tags=["events"])


async def _signed_or_data_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    signed = sign_gcs_url(uri)
    if not signed.startswith("gs://"):
        return signed
    # Signing unavailable (local dev ADC) — download and inline as data URI.
    # Runs in a thread so it doesn't block the async event loop.
    obj = await asyncio.to_thread(fetch_gcs_object, uri)
    if obj is None:
        return None
    data, content_type = obj
    return f"data:{content_type};base64,{base64.b64encode(data).decode()}"


async def _to_response(event: Event) -> EventResponse:
    resp = EventResponse.model_validate(event)
    snapshot, clip = await asyncio.gather(
        _signed_or_data_uri(event.snapshot_url),
        _signed_or_data_uri(event.clip_url),
    )
    resp.snapshot_url = snapshot or ""
    resp.clip_url = clip
    return resp


def _event_query(user: User):
    q = select(Event)
    if user.role != "super_admin":
        q = q.where(Event.org_id == user.org_id)
    return scope_to_sites(q, Event.site_id, user)


@router.get("", response_model=dict)
async def list_events(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    camera_id: uuid.UUID | None = Query(None),
    site_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID | None = Query(None),
    event_type: str | None = Query(None),
    severity: str | None = Query(None),
    feedback: str | None = Query(None),
    status: str | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    q = _event_query(user)
    count_q = select(func.count()).select_from(Event)
    if user.role != "super_admin":
        count_q = count_q.where(Event.org_id == user.org_id)
    # The count is built separately from _event_query, so the site scope has
    # to be applied here too — filtering only the rows would hide the events
    # while the pagination total still reported how many exist out of scope.
    count_q = scope_to_sites(count_q, Event.site_id, user)
    if user.role == "super_admin" and org_id:
        q = q.where(Event.org_id == org_id)
        count_q = count_q.where(Event.org_id == org_id)

    if camera_id:
        q = q.where(Event.camera_id == camera_id)
        count_q = count_q.where(Event.camera_id == camera_id)
    if site_id:
        q = q.where(Event.site_id == site_id)
        count_q = count_q.where(Event.site_id == site_id)
    if event_type:
        q = q.where(Event.event_type == event_type)
        count_q = count_q.where(Event.event_type == event_type)
    if severity:
        severities = severity.split(",")
        q = q.where(Event.severity.in_(severities))
        count_q = count_q.where(Event.severity.in_(severities))
    if feedback:
        if feedback == "pending":
            q = q.where(Event.feedback.is_(None))
            count_q = count_q.where(Event.feedback.is_(None))
        else:
            q = q.where(Event.feedback == feedback)
            count_q = count_q.where(Event.feedback == feedback)
    if status:
        # "open" is the shift-handover filter: everything still needing
        # attention, whether or not anyone has picked it up yet.
        if status == "open":
            q = q.where(Event.status.notin_(("resolved", "dismissed")))
            count_q = count_q.where(Event.status.notin_(("resolved", "dismissed")))
        else:
            statuses = status.split(",")
            q = q.where(Event.status.in_(statuses))
            count_q = count_q.where(Event.status.in_(statuses))
    if start:
        q = q.where(Event.timestamp >= start)
        count_q = count_q.where(Event.timestamp >= start)
    if end:
        q = q.where(Event.timestamp <= end)
        count_q = count_q.where(Event.timestamp <= end)
    if search:
        q = q.where(Event.description.ilike(f"%{search}%"))
        count_q = count_q.where(Event.description.ilike(f"%{search}%"))

    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    q = q.order_by(Event.timestamp.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    events = await asyncio.gather(*[_to_response(e) for e in result.scalars().all()])

    return {"events": events, "total": total, "page": page, "pages": (total + per_page - 1) // per_page}


@router.get("/stats", response_model=EventStatsResponse)
async def event_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    period: str = Query("24h"),
    site_id: uuid.UUID | None = Query(None),
    org_id: uuid.UUID | None = Query(None),
):
    hours = {"24h": 24, "7d": 168, "30d": 720}.get(period, 24)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    base = select(Event).where(Event.timestamp >= since)
    if user.role != "super_admin":
        base = base.where(Event.org_id == user.org_id)
    elif org_id:
        base = base.where(Event.org_id == org_id)
    # Stats build their own base query rather than going through
    # _event_query, so scoping has to be repeated — an unscoped aggregate
    # leaks estate-wide activity even when every individual row is hidden.
    base = scope_to_sites(base, Event.site_id, user)
    if site_id:
        base = base.where(Event.site_id == site_id)

    # Aggregate in SQL, not in Python.
    #
    # This used to load every event in the window into ORM objects and count
    # them in a loop. At 400 cameras that is ~360k rows for period=30d, which
    # measured at 4+ seconds just to fetch — before any counting — and holds
    # all of it in memory at once. Every figure below is a GROUP BY, so the
    # database does the work and returns tens of rows instead of hundreds of
    # thousands.
    #
    # `base` carries the org/site scoping built above; every aggregate reuses
    # its WHERE clause verbatim so the scoping cannot drift between them.
    where = base.whereclause

    def agg(*columns):
        return select(*columns).select_from(Event).where(where)

    type_rows = (await db.execute(
        agg(Event.event_type, func.count()).group_by(Event.event_type)
    )).all()
    by_type = {r[0]: r[1] for r in type_rows}

    sev_rows = (await db.execute(
        agg(Event.severity, func.count()).group_by(Event.severity)
    )).all()
    by_severity = {r[0]: r[1] for r in sev_rows}

    total = sum(by_severity.values())

    feedback_rows = (await db.execute(
        agg(Event.feedback, func.count()).group_by(Event.feedback)
    )).all()
    reviewed = sum(c for f, c in feedback_rows if f is not None)
    rejected = sum(c for f, c in feedback_rows if f == "rejected")

    # Time-bucketed volume: hourly for the 24h view, daily otherwise.
    # date_trunc keeps bucketing in the database rather than materialising
    # every timestamp to bucket it in Python.
    grain = "hour" if period == "24h" else "day"
    bucket_col = func.date_trunc(grain, Event.timestamp).label("bucket")
    bucket_rows = (await db.execute(
        agg(bucket_col, Event.severity, func.count())
        .group_by("bucket", Event.severity)
        .order_by("bucket")
    )).all()
    buckets: dict[datetime, dict[str, int]] = {}
    for bucket, severity, count in bucket_rows:
        buckets.setdefault(bucket, {})[severity] = count
    time_series = [
        EventStatsTimeBucket(
            bucket=key,
            count=sum(sev_counts.values()),
            by_severity=sev_counts,
        )
        for key, sev_counts in sorted(buckets.items())
    ]

    # Per-camera breakdown, folding anything past the top N into "Other" so
    # the response stays bounded however many cameras a site has. The tail is
    # summed in SQL rather than by fetching every camera's row.
    camera_rows = (await db.execute(
        agg(Event.camera_id, func.count().label("n"))
        .group_by(Event.camera_id)
        .order_by(func.count().desc())
    )).all()

    top = camera_rows[:MAX_CAMERA_BREAKDOWN_ROWS]
    camera_names: dict[uuid.UUID, str] = {}
    if top:
        cam_result = await db.execute(
            select(Camera.id, Camera.name).where(Camera.id.in_([r[0] for r in top]))
        )
        camera_names = {row[0]: row[1] for row in cam_result.all()}

    by_camera = [
        EventStatsCameraBreakdown(
            camera_id=cam_id,
            camera_name=camera_names.get(cam_id, "Unknown camera"),
            count=count,
        )
        for cam_id, count in top
    ]
    if len(camera_rows) > MAX_CAMERA_BREAKDOWN_ROWS:
        other_count = sum(c for _, c in camera_rows[MAX_CAMERA_BREAKDOWN_ROWS:])
        by_camera.append(
            EventStatsCameraBreakdown(camera_id=None, camera_name="Other", count=other_count)
        )

    return EventStatsResponse(
        total_events=total,
        by_type=by_type,
        by_severity=by_severity,
        feedback_rate=reviewed / total if total else 0,
        false_positive_rate=rejected / reviewed if reviewed else 0,
        time_series=time_series,
        by_camera=by_camera,
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = _event_query(user).where(Event.id == event_id)
    result = await db.execute(q)
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return await _to_response(event)


@router.post("/{event_id}/feedback", status_code=200)
async def submit_feedback(
    event_id: uuid.UUID,
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "operator")

    q = _event_query(user).where(Event.id == event_id)
    result = await db.execute(q)
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event.feedback = body.feedback
    event.feedback_label = body.label
    event.feedback_by = user.id
    event.feedback_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "ok", "feedback": body.feedback}


# Operational states an event can be moved to. "new" is included so an event
# acknowledged by mistake can be handed back to the queue rather than being
# stuck owned by whoever mis-clicked.
EVENT_STATUSES = {"new", "acknowledged", "resolved", "dismissed"}
# States that mean "no longer needs attention" — the escalation sweep stops at
# these, and the handover view excludes them.
CLOSED_STATUSES = {"resolved", "dismissed"}


@router.patch("/{event_id}/status", response_model=EventResponse)
async def set_event_status(
    event_id: uuid.UUID,
    body: EventStatusRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Move an event through the control-room workflow.

    Independent of `/feedback`, which records whether the detection was
    correct. An operator acknowledges an event because they are dealing with
    it, not because they agree with the AI.

    Attribution is written onto the event row itself rather than into
    `audit_log` — that table is HTTP-request-shaped (method/path/status) and
    populated by middleware, whereas "who acknowledged this and when" is a
    domain fact the handover view has to query directly.
    """
    require_role(user, "operator")

    if body.status not in EVENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of: {', '.join(sorted(EVENT_STATUSES))}",
        )

    q = _event_query(user).where(Event.id == event_id)
    event = (await db.execute(q)).scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    now = datetime.now(timezone.utc)
    event.status = body.status

    if body.status == "acknowledged":
        # First acknowledgement wins: it records who actually picked it up.
        # Re-acknowledging (e.g. a second operator opening the same event)
        # must not rewrite that to the later person.
        if event.acknowledged_at is None:
            event.acknowledged_by = user.id
            event.acknowledged_at = now
        event.resolved_by = None
        event.resolved_at = None
    elif body.status in CLOSED_STATUSES:
        # Closing implies it was seen, so backfill acknowledgement rather than
        # leaving a resolved event that was somehow never acknowledged.
        if event.acknowledged_at is None:
            event.acknowledged_by = user.id
            event.acknowledged_at = now
        event.resolved_by = user.id
        event.resolved_at = now
    else:  # back to "new"
        event.acknowledged_by = None
        event.acknowledged_at = None
        event.resolved_by = None
        event.resolved_at = None

    if body.note is not None:
        event.resolution_note = body.note

    await db.flush()
    return await _to_response(event)
