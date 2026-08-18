# Edge Detection Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move event detection (motion gate → Gemini Vision → event packaging) from the cloud Worker to a self-contained edge box, so the cloud only ever handles small event payloads and on-demand WebRTC live view — no continuous video, no static shared secrets on customer-owned hardware.

**Architecture:** `agent/` gains a supervised Python pipeline sidecar (`agent/pipeline/`, copied from `worker/`) and an embedded WebRTC answer stack (`agent/webrtcsignal/`, copied from `relay/webrtcsignal/`), talking to Backend over one persistent, device-token-authenticated control WebSocket for heartbeat and WebRTC signaling. Backend gains: a dual-mode `/internal/*` auth dependency (existing `X-Worker-Key` OR new device-token Bearer), a write-scoped signed-GCS-upload endpoint, a Gemini/Vertex short-lived token broker, and a control-WebSocket registry that routes signaling to the right edge box. `worker/` and `relay/` stay untouched as the deployable fallback path.

**Tech Stack:** Go (agent, `pion/webrtc` already a dependency via `relay/webrtcsignal`), Python/FastAPI (backend, pipeline sidecar), SQLite (offline queue, unchanged), Google Cloud Storage + Vertex AI.

## Global Constraints

- No TDD — implement each task directly, then self-review for correctness, simplicity, SOLID boundaries, and control flow before committing. (Per project preference — skip write-test-first cycles.)
- `worker/` and `relay/` are copied FROM, never modified. Any fix belongs in both the original and the copy by hand — this plan does not set up auto-sync tooling.
- No new inbound ports on the edge box. All edge↔cloud communication is outbound-initiated (control WebSocket, HTTPS calls).
- `/internal/*` routes keep working unauthenticated-by-`X-Worker-Key` exactly as today — this plan is additive only, never removes or breaks the existing Worker-VM-fallback auth path.
- Device-token Bearer auth reuses the existing pattern in `backend/app/core/dependencies.py::get_agent_from_token` — don't invent a second token scheme.
- `agent/pipeline/`'s only permitted behavioral differences from `worker/` are: (1) auth header, (2) GCS upload mechanism, (3) Gemini credential source. Everything else (motion gate, YOLO fastpath, event packaging, offline queue) must be byte-identical after copy.

---

## File Structure

```
backend/app/core/dependencies.py          # MODIFY: verify_worker_key accepts device-token Bearer too
backend/app/api/internal.py               # MODIFY: heartbeat schema extended (additive fields)
backend/app/services/gcs.py               # MODIFY: add sign_gcs_upload_url()
backend/app/api/edge_uploads.py           # CREATE: POST /api/edge/upload-url route
backend/app/services/gemini_broker.py     # CREATE: short-lived Vertex AI token minting
backend/app/api/edge_credentials.py       # CREATE: POST /api/edge/gemini-token route
backend/app/api/agent_control.py          # CREATE: WS /api/agents/me/control + signaling registry
backend/app/api/cameras.py                # MODIFY: webrtc-offer route branches to control-WS path
backend/app/schemas/heartbeat.py          # CREATE: pydantic schema for merged heartbeat body

agent/pipeline/                           # CREATE: copy of worker/ (git cp, then 3 files touched)
agent/pipeline/api_client.py              # MODIFY (post-copy): Bearer device-token auth
agent/pipeline/gcs_uploader.py            # MODIFY (post-copy): signed-upload-URL flow
agent/pipeline/gemini_client.py           # MODIFY (post-copy): broker-token flow

agent/webrtcsignal/                       # CREATE: copy of relay/webrtcsignal/ + supporting packages
agent/internal/republish/                 # CREATE: copy of relay/internal/republish/
agent/internal/buffer/                    # CREATE: copy of relay/internal/buffer/
agent/webrtcsignal/answer.go              # CREATE (post-copy): offer/answer logic factored out of ServeHTTP

agent/internal/pipeline/supervisor.go     # CREATE: spawns/restarts agent/pipeline/ as child process
agent/internal/control/client.go          # CREATE: persistent control WebSocket client (heartbeat + signaling)
agent/cmd/agent/main.go                   # MODIFY: wires pipeline supervisor + control client into startup

deploy/coturn/                            # CREATE: coturn config + systemd unit + docs
```

---

### Task 1: Backend — dual-mode `/internal/*` auth

**Files:**
- Modify: `backend/app/core/dependencies.py`
- Test: manual (see step 3)

**Interfaces:**
- Produces: `verify_worker_key` now attaches `request.state.internal_principal: dict` with `{"kind": "worker"} ` or `{"kind": "agent", "agent_id": UUID, "org_id": UUID}`, so downstream handlers (Task 2) can tell which principal made the call.
- Consumes: existing `get_agent_from_token` (already reads `Authorization: Bearer <token>`, verifies against `Agent` rows via `DeviceTokenService.verify`).

- [ ] **Step 1: Extend `verify_worker_key`**

Current signature (confirmed in codebase):
```python
async def verify_worker_key(x_worker_key: str | None = Header(default=None, alias="X-Worker-Key")):
    ...
```

Replace with a version that also accepts a device-token Bearer, resolving to an `Agent` row:

```python
async def verify_worker_key(
    request: Request,
    x_worker_key: str | None = Header(default=None, alias="X-Worker-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
):
    if x_worker_key and x_worker_key == settings.worker_api_key:
        request.state.internal_principal = {"kind": "worker"}
        return
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        result = await db.execute(select(Agent))
        for agent in result.scalars():
            if agent.device_token_hash and DeviceTokenService.verify(token, agent.device_token_hash):
                request.state.internal_principal = {"kind": "agent", "agent_id": agent.id, "org_id": agent.org_id}
                return
    raise HTTPException(status_code=401, detail="Invalid worker key or device token")
```

Reuse the existing linear-scan-and-verify pattern already used in `get_agent_from_token` for the Bearer branch (same DeviceTokenService.verify call, same table) — don't add a second lookup strategy.

- [ ] **Step 2: Confirm no route regression**

Run: `cd backend && uv run python3 -c "from app.main import app"`
Expected: imports cleanly, no errors.

- [ ] **Step 3: Manual verification**

