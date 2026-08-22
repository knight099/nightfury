"""Read-only tools the assistant model can call.

Every tool here mirrors the query construction of the API route named in its
docstring: same filter columns, same `scope_to_sites()` call. The one
deliberate deviation from the routes themselves is the org filter — routes
gate it on `user.role == "super_admin"` (unrestricted unless an explicit
`org_id` query param narrows it), but tools have no `org_id` parameter to
narrow with, so every tool here filters unconditionally on
`ctx.org_id` (the org bound to this session, per `ToolContext`). For a
super_admin that org is their own `nightwatch-hq` (see backend/CLAUDE.md) —
the assistant never gives a super_admin session cross-org reach that an
explicit `org_id` argument would otherwise require.
"""

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.dependencies import permitted_site_ids, scope_to_sites
from app.models.agent import Agent
from app.models.alert_rule import AlertRule
from app.models.camera import Camera
from app.models.camera_connection import CameraConnection
from app.models.digest import Digest
from app.models.event import Event
from app.models.site import Site
from app.services.assistant.registry import ToolContext, register

MAX_LIMIT = 100
DEFAULT_LIMIT = 20

SEVERITY_ORDER = ["low", "medium", "high", "critical"]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def _camera_names(ctx: ToolContext, camera_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not camera_ids:
        return {}
    rows = (
        await ctx.db.execute(select(Camera.id, Camera.name).where(Camera.id.in_(camera_ids)))
    ).all()
    return {row[0]: row[1] for row in rows}


# ─── query_events ───────────────────────────────────────────────────────────
# Mirrors backend/app/api/events.py:list_events — same filter columns and the
# same `scope_to_sites()` call as `_event_query`, with the org half hardened
# to `ctx.org_id` (see module docstring).

QUERY_EVENTS_DECL = {
    "name": "query_events",
    "description": (
        "Search detected events. Returns the matching events with camera "
        "name, severity, status, timestamp and description. Use this for any "
        "question about what happened, when, or where."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID. Omit for all sites the user can see."},
            "camera_id": {"type": "string", "description": "Camera UUID."},
            "since": {"type": "string", "description": "ISO-8601 timestamp, inclusive lower bound."},
            "until": {"type": "string", "description": "ISO-8601 timestamp, exclusive upper bound."},
            "min_severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "status": {"type": "string", "enum": ["new", "acknowledged", "resolved", "dismissed"]},
            "limit": {"type": "integer", "description": "Max results, default 20, hard cap 100."},
        },
        "required": [],
    },
}


async def _query_events_rows(
    ctx: ToolContext,
    site_id: str | None = None,
    camera_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    min_severity: str | None = None,
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[Event]:
    q = select(Event).where(Event.org_id == ctx.org_id)
    q = scope_to_sites(q, Event.site_id, ctx.user)

    if site_id:
        q = q.where(Event.site_id == uuid.UUID(site_id))
    if camera_id:
        q = q.where(Event.camera_id == uuid.UUID(camera_id))
    if since:
        q = q.where(Event.timestamp >= datetime.fromisoformat(since))
    if until:
        q = q.where(Event.timestamp < datetime.fromisoformat(until))
    if min_severity:
        idx = SEVERITY_ORDER.index(min_severity)
        q = q.where(Event.severity.in_(SEVERITY_ORDER[idx:]))
    if status:
        q = q.where(Event.status == status)

    capped = max(1, min(limit or DEFAULT_LIMIT, MAX_LIMIT))
    q = q.order_by(Event.timestamp.desc()).limit(capped)

    result = await ctx.db.execute(q)
    return list(result.scalars().all())


@register(QUERY_EVENTS_DECL)
async def query_events(ctx: ToolContext, **kwargs) -> dict:
    events = await _query_events_rows(ctx, **kwargs)
    camera_names = await _camera_names(ctx, {e.camera_id for e in events})
    return {
        "events": [
            {
                "id": str(e.id),
                "camera_id": str(e.camera_id),
                "camera_name": camera_names.get(e.camera_id, "Unknown camera"),
                "site_id": str(e.site_id),
                "event_type": e.event_type,
                "severity": e.severity,
                "status": e.status,
                "timestamp": _iso(e.timestamp),
                "description": e.description,
            }
            for e in events
        ],
        "count": len(events),
    }


# ─── get_cameras ────────────────────────────────────────────────────────────
# Mirrors backend/app/api/cameras.py:list_cameras / `_camera_query`.

GET_CAMERAS_DECL = {
    "name": "get_cameras",
    "description": "List cameras, optionally filtered by site or status. Returns camera name, site, status.",
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID."},
            "status": {"type": "string", "enum": ["online", "offline", "error"]},
        },
        "required": [],
    },
}


