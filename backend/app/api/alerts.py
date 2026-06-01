import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.alert_history import AlertHistory
from app.models.alert_rule import AlertRule
from app.models.user import User
from app.schemas.alert import (
    AlertHistoryResponse,
    AlertRuleResponse,
    CreateAlertRuleRequest,
    UpdateAlertRuleRequest,
)

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _rule_query(user: User):
    q = select(AlertRule)
    if user.role != "super_admin":
        q = q.where(AlertRule.org_id == user.org_id)
    return q


@router.get("/rules", response_model=list[AlertRuleResponse])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = Query(None),
):
    q = _rule_query(user)
    if user.role == "super_admin" and org_id:
        q = q.where(AlertRule.org_id == org_id)
    result = await db.execute(q.order_by(AlertRule.created_at.desc()))
    return [AlertRuleResponse.model_validate(r) for r in result.scalars().all()]


@router.post("/rules", response_model=AlertRuleResponse, status_code=201)
async def create_rule(
    body: CreateAlertRuleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    rule = AlertRule(
        org_id=user.org_id,
        name=body.name,
        cameras=body.cameras,
        event_types=body.event_types,
        min_severity=body.min_severity,
        time_window=body.time_window,
        zones=body.zones,
        notify_channels=body.notify_channels,
        notify_contacts=body.notify_contacts,
        webhook_url=body.webhook_url,
        cooldown_seconds=body.cooldown_seconds,
    )
    db.add(rule)
    await db.flush()
    return AlertRuleResponse.model_validate(rule)


@router.patch("/rules/{rule_id}", response_model=AlertRuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    body: UpdateAlertRuleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = _rule_query(user).where(AlertRule.id == rule_id)
    result = await db.execute(q)
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await db.flush()
    return AlertRuleResponse.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = _rule_query(user).where(AlertRule.id == rule_id)
    result = await db.execute(q)
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)


@router.get("/history", response_model=list[AlertHistoryResponse])
async def alert_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    rule_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
):
    q = select(AlertHistory)
    if user.role != "super_admin":
        q = q.where(AlertHistory.org_id == user.org_id)
    if rule_id:
        q = q.where(AlertHistory.rule_id == rule_id)

    q = q.order_by(AlertHistory.sent_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    return [AlertHistoryResponse.model_validate(h) for h in result.scalars().all()]
