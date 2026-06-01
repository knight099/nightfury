import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.event import Event
from app.models.user import User
from app.schemas.event import EventResponse, EventStatsResponse, FeedbackRequest
from app.services.gcs import sign_gcs_url

router = APIRouter(prefix="/api/events", tags=["events"])


def _to_response(event: Event) -> EventResponse:
    resp = EventResponse.model_validate(event)
    resp.snapshot_url = sign_gcs_url(event.snapshot_url)
    if event.clip_url:
        resp.clip_url = sign_gcs_url(event.clip_url)
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
    events = [_to_response(e) for e in result.scalars().all()]

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
    return EventStatsResponse(
        total_events=total,
        by_type=by_type,
        by_severity=by_severity,
        feedback_rate=reviewed / total if total else 0,
        false_positive_rate=rejected / reviewed if reviewed else 0,
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
    return _to_response(event)


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
