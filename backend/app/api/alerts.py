import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.redis import get_redis
from app.models.alert_history import AlertHistory
from app.models.alert_rule import AlertRule
from app.models.user import User
from app.schemas.alert import (
    AlertHistoryResponse,
    AlertRuleResponse,
    CreateAlertRuleRequest,
    TestNotificationResponse,
    UpdateAlertRuleRequest,
)
from app.services.notification_service import notification_service
from app.services.soft_delete_service import soft_delete_service

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

TEST_NOTIFICATION_LIMIT = 5
TEST_NOTIFICATION_WINDOW_SECONDS = 3600


def _rule_query(user: User, include_deleted: bool = False):
    q = select(AlertRule)
    if not include_deleted:
        q = q.where(AlertRule.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(AlertRule.org_id == user.org_id)
    return q


@router.get("/rules", response_model=list[AlertRuleResponse])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    org_id: uuid.UUID | None = Query(None),
    include_deleted: bool = Query(False),
):
    q = _rule_query(user, include_deleted=include_deleted)
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
        site_id=body.site_id,
        cameras=body.cameras,
        event_types=body.event_types,
        min_severity=body.min_severity,
        time_window=body.time_window,
        zones=body.zones,
        notify_channels=body.notify_channels,
        notify_contacts=body.notify_contacts,
        webhook_url=body.webhook_url,
        cooldown_seconds=body.cooldown_seconds,
        escalation=body.escalation,
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
    await soft_delete_service.delete_alert_rule(rule, db)


@router.post("/rules/{rule_id}/restore", response_model=AlertRuleResponse)
async def restore_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")

    q = select(AlertRule).where(AlertRule.id == rule_id)
    if user.role != "super_admin":
        q = q.where(AlertRule.org_id == user.org_id)
    result = await db.execute(q)
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.deleted_at is None:
        raise HTTPException(status_code=400, detail="Rule is not deleted")
    await soft_delete_service.restore_alert_rule(rule, db)
    return AlertRuleResponse.model_validate(rule)


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


@router.post("/test", response_model=TestNotificationResponse)
async def send_test_notification(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TestNotificationResponse:
    """Prove the delivery channel works, without touching Gemini or an Event row.

    Onboarding's final step needs a real signal that WhatsApp/email actually
    reaches the customer before asking them to trust a walk-test. Sends
    through the same contacts an alert rule would notify, but the message is
    explicitly labelled as a test so it can never be mistaken for a real
    detection.
    """
    redis = await get_redis()
    rl_key = f"onboarding:test_notify:{user.org_id}"
    count = await redis.incr(rl_key)
    if count == 1:
        await redis.expire(rl_key, TEST_NOTIFICATION_WINDOW_SECONDS)
    if count > TEST_NOTIFICATION_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Too many test notifications sent. Try again in a bit.",
        )

    rows = await db.execute(
        select(AlertRule).where(
            AlertRule.org_id == user.org_id,
            AlertRule.deleted_at.is_(None),
            AlertRule.enabled.is_(True),
        )
    )
    contacts: list[dict] = []
    for rule in rows.scalars().all():
        for contact in rule.notify_contacts or []:
            if contact not in contacts:
                contacts.append(contact)

    if not contacts:
        return TestNotificationResponse(
            delivered=False,
            detail="No alert contacts configured yet. Add one under Alerts before testing.",
        )

    message = (
        "This is a test message from Nightwatch confirming your alerts "
        "reach you. No action needed."
    )
    delivered_any = False
    for contact in contacts:
        ctype = contact.get("type")
        value = contact.get("value")
        if not value:
            continue
        if ctype == "whatsapp":
            ok = await notification_service.send_text_whatsapp(value, message)
        elif ctype == "email":
            ok = await notification_service.send_text_email(
                value, "Nightwatch test notification", message
            )
        else:
            continue
        delivered_any = delivered_any or ok

    return TestNotificationResponse(
        delivered=delivered_any,
        detail=(
            "Test notification sent."
            if delivered_any
            else "Could not deliver to any configured contact. Check WhatsApp/email settings."
        ),
    )