Run backend locally, `curl -X POST localhost:8080/internal/heartbeat -H "X-Worker-Key: $WORKER_API_KEY" -d '{}'` → still 200/expected response (existing path unaffected). This is the regression check for the existing fallback path — no automated test per project preference, but this manual check is mandatory before moving on.

- [ ] **Step 4: Self-review**

Check: does the Bearer branch leak timing information distinguishing "no such token" from "wrong worker key"? Both should 401 with the same generic message (already true above). Check SOLID: `verify_worker_key` now does two things (worker-key check, agent-token check) — acceptable here since both branches produce the same `Depends()`-shaped contract for `/internal/*` routers; don't split unless a fourth auth mode gets added later.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/dependencies.py
git commit -m "backend: accept device-token Bearer auth on /internal/* routes"
```

---

### Task 2: Backend — merged heartbeat schema (additive)

**Files:**
- Create: `backend/app/schemas/heartbeat.py`
- Modify: `backend/app/api/internal.py`

**Interfaces:**
- Consumes: `request.state.internal_principal` from Task 1.
- Produces: `POST /internal/heartbeat` accepts the existing `{worker_id, camera_id, status, ...metrics}` body unchanged AND a new optional `pipeline` object; response unchanged.

- [ ] **Step 1: Add the schema**

```python
# backend/app/schemas/heartbeat.py
from pydantic import BaseModel

class PipelineHealth(BaseModel):
    status: str  # "running" | "restarting" | "down"
    last_event_at: str | None = None
    gemini_call_failures_last_hour: int = 0

class HeartbeatRequest(BaseModel):
    worker_id: str | None = None
    camera_id: str | None = None
    status: str | None = None
    pipeline: PipelineHealth | None = None

    class Config:
        extra = "allow"  # preserve today's free-form **metrics passthrough
```

- [ ] **Step 2: Wire into the route**

Current handler signature: `async def worker_heartbeat(body: dict, db: AsyncSession = Depends(get_db))`. Change the parameter type only:

```python
@router.post("/heartbeat", status_code=200)
async def worker_heartbeat(body: HeartbeatRequest, db: AsyncSession = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    camera_id = data.get("camera_id")
    status = data.get("status")
    # ... existing camera.status / camera.last_frame_at / camera.worker_id update logic, unchanged
    # NEW: if data.get("pipeline"), store/log it — no schema migration needed yet, log only
    if pipeline := data.get("pipeline"):
        logger.info("pipeline health for camera %s: %s", camera_id, pipeline)
```

Keep the rest of the existing handler body exactly as-is — only the parameter type and the new `if pipeline:` branch are additions.

- [ ] **Step 3: Verify backward compatibility**

Run: `cd backend && uv run python3 -c "from app.main import app"`
Then manually POST the OLD shape (`{"worker_id": "x", "camera_id": "...", "status": "healthy"}`, no `pipeline` field) and confirm 200 — `HeartbeatRequest`'s `extra = "allow"` and optional fields guarantee this, but verify once by hand since this is the compatibility-critical path for existing Worker-VM-fallback deployments.

- [ ] **Step 4: Self-review**

Check: is `pipeline` genuinely optional end-to-end (schema, handler, no downstream code assumes it exists)? Yes — handler only reads it inside `if pipeline := ...`. Check: did the `extra = "allow"` choice preserve every existing free-form metric key the old `dict`-typed body used to accept? Yes, `extra="allow"` means undeclared keys pass through into `model_dump()`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/heartbeat.py backend/app/api/internal.py
git commit -m "backend: accept optional pipeline health in /internal/heartbeat"
```

---

### Task 3: Backend — write-scoped signed GCS upload URLs

**Files:**
- Modify: `backend/app/services/gcs.py`
- Create: `backend/app/api/edge_uploads.py`
- Modify: `backend/app/main.py` (register router)

**Interfaces:**
- Consumes: `get_agent_from_token` (existing dependency, resolves calling `Agent`).
- Produces: `sign_gcs_upload_url(path: str, content_type: str, expires_in: int | None = None) -> str`; route `POST /api/edge/upload-url {"path": str, "content_type": str} -> {"upload_url": str, "gs_uri": str}`.

- [ ] **Step 1: Add the signing function**

Mirror the existing `sign_gcs_url` read-signer in the same file:

```python
# backend/app/services/gcs.py — add alongside existing sign_gcs_url()
def sign_gcs_upload_url(path: str, content_type: str, expires_in: int | None = None) -> str:
    client = _get_client()
    bucket = client.bucket(settings.gcs_bucket)
    blob = bucket.blob(path)
    ttl = expires_in or settings.gcs_signed_url_expiry
    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=ttl),
        method="PUT",
        content_type=content_type,
    )
    return url
```

- [ ] **Step 2: Add the route**

```python
# backend/app/api/edge_uploads.py
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.dependencies import get_agent_from_token
from app.models.agent import Agent
from app.services.gcs import sign_gcs_upload_url

router = APIRouter(prefix="/api/edge", tags=["edge"])

class UploadUrlRequest(BaseModel):
    path: str  # e.g. "{org_id}/2026/08/12/{camera_id}/{event_id}/snapshot.webp"
    content_type: str

class UploadUrlResponse(BaseModel):
    upload_url: str
    gs_uri: str

@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(body: UploadUrlRequest, agent: Agent = Depends(get_agent_from_token)):
    expected_prefix = f"{agent.org_id}/"
    if not body.path.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="path must be scoped to caller's org_id")
    url = sign_gcs_upload_url(body.path, body.content_type)
    return UploadUrlResponse(upload_url=url, gs_uri=f"gs://{settings.gcs_bucket}/{body.path}")
```

The `expected_prefix` check is the multi-tenant guard — matches this codebase's existing rule that every query/write filters by `org_id`.

- [ ] **Step 3: Register the router**

Find where other routers are registered in `backend/app/main.py` (pattern: `app.include_router(...)`), add:
```python
from app.api.edge_uploads import router as edge_uploads_router
app.include_router(edge_uploads_router)
```

- [ ] **Step 4: Verify**

Run: `cd backend && uv run python3 -c "from app.main import app"`
Expected: clean import, no route conflicts.

- [ ] **Step 5: Self-review**

Check: does `sign_gcs_upload_url` reuse `_get_client()` (cached client) rather than constructing a new `storage.Client` per call? Yes. Check: is the org-scoping check bypassable by a crafted path (e.g. `../other-org/...`)? `str.startswith` on a GCS object path is safe here since GCS paths aren't filesystem paths (no `..` traversal semantics), but confirm `body.path` doesn't contain a literal different org_id string as a substring elsewhere — the `startswith(f"{org_id}/")` check with the trailing slash is sufficient since UUIDs don't collide as prefixes.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gcs.py backend/app/api/edge_uploads.py backend/app/main.py
git commit -m "backend: add org-scoped signed GCS upload URL endpoint for edge boxes"
```

---

### Task 4: Backend — Gemini/Vertex AI short-lived token broker

**Files:**
- Create: `backend/app/services/gemini_broker.py`
- Create: `backend/app/api/edge_credentials.py`
- Modify: `backend/app/main.py` (register router)

**Interfaces:**
- Consumes: `get_agent_from_token`.
- Produces: `mint_vertex_token(ttl_seconds: int) -> tuple[str, datetime]`; route `POST /api/edge/gemini-token -> {"access_token": str, "expires_at": str, "vertex_project": str, "vertex_location": str}`.

- [ ] **Step 1: Add the broker service**

Uses Google's `google.auth` short-lived credentials support (`impersonated_credentials`) — Backend's own service account impersonates itself to mint a token capped at the requested TTL, which is the standard pattern for issuing short-lived tokens without a second static secret:

```python
# backend/app/services/gemini_broker.py
from datetime import datetime, timedelta, timezone
import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request as GoogleAuthRequest

_source_creds, _project = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)

