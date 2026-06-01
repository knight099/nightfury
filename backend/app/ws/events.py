from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.sessions import session_manager

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, org_id: str):
        await websocket.accept()
        self.connections.setdefault(org_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, org_id: str):
        if org_id in self.connections:
            self.connections[org_id] = [ws for ws in self.connections[org_id] if ws != websocket]

    async def broadcast_to_org(self, org_id: str, data: dict):
        if org_id not in self.connections:
            return
        dead = []
        for ws in self.connections[org_id]:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, org_id)


ws_manager = ConnectionManager()


async def broadcast_to_org(org_id: str, payload: dict) -> None:
    """Module-level helper to broadcast a payload to all WS clients of an org."""
    await ws_manager.broadcast_to_org(org_id, payload)


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

    await ws_manager.connect(websocket, effective_org)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, effective_org)