@register(GET_CAMERAS_DECL)
async def get_cameras(ctx: ToolContext, site_id: str | None = None, status: str | None = None) -> dict:
    q = select(Camera).where(Camera.org_id == ctx.org_id, Camera.deleted_at.is_(None))
    q = scope_to_sites(q, Camera.site_id, ctx.user)
    if site_id:
        q = q.where(Camera.site_id == uuid.UUID(site_id))
    if status:
        q = q.where(Camera.status == status)

    result = await ctx.db.execute(q.order_by(Camera.name))
    cameras = result.scalars().all()
    return {
        "cameras": [
            {
                "id": str(c.id),
                "name": c.name,
                "site_id": str(c.site_id),
                "status": c.status,
                "last_frame_at": _iso(c.last_frame_at),
            }
            for c in cameras
        ],
        "count": len(cameras),
    }


# ─── get_camera_health ──────────────────────────────────────────────────────
# Mirrors backend/app/api/cameras.py:get_camera (`_camera_query` + id filter).

GET_CAMERA_HEALTH_DECL = {
    "name": "get_camera_health",
    "description": "Get one camera's current health: status, last decoded frame, and configuration summary.",
    "parameters": {
        "type": "object",
        "properties": {
            "camera_id": {"type": "string", "description": "Camera UUID."},
        },
        "required": ["camera_id"],
    },
}


@register(GET_CAMERA_HEALTH_DECL)
async def get_camera_health(ctx: ToolContext, camera_id: str) -> dict:
    q = select(Camera).where(Camera.org_id == ctx.org_id, Camera.deleted_at.is_(None))
    q = scope_to_sites(q, Camera.site_id, ctx.user)
    q = q.where(Camera.id == uuid.UUID(camera_id))
    camera = (await ctx.db.execute(q)).scalar_one_or_none()
    if camera is None:
        return {"error": "camera not found"}
    return {
        "id": str(camera.id),
        "name": camera.name,
        "site_id": str(camera.site_id),
        "status": camera.status,
        "last_frame_at": _iso(camera.last_frame_at),
        "agent_id": str(camera.agent_id) if camera.agent_id else None,
        "enabled_events": camera.enabled_events,
        "sensitivity": camera.sensitivity,
    }


# ─── get_sites ───────────────────────────────────────────────────────────────
# Mirrors backend/app/api/sites.py:list_sites.

GET_SITES_DECL = {
    "name": "get_sites",
    "description": "List sites the user can see, with name and timezone.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}


@register(GET_SITES_DECL)
async def get_sites(ctx: ToolContext) -> dict:
    q = select(Site).where(Site.org_id == ctx.org_id, Site.deleted_at.is_(None))
    q = scope_to_sites(q, Site.id, ctx.user)
    result = await ctx.db.execute(q.order_by(Site.created_at.desc()))
    sites = result.scalars().all()
    return {
        "sites": [
            {
                "id": str(s.id),
                "name": s.name,
                "address": s.address,
                "timezone": s.timezone,
            }
            for s in sites
        ],
        "count": len(sites),
    }


async def _get_site_or_none(ctx: ToolContext, site_id: str) -> Site | None:
    q = select(Site).where(
        Site.org_id == ctx.org_id, Site.deleted_at.is_(None), Site.id == uuid.UUID(site_id)
    )
    q = scope_to_sites(q, Site.id, ctx.user)
    return (await ctx.db.execute(q)).scalar_one_or_none()


# ─── get_fleet ───────────────────────────────────────────────────────────────
# Mirrors backend/app/api/fleet.py:get_site_fleet (`_load_site` + the
# per-agent/per-camera aggregation below it), org-hardened as above.

GET_FLEET_DECL = {
    "name": "get_fleet",
    "description": (
        "Get appliance (edge box) coverage for a site: how many cameras are "
        "covered, unassigned, and each appliance's status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID."},
        },
        "required": ["site_id"],
    },
}

