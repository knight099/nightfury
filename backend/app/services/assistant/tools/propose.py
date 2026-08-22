"""Write-shaped tools the assistant model can call.

Both tools here ONLY create a pending `Proposal` row via `create_proposal` —
neither writes to `alert_rules` or `camera_connections`. The model can
describe a change; only a human applying the resulting proposal (via the
API route that calls `apply_proposal`, never from a tool) makes it real.
That split is the entire point of this module: see
`backend/app/services/assistant/proposals.py` for why.
"""

import uuid

from app.services.assistant.proposals import create_proposal
from app.services.assistant.registry import ToolContext, register

PROPOSE_ALERT_RULE_DECL = {
    "name": "propose_alert_rule",
    "description": (
        "Prepare a new alert rule for the user to confirm. This does NOT "
        "create the rule — it produces a proposal the user must approve. "
        "Say so when you report back."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short human name for the rule."},
            "site_id": {"type": "string"},
            "cameras": {"type": "array", "items": {"type": "string"}, "description": "Camera UUIDs. Empty means all cameras."},
            "event_types": {"type": "array", "items": {"type": "string"}},
            "min_severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "time_window": {"type": "object", "description": "{start:'22:00', end:'06:00'} 24h local time."},
            "notify_channels": {"type": "array", "items": {"type": "string", "enum": ["whatsapp", "email", "webhook"]}},
            "notify_contacts": {"type": "array", "items": {"type": "object"}, "description": "[{type, value}]"},
            "cooldown_seconds": {"type": "integer"},
        },
        "required": ["name", "notify_channels", "notify_contacts"],
    },
}


@register(PROPOSE_ALERT_RULE_DECL)
async def propose_alert_rule(
    ctx: ToolContext,
    name: str,
    notify_channels: list[str],
    notify_contacts: list[dict],
    site_id: str | None = None,
    cameras: list[str] | None = None,
    event_types: list[str] | None = None,
    min_severity: str | None = None,
    time_window: dict | None = None,
    cooldown_seconds: int | None = None,
) -> dict:
    payload = {
        "name": name,
        "site_id": site_id,
        "cameras": cameras or [],
        "event_types": event_types or [],
        "min_severity": min_severity or "low",
        "time_window": time_window,
        "notify_channels": notify_channels,
        "notify_contacts": notify_contacts,
    }
    if cooldown_seconds is not None:
        payload["cooldown_seconds"] = cooldown_seconds

    try:
        prop = await create_proposal(
            ctx,
            kind="alert_rule",
            payload=payload,
            site_id=uuid.UUID(site_id) if site_id else None,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    return {
        "proposal_id": str(prop.id),
        "summary": prop.summary,
        "status": "pending_user_confirmation",
        "note": "Nothing has been changed yet. The user must confirm this.",
    }


PROPOSE_CAMERA_CONNECTION_DECL = {
    "name": "propose_camera_connection",
    "description": (
        "Prepare a new camera adjacency link (the Map) for the user to "
        "confirm. This does NOT create the connection — it produces a "
        "proposal the user must approve. Say so when you report back."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string"},
            "camera_a_id": {"type": "string"},
            "camera_b_id": {"type": "string"},
            "label": {"type": "string", "description": "Optional label for the link, e.g. 'Back hallway'."},
        },
        "required": ["site_id", "camera_a_id", "camera_b_id"],
    },
}


@register(PROPOSE_CAMERA_CONNECTION_DECL)
async def propose_camera_connection(
    ctx: ToolContext,
    site_id: str,
    camera_a_id: str,
    camera_b_id: str,
    label: str | None = None,
) -> dict:
    payload = {
        "camera_a_id": camera_a_id,
        "camera_b_id": camera_b_id,
        "label": label,
    }

    try:
        prop = await create_proposal(
            ctx,
            kind="camera_connection",
            payload=payload,
            site_id=uuid.UUID(site_id),
        )
    except ValueError as exc:
        return {"error": str(exc)}

    return {
        "proposal_id": str(prop.id),
        "summary": prop.summary,
        "status": "pending_user_confirmation",
        "note": "Nothing has been changed yet. The user must confirm this.",
    }
