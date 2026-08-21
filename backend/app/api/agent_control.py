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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import async_session_factory
from app.services.agent_auth import resolve_agent_by_token

logger = logging.getLogger(__name__)

router = APIRouter()


class SignalError(Exception):
    """The agent replied to a signaling request with an explicit error.

    Distinct from ConnectionError (socket gone) and asyncio.TimeoutError (no
    reply at all): this is a fast, definitive "I can't serve this" from the
    edge box, e.g. the camera isn't published locally.
    """


class ControlRegistry:
    """Tracks open agent control sockets and brokers signaling round-trips.

    Wire protocol (both directions, JSON over the control WebSocket):

    - Backend → agent: ``{"type": "signal_offer", "request_id": str,
      "camera_id": str, "view_token": str, "offer": <SDP string>}``
    - Agent → backend: ``{"type": "signal_answer", "request_id": str,
      "answer": <SDP string>}`` on success, or
      ``{"type": "signal_answer", "request_id": str, "error": str}`` on any
      failure.

    ``offer``/``answer`` are RAW SDP STRINGS — the same representation the
    relay HTTP path and the browser already use (see
    ``schemas.camera.WebRTCOfferRequest.offer``), never marshalled
    RTCSessionDescription objects.
    """

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
        """Push a signaling message to an agent and await its signal_answer.

        Raises ConnectionError if the agent is not connected or the socket
        send fails, SignalError if the agent replied with an explicit
        ``error`` field (fast failure, no timeout wait), and
        asyncio.TimeoutError if no reply arrives within ``timeout``.
        """
        ws = self.get(agent_id)
        if ws is None:
            raise ConnectionError("agent not connected")
        request_id = str(uuid.uuid4())
        msg["request_id"] = request_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
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
            payload = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

        # The agent always replies, even on failure, with an explicit
        # {"error": "..."} field — surface that as an immediate failure
        # rather than making callers wait out the full timeout.
        if payload.get("error"):
            raise SignalError(str(payload["error"]))
        if not payload.get("answer"):
            raise SignalError("agent returned no answer")
        return payload

    async def send_command(self, agent_id: uuid.UUID, msg: dict) -> None:
        """Push a fire-and-forget command to an agent.

        Distinct from request_signal, which is a WebRTC round-trip and
        insists on an `answer` in the reply. Commands like scan_now have no
        synchronous result — discovery lands later via
        POST /api/agents/me/discovered — so waiting for one would guarantee
        a timeout on every call.
        """
        ws = self.get(agent_id)
        if ws is None:
            raise ConnectionError("agent not connected")
        try:
            await ws.send_json(msg)
        except Exception as e:
            raise ConnectionError(f"agent socket send failed: {e}") from e

    def resolve(self, request_id: str, payload: dict) -> None:
        fut = self._pending.get(request_id)
        if fut and not fut.done():
            fut.set_result(payload)


registry = ControlRegistry()


async def _authenticate_ws(token: str) -> uuid.UUID | None:
    """Resolve a paired agent's id from a device token.

    Shares `app.services.agent_auth.resolve_agent_by_token` with the HTTP
    dependencies so this path also gets the indexed lookup rather than an
    O(N_agents) Argon2 scan.

    Returns the id rather than the ORM object: the session closes here, and
    committing the possible device_token_id backfill expires the instance's
    attributes, so the object must not outlive the session.
    """
    async with async_session_factory() as db:
        agent = await resolve_agent_by_token(db, token)
        if agent is None:
            return None
        agent_id = agent.id
        # resolve_agent_by_token may backfill device_token_id; this session
        # is ours, so commit that before it's discarded.
        await db.commit()
        return agent_id


def _bearer_token(websocket: WebSocket) -> str:
    """Extract the device token from the upgrade request's Authorization header.

    The token is deliberately NOT accepted as a query parameter: query-string
    secrets end up in access logs, proxy logs and APM traces. The only client
    of this endpoint is the Go agent (agent/internal/control/client.go), which
    sets this header on the WebSocket handshake — no browser is involved, so
    the usual "browsers can't set WS headers" constraint does not apply.
    """
    header = websocket.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


@router.websocket("/api/agents/me/control")
async def agent_control_socket(websocket: WebSocket):
    token = _bearer_token(websocket)
    agent_id = await _authenticate_ws(token) if token else None
    if agent_id is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    registry.register(agent_id, websocket)
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
        registry.unregister(agent_id)