STALE_AFTER = timedelta(seconds=100)
DEFAULT_CAPACITY = 8


@register(GET_FLEET_DECL)
async def get_fleet(ctx: ToolContext, site_id: str) -> dict:
    site = await _get_site_or_none(ctx, site_id)
    if site is None:
        return {"error": "site not found"}

    agents = list(
        (
            await ctx.db.execute(
                select(Agent).where(Agent.org_id == site.org_id, Agent.site_id == site.id)
            )
        )
        .scalars()
        .all()
    )
    cameras = list(
        (
            await ctx.db.execute(
                select(Camera).where(Camera.site_id == site.id, Camera.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )

    by_agent: dict[uuid.UUID, list[Camera]] = {a.id: [] for a in agents}
    unassigned: list[Camera] = []
    for camera in cameras:
        if camera.agent_id in by_agent:
            by_agent[camera.agent_id].append(camera)
        else:
            unassigned.append(camera)

    now = datetime.now(timezone.utc)
    appliances = []
    stale_count = 0
    cameras_covered = 0
    for agent in agents:
        is_stale = agent.last_seen_at is None or (now - agent.last_seen_at) > STALE_AFTER
        if is_stale:
            stale_count += 1
        else:
            cameras_covered += len(by_agent[agent.id])
        appliances.append(
            {
                "id": str(agent.id),
                "machine_id": agent.machine_id,
                "status": agent.status,
                "is_stale": is_stale,
                "cameras_assigned": len(by_agent[agent.id]),
                "capacity_cameras": agent.capacity_cameras or DEFAULT_CAPACITY,
            }
        )

    return {
        "site_id": str(site.id),
        "site_name": site.name,
        "cameras_total": len(cameras),
        "cameras_covered": cameras_covered,
        "unassigned": [{"id": str(c.id), "name": c.name} for c in unassigned],
        "appliances": appliances,
        "appliances_stale": stale_count,
    }


# ─── get_alert_rules ─────────────────────────────────────────────────────────
# Mirrors backend/app/api/alerts.py:list_rules (`_rule_query`). That route
# does not call `scope_to_sites()` at all — a pre-existing gap in
# alerts.py, not something this tool should inherit given rule 2's
# requirement that every tool query apply both halves of scoping. `scope_to_sites`
# is added here on top of the mirrored filters.

GET_ALERT_RULES_DECL = {
    "name": "get_alert_rules",
    "description": "List alert rules, optionally filtered by site.",
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID."},
        },
        "required": [],
    },
}


@register(GET_ALERT_RULES_DECL)
async def get_alert_rules(ctx: ToolContext, site_id: str | None = None) -> dict:
    q = select(AlertRule).where(AlertRule.org_id == ctx.org_id, AlertRule.deleted_at.is_(None))
    q = scope_to_sites(q, AlertRule.site_id, ctx.user)
    if site_id:
        q = q.where(AlertRule.site_id == uuid.UUID(site_id))

    result = await ctx.db.execute(q.order_by(AlertRule.created_at.desc()))
    rules = result.scalars().all()
    return {
        "rules": [
            {
                "id": str(r.id),
                "name": r.name,
                "site_id": str(r.site_id) if r.site_id else None,
                "event_types": r.event_types,
                "min_severity": r.min_severity,
                "notify_channels": r.notify_channels,
                "enabled": r.enabled,
            }
            for r in rules
        ],
        "count": len(rules),
    }


# ─── get_camera_connections ─────────────────────────────────────────────────
# Mirrors backend/app/api/camera_connections.py:47 (`list_connections`),
# which authorises via `_load_site` (org + scope_to_sites) then loads
# connections by `site_id` alone — a connection's `site_id` cannot itself
# leak cross-org rows once the site lookup has already verified ownership.

GET_CAMERA_CONNECTIONS_DECL = {
    "name": "get_camera_connections",
    "description": "List operator-drawn camera adjacency links (the Map) for a site.",
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID."},
        },
        "required": ["site_id"],
    },
}