def mint_vertex_token(ttl_seconds: int = 1800) -> tuple[str, datetime]:
    target = impersonated_credentials.Credentials(
        source_credentials=_source_creds,
        target_principal=_source_creds.service_account_email,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
        lifetime=ttl_seconds,
    )
    target.refresh(GoogleAuthRequest())
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return target.token, expires_at
```

- [ ] **Step 2: Add the route**

```python
# backend/app/api/edge_credentials.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.dependencies import get_agent_from_token
from app.models.agent import Agent
from app.core.config import settings
from app.services.gemini_broker import mint_vertex_token

router = APIRouter(prefix="/api/edge", tags=["edge"])

class GeminiTokenResponse(BaseModel):
    access_token: str
    expires_at: str
    vertex_project: str
    vertex_location: str

@router.post("/gemini-token", response_model=GeminiTokenResponse)
async def get_gemini_token(agent: Agent = Depends(get_agent_from_token)):
    token, expires_at = mint_vertex_token(ttl_seconds=1800)
    return GeminiTokenResponse(
        access_token=token,
        expires_at=expires_at.isoformat(),
        vertex_project=settings.gemini_vertex_project,
        vertex_location=settings.gemini_vertex_location,
    )
```

`settings.gemini_vertex_project`/`gemini_vertex_location` already exist as worker-side config names (confirmed in `worker/gemini_client.py`) — add matching fields to `backend/app/core/config.py` if not already present there.

- [ ] **Step 3: Register the router**

```python
from app.api.edge_credentials import router as edge_credentials_router
app.include_router(edge_credentials_router)
```

- [ ] **Step 4: Verify**

Run: `cd backend && uv run python3 -c "from app.main import app"`. Then manually call the route with a valid device token from a paired test agent and confirm a token comes back; decode it (or call a cheap Vertex API) to confirm it's valid.

- [ ] **Step 5: Self-review**

Check: is the 30-minute default TTL (`ttl_seconds=1800`) consistent with the spec's "15–60 min TTL" range? Yes. Check: does `mint_vertex_token` avoid holding the impersonated credentials object across requests (each call mints fresh)? Yes — matches the "short-lived, minted per request" intent; don't cache/reuse a single `impersonated_credentials.Credentials` object across different agents.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gemini_broker.py backend/app/api/edge_credentials.py backend/app/main.py
git commit -m "backend: add short-lived Vertex AI token broker for edge boxes"
```

---

### Task 5: Backend — control WebSocket registry + signaling relay

**Files:**
- Create: `backend/app/api/agent_control.py`
- Modify: `backend/app/api/cameras.py`
- Modify: `backend/app/main.py` (register router)

**Interfaces:**
- Consumes: `get_agent_from_token` (WebSocket variant — see step 1), the existing `WebRTCOfferRequest`/`WebRTCAnswerResponse` schemas already used by `camera_webrtc_offer`.
- Produces: `ControlRegistry.get(agent_id) -> WebSocket | None`, `ControlRegistry.register(agent_id, ws)`, `ControlRegistry.unregister(agent_id)`; module-level singleton `registry = ControlRegistry()` importable from `cameras.py`.

- [ ] **Step 1: Build the registry + WS endpoint**

```python
# backend/app/api/agent_control.py
import asyncio
import json
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.device_token_service import DeviceTokenService
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from sqlalchemy import select

router = APIRouter()

class ControlRegistry:
    def __init__(self):
        self._conns: dict[uuid.UUID, WebSocket] = {}
        self._pending: dict[str, asyncio.Future] = {}

    def register(self, agent_id: uuid.UUID, ws: WebSocket):
        self._conns[agent_id] = ws

    def unregister(self, agent_id: uuid.UUID):
        self._conns.pop(agent_id, None)

    def get(self, agent_id: uuid.UUID) -> WebSocket | None:
        return self._conns.get(agent_id)

    async def request_signal(self, agent_id: uuid.UUID, msg: dict, timeout: float = 10.0) -> dict:
        ws = self.get(agent_id)
        if ws is None:
            raise ConnectionError("agent not connected")
        request_id = str(uuid.uuid4())
        msg["request_id"] = request_id
        fut = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        await ws.send_json(msg)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, payload: dict):
        fut = self._pending.get(request_id)
        if fut and not fut.done():
            fut.set_result(payload)

registry = ControlRegistry()

async def _authenticate_ws(token: str) -> Agent | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Agent))
        for agent in result.scalars():
            if agent.device_token_hash and DeviceTokenService.verify(token, agent.device_token_hash):
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
            data = json.loads(raw)
            if data.get("type") == "heartbeat":
                pass  # Task 2's schema/logging handles this if forwarded to /internal/heartbeat separately;
                      # this socket only carries signaling replies + a lightweight liveness ping in this task
            elif data.get("type") == "signal_answer" and data.get("request_id"):
                registry.resolve(data["request_id"], data)
    except WebSocketDisconnect:
        registry.unregister(agent.id)
```

