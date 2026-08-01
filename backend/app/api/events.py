import asyncio
import base64
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.camera import Camera
from app.models.event import Event
from app.models.user import User
from app.schemas.event import (
    EventResponse,
    EventStatsCameraBreakdown,
    EventStatsResponse,
    EventStatsTimeBucket,
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
    return q


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
    elif org_id:
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
    if site_id:
        base = base.where(Event.site_id == site_id)

    result = await db.execute(base)
    events = result.scalars().all()

    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    reviewed = 0
    rejected = 0

    for e in events:
        by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
        by_severity[e.severity] = by_severity.get(e.severity, 0) + 1
        if e.feedback:
            reviewed += 1
            if e.feedback == "rejected":
                rejected += 1

    total = len(events)

    # Time-bucketed volume: hourly for the 24h view, daily otherwise — matches
    # the same period options the endpoint already accepts.
    bucket_by_day = period != "24h"
    buckets: dict[datetime, dict[str, int]] = {}
    for e in events:
        ts = e.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if bucket_by_day:
            key = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            key = ts.replace(minute=0, second=0, microsecond=0)
        bucket = buckets.setdefault(key, {})
        bucket[e.severity] = bucket.get(e.severity, 0) + 1
    time_series = [
        EventStatsTimeBucket(
            bucket=key,
            count=sum(sev_counts.values()),
            by_severity=sev_counts,
        )
        for key, sev_counts in sorted(buckets.items())
    ]

    # Per-camera breakdown, folding anything past the top N into "Other" —
    # never a generated per-camera hue/row past a bounded count.
    camera_counts: dict[uuid.UUID, int] = {}
    for e in events:
        camera_counts[e.camera_id] = camera_counts.get(e.camera_id, 0) + 1

    camera_names: dict[uuid.UUID, str] = {}
    if camera_counts:
        cam_result = await db.execute(
            select(Camera.id, Camera.name).where(Camera.id.in_(camera_counts.keys()))
        )
        camera_names = {row[0]: row[1] for row in cam_result.all()}

    ranked = sorted(camera_counts.items(), key=lambda kv: kv[1], reverse=True)
    by_camera = [
        EventStatsCameraBreakdown(
            camera_id=cam_id,
            camera_name=camera_names.get(cam_id, "Unknown camera"),
            count=count,
        )
        for cam_id, count in ranked[:MAX_CAMERA_BREAKDOWN_ROWS]
    ]
    if len(ranked) > MAX_CAMERA_BREAKDOWN_ROWS:
        other_count = sum(count for _, count in ranked[MAX_CAMERA_BREAKDOWN_ROWS:])
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
