"""Control WebSocket for edge-box agents.

Edge boxes sit behind NAT with no inbound ports, so instead of Backend
proxying WebRTC signaling to an always-on relay VM (the existing
Worker-VM-fallback path in `cameras.camera_webrtc_offer`), an edge-box agent
keeps one persistent outbound WebSocket open to Backend. When someone
requests live view for a camera served by that agent, Backend pushes the
WebRTC offer down this socket and relays back the answer.

Scoped to WebRTC signaling only — heartbeat stays on the existing
`POST /internal/heartbeat` (Task 2); multiplexing both concerns over one
socket isn't needed here and would require the pipeline sidecar to route
its own heartbeat through the Go agent's socket.
"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.agent import Agent
from app.services.device_token_service import DeviceTokenService

logger = logging.getLogger(__name__)

router = APIRouter()


class ControlRegistry:
    """Tracks open agent control sockets and brokers signaling round-trips."""

    def __init__(self):
        self._conns: dict[uuid.UUID, WebSocket] = {}
        self._pending: dict[str, asyncio.Future] = {}

    def register(self, agent_id: uuid.UUID, ws: WebSocket) -> None:
        self._conns[agent_id] = ws

    def unregister(self, agent_id: uuid.UUID) -> None:
        self._conns.pop(agent_id, None)

    def get(self, agent_id: uuid.UUID) -> WebSocket | None:
        return self._conns.get(agent_id)

    async def request_signal(self, agent_id: uuid.UUID, msg: dict, timeout: float = 10.0) -> dict:
        ws = self.get(agent_id)
        if ws is None:
            raise ConnectionError("agent not connected")
        request_id = str(uuid.uuid4())
        msg["request_id"] = request_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        try:
            try:
                await ws.send_json(msg)
            except asyncio.TimeoutError:
                raise
            except Exception as e:
                # Covers the TOCTOU window between the registry.get() check
                # in the caller and this send: the agent's socket can have
                # gone away in between (e.g. Starlette's
                # "Cannot call send once a close message has been sent").
                # Normalize any such transport failure to ConnectionError so
                # callers only need to handle one exception type.
                raise ConnectionError(f"agent socket send failed: {e}") from e
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, payload: dict) -> None:
        fut = self._pending.get(request_id)
        if fut and not fut.done():
            fut.set_result(payload)


registry = ControlRegistry()


async def _authenticate_ws(token: str) -> Agent | None:
    """Resolve a paired Agent from a device token, same scan-and-verify
    pattern as `app.core.dependencies.get_agent_from_token`, adapted for a
    WebSocket handler (token arrives as a query param, not a header, since
    browsers' native WebSocket API can't set custom headers)."""
    svc = DeviceTokenService()
    async with async_session_factory() as db:
        result = await db.execute(select(Agent).where(Agent.status != "unpaired"))
        for agent in result.scalars():
            if agent.device_token_hash and svc.verify(token, agent.device_token_hash):
                return agent
    return None


@router.websocket("/api/agents/me/control")
async def agent_control_socket(websocket: WebSocket, token: str = Query(...)):
    agent = await _authenticate_ws(token)
    if agent is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    registry.register(agent.id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            if data.get("type") == "heartbeat":
                # Liveness ping only — real heartbeat reporting stays on
                # POST /internal/heartbeat (Task 2).
                continue
            if data.get("type") == "signal_answer" and data.get("request_id"):
                registry.resolve(data["request_id"], data)
    except WebSocketDisconnect:
        pass
    finally:
        registry.unregister(agent.id)