Note: this task scopes the control socket to WebRTC signaling only (heartbeat stays on the existing `POST /internal/heartbeat`, per Task 2 — simpler than multiplexing two concerns over one socket, and doesn't require the pipeline sidecar to route through the Go agent's socket for its own heartbeat).

- [ ] **Step 2: Rework the webrtc-offer route to try the control channel first**

Current `camera_webrtc_offer` proxies unconditionally to `settings.relay_webrtc_url`. Change it to check the control registry first (edge-box path), falling back to the existing relay-VM proxy (Worker-VM-fallback path) if the camera's agent isn't connected via the control socket:

```python
# backend/app/api/cameras.py — inside camera_webrtc_offer, replace the unconditional relay proxy with:
from app.api.agent_control import registry as control_registry

camera = await get_camera_or_404(db, camera_id)  # however this route already resolves the camera
agent_id = camera.agent_id  # existing FK, confirm field name against Camera model before wiring

if agent_id and control_registry.get(agent_id) is not None:
    view_token = sign_stream_token(str(camera_id), ttl_seconds=300)
    try:
        result = await control_registry.request_signal(
            agent_id,
            {"type": "signal_offer", "camera_id": str(camera_id), "view_token": view_token, "offer": body.offer.model_dump()},
        )
    except (ConnectionError, asyncio.TimeoutError):
        raise HTTPException(status_code=503, detail="Edge box unreachable")
    return WebRTCAnswerResponse(answer=result["answer"])

# existing relay-VM proxy logic, unchanged, as the fallback:
async with httpx.AsyncClient() as client:
    ...
```

Confirm `Camera.agent_id` is the actual FK field name in the model before wiring this — if the model instead only has a `site_id`/`org_id` relationship to agents, resolve via that association instead; don't invent a field.

- [ ] **Step 3: Register the router**

```python
from app.api.agent_control import router as agent_control_router
app.include_router(agent_control_router)
```

- [ ] **Step 4: Verify**

Run: `cd backend && uv run python3 -c "from app.main import app"`. Manual check deferred to Task 9 (needs the agent side built first to actually connect a socket end-to-end).

- [ ] **Step 5: Self-review**

