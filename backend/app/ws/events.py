import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.dependencies import permitted_site_ids
from app.core.sessions import session_manager
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class Subscriber:
    """One open socket plus the site scope it is allowed to see.

    ``site_ids is None`` means unrestricted (super_admin, or a user with no
    site restriction), matching ``permitted_site_ids``.
    """

    __slots__ = ("websocket", "site_ids")

    def __init__(self, websocket: WebSocket, site_ids: list[uuid.UUID] | None):
        self.websocket = websocket
        self.site_ids = None if site_ids is None else {str(s) for s in site_ids}

    def may_see(self, payload: dict) -> bool:
        if self.site_ids is None:
            return True
        event = payload.get("event") or {}
        site_id = event.get("site_id")
        # Fail closed: a message we cannot attribute to a site is not
        # delivered to a scoped subscriber. Restricting access is the whole
        # point, so an unknown shape must not default to "send it".
        if site_id is None:
            return False
        return str(site_id) in self.site_ids


class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, list[Subscriber]] = {}

    async def connect(
        self, websocket: WebSocket, org_id: str, site_ids: list[uuid.UUID] | None
    ):
        await websocket.accept()
        self.connections.setdefault(org_id, []).append(Subscriber(websocket, site_ids))

    def disconnect(self, websocket: WebSocket, org_id: str):
        if org_id in self.connections:
            self.connections[org_id] = [
                s for s in self.connections[org_id] if s.websocket != websocket
            ]

    async def broadcast_to_org(self, org_id: str, data: dict):
        if org_id not in self.connections:
            return
        dead = []
        for sub in self.connections[org_id]:
            # Filtered per subscriber, not per channel: two operators on the
            # same org can legitimately have different site scopes, so the
            # decision has to be made at send time.
            if not sub.may_see(data):
                continue
            try:
                await sub.websocket.send_json(data)
            except Exception:
                dead.append(sub.websocket)
        for ws in dead:
            self.disconnect(ws, org_id)


ws_manager = ConnectionManager()


async def broadcast_to_org(org_id: str, payload: dict) -> None:
    """Module-level helper to broadcast a payload to all WS clients of an org."""
    await ws_manager.broadcast_to_org(org_id, payload)


async def _load_site_scope(user_id: str) -> list[uuid.UUID] | None:
    """Resolve the connecting user's site scope from the database.

    Read fresh at connect rather than carried in the session: sessions live up
    to 24 hours, and a permissions change must not wait for a re-login to take
    effect. Sockets connect rarely, so this costs one query per connection.
    """
    async with async_session_factory() as db:
        user = (
            await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        ).scalar_one_or_none()
        if user is None:
            return []  # Unknown user: deliver nothing.
        return permitted_site_ids(user)


@router.websocket("/ws/events")
async def websocket_events(
    websocket: WebSocket,
    token: str = Query(...),
):
    # Validate session (use a generic fingerprint for WS since we can't get real UA easily)
    ip = websocket.client.host if websocket.client else "unknown"
    headers = dict(websocket.headers)
    user_agent = headers.get("user-agent", "websocket-client")

    session = await session_manager.validate_session(token, ip, user_agent)
    if not session:
        await websocket.close(code=4001, reason="Invalid session")
        return

    org_id = session.get("org_id", "")
    role = session.get("role", "")
    effective_org = "all" if role == "super_admin" else org_id

    if role == "super_admin":
        site_ids = None
    else:
        try:
            site_ids = await _load_site_scope(session.get("user_id", ""))
        except Exception as exc:  # noqa: BLE001
            # Fail closed rather than falling back to an unscoped feed.
            logger.warning("ws site-scope lookup failed: %s", exc)
            await websocket.close(code=4003, reason="Could not resolve access scope")
            return

    await ws_manager.connect(websocket, effective_org, site_ids)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, effective_org)