@register(GET_CAMERA_CONNECTIONS_DECL)
async def get_camera_connections(ctx: ToolContext, site_id: str) -> dict:
    site = await _get_site_or_none(ctx, site_id)
    if site is None:
        return {"error": "site not found"}

    result = await ctx.db.execute(
        select(CameraConnection).where(CameraConnection.site_id == site.id)
    )
    connections = result.scalars().all()
    camera_ids = {c.camera_a_id for c in connections} | {c.camera_b_id for c in connections}
    camera_names = await _camera_names(ctx, camera_ids)
    return {
        "connections": [
            {
                "id": str(c.id),
                "camera_a_id": str(c.camera_a_id),
                "camera_a_name": camera_names.get(c.camera_a_id, "Unknown camera"),
                "camera_b_id": str(c.camera_b_id),
                "camera_b_name": camera_names.get(c.camera_b_id, "Unknown camera"),
                "label": c.label,
            }
            for c in connections
        ],
        "count": len(connections),
    }


# ─── get_digests ─────────────────────────────────────────────────────────────
# Mirrors backend/app/api/digests.py:list_digests (`_scope`), org-hardened.

GET_DIGESTS_DECL = {
    "name": "get_digests",
    "description": "List recent digests (scheduled or on-demand summaries), optionally filtered by site.",
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID."},
            "limit": {"type": "integer", "description": "Max results, default 20, hard cap 100."},
        },
        "required": [],
    },
}


@register(GET_DIGESTS_DECL)
async def get_digests(ctx: ToolContext, site_id: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    q = select(Digest).where(Digest.org_id == ctx.org_id)
    site_ids = permitted_site_ids(ctx.user)
    if site_ids is not None:
        # Same exclusion as digests.py:_scope — org-wide digests (site_id
        # NULL) are hidden from site-restricted accounts, not just filtered
        # by an in-scope site_id, because they summarise the whole org.
        q = q.where(Digest.site_id.in_(site_ids))
    if site_id:
        q = q.where(Digest.site_id == uuid.UUID(site_id))

    capped = max(1, min(limit or DEFAULT_LIMIT, MAX_LIMIT))
    result = await ctx.db.execute(q.order_by(Digest.created_at.desc()).limit(capped))
    digests = result.scalars().all()
    return {
        "digests": [
            {
                "id": str(d.id),
                "site_id": str(d.site_id) if d.site_id else None,
                "kind": d.kind,
                "range_start": _iso(d.range_start),
                "range_end": _iso(d.range_end),
                "event_count": d.event_count,
                "created_at": _iso(d.created_at),
            }
            for d in digests
        ],
        "count": len(digests),
    }


# ─── Narrow shortcuts ────────────────────────────────────────────────────────
# Implemented in terms of the fat tools above, so there is one query path per
# resource.

WHAT_HAPPENED_LAST_NIGHT_DECL = {
    "name": "what_happened_last_night",
    "description": (
        "Events from 18:00 yesterday to 08:00 today, in the site's local "
        "timezone. Use for 'what happened last night' / overnight recap "
        "questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID. Required to resolve the local timezone."},
        },
        "required": ["site_id"],
    },
}


