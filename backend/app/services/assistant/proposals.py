"""Proposal service: the assistant's entire write path.

Nothing in this module writes to `alert_rules` or `camera_connections`. A
proposal is a row in `assistant_proposals` (Task 1) describing a change the
assistant wants to make; only a human applying it — via `apply_proposal`,
called from an authenticated API route, never from a tool — turns that into
a real row. See `backend/app/services/assistant/tools/propose.py` for the
tool-facing side of this, which only ever calls `create_proposal`.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.core.dependencies import require_role
from app.models.camera import Camera
from app.models.camera_connection import CameraConnection
from app.models.alert_rule import AlertRule
from app.models.proposal import Proposal
from app.models.site import Site
from app.schemas.alert import CreateAlertRuleRequest
from app.schemas.journey import CreateConnectionRequest
from app.services.assistant.registry import ToolContext
from app.services.journeys import normalise_pair

PROPOSAL_TTL = timedelta(hours=24)

_SCHEMAS = {
    "alert_rule": CreateAlertRuleRequest,
    "camera_connection": CreateConnectionRequest,
}


def render_summary(kind: str, payload: dict, names: dict[str, str]) -> str:
    """Build the confirm-card sentence from the payload.

    Never model-generated. If the model wrote this string, the sentence and
    the payload would be two independent artifacts that can disagree — the
    card could read "notify on critical events at the Back Door" while the
    payload writes a rule for a different camera. The user confirms the
    sentence; the system executes the payload. Templating from the payload
    makes that divergence structurally impossible.
    """
    if kind == "camera_connection":
        a = names.get(str(payload["camera_a_id"]), "a camera")
        b = names.get(str(payload["camera_b_id"]), "a camera")
        label = payload.get("label")
        via = f" via {label}" if label else ""
        return f"Connect {a} to {b} on the camera map{via}."

    if kind == "alert_rule":
        sev = payload.get("min_severity", "low")
        cams = payload.get("cameras") or []
        where = (
            ", ".join(names.get(str(c), "a camera") for c in cams)
            if cams
            else "all cameras"
        )
        channels = ", ".join(payload.get("notify_channels") or []) or "no channels"
        window = payload.get("time_window")
        when = f" between {window['start']} and {window['end']}" if window else ""
        return (
            f"Create alert rule \"{payload['name']}\": notify via {channels} "
            f"on {sev}-or-higher events at {where}{when}."
        )

    raise ValueError(f"no summary template for kind: {kind}")


async def _resolve_camera_names(ctx: ToolContext, camera_ids: set[uuid.UUID]) -> dict[str, str]:
    if not camera_ids:
        return {}
    rows = (
        await ctx.db.execute(select(Camera.id, Camera.name).where(Camera.id.in_(camera_ids)))
    ).all()
    return {str(row[0]): row[1] for row in rows}


async def create_proposal(
    ctx: ToolContext, kind: str, payload: dict, site_id: uuid.UUID | None
) -> Proposal:
    """Validate `payload`, template a summary, and persist a pending Proposal.

    This is the only thing a write-tool is allowed to do — it never touches
    `alert_rules` or `camera_connections`. Validation failure raises
    `ValueError` with the pydantic message; the tool wrapper turns that into
    an `{"error": ...}` dict the model can read and retry against.
    """
    schema_cls = _SCHEMAS.get(kind)
    if schema_cls is None:
        raise ValueError(f"no proposal schema for kind: {kind}")

    try:
        validated = schema_cls.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    # model_dump(mode="json") turns UUIDs into strings so the payload is
    # plain JSON before it goes into the JSONB column.
    clean_payload = validated.model_dump(mode="json")

    camera_ids: set[uuid.UUID] = set()
    if kind == "alert_rule":
        camera_ids.update(validated.cameras)
    else:  # camera_connection
        camera_ids.add(validated.camera_a_id)
        camera_ids.add(validated.camera_b_id)

    names = await _resolve_camera_names(ctx, camera_ids)
    summary = render_summary(kind, clean_payload, names)

    prop = Proposal(
        org_id=ctx.org_id,
        site_id=site_id,
        user_id=ctx.user.id,
        conversation_id=ctx.conversation_id,
        kind=kind,
        payload=clean_payload,
        summary=summary,
        status="pending",
        expires_at=datetime.now(timezone.utc) + PROPOSAL_TTL,
    )
    ctx.db.add(prop)
    await ctx.db.flush()
    return prop


async def _load_proposal_for_user(db, user, proposal_id: uuid.UUID) -> Proposal:
    prop = (
        await db.execute(select(Proposal).where(Proposal.id == proposal_id))
    ).scalar_one_or_none()
    if prop is None or prop.org_id != user.org_id:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return prop


async def _apply_alert_rule(db, user, prop: Proposal) -> uuid.UUID:
    body = CreateAlertRuleRequest.model_validate(prop.payload)
    # Mirrors backend/app/api/alerts.py:create_rule field-for-field.
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
    return rule.id


async def _apply_camera_connection(db, user, prop: Proposal) -> uuid.UUID:
    body = CreateConnectionRequest.model_validate(prop.payload)
    if prop.site_id is None:
        raise HTTPException(status_code=409, detail="Proposal is missing a site")

    # Mirrors backend/app/api/camera_connections.py:create_connection's
    # _load_site + the ownership/pair checks that follow it.
    site = (
        await db.execute(
            select(Site).where(
                Site.id == prop.site_id,
                Site.org_id == user.org_id,
                Site.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    if body.camera_a_id == body.camera_b_id:
        raise HTTPException(status_code=400, detail="A camera cannot connect to itself")

    cameras = (
        (
            await db.execute(
                select(Camera).where(
                    Camera.id.in_([body.camera_a_id, body.camera_b_id]),
                    Camera.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if len(cameras) != 2:
        raise HTTPException(status_code=404, detail="Camera not found")
    if any(c.site_id != site.id for c in cameras):
        raise HTTPException(status_code=400, detail="Both cameras must belong to this site")

    a_id, b_id = normalise_pair(body.camera_a_id, body.camera_b_id)
    existing = (
        await db.execute(
            select(CameraConnection).where(
                CameraConnection.camera_a_id == a_id,
                CameraConnection.camera_b_id == b_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Same idempotency as the route: drawing an edge that already exists
        # returns it rather than erroring.
        return existing.id

    conn = CameraConnection(
        org_id=site.org_id,
        site_id=site.id,
        camera_a_id=a_id,
        camera_b_id=b_id,
        label=body.label,
    )
    db.add(conn)
    await db.flush()
    return conn.id


_APPLIERS = {
    "alert_rule": _apply_alert_rule,
    "camera_connection": _apply_camera_connection,
}


async def apply_proposal(db, user, proposal_id: uuid.UUID) -> dict:
    """Execute a pending proposal.

    Scope is re-checked against the CURRENT session user, not against
    whoever created the proposal: a proposal is a request, not a capability,
    and permissions can change between proposing and applying.
    """
    prop = await _load_proposal_for_user(db, user, proposal_id)

    # Idempotent: a double-click must not create two alert rules.
    if prop.status == "applied":
        return {"status": "applied", "already": True}
    if prop.status in ("rejected", "expired"):
        raise HTTPException(status_code=409, detail=f"Proposal is {prop.status}")
    if prop.expires_at <= datetime.now(timezone.utc):
        prop.status = "expired"
        await db.flush()
        raise HTTPException(status_code=409, detail="Proposal has expired")

    # Both underlying create paths require admin; enforce it here rather than
    # letting the service call fail deeper with a confusing error.
    require_role(user, "admin")

    applier = _APPLIERS.get(prop.kind)
    if applier is None:
        raise HTTPException(status_code=500, detail=f"unknown proposal kind: {prop.kind}")

    created_id = await applier(db, user, prop)

    prop.status = "applied"
    prop.applied_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "applied", "id": str(created_id)}


async def reject_proposal(db, user, proposal_id: uuid.UUID) -> None:
    """Reject a pending proposal.

    Rejected and expired rows are retained: a declined suggestion is signal
    about where the assistant is wrong.
    """
    prop = await _load_proposal_for_user(db, user, proposal_id)
    if prop.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal is {prop.status}")
    prop.status = "rejected"
    await db.flush()