Check: does `request_signal`'s `asyncio.Future` cleanup run even on timeout? Yes — `finally` pops it. Check: is there a risk of two browsers requesting the same camera's view simultaneously colliding on `request_id`? No — `request_id` is a fresh UUID per call, keyed independently in `_pending`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/agent_control.py backend/app/api/cameras.py backend/app/main.py
git commit -m "backend: add control-WebSocket signaling relay, edge-box-first webrtc-offer routing"
```

---

### Task 6: Copy `worker/` → `agent/pipeline/`

**Files:**
- Create: `agent/pipeline/` (entire directory, copied)

- [ ] **Step 1: Copy**

```bash
git -C /Users/vaibhaw/Developer/vision cp -r worker agent/pipeline
```

(If `git cp` isn't available in this git version, use `cp -r worker agent/pipeline && git add agent/pipeline`.)

- [ ] **Step 2: Verify it still runs standalone**

```bash
cd /Users/vaibhaw/Developer/vision/agent/pipeline
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python3 -c "import main"
```
Expected: imports cleanly, same as `worker/` does today — confirms the copy didn't break relative imports.

- [ ] **Step 3: Self-review**

Check: diff `agent/pipeline/` against `worker/` — should be byte-identical at this point (no edits yet; those come in Tasks 8–10). Check: `.venv/` isn't accidentally staged (should be gitignored the same way `worker/.venv` is).

- [ ] **Step 4: Commit**

```bash
git add agent/pipeline
git commit -m "agent: copy worker/ pipeline into agent/pipeline (unmodified)"
```

---

### Task 7: Copy `relay/webrtcsignal/` + dependencies → `agent/webrtcsignal/`

**Files:**
- Create: `agent/webrtcsignal/` (copied from `relay/webrtcsignal/`)
- Create: `agent/internal/republish/` (copied from `relay/internal/republish/`)
- Create: `agent/internal/buffer/` (copied from `relay/internal/buffer/`)

- [ ] **Step 1: Copy**

```bash
git -C /Users/vaibhaw/Developer/vision cp -r relay/webrtcsignal agent/webrtcsignal
git -C /Users/vaibhaw/Developer/vision cp -r relay/internal/republish agent/internal/republish
git -C /Users/vaibhaw/Developer/vision cp -r relay/internal/buffer agent/internal/buffer
```

- [ ] **Step 2: Fix import paths**

The copied files import via the relay module's Go module path (e.g. `nightwatch/relay/internal/republish`). Update imports in `agent/webrtcsignal/*.go` to point at the agent module path instead (e.g. `nightwatch/agent/internal/republish`) — check `agent/go.mod`'s module name first:

```bash
head -1 /Users/vaibhaw/Developer/vision/agent/go.mod
```

Then, for each copied `.go` file, replace the relay-module import prefix with the agent-module one. This is a straightforward find-and-replace across the copied files, not a logic change.

- [ ] **Step 3: Build**

```bash
cd /Users/vaibhaw/Developer/vision/agent && go build ./...
```
Expected: fails at this point only on missing `agent/internal/auth` (the relay `Verifier`/`DeviceTokenAuthenticator` used by `webrtcsignal/server.go` for the agent-facing `/signal` HTTP handler) — that's expected and out of scope for the copy; Task 8 replaces that handler's role entirely with the control-socket flow, so `webrtcsignal/server.go`'s HTTP-serving parts (not its underlying WebRTC peer logic) won't be used. Note this rather than fixing it here.

- [ ] **Step 4: Self-review**

Check: did the copy pull in anything relay-specific that doesn't belong on the agent (e.g. relay's own RTSP republishing server `rtsp_server.go`, which agent doesn't need since the edge box already has its own RTSP client)? If `relay/internal/republish/rtsp_server.go` got copied, that's dead code for the agent's purposes — fine to leave uncompiled/unused for now, don't spend time deleting it in this task (deletion happens naturally in Task 8 when `answer.go` is written against only what's needed).

- [ ] **Step 5: Commit**

```bash
git add agent/webrtcsignal agent/internal/republish agent/internal/buffer
git commit -m "agent: copy relay webrtcsignal + republish/buffer packages into agent (unwired)"
```

---

### Task 8: Factor offer/answer logic out of copied `ViewerServer`

**Files:**
- Create: `agent/webrtcsignal/answer.go`
- Modify: `agent/webrtcsignal/viewer.go` (the copy, not `relay/webrtcsignal/viewer.go`)

**Interfaces:**
- Produces: `func (s *ViewerServer) HandleOffer(cameraID, viewToken string, offer webrtc.SessionDescription) (webrtc.SessionDescription, error)` — callable directly, no HTTP involved.
- Consumes: `republish.Registry` / `republish.Publisher` from Task 7's copy (unchanged).

- [ ] **Step 1: Extract the handler**

The copied `viewer.go`'s `ServeHTTP` currently does: read+decode the JSON body, call `verifyToken`, build a `webrtc.PeerConnection`, add a track sourced from `republish.Publisher`, set remote description from the offer, create+set local answer, write the JSON response. Split the middle (everything after body-decoding, before response-writing) into:

```go
// agent/webrtcsignal/answer.go
package webrtcsignal

import "github.com/pion/webrtc/v3"

func (s *ViewerServer) HandleOffer(cameraID, viewToken string, offer webrtc.SessionDescription) (webrtc.SessionDescription, error) {
	if !s.verifyToken(cameraID, viewToken) {
		return webrtc.SessionDescription{}, ErrInvalidToken
	}
	pub, ok := s.registry.Get(cameraID)
	if !ok {
		return webrtc.SessionDescription{}, ErrCameraNotFound
	}
	pc, err := webrtc.NewPeerConnection(webrtc.Configuration{})
	if err != nil {
		return webrtc.SessionDescription{}, err
	}
	track, err := webrtc.NewTrackLocalStaticSample(webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeH264}, "video", "pion")
	if err != nil {
		return webrtc.SessionDescription{}, err
	}
	if _, err := pc.AddTrack(track); err != nil {
		return webrtc.SessionDescription{}, err
	}
	go viewerPump(pc, track, pub)
	if err := pc.SetRemoteDescription(offer); err != nil {
		return webrtc.SessionDescription{}, err
	}
	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		return webrtc.SessionDescription{}, err
	}
	if err := pc.SetLocalDescription(answer); err != nil {
		return webrtc.SessionDescription{}, err
	}
	return answer, nil
}
```

Add `ErrInvalidToken`/`ErrCameraNotFound` as package-level `errors.New(...)` vars if not already present as some equivalent error in the copy.

- [ ] **Step 2: Rewrite `ServeHTTP` (the copy) to call `HandleOffer`**

Keep `ServeHTTP` as a thin wrapper (still used if this copy is ever exposed over HTTP for local debugging), decoding the body and calling `HandleOffer`, so there's exactly one place the peer-connection logic lives.

- [ ] **Step 3: Build**

```bash
cd /Users/vaibhaw/Developer/vision/agent && go build ./webrtcsignal/...
```
Expected: compiles clean.

- [ ] **Step 4: Self-review**

Check: does `HandleOffer` leak the `pc` (PeerConnection) on any early-return error path before `viewerPump` starts? Add `pc.Close()` in each error branch after `NewPeerConnection` succeeds, matching whatever cleanup discipline the original `ServeHTTP` used — check the original for a `defer`/close pattern and preserve it.

- [ ] **Step 5: Commit**

```bash
git add agent/webrtcsignal/answer.go agent/webrtcsignal/viewer.go
git commit -m "agent: factor WebRTC offer/answer handling out of HTTP-only ServeHTTP"
```

---

### Task 9: Agent — pipeline sidecar supervisor

**Files:**
- Create: `agent/internal/pipeline/supervisor.go`
- Modify: `agent/cmd/agent/main.go`

**Interfaces:**
- Produces: `type Supervisor struct{...}`, `func NewSupervisor(pythonPath, pipelineDir string, env []string) *Supervisor`, `func (s *Supervisor) Run(ctx context.Context) error` (blocks, restarts child on exit, respects ctx cancellation), `func (s *Supervisor) Health() Health` where `type Health struct { Status string; LastRestart time.Time }`.

- [ ] **Step 1: Implement the supervisor**

```go
// agent/internal/pipeline/supervisor.go
package pipeline

import (
	"context"
	"log"
	"os/exec"
	"sync"
	"time"
)

type Health struct {
	Status      string
	LastRestart time.Time
}

type Supervisor struct {
	pythonPath  string
	pipelineDir string
	env         []string

	mu     sync.Mutex
	health Health
}

func NewSupervisor(pythonPath, pipelineDir string, env []string) *Supervisor {
	return &Supervisor{pythonPath: pythonPath, pipelineDir: pipelineDir, env: env, health: Health{Status: "starting"}}
}

func (s *Supervisor) Health() Health {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.health
}

func (s *Supervisor) setHealth(status string) {
	s.mu.Lock()
	s.health = Health{Status: status, LastRestart: time.Now()}
	s.mu.Unlock()
}

func (s *Supervisor) Run(ctx context.Context) error {
	backoff := time.Second
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		cmd := exec.CommandContext(ctx, s.pythonPath, "main.py")
		cmd.Dir = s.pipelineDir
		cmd.Env = s.env
		cmd.Stdout = log.Writer()
		cmd.Stderr = log.Writer()
		s.setHealth("running")
		err := cmd.Run()
		if ctx.Err() != nil {
			return ctx.Err()
		}
		s.setHealth("restarting")
		log.Printf("pipeline sidecar exited (%v), restarting in %s", err, backoff)
		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return ctx.Err()
		}
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
}
```

- [ ] **Step 2: Wire into `main.go`**

In `agent/cmd/agent/main.go`, after the existing pairing/token-load logic and before (or alongside) `supervisor.Run(ctx)` (the existing `Supervisor` for camera transports — note the name collision, see self-review below), add:

```go
pipelineEnv := append(os.Environ(),
	"NIGHTWATCH_DEVICE_TOKEN="+tok.DeviceToken,
	"NIGHTWATCH_BACKEND_URL="+cfg.BackendURL,
)
pipelineSup := pipeline.NewSupervisor(
	filepath.Join(cfg.PipelineDir, ".venv", "bin", "python3"),
	cfg.PipelineDir,
	pipelineEnv,
)
go func() {
	if err := pipelineSup.Run(ctx); err != nil && ctx.Err() == nil {
		log.Printf("pipeline supervisor stopped: %v", err)
	}
}()
```

Add `PipelineDir string` (default e.g. `/opt/nightwatch/agent/pipeline`, env `AGENT_PIPELINE_DIR`) to the agent's existing config struct, following the same pattern as `StateDir`/`AGENT_STATE_DIR`.

- [ ] **Step 3: Build**

```bash
cd /Users/vaibhaw/Developer/vision/agent && go build ./...
```

- [ ] **Step 4: Self-review**

Check the naming collision flagged above: `agent/internal/supervisor.Supervisor` (existing, camera-transport orchestration) vs. the new `agent/internal/pipeline.Supervisor` — different packages so no compile collision, but confirm `main.go`'s local variable names (`pipelineSup` vs whatever the existing transport supervisor variable is called) don't shadow each other or read confusingly at the call site. Check: does `cmd.Env = s.env` fully replace the environment (losing `PATH` etc.) or does it need to start from `os.Environ()`? The wiring above uses `append(os.Environ(), ...)` — correct; a bare `s.env` without that base would break the Python venv's ability to find system libraries.

- [ ] **Step 5: Commit**

```bash
git add agent/internal/pipeline agent/cmd/agent/main.go
git commit -m "agent: supervise pipeline sidecar as a restarting child process"
```

---

### Task 10: Agent — control WebSocket client (signaling)

**Files:**
- Create: `agent/internal/control/client.go`
- Modify: `agent/cmd/agent/main.go`

**Interfaces:**
- Consumes: `agent/webrtcsignal.ViewerServer.HandleOffer` (Task 8), `agent/internal/republish.Registry` (Task 7 copy) — the registry needs a `Publisher` registered for each open camera; wiring the edge box's own RTSP frames into it is a **follow-up task not covered by this plan** (flagged in Open Questions below — today's `agent/internal/rtsp/client.go` frames need a new sink added, out of scope for this control-channel task).
- Produces: `func NewClient(backendURL, deviceToken string, viewer *webrtcsignal.ViewerServer) *Client`, `func (c *Client) Run(ctx context.Context) error` (connects, reconnects with backoff, dispatches `signal_offer` messages to `viewer.HandleOffer`, replies `signal_answer`).

- [ ] **Step 1: Implement the client**

```go
// agent/internal/control/client.go
package control

import (
	"context"
	"encoding/json"
	"log"
	"net/url"
	"time"

	"github.com/gorilla/websocket"
	"github.com/pion/webrtc/v3"

	"nightwatch/agent/webrtcsignal"
)

type Client struct {
	backendURL  string
	deviceToken string
	viewer      *webrtcsignal.ViewerServer
}

func NewClient(backendURL, deviceToken string, viewer *webrtcsignal.ViewerServer) *Client {
	return &Client{backendURL: backendURL, deviceToken: deviceToken, viewer: viewer}
}

func (c *Client) Run(ctx context.Context) error {
	backoff := time.Second
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err := c.runOnce(ctx); err != nil {
			log.Printf("control channel disconnected: %v, retrying in %s", err, backoff)
		}
		select {
		case <-time.After(backoff):
		case <-ctx.Done():
			return ctx.Err()
		}
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
}

func (c *Client) runOnce(ctx context.Context) error {
	u, err := url.Parse(c.backendURL)
	if err != nil {
		return err
	}
	u.Scheme = "wss"
	if u.Scheme == "http" {
		u.Scheme = "ws"
	}
	u.Path = "/api/agents/me/control"
	q := u.Query()
	q.Set("token", c.deviceToken)
	u.RawQuery = q.Encode()

	conn, _, err := websocket.DefaultDialer.DialContext(ctx, u.String(), nil)
	if err != nil {
		return err
	}
	defer conn.Close()

	for {
		var msg map[string]any
		if err := conn.ReadJSON(&msg); err != nil {
			return err
		}
		if msg["type"] != "signal_offer" {
			continue
		}
		go c.handleOffer(conn, msg)
	}
}

func (c *Client) handleOffer(conn *websocket.Conn, msg map[string]any) {
	cameraID, _ := msg["camera_id"].(string)
	viewToken, _ := msg["view_token"].(string)
	requestID, _ := msg["request_id"].(string)
	offerRaw, _ := json.Marshal(msg["offer"])
	var offer webrtc.SessionDescription
	if err := json.Unmarshal(offerRaw, &offer); err != nil {
		log.Printf("bad offer payload: %v", err)
		return
	}
	answer, err := c.viewer.HandleOffer(cameraID, viewToken, offer)
	if err != nil {
		log.Printf("HandleOffer failed: %v", err)
		return
	}
	conn.WriteJSON(map[string]any{
		"type":       "signal_answer",
		"request_id": requestID,
		"answer":     answer,
	})
}
```

(`github.com/gorilla/websocket` — check `agent/go.mod` for whether this or another WS library is already a dependency, e.g. `nhooyr.io/websocket`; use whichever is already vendored rather than adding a new one.)

- [ ] **Step 2: Wire into `main.go`**

```go
viewer := webrtcsignal.NewViewerServer(cfg.StreamTokenSecret, registry)
controlClient := control.NewClient(cfg.BackendURL, tok.DeviceToken, viewer)
go func() {
	if err := controlClient.Run(ctx); err != nil && ctx.Err() == nil {
		log.Printf("control client stopped: %v", err)
	}
}()
```

`cfg.StreamTokenSecret` must match Backend's `settings.stream_token_secret` (same shared-secret convention already used for `sign_stream_token`/`verify_token` elsewhere in this codebase) — add it to the agent's config struct if not already present, sourced the same way as other shared secrets in `agent/`.

- [ ] **Step 3: Build**

```bash
cd /Users/vaibhaw/Developer/vision/agent && go build ./...
```

- [ ] **Step 4: Self-review**

Check: does `handleOffer` run concurrently (`go c.handleOffer(...)`) safely against `conn.WriteJSON` from multiple goroutines if two offers arrive close together? `gorilla/websocket` connections are not safe for concurrent writes from multiple goroutines — add a `sync.Mutex` around `conn.WriteJSON` calls (one per connection, held for the duration of each write) before this task is considered done, since concurrent view requests are a realistic scenario (two dashboard tabs open).

- [ ] **Step 5: Commit**

```bash
git add agent/internal/control agent/cmd/agent/main.go
git commit -m "agent: add control WebSocket client answering WebRTC signaling requests"
```

---

### Task 11: `agent/pipeline` — auth swap (device-token Bearer)

**Files:**
- Modify: `agent/pipeline/api_client.py` (the copy, not `worker/api_client.py`)
- Modify: `agent/pipeline/config.py` (the copy)

- [ ] **Step 1: Add the new config field**

```python
# agent/pipeline/config.py — add alongside existing worker_api_key field
device_token: str = ""  # read from NIGHTWATCH_DEVICE_TOKEN, set by the Go supervisor's child-process env
```

- [ ] **Step 2: Swap the auth header**

Current `ApiClient.__init__` sets `self.headers = {"X-Worker-Key": config.worker_api_key, ...}`. Change to prefer the device token when present:

```python
# agent/pipeline/api_client.py
auth_header = (
    {"Authorization": f"Bearer {config.device_token}"}
    if config.device_token
    else {"X-Worker-Key": config.worker_api_key}
)
self.headers = {**auth_header, "Content-Type": "application/json"}
```

This keeps `agent/pipeline/` able to run in either mode (device-token OR worker-key), which matters if someone ever runs this copy standalone for local testing without a spawning Go agent present.

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/agent/pipeline
NIGHTWATCH_DEVICE_TOKEN=test-token .venv/bin/python3 -c "
from config import config
from api_client import ApiClient
c = ApiClient()
assert c.headers.get('Authorization') == 'Bearer test-token'
print('ok')
"
```
Expected: prints `ok`.

- [ ] **Step 4: Self-review**

Check: does this break `worker/api_client.py` (the untouched original)? No — only the copy was edited. Check: is there a risk of both `device_token` and `worker_api_key` being set simultaneously and the wrong one winning? The `if config.device_token` check prioritizes device-token unconditionally, which is correct for the edge-box path (device-token should always win when present) — no ambiguity.

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline/api_client.py agent/pipeline/config.py
git commit -m "agent/pipeline: prefer device-token Bearer auth over shared worker key"
```

---

### Task 12: `agent/pipeline` — signed-upload-URL GCS flow

**Files:**
- Modify: `agent/pipeline/gcs_uploader.py` (the copy)
- Modify: `agent/pipeline/config.py` (the copy)

**Interfaces:**
- Consumes: Task 3's `POST /api/edge/upload-url` (via the existing `ApiClient`'s httpx client, or a new small httpx call — reuse `ApiClient`'s `self.client`/`self.headers` rather than building a second HTTP client).

- [ ] **Step 1: Rewrite `upload()`**

Current `GCSUploader.upload` does a direct ADC-authenticated `blob.upload_from_string`. Replace with: request a signed PUT URL from Backend, then PUT the bytes there.

```python
# agent/pipeline/gcs_uploader.py
import httpx

class GCSUploader:
    def __init__(self, api_client: "ApiClient"):
        self.api_client = api_client  # reuse existing device-token-authenticated client

    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        resp = await self.api_client.client.post(
            "/api/edge/upload-url",
            json={"path": path, "content_type": content_type},
        )
        resp.raise_for_status()
        body = resp.json()
        async with httpx.AsyncClient() as put_client:
            put_resp = await put_client.put(
                body["upload_url"], content=data, headers={"Content-Type": content_type}
            )
            put_resp.raise_for_status()
        return body["gs_uri"]
```

This changes `GCSUploader.__init__`'s signature (now takes `api_client` instead of constructing its own `storage.Client`) — find every call site in `agent/pipeline/` that constructs `GCSUploader()` (should be `event_packager.py`, per the earlier facts: `EventPackager.__init__(self, gcs: GCSUploader, api: ApiClient)`) and update the construction site (likely in `supervisor.py` or `main.py`) to pass the already-constructed `ApiClient` in.

- [ ] **Step 2: Update the construction site**

Find where `GCSUploader()` and `ApiClient()` are both constructed (likely `agent/pipeline/supervisor.py` per the `WorkerSupervisor` class named in the facts) and change:
```python
api_client = ApiClient()
gcs = GCSUploader(api_client)  # was: GCSUploader()
```

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/agent/pipeline
.venv/bin/python3 -c "import supervisor"
```
Expected: imports cleanly (catches any missed call sites as an `ImportError`/`TypeError` at import or construction time — if `WorkerSupervisor.__init__` eagerly constructs `GCSUploader`, this import alone may not trigger the error; if not, run `main.py`'s startup path far enough to construct it, or grep for all `GCSUploader(` call sites and confirm each was updated).

- [ ] **Step 4: Self-review**

Check: does the new `upload()` still return the same `"gs://{bucket}/{path}"`-shaped string the rest of the pipeline expects (used to build `snapshot_url`/`clip_url` in `CreateEventRequest`)? Yes — `gs_uri` from the backend response is built exactly that way in Task 3. Check: is there duplicate httpx client construction (one in `ApiClient`, a throwaway one in `upload()` for the PUT)? Acceptable — the PUT goes to a GCS-signed URL, not Backend, so it intentionally doesn't reuse `ApiClient`'s Backend-scoped headers/base_url; a fresh unauthenticated client is correct there since the signature in the URL is the auth.

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline/gcs_uploader.py agent/pipeline/supervisor.py
git commit -m "agent/pipeline: upload via backend-issued signed URLs instead of direct ADC"
```

---

### Task 13: `agent/pipeline` — Gemini broker-token flow

**Files:**
- Modify: `agent/pipeline/gemini_client.py` (the copy)

**Interfaces:**
- Consumes: Task 4's `POST /api/edge/gemini-token`.

- [ ] **Step 1: Add token fetch + refresh**

```python
# agent/pipeline/gemini_client.py
import time

class GeminiClient:
    def __init__(self, api_client: "ApiClient"):
        self.api_client = api_client
        self._token: str | None = None
        self._token_expires_at: float = 0
        self._build_client()  # existing method, called again after refresh in _ensure_token

    async def _ensure_token(self):
        if self._token and time.time() < self._token_expires_at - 60:
            return
        resp = await self.api_client.client.post("/api/edge/gemini-token")
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires_at = time.time() + 1700  # slightly under the 1800s broker TTL
        self._vertex_project = body["vertex_project"]
        self._vertex_location = body["vertex_location"]
        self._build_client()  # rebuild the Vertex client using the fresh token

    async def analyze_frame(self, frame_jpeg: bytes, camera_config) -> list:
        await self._ensure_token()
        # ... existing body, unchanged
```

`_build_client()` (existing method, per the facts: "tries Vertex AI (ADC) first, falls back to Gemini API key") needs its Vertex branch changed to construct credentials from `self._token` (an `google.oauth2.credentials.Credentials(token=self._token)`) instead of calling `google.auth.default()` — this is the one real logic change in this file, everything else (`_is_auth_error`, `_try_api_key_fallback`, `_parse_response`, `_record_failure`) stays as-is.

- [ ] **Step 2: Update the construction site**

Same pattern as Task 12 — find where `GeminiClient()` is constructed (likely alongside `ApiClient()`/`GCSUploader()` in `supervisor.py`) and pass the shared `api_client` in: `gemini = GeminiClient(api_client)`.

- [ ] **Step 3: Verify**

```bash
cd /Users/vaibhaw/Developer/vision/agent/pipeline
.venv/bin/python3 -c "import supervisor"
```
Expected: imports cleanly.

- [ ] **Step 4: Self-review**

Check: does `_ensure_token`'s 60-second refresh buffer leave enough margin given Gemini calls can take several seconds? Yes — refreshing a minute before expiry against a 30-minute TTL is generous. Check: what happens if `_ensure_token`'s POST fails (broker/Backend unreachable)? It should propagate the exception up through `analyze_frame` so the pipeline's existing retry/circuit-breaker logic (mentioned in the facts: "circuit breaker, structured JSON parsing, confidence filtering") handles it the same way it already handles a Gemini API failure — confirm this by tracing the existing exception-handling path in `analyze_frame`'s caller, don't add a second, different error-handling path here.

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline/gemini_client.py agent/pipeline/supervisor.py
git commit -m "agent/pipeline: fetch Gemini/Vertex credentials from backend token broker"
```

---

### Task 14: coturn deployment config

**Files:**
- Create: `deploy/coturn/turnserver.conf`
- Create: `deploy/coturn/nightwatch-coturn.service`
- Create: `deploy/coturn/README.md`

- [ ] **Step 1: Write the coturn config**

```ini
# deploy/coturn/turnserver.conf
listening-port=3478
tls-listening-port=5349
fingerprint
lt-cred-mech
realm=turn.yourdomain.com
use-auth-secret
static-auth-secret=CHANGE_ME_SHARED_WITH_BACKEND
total-quota=100
stale-nonce=600
cert=/etc/coturn/cert.pem
pkey=/etc/coturn/key.pem
no-stdout-log
log-file=/var/log/coturn.log
```

`static-auth-secret` uses coturn's time-limited REST API credential mechanism — Backend mints short-lived TURN username/password pairs derived from this shared secret when issuing ICE server config to the frontend/agent, the same way it already mints signed stream tokens. (Wiring that into the frontend's ICE server config is a follow-up task — see Open Questions.)

- [ ] **Step 2: Write the systemd unit**

```ini
# deploy/coturn/nightwatch-coturn.service
[Unit]
Description=Nightwatch coturn TURN server
After=network.target

[Service]
ExecStart=/usr/bin/turnserver -c /etc/coturn/turnserver.conf
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write the README**

```markdown
# coturn deployment

Fallback-only TURN relay for live view when direct WebRTC P2P between
browser and edge box fails (symmetric NAT/CGNAT).

## Setup
1. `apt install coturn` on a small public-IP VM.
2. Copy `turnserver.conf` to `/etc/coturn/`, replace `static-auth-secret`
   and `realm`, provision a TLS cert (e.g. via certbot) at the paths
   referenced in the config.
3. Copy `nightwatch-coturn.service` to `/etc/systemd/system/`,
   `systemctl enable --now nightwatch-coturn`.
4. Set `TURN_SHARED_SECRET` (same value as `static-auth-secret`) and
   `TURN_URL` in Backend's environment so it can mint short-lived
   credentials for ICE server config.
```

- [ ] **Step 4: Self-review**

Check: is `static-auth-secret` ever referenced in code anywhere else in this plan? Not yet — the frontend/agent ICE-server-config wiring that actually uses it is out of scope for this plan (flagged in Open Questions). This task only stands up the server; wiring TURN credentials into the WebRTC negotiation itself is separate follow-up work.

- [ ] **Step 5: Commit**

```bash
git add deploy/coturn
git commit -m "deploy: add coturn TURN server config for edge-box live-view fallback"
```

---

## Open Questions / Follow-up (not covered by this plan)

- **Wiring the edge box's RTSP frames into `agent/webrtcsignal`'s `republish.Registry`.** Today `agent/internal/rtsp/client.go` feeds frames into the gRPC/WebRTC *transport* layer (`agent/internal/transport`) bound for a remote relay. The embedded webrtcsignal path (Task 10) needs those same frames pushed in-process into a local `Publisher` instead. This is a real, non-trivial task — touches `agent/internal/rtsp/client.go` and `agent/internal/supervisor/supervisor.go` — deliberately left out of this plan's scope; do it as an immediate next plan once Tasks 1–14 are reviewed, since it's the one piece that makes live view actually show video end-to-end.
- **ICE server (STUN/TURN) config delivery to the frontend's `RTCPeerConnection`.** Task 14 stands up coturn; nothing in this plan yet issues short-lived TURN credentials to the browser or configures the frontend's `WebRTCPlayer` component with `iceServers`. Follow-up task.
- **Agent's own device-token refresh/expiry.** This plan assumes `tok.DeviceToken` (loaded once at startup from `state/token.json`) stays valid indefinitely, matching today's behavior — if device tokens ever get a TTL, the control client and pipeline env need a refresh mechanism, out of scope here.
- **Existing paired devices in the field** need a software update to pick up any of this — no OTA mechanism exists yet per earlier discussion; deployment/rollout of these binary changes to already-installed devices is an ops task, not a code task, and isn't covered here.