@register(WHAT_HAPPENED_LAST_NIGHT_DECL)
async def what_happened_last_night(ctx: ToolContext, site_id: str) -> dict:
    site = await _get_site_or_none(ctx, site_id)
    if site is None:
        return {"error": "site not found"}

    tz = ZoneInfo(site.timezone)
    now_local = datetime.now(tz)
    today = now_local.date()
    since_local = datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=tz).replace(hour=18)
    until_local = datetime.combine(today, datetime.min.time(), tzinfo=tz).replace(hour=8)

    since_utc = since_local.astimezone(timezone.utc)
    until_utc = until_local.astimezone(timezone.utc)

    events = await _query_events_rows(
        ctx,
        site_id=site_id,
        since=since_utc.isoformat(),
        until=until_utc.isoformat(),
        limit=MAX_LIMIT,
    )
    camera_names = await _camera_names(ctx, {e.camera_id for e in events})
    return {
        "site_id": site_id,
        "since": _iso(since_utc),
        "until": _iso(until_utc),
        "events": [
            {
                "id": str(e.id),
                "camera_id": str(e.camera_id),
                "camera_name": camera_names.get(e.camera_id, "Unknown camera"),
                "event_type": e.event_type,
                "severity": e.severity,
                "status": e.status,
                "timestamp": _iso(e.timestamp),
                "description": e.description,
            }
            for e in events
        ],
        "count": len(events),
    }


CURRENT_SITE_STATUS_DECL = {
    "name": "current_site_status",
    "description": (
        "Current at-a-glance status for a site: cameras online/total, "
        "unassigned cameras, and stale appliances."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID."},
        },
        "required": ["site_id"],
    },
}


@register(CURRENT_SITE_STATUS_DECL)
async def current_site_status(ctx: ToolContext, site_id: str) -> dict:
    cameras = await get_cameras(ctx, site_id=site_id)
    if "error" in cameras:
        return cameras
    fleet = await get_fleet(ctx, site_id=site_id)
    if "error" in fleet:
        return fleet

    cameras_online = sum(1 for c in cameras["cameras"] if c["status"] == "online")
    return {
        "site_id": site_id,
        "cameras_online": cameras_online,
        "cameras_total": cameras["count"],
        "unassigned": len(fleet["unassigned"]),
        "appliances_stale": fleet["appliances_stale"],
    }


UNRESOLVED_CRITICAL_EVENTS_DECL = {
    "name": "unresolved_critical_events",
    "description": "Critical-severity events that are still new (not acknowledged, resolved, or dismissed).",
    "parameters": {
        "type": "object",
        "properties": {
            "site_id": {"type": "string", "description": "Site UUID. Omit for all sites the user can see."},
            "limit": {"type": "integer", "description": "Max results, default 20, hard cap 100."},
        },
        "required": [],
    },
}


@register(UNRESOLVED_CRITICAL_EVENTS_DECL)
async def unresolved_critical_events(ctx: ToolContext, site_id: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    return await query_events(ctx, site_id=site_id, min_severity="critical", status="new", limit=limit)


# ─── navigate ────────────────────────────────────────────────────────────────
# Reads nothing but belongs with the non-mutating tools.

ALLOWED_ROUTES = {
    "/app", "/app/sites", "/app/cameras", "/app/map", "/app/activity",
    "/app/alerts", "/app/wall", "/app/fleet", "/app/digests",
    "/app/usage", "/app/settings",
}

NAVIGATE_DECL = {
    "name": "navigate",
    "description": (
        "Open a page in the app for the user. Use when they ask to see or go "
        "to a section, e.g. 'show me the map'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "route": {"type": "string", "enum": sorted(ALLOWED_ROUTES)},
        },
        "required": ["route"],
    },
}


@register(NAVIGATE_DECL)
async def navigate(ctx: ToolContext, route: str) -> dict:
    # Allowlisted rather than free-form so the model cannot construct routes
    # that don't exist or that point outside the app.
    if route not in ALLOWED_ROUTES:
        return {"error": f"route not allowed: {route}"}
    return {"navigate": route}
