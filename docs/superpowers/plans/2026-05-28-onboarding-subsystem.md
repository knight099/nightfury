# Onboarding & Pairing Subsystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a non-technical home user install the LAN agent, pair it with their Nightwatch org via a 6-digit code, discover NVR cameras (ONVIF auto-discover + manual brand-picker fallback), and bring those cameras online — replacing the dev-only `X-Agent-Key` auth from the tunnel plan with proper device tokens bound to the agent's pubkey.

**Architecture:** Backend gains two new tables (`agents`, `agent_pair_codes`) and four new endpoints (mint code, redeem code, list agents, register cameras). Relay's auth middleware swaps from static header to device-token lookup. Agent gains a local web UI on `:8765` for code entry + ONVIF discovery + manual RTSP entry. Frontend gains a 4-step `/onboard` wizard.

**Tech Stack:** Backend (FastAPI + SQLAlchemy 2.0 async + Argon2id for token hashing), Relay (Go, shares Postgres read), Agent (Go + go-onvif + embedded HTML for local UI), Frontend (Next.js 14 + shadcn/ui + Zustand).

**Prereqs:** [tunnel-subsystem](./2026-05-28-tunnel-subsystem.md) plan must be merged first — this plan replaces its static auth.

---

## File Structure

```
backend/app/
├── models/
│   ├── agent.py                   # NEW: Agent ORM model
│   └── agent_pair_code.py         # NEW: AgentPairCode ORM model
├── schemas/
│   └── agent.py                   # NEW: Pydantic request/response
├── services/
│   ├── pairing_service.py         # NEW: mint/redeem/expire codes
│   └── device_token_service.py    # NEW: mint, hash, verify
├── api/
│   └── agents.py                  # NEW: 4 endpoints
└── core/
    └── deps.py                    # MODIFY: add get_agent_from_token

relay/internal/
└── auth/
    └── device_token.go            # NEW: replaces static X-Agent-Key

agent/
├── cmd/agent/main.go              # MODIFY: load device_token from disk
└── internal/
    ├── localui/                   # NEW: local web UI on :8765
    │   ├── server.go
    │   ├── handlers.go
    │   └── static/index.html
    ├── pairing/
    │   └── client.go              # NEW: POST /api/agents/pair
    ├── onvif/
    │   └── discover.go            # NEW: WS-Discovery on UDP 3702
    └── store/
        └── token.go               # NEW: persist device_token to disk

frontend/app/
├── onboard/
│   ├── page.tsx                   # NEW: wizard shell
│   ├── steps/
│   │   ├── install.tsx            # NEW: docker run / image download
│   │   ├── pair.tsx               # NEW: 6-digit code display
│   │   ├── discover.tsx           # NEW: ONVIF results + manual fallback
│   │   └── test.tsx               # NEW: stream confirmation
│   └── lib/
│       └── brands.ts              # NEW: RTSP URL templates per brand
```

---

## Task 1: DB model — `agents` table

**Files:**
- Create: `backend/app/models/agent.py`
- Test: `backend/tests/models/test_agent_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/models/test_agent_model.py
import pytest
from sqlalchemy import select
from app.models.agent import Agent

@pytest.mark.asyncio
async def test_create_agent(db_session, sample_org):
    agent = Agent(
        org_id=sample_org.id,
        machine_id="abc123",
        pubkey="ed25519-pub",
        device_token_hash="$argon2id$...",
        version="0.1.0",
        status="unpaired",
    )
    db_session.add(agent)
    await db_session.flush()
    result = await db_session.execute(select(Agent).where(Agent.id == agent.id))
    fetched = result.scalar_one()
    assert fetched.machine_id == "abc123"
    assert fetched.status == "unpaired"

@pytest.mark.asyncio
async def test_unique_org_machine(db_session, sample_org):
    db_session.add(Agent(org_id=sample_org.id, machine_id="dup", pubkey="k", device_token_hash="h", status="online"))
    await db_session.flush()
    db_session.add(Agent(org_id=sample_org.id, machine_id="dup", pubkey="k2", device_token_hash="h2", status="online"))
    with pytest.raises(Exception):
        await db_session.flush()
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `pytest backend/tests/models/test_agent_model.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models.agent`

- [ ] **Step 3: Implement model**

```python
# backend/app/models/agent.py
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("org_id", "machine_id", name="uq_agent_org_machine"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    machine_id: Mapped[str] = mapped_column(String(128), nullable=False)
    pubkey: Mapped[str] = mapped_column(String(512), nullable=False)
    device_token_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unpaired")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
```

- [ ] **Step 4: Register model in `app/models/__init__.py`**

```python
from app.models.agent import Agent  # noqa
```

- [ ] **Step 5: Run tests**

Run: `pytest backend/tests/models/test_agent_model.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/agent.py backend/app/models/__init__.py backend/tests/models/test_agent_model.py
git commit -m "feat(backend): add Agent ORM model"
```

---

## Task 2: DB model — `agent_pair_codes` table

**Files:**
- Create: `backend/app/models/agent_pair_code.py`
- Test: `backend/tests/models/test_pair_code_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/models/test_pair_code_model.py
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.models.agent_pair_code import AgentPairCode

@pytest.mark.asyncio
async def test_create_code(db_session, sample_org, sample_user):
    code = AgentPairCode(
        code="123456",
        org_id=sample_org.id,
        created_by=sample_user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db_session.add(code)
    await db_session.flush()
    result = await db_session.execute(select(AgentPairCode).where(AgentPairCode.code == "123456"))
    assert result.scalar_one().org_id == sample_org.id
```

- [ ] **Step 2: Run test — expect failure**

Run: `pytest backend/tests/models/test_pair_code_model.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement model**

```python
# backend/app/models/agent_pair_code.py
import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class AgentPairCode(Base):
    __tablename__ = "agent_pair_codes"

    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
```

- [ ] **Step 4: Register + run + commit**

```bash
# add to app/models/__init__.py
# from app.models.agent_pair_code import AgentPairCode

pytest backend/tests/models/test_pair_code_model.py -v
git add backend/app/models/agent_pair_code.py backend/app/models/__init__.py backend/tests/models/test_pair_code_model.py
git commit -m "feat(backend): add AgentPairCode ORM model"
```

---

## Task 3: `cameras.agent_id` column + `organizations.timezone/whatsapp_number`

**Files:**
- Modify: `backend/app/models/camera.py`
- Modify: `backend/app/models/organization.py`
- Test: `backend/tests/models/test_camera_agent_link.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/models/test_camera_agent_link.py
import pytest
from app.models.camera import Camera
from app.models.agent import Agent

@pytest.mark.asyncio
async def test_camera_links_to_agent(db_session, sample_org):
    agent = Agent(org_id=sample_org.id, machine_id="m1", pubkey="p", device_token_hash="h", status="online")
    db_session.add(agent)
    await db_session.flush()
    cam = Camera(org_id=sample_org.id, name="cam1", rtsp_url="rtsp://x", agent_id=agent.id)
    db_session.add(cam)
    await db_session.flush()
    assert cam.agent_id == agent.id
```

- [ ] **Step 2: Run — expect AttributeError on `agent_id`**

- [ ] **Step 3: Modify `camera.py`**

Add to `Camera` model:
```python
agent_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
)
```

- [ ] **Step 4: Modify `organization.py`**

Add:
```python
timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
whatsapp_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

- [ ] **Step 5: Run + commit**

```bash
pytest backend/tests/models/test_camera_agent_link.py -v
git add backend/app/models/camera.py backend/app/models/organization.py backend/tests/models/test_camera_agent_link.py
git commit -m "feat(backend): link cameras to agents, add org timezone/whatsapp"
```

---

## Task 4: Pairing service — mint code

**Files:**
- Create: `backend/app/services/pairing_service.py`
- Test: `backend/tests/services/test_pairing_service.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/services/test_pairing_service.py
from datetime import datetime, timezone
import pytest
from app.services.pairing_service import PairingService

@pytest.mark.asyncio
async def test_mint_returns_six_digits(db_session, sample_org, sample_user):
    svc = PairingService(db_session)
    code = await svc.mint_code(org_id=sample_org.id, user_id=sample_user.id)
    assert len(code) == 6
    assert code.isdigit()

@pytest.mark.asyncio
async def test_mint_persists_with_10min_ttl(db_session, sample_org, sample_user):
    svc = PairingService(db_session)
    code = await svc.mint_code(org_id=sample_org.id, user_id=sample_user.id)
    row = await svc.get_code(code)
    delta = (row.expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 590 < delta < 610
```

- [ ] **Step 2: Run — expect ImportError**

- [ ] **Step 3: Implement service**

```python
# backend/app/services/pairing_service.py
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent_pair_code import AgentPairCode

PAIR_CODE_TTL_SECONDS = 600


class PairingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def mint_code(self, org_id: UUID, user_id: UUID) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        row = AgentPairCode(
            code=code,
            org_id=org_id,
            created_by=user_id,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=PAIR_CODE_TTL_SECONDS),
        )
        self.db.add(row)
        await self.db.flush()
        return code

    async def get_code(self, code: str) -> AgentPairCode | None:
        result = await self.db.execute(select(AgentPairCode).where(AgentPairCode.code == code))
        return result.scalar_one_or_none()
```

- [ ] **Step 4: Run + commit**

```bash
pytest backend/tests/services/test_pairing_service.py -v
git add backend/app/services/pairing_service.py backend/tests/services/test_pairing_service.py
git commit -m "feat(backend): pairing service mint_code"
```

---

## Task 5: Pairing service — redeem code

**Files:**
- Modify: `backend/app/services/pairing_service.py`
- Modify: `backend/tests/services/test_pairing_service.py`

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
async def test_redeem_valid_code(db_session, sample_org, sample_user):
    svc = PairingService(db_session)
    code = await svc.mint_code(sample_org.id, sample_user.id)
    org_id = await svc.redeem_code(code)
    assert org_id == sample_org.id

@pytest.mark.asyncio
async def test_redeem_expired_raises(db_session, sample_org, sample_user):
    from app.models.agent_pair_code import AgentPairCode
    from datetime import datetime, timedelta, timezone
    row = AgentPairCode(code="000000", org_id=sample_org.id, created_by=sample_user.id,
                        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    db_session.add(row)
    await db_session.flush()
    svc = PairingService(db_session)
    with pytest.raises(ValueError, match="expired"):
        await svc.redeem_code("000000")

@pytest.mark.asyncio
async def test_redeem_consumed_raises(db_session, sample_org, sample_user):
    svc = PairingService(db_session)
    code = await svc.mint_code(sample_org.id, sample_user.id)
    await svc.redeem_code(code)
    with pytest.raises(ValueError, match="consumed"):
        await svc.redeem_code(code)

@pytest.mark.asyncio
async def test_redeem_unknown_raises(db_session):
    svc = PairingService(db_session)
    with pytest.raises(ValueError, match="not found"):
        await svc.redeem_code("999999")
```

- [ ] **Step 2: Run — 4 fail**

- [ ] **Step 3: Add to PairingService**

```python
async def redeem_code(self, code: str) -> UUID:
    row = await self.get_code(code)
    if row is None:
        raise ValueError("not found")
    if row.consumed_at is not None:
        raise ValueError("consumed")
    if row.expires_at < datetime.now(timezone.utc):
        raise ValueError("expired")
    row.consumed_at = datetime.now(timezone.utc)
    await self.db.flush()
    return row.org_id
```

- [ ] **Step 4: Run + commit**

```bash
pytest backend/tests/services/test_pairing_service.py -v
git add backend/app/services/pairing_service.py backend/tests/services/test_pairing_service.py
git commit -m "feat(backend): pairing service redeem_code"
```

---

## Task 6: Device token service — mint + verify

**Files:**
- Create: `backend/app/services/device_token_service.py`
- Test: `backend/tests/services/test_device_token_service.py`

- [ ] **Step 1: Failing tests**

```python
# backend/tests/services/test_device_token_service.py
import pytest
from app.services.device_token_service import DeviceTokenService

def test_mint_returns_64char_token():
    svc = DeviceTokenService()
    token, hashed = svc.mint()
    assert len(token) >= 32
    assert hashed.startswith("$argon2")
    assert hashed != token

def test_verify_correct_token():
    svc = DeviceTokenService()
    token, hashed = svc.mint()
    assert svc.verify(token, hashed) is True

def test_verify_wrong_token():
    svc = DeviceTokenService()
    _, hashed = svc.mint()
    assert svc.verify("wrong-token-123", hashed) is False
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# backend/app/services/device_token_service.py
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


class DeviceTokenService:
    def __init__(self):
        self._ph = PasswordHasher()

    def mint(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(48)
        return token, self._ph.hash(token)

    def verify(self, token: str, token_hash: str) -> bool:
        try:
            return self._ph.verify(token_hash, token)
        except VerifyMismatchError:
            return False
```

- [ ] **Step 4: Run + commit**

```bash
pytest backend/tests/services/test_device_token_service.py -v
git add backend/app/services/device_token_service.py backend/tests/services/test_device_token_service.py
git commit -m "feat(backend): device token mint/verify with argon2id"
```

---

## Task 7: Pydantic schemas for agent endpoints

**Files:**
- Create: `backend/app/schemas/agent.py`

- [ ] **Step 1: Write schemas**

```python
# backend/app/schemas/agent.py
import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class PairCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class PairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    machine_id: str = Field(min_length=8, max_length=128)
    pubkey: str = Field(min_length=16, max_length=512)
    version: str | None = None


class PairResponse(BaseModel):
    device_token: str
    relay_url: str
    org_id: uuid.UUID
    agent_id: uuid.UUID


class AgentSummary(BaseModel):
    id: uuid.UUID
    machine_id: str
    version: str | None
    transport: str | None
    status: str
    last_seen_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class AgentListResponse(BaseModel):
    agents: list[AgentSummary]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/agent.py
git commit -m "feat(backend): pydantic schemas for agent endpoints"
```

---

## Task 8: API — `POST /api/agents/pair-codes`

**Files:**
- Create: `backend/app/api/agents.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/api/test_agents_pair_codes.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/api/test_agents_pair_codes.py
import pytest

@pytest.mark.asyncio
async def test_mint_pair_code_authed(client, auth_headers):
    r = await client.post("/api/agents/pair-codes", headers=auth_headers)
    assert r.status_code == 201
    body = r.json()
    assert len(body["code"]) == 6
    assert body["code"].isdigit()

@pytest.mark.asyncio
async def test_mint_pair_code_unauthed(client):
    r = await client.post("/api/agents/pair-codes")
    assert r.status_code == 401
```

- [ ] **Step 2: Run — fail (404)**

- [ ] **Step 3: Implement router**

```python
# backend/app/api/agents.py
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.agent import PairCodeResponse
from app.services.pairing_service import PairingService

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("/pair-codes", response_model=PairCodeResponse, status_code=status.HTTP_201_CREATED)
async def create_pair_code(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.org_id is None:
        from fastapi import HTTPException
        raise HTTPException(400, "super_admin must select an org first")
    svc = PairingService(db)
    code = await svc.mint_code(org_id=user.org_id, user_id=user.id)
    row = await svc.get_code(code)
    return PairCodeResponse(code=code, expires_at=row.expires_at)
```

- [ ] **Step 4: Register router in `main.py`**

```python
from app.api import agents as agents_router
app.include_router(agents_router.router)
```

- [ ] **Step 5: Run + commit**

```bash
pytest backend/tests/api/test_agents_pair_codes.py -v
git add backend/app/api/agents.py backend/app/main.py backend/tests/api/test_agents_pair_codes.py
git commit -m "feat(backend): POST /api/agents/pair-codes"
```

---

## Task 9: API — `POST /api/agents/pair`

**Files:**
- Modify: `backend/app/api/agents.py`
- Test: `backend/tests/api/test_agents_pair.py`

- [ ] **Step 1: Failing tests**

```python
# backend/tests/api/test_agents_pair.py
import pytest

@pytest.mark.asyncio
async def test_pair_with_valid_code(client, auth_headers, settings):
    code_r = await client.post("/api/agents/pair-codes", headers=auth_headers)
    code = code_r.json()["code"]
    r = await client.post("/api/agents/pair", json={
        "code": code, "machine_id": "machine-abc-123", "pubkey": "ed25519-pubkey-here", "version": "0.1.0",
    })
    assert r.status_code == 200
    body = r.json()
    assert "device_token" in body
    assert body["relay_url"].startswith("grpcs://") or body["relay_url"].startswith("https://")

@pytest.mark.asyncio
async def test_pair_unknown_code(client):
    r = await client.post("/api/agents/pair", json={
        "code": "999999", "machine_id": "m", "pubkey": "p" * 16,
    })
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_pair_consumed_code(client, auth_headers):
    code = (await client.post("/api/agents/pair-codes", headers=auth_headers)).json()["code"]
    body = {"code": code, "machine_id": "m1234567", "pubkey": "p" * 16}
    assert (await client.post("/api/agents/pair", json=body)).status_code == 200
    body2 = {"code": code, "machine_id": "m12345678", "pubkey": "p" * 16}
    assert (await client.post("/api/agents/pair", json=body2)).status_code == 400
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement endpoint**

```python
# in backend/app/api/agents.py
from fastapi import HTTPException
from app.config import settings
from app.models.agent import Agent
from app.schemas.agent import PairRequest, PairResponse
from app.services.device_token_service import DeviceTokenService


@router.post("/pair", response_model=PairResponse)
async def pair_agent(req: PairRequest, db: AsyncSession = Depends(get_db)):
    pairing = PairingService(db)
    try:
        org_id = await pairing.redeem_code(req.code)
    except ValueError as e:
        raise HTTPException(400, f"pairing failed: {e}")

    token_svc = DeviceTokenService()
    token, token_hash = token_svc.mint()

    agent = Agent(
        org_id=org_id,
        machine_id=req.machine_id,
        pubkey=req.pubkey,
        device_token_hash=token_hash,
        version=req.version,
        status="online",
    )
    db.add(agent)
    await db.flush()

    return PairResponse(
        device_token=token,
        relay_url=settings.RELAY_PUBLIC_URL,
        org_id=org_id,
        agent_id=agent.id,
    )
```

- [ ] **Step 4: Add `RELAY_PUBLIC_URL` to `app/config.py`**

```python
RELAY_PUBLIC_URL: str = "grpcs://relay.nightwatch.local:443"
```

- [ ] **Step 5: Run + commit**

```bash
pytest backend/tests/api/test_agents_pair.py -v
git add backend/app/api/agents.py backend/app/config.py backend/tests/api/test_agents_pair.py
git commit -m "feat(backend): POST /api/agents/pair issues device token"
```

---

## Task 10: API — `GET /api/agents` list

**Files:**
- Modify: `backend/app/api/agents.py`
- Test: `backend/tests/api/test_agents_list.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_list_only_own_org(client, auth_headers, sample_org, db_session):
    from app.models.agent import Agent
    db_session.add(Agent(org_id=sample_org.id, machine_id="m1", pubkey="p", device_token_hash="h", status="online"))
    await db_session.commit()
    r = await client.get("/api/agents", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()["agents"]) == 1
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
from sqlalchemy import select
from app.schemas.agent import AgentListResponse, AgentSummary

@router.get("", response_model=AgentListResponse)
async def list_agents(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Agent).order_by(Agent.created_at.desc())
    if user.org_id is not None:
        stmt = stmt.where(Agent.org_id == user.org_id)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return AgentListResponse(agents=[AgentSummary.model_validate(r) for r in rows])
```

- [ ] **Step 4: Run + commit**

```bash
pytest backend/tests/api/test_agents_list.py -v
git add backend/app/api/agents.py backend/tests/api/test_agents_list.py
git commit -m "feat(backend): GET /api/agents lists per-org agents"
```

---

## Task 11: Dependency — `get_agent_from_token`

**Files:**
- Modify: `backend/app/core/deps.py`
- Test: `backend/tests/core/test_get_agent_from_token.py`

- [ ] **Step 1: Failing test**

```python
# backend/tests/core/test_get_agent_from_token.py
import pytest
from fastapi import HTTPException
from app.core.deps import get_agent_from_token

@pytest.mark.asyncio
async def test_valid_token(db_session, sample_org):
    from app.models.agent import Agent
    from app.services.device_token_service import DeviceTokenService
    svc = DeviceTokenService()
    token, h = svc.mint()
    agent = Agent(org_id=sample_org.id, machine_id="m", pubkey="p", device_token_hash=h, status="online")
    db_session.add(agent)
    await db_session.commit()
    out = await get_agent_from_token(authorization=f"Bearer {token}", db=db_session)
    assert out.id == agent.id

@pytest.mark.asyncio
async def test_missing_header(db_session):
    with pytest.raises(HTTPException) as e:
        await get_agent_from_token(authorization=None, db=db_session)
    assert e.value.status_code == 401

@pytest.mark.asyncio
async def test_bad_token(db_session):
    with pytest.raises(HTTPException) as e:
        await get_agent_from_token(authorization="Bearer not-a-real-token", db=db_session)
    assert e.value.status_code == 401
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```python
# add to backend/app/core/deps.py
from fastapi import Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent import Agent
from app.services.device_token_service import DeviceTokenService

async def get_agent_from_token(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    svc = DeviceTokenService()
    result = await db.execute(select(Agent).where(Agent.status != "unpaired"))
    for agent in result.scalars():
        if svc.verify(token, agent.device_token_hash):
            return agent
    raise HTTPException(401, "invalid device token")
```

> Note: linear scan is fine for hundreds-of-agents scale. If we ever exceed ~10k agents, switch to a token-id prefix index. Out of scope here.

- [ ] **Step 4: Run + commit**

```bash
pytest backend/tests/core/test_get_agent_from_token.py -v
git add backend/app/core/deps.py backend/tests/core/test_get_agent_from_token.py
git commit -m "feat(backend): get_agent_from_token dependency"
```

---

## Task 12: Internal endpoint for relay — `POST /internal/agents/verify-token`

> Why: relay (Go) cannot import Python deps. It calls backend to validate device tokens with one round-trip per tunnel open (then caches in-memory for 5 min).

**Files:**
- Modify: `backend/app/api/internal.py` (or create if absent — check first)
- Test: `backend/tests/api/test_internal_verify_token.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_verify_token_returns_org_id(client, db_session, sample_org, settings):
    from app.models.agent import Agent
    from app.services.device_token_service import DeviceTokenService
    svc = DeviceTokenService()
    token, h = svc.mint()
    agent = Agent(org_id=sample_org.id, machine_id="m", pubkey="p", device_token_hash=h, status="online")
    db_session.add(agent)
    await db_session.commit()
    r = await client.post(
        "/internal/agents/verify-token",
        json={"token": token},
        headers={"X-Worker-Key": settings.WORKER_API_KEY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["org_id"] == str(sample_org.id)
    assert body["agent_id"] == str(agent.id)

@pytest.mark.asyncio
async def test_verify_token_invalid(client, settings):
    r = await client.post(
        "/internal/agents/verify-token",
        json={"token": "garbage"},
        headers={"X-Worker-Key": settings.WORKER_API_KEY},
    )
    assert r.status_code == 401
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement endpoint** (uses existing `verify_worker_key` dep)

```python
# backend/app/api/internal.py
from pydantic import BaseModel

class VerifyTokenReq(BaseModel):
    token: str

class VerifyTokenResp(BaseModel):
    org_id: str
    agent_id: str

@router.post("/agents/verify-token", response_model=VerifyTokenResp)
async def verify_agent_token(
    req: VerifyTokenReq,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_worker_key),
):
    from app.models.agent import Agent
    from app.services.device_token_service import DeviceTokenService
    svc = DeviceTokenService()
    result = await db.execute(select(Agent).where(Agent.status != "unpaired"))
    for agent in result.scalars():
        if svc.verify(req.token, agent.device_token_hash):
            return VerifyTokenResp(org_id=str(agent.org_id), agent_id=str(agent.id))
    raise HTTPException(401, "invalid token")
```

- [ ] **Step 4: Run + commit**

```bash
pytest backend/tests/api/test_internal_verify_token.py -v
git add backend/app/api/internal.py backend/tests/api/test_internal_verify_token.py
git commit -m "feat(backend): internal endpoint for relay to verify device tokens"
```

---

## Task 13: Relay — replace `X-Agent-Key` with device-token auth

**Files:**
- Create: `relay/internal/auth/device_token.go`
- Modify: `relay/internal/grpc_server/server.go` (point at new auth)
- Test: `relay/internal/auth/device_token_test.go`

- [ ] **Step 1: Failing test**

```go
// relay/internal/auth/device_token_test.go
package auth

import (
    "context"
    "net/http"
    "net/http/httptest"
    "testing"
    "time"
)

func TestVerifyTokenSuccess(t *testing.T) {
    srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        w.Write([]byte(`{"org_id":"00000000-0000-0000-0000-000000000001","agent_id":"00000000-0000-0000-0000-000000000002"}`))
    }))
    defer srv.Close()
    v := NewVerifier(srv.URL, "worker-key", 5*time.Minute)
    info, err := v.Verify(context.Background(), "good-token")
    if err != nil {
        t.Fatal(err)
    }
    if info.OrgID == "" {
        t.Fatal("empty org_id")
    }
}

func TestVerifyTokenCached(t *testing.T) {
    calls := 0
    srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        calls++
        w.Write([]byte(`{"org_id":"o","agent_id":"a"}`))
    }))
    defer srv.Close()
    v := NewVerifier(srv.URL, "k", 5*time.Minute)
    v.Verify(context.Background(), "tok")
    v.Verify(context.Background(), "tok")
    if calls != 1 {
        t.Fatalf("expected 1 call, got %d", calls)
    }
}

func TestVerifyTokenRejected(t *testing.T) {
    srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(401)
    }))
    defer srv.Close()
    v := NewVerifier(srv.URL, "k", time.Minute)
    if _, err := v.Verify(context.Background(), "bad"); err == nil {
        t.Fatal("expected error")
    }
}
```

- [ ] **Step 2: Run — fail (no Verifier)**

- [ ] **Step 3: Implement**

```go
// relay/internal/auth/device_token.go
package auth

import (
    "bytes"
    "context"
    "encoding/json"
    "errors"
    "fmt"
    "net/http"
    "sync"
    "time"
)

type AgentInfo struct {
    OrgID   string `json:"org_id"`
    AgentID string `json:"agent_id"`
}

type cacheEntry struct {
    info     AgentInfo
    expireAt time.Time
}

type Verifier struct {
    backendURL string
    workerKey  string
    ttl        time.Duration
    client     *http.Client

    mu    sync.Mutex
    cache map[string]cacheEntry
}

func NewVerifier(backendURL, workerKey string, ttl time.Duration) *Verifier {
    return &Verifier{
        backendURL: backendURL,
        workerKey:  workerKey,
        ttl:        ttl,
        client:     &http.Client{Timeout: 5 * time.Second},
        cache:      map[string]cacheEntry{},
    }
}

func (v *Verifier) Verify(ctx context.Context, token string) (AgentInfo, error) {
    v.mu.Lock()
    if e, ok := v.cache[token]; ok && time.Now().Before(e.expireAt) {
        v.mu.Unlock()
        return e.info, nil
    }
    v.mu.Unlock()

    body, _ := json.Marshal(map[string]string{"token": token})
    req, _ := http.NewRequestWithContext(ctx, "POST", v.backendURL+"/internal/agents/verify-token", bytes.NewReader(body))
    req.Header.Set("Content-Type", "application/json")
    req.Header.Set("X-Worker-Key", v.workerKey)
    resp, err := v.client.Do(req)
    if err != nil {
        return AgentInfo{}, err
    }
    defer resp.Body.Close()
    if resp.StatusCode != 200 {
        return AgentInfo{}, fmt.Errorf("verify failed: %d", resp.StatusCode)
    }
    var info AgentInfo
    if err := json.NewDecoder(resp.Body).Decode(&info); err != nil {
        return AgentInfo{}, err
    }
    if info.OrgID == "" {
        return AgentInfo{}, errors.New("empty org_id")
    }
    v.mu.Lock()
    v.cache[token] = cacheEntry{info: info, expireAt: time.Now().Add(v.ttl)}
    v.mu.Unlock()
    return info, nil
}
```

- [ ] **Step 4: Wire into gRPC server**

In `relay/internal/grpc_server/server.go`, replace the static `X-Agent-Key` check inside the `Stream` RPC's first-message handling with:

```go
info, err := s.verifier.Verify(stream.Context(), authToken)
if err != nil {
    return status.Error(codes.Unauthenticated, "invalid device token")
}
// pin connection to info.OrgID and info.AgentID
```

- [ ] **Step 5: Run + commit**

```bash
cd relay && go test ./internal/auth/...
git add relay/internal/auth/device_token.go relay/internal/auth/device_token_test.go relay/internal/grpc_server/server.go
git commit -m "feat(relay): replace static key with device-token verifier"
```

---

## Task 14: Agent — persist device token to disk

**Files:**
- Create: `agent/internal/store/token.go`
- Test: `agent/internal/store/token_test.go`

- [ ] **Step 1: Failing test**

```go
// agent/internal/store/token_test.go
package store

import (
    "os"
    "path/filepath"
    "testing"
)

func TestSaveLoad(t *testing.T) {
    dir := t.TempDir()
    path := filepath.Join(dir, "token.json")
    s := New(path)
    if err := s.Save(Token{DeviceToken: "abc", RelayURL: "grpcs://r", OrgID: "o", AgentID: "a"}); err != nil {
        t.Fatal(err)
    }
    info, err := os.Stat(path)
    if err != nil {
        t.Fatal(err)
    }
    if info.Mode().Perm() != 0600 {
        t.Fatalf("expected 0600, got %v", info.Mode().Perm())
    }
    tok, err := s.Load()
    if err != nil {
        t.Fatal(err)
    }
    if tok.DeviceToken != "abc" {
        t.Fatal("wrong token")
    }
}

func TestLoadMissing(t *testing.T) {
    s := New(filepath.Join(t.TempDir(), "missing.json"))
    if _, err := s.Load(); err == nil {
        t.Fatal("expected error")
    }
}
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```go
// agent/internal/store/token.go
package store

import (
    "encoding/json"
    "errors"
    "io/fs"
    "os"
)

type Token struct {
    DeviceToken string `json:"device_token"`
    RelayURL    string `json:"relay_url"`
    OrgID       string `json:"org_id"`
    AgentID     string `json:"agent_id"`
}

type Store struct{ path string }

func New(path string) *Store { return &Store{path: path} }

func (s *Store) Save(t Token) error {
    b, err := json.Marshal(t)
    if err != nil {
        return err
    }
    return os.WriteFile(s.path, b, 0600)
}

func (s *Store) Load() (Token, error) {
    b, err := os.ReadFile(s.path)
    if err != nil {
        if errors.Is(err, fs.ErrNotExist) {
            return Token{}, errors.New("not paired yet")
        }
        return Token{}, err
    }
    var t Token
    return t, json.Unmarshal(b, &t)
}

func (s *Store) Exists() bool {
    _, err := os.Stat(s.path)
    return err == nil
}
```

- [ ] **Step 4: Run + commit**

```bash
cd agent && go test ./internal/store/...
git add agent/internal/store/
git commit -m "feat(agent): persist device token at 0600"
```

---

## Task 15: Agent — pairing client (POSTs `/api/agents/pair`)

**Files:**
- Create: `agent/internal/pairing/client.go`
- Test: `agent/internal/pairing/client_test.go`

- [ ] **Step 1: Failing test**

```go
// agent/internal/pairing/client_test.go
package pairing

import (
    "context"
    "encoding/json"
    "net/http"
    "net/http/httptest"
    "testing"
)

func TestPairSuccess(t *testing.T) {
    srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        var body map[string]string
        json.NewDecoder(r.Body).Decode(&body)
        if body["code"] != "123456" {
            t.Fatalf("got code %q", body["code"])
        }
        w.Write([]byte(`{"device_token":"t","relay_url":"grpcs://r","org_id":"o","agent_id":"a"}`))
    }))
    defer srv.Close()
    c := NewClient(srv.URL)
    out, err := c.Pair(context.Background(), Request{Code: "123456", MachineID: "m12345678", Pubkey: "pubkey1234567890", Version: "0.1.0"})
    if err != nil {
        t.Fatal(err)
    }
    if out.DeviceToken != "t" {
        t.Fatal("wrong token")
    }
}

func TestPair400(t *testing.T) {
    srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        http.Error(w, `{"detail":"pairing failed: expired"}`, 400)
    }))
    defer srv.Close()
    c := NewClient(srv.URL)
    if _, err := c.Pair(context.Background(), Request{Code: "000000", MachineID: "m12345678", Pubkey: "pubkey1234567890"}); err == nil {
        t.Fatal("expected error")
    }
}
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```go
// agent/internal/pairing/client.go
package pairing

import (
    "bytes"
    "context"
    "encoding/json"
    "fmt"
    "net/http"
    "time"
)

type Request struct {
    Code      string `json:"code"`
    MachineID string `json:"machine_id"`
    Pubkey    string `json:"pubkey"`
    Version   string `json:"version,omitempty"`
}

type Response struct {
    DeviceToken string `json:"device_token"`
    RelayURL    string `json:"relay_url"`
    OrgID       string `json:"org_id"`
    AgentID     string `json:"agent_id"`
}

type Client struct {
    backendURL string
    http       *http.Client
}

func NewClient(backendURL string) *Client {
    return &Client{backendURL: backendURL, http: &http.Client{Timeout: 10 * time.Second}}
}

func (c *Client) Pair(ctx context.Context, req Request) (Response, error) {
    body, _ := json.Marshal(req)
    httpReq, _ := http.NewRequestWithContext(ctx, "POST", c.backendURL+"/api/agents/pair", bytes.NewReader(body))
    httpReq.Header.Set("Content-Type", "application/json")
    resp, err := c.http.Do(httpReq)
    if err != nil {
        return Response{}, err
    }
    defer resp.Body.Close()
    if resp.StatusCode != 200 {
        return Response{}, fmt.Errorf("pair failed: %d", resp.StatusCode)
    }
    var out Response
    return out, json.NewDecoder(resp.Body).Decode(&out)
}
```

- [ ] **Step 4: Run + commit**

```bash
cd agent && go test ./internal/pairing/...
git add agent/internal/pairing/
git commit -m "feat(agent): pairing HTTP client"
```

---

## Task 16: Agent — ONVIF WS-Discovery

**Files:**
- Create: `agent/internal/onvif/discover.go`
- Test: `agent/internal/onvif/discover_test.go`

- [ ] **Step 1: Failing test**

> Note: WS-Discovery requires multicast UDP, hard to test fully in CI. We test parsing of an `ProbeMatch` SOAP envelope deterministically; live multicast is covered in Task 22 manual testing.

```go
// agent/internal/onvif/discover_test.go
package onvif

import (
    "strings"
    "testing"
)

const sampleProbeMatch = `<?xml version="1.0" encoding="UTF-8"?>
<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope"
              xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
              xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <env:Body><d:ProbeMatches><d:ProbeMatch>
    <wsa:EndpointReference><wsa:Address>urn:uuid:cam-1</wsa:Address></wsa:EndpointReference>
    <d:Types>dn:NetworkVideoTransmitter</d:Types>
    <d:Scopes>onvif://www.onvif.org/name/CP-PLUS</d:Scopes>
    <d:XAddrs>http://192.168.1.50:80/onvif/device_service</d:XAddrs>
  </d:ProbeMatch></d:ProbeMatches></env:Body>
</env:Envelope>`

func TestParseProbeMatch(t *testing.T) {
    devs, err := parseProbeMatches(strings.NewReader(sampleProbeMatch))
    if err != nil {
        t.Fatal(err)
    }
    if len(devs) != 1 {
        t.Fatalf("got %d devices", len(devs))
    }
    if devs[0].XAddr != "http://192.168.1.50:80/onvif/device_service" {
        t.Fatalf("wrong xaddr: %s", devs[0].XAddr)
    }
    if devs[0].Name != "CP-PLUS" {
        t.Fatalf("wrong name: %s", devs[0].Name)
    }
}
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```go
// agent/internal/onvif/discover.go
package onvif

import (
    "context"
    "encoding/xml"
    "io"
    "net"
    "strings"
    "time"

    "github.com/google/uuid"
)

type Device struct {
    UUID  string
    Name  string
    XAddr string
}

const probePayload = `<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <e:Header>
    <w:MessageID>uuid:%s</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe><d:Types xmlns:dn="http://www.onvif.org/ver10/network/wsdl">dn:NetworkVideoTransmitter</d:Types></d:Probe>
  </e:Body>
</e:Envelope>`

type probeEnvelope struct {
    XMLName xml.Name `xml:"Envelope"`
    Body    struct {
        Matches struct {
            Match []struct {
                Scopes string `xml:"Scopes"`
                XAddrs string `xml:"XAddrs"`
                EPR    struct {
                    Addr string `xml:"Address"`
                } `xml:"EndpointReference"`
            } `xml:"ProbeMatch"`
        } `xml:"ProbeMatches"`
    } `xml:"Body"`
}

func parseProbeMatches(r io.Reader) ([]Device, error) {
    var env probeEnvelope
    if err := xml.NewDecoder(r).Decode(&env); err != nil {
        return nil, err
    }
    out := make([]Device, 0, len(env.Body.Matches.Match))
    for _, m := range env.Body.Matches.Match {
        out = append(out, Device{
            UUID:  m.EPR.Addr,
            XAddr: strings.TrimSpace(strings.Fields(m.XAddrs)[0]),
            Name:  extractName(m.Scopes),
        })
    }
    return out, nil
}

func extractName(scopes string) string {
    for _, s := range strings.Fields(scopes) {
        if i := strings.Index(s, "/name/"); i >= 0 {
            return s[i+len("/name/"):]
        }
    }
    return "unknown"
}

func Discover(ctx context.Context, timeout time.Duration) ([]Device, error) {
    addr, _ := net.ResolveUDPAddr("udp4", "239.255.255.250:3702")
    conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4zero, Port: 0})
    if err != nil {
        return nil, err
    }
    defer conn.Close()
    msgID := uuid.NewString()
    payload := []byte(strings.Replace(probePayload, "%s", msgID, 1))
    if _, err := conn.WriteToUDP(payload, addr); err != nil {
        return nil, err
    }
    deadline := time.Now().Add(timeout)
    conn.SetReadDeadline(deadline)
    buf := make([]byte, 32*1024)
    var devs []Device
    seen := map[string]struct{}{}
    for {
        n, _, err := conn.ReadFromUDP(buf)
        if err != nil {
            break
        }
        parsed, err := parseProbeMatches(strings.NewReader(string(buf[:n])))
        if err != nil {
            continue
        }
        for _, d := range parsed {
            if _, ok := seen[d.UUID]; ok {
                continue
            }
            seen[d.UUID] = struct{}{}
            devs = append(devs, d)
        }
    }
    return devs, nil
}
```

- [ ] **Step 4: Run + commit**

```bash
cd agent && go get github.com/google/uuid && go test ./internal/onvif/...
git add agent/go.mod agent/go.sum agent/internal/onvif/
git commit -m "feat(agent): ONVIF WS-Discovery"
```

---

## Task 17: Agent — local web UI on `:8765`

**Files:**
- Create: `agent/internal/localui/server.go`
- Create: `agent/internal/localui/handlers.go`
- Create: `agent/internal/localui/static/index.html`
- Test: `agent/internal/localui/handlers_test.go`

- [ ] **Step 1: Failing test**

```go
// agent/internal/localui/handlers_test.go
package localui

import (
    "context"
    "encoding/json"
    "net/http"
    "net/http/httptest"
    "strings"
    "testing"
)

type fakePairer struct{ called bool }

func (f *fakePairer) Pair(ctx context.Context, code string) error {
    f.called = true
    if code != "123456" {
        return errCodeFmt
    }
    return nil
}

func TestPairHandlerSuccess(t *testing.T) {
    fp := &fakePairer{}
    h := newHandlers(fp)
    req := httptest.NewRequest("POST", "/api/pair", strings.NewReader(`{"code":"123456"}`))
    rr := httptest.NewRecorder()
    h.Pair(rr, req)
    if rr.Code != 200 {
        t.Fatalf("status %d body=%s", rr.Code, rr.Body.String())
    }
    if !fp.called {
        t.Fatal("Pair not called")
    }
}

func TestPairHandlerBadCode(t *testing.T) {
    h := newHandlers(&fakePairer{})
    req := httptest.NewRequest("POST", "/api/pair", strings.NewReader(`{"code":"abc"}`))
    rr := httptest.NewRecorder()
    h.Pair(rr, req)
    if rr.Code != 400 {
        t.Fatalf("status %d", rr.Code)
    }
}

func TestStatusHandler(t *testing.T) {
    h := newHandlers(&fakePairer{})
    req := httptest.NewRequest("GET", "/api/status", nil)
    rr := httptest.NewRecorder()
    h.Status(rr, req)
    var body map[string]any
    json.NewDecoder(rr.Body).Decode(&body)
    if _, ok := body["paired"]; !ok {
        t.Fatal("missing paired field")
    }
}
```

- [ ] **Step 2: Run — fail**

- [ ] **Step 3: Implement**

```go
// agent/internal/localui/handlers.go
package localui

import (
    "context"
    "encoding/json"
    "errors"
    "net/http"
    "regexp"
)

var errCodeFmt = errors.New("bad code format")
var codeRE = regexp.MustCompile(`^\d{6}$`)

type Pairer interface {
    Pair(ctx context.Context, code string) error
    IsPaired() bool
}

type handlers struct{ pairer Pairer }

func newHandlers(p Pairer) *handlers { return &handlers{pairer: p} }

func (h *handlers) Pair(w http.ResponseWriter, r *http.Request) {
    var body struct{ Code string `json:"code"` }
    if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
        http.Error(w, "bad json", 400)
        return
    }
    if !codeRE.MatchString(body.Code) {
        http.Error(w, "code must be 6 digits", 400)
        return
    }
    if err := h.pairer.Pair(r.Context(), body.Code); err != nil {
        http.Error(w, err.Error(), 400)
        return
    }
    w.Write([]byte(`{"ok":true}`))
}

func (h *handlers) Status(w http.ResponseWriter, r *http.Request) {
    json.NewEncoder(w).Encode(map[string]any{"paired": h.pairer.IsPaired()})
}
```

> Note: the fake in the test only implements `Pair`. Add `IsPaired() bool` to the fake too:
```go
func (f *fakePairer) IsPaired() bool { return false }
```

- [ ] **Step 4: Server + static page**

```go
// agent/internal/localui/server.go
package localui

import (
    "embed"
    "io/fs"
    "net/http"
)

//go:embed static
var staticFS embed.FS

func Serve(addr string, p Pairer) error {
    h := newHandlers(p)
    mux := http.NewServeMux()
    sub, _ := fs.Sub(staticFS, "static")
    mux.Handle("/", http.FileServer(http.FS(sub)))
    mux.HandleFunc("/api/pair", h.Pair)
    mux.HandleFunc("/api/status", h.Status)
    return http.ListenAndServe(addr, mux)
}
```

```html
<!-- agent/internal/localui/static/index.html -->
<!doctype html>
<html><head><meta charset="utf-8"><title>Nightwatch Agent</title>
<style>body{font-family:sans-serif;background:#0d0d0d;color:#fff;padding:2rem;max-width:480px;margin:auto}
input{font-size:2rem;letter-spacing:.5em;text-align:center;width:100%;padding:.5rem;background:#1a1a1a;color:#fff;border:1px solid #333}
button{background:#1e90ff;color:#fff;border:0;padding:1rem 2rem;font-size:1rem;cursor:pointer;width:100%;margin-top:1rem}
.status{margin-top:1rem;color:#888}</style></head>
<body>
<h1>Nightwatch Agent</h1>
<p>Open <a href="https://app.nightwatch.local/onboard">Nightwatch dashboard</a> to get a 6-digit pairing code, then enter it below.</p>
<input id="code" maxlength="6" placeholder="000000">
<button onclick="pair()">Pair</button>
<div class="status" id="status"></div>
<script>
async function pair(){
  const code=document.getElementById("code").value;
  const r=await fetch("/api/pair",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code})});
  document.getElementById("status").innerText=r.ok?"Paired. You can close this page.":"Failed: "+(await r.text());
}
async function poll(){const r=await fetch("/api/status");const d=await r.json();
  if(d.paired)document.getElementById("status").innerText="Already paired.";}
poll();
</script></body></html>
```

- [ ] **Step 5: Run + commit**

```bash
cd agent && go test ./internal/localui/...
git add agent/internal/localui/
git commit -m "feat(agent): local web UI on :8765 for pairing"
```

---

## Task 18: Agent — wire pairing into main

**Files:**
- Modify: `agent/cmd/agent/main.go`

- [ ] **Step 1: Wire components**

```go
// agent/cmd/agent/main.go (relevant additions)
package main

import (
    "context"
    "log"
    "os"
    "path/filepath"

    "github.com/nightwatch/agent/internal/localui"
    "github.com/nightwatch/agent/internal/pairing"
    "github.com/nightwatch/agent/internal/store"
)

type pairAdapter struct {
    backend   string
    store     *store.Store
    machineID string
    pubkey    string
    version   string
}

func (p *pairAdapter) IsPaired() bool { return p.store.Exists() }

func (p *pairAdapter) Pair(ctx context.Context, code string) error {
    c := pairing.NewClient(p.backend)
    resp, err := c.Pair(ctx, pairing.Request{Code: code, MachineID: p.machineID, Pubkey: p.pubkey, Version: p.version})
    if err != nil {
        return err
    }
    return p.store.Save(store.Token{
        DeviceToken: resp.DeviceToken, RelayURL: resp.RelayURL, OrgID: resp.OrgID, AgentID: resp.AgentID,
    })
}

func main() {
    dataDir := os.Getenv("AGENT_DATA_DIR")
    if dataDir == "" {
        dataDir = "/var/lib/nightwatch-agent"
    }
    backend := os.Getenv("BACKEND_URL")
    if backend == "" {
        backend = "https://api.nightwatch.local"
    }
    s := store.New(filepath.Join(dataDir, "token.json"))

    if !s.Exists() {
        log.Println("not paired yet — start http://localhost:8765 and enter code")
        adapter := &pairAdapter{
            backend: backend, store: s,
            machineID: machineID(), pubkey: ensurePubkey(dataDir), version: "0.1.0",
        }
        go func() { log.Fatal(localui.Serve(":8765", adapter)) }()
        for !s.Exists() {
            time.Sleep(2 * time.Second)
        }
        log.Println("paired — starting tunnel")
    }

    tok, _ := s.Load()
    // hand tok.DeviceToken + tok.RelayURL to existing tunnel code from tunnel-subsystem plan
    runTunnel(tok)
}
```

> `machineID()` and `ensurePubkey()` are small helpers — `machineID` reads `/etc/machine-id` (Linux) or hashes hostname+MAC; `ensurePubkey` generates an ed25519 keypair on first run and persists at `dataDir/agent.key`. Keep them inline; they're 10-20 lines each.

- [ ] **Step 2: Build + commit**

```bash
cd agent && go build ./cmd/agent
git add agent/cmd/agent/main.go
git commit -m "feat(agent): wire pairing flow into main"
```

---

## Task 19: Frontend — `/onboard` wizard shell

**Files:**
- Create: `frontend/app/onboard/page.tsx`

- [ ] **Step 1: Implement shell**

```tsx
// frontend/app/onboard/page.tsx
"use client";
import { useState } from "react";
import { InstallStep } from "./steps/install";
import { PairStep } from "./steps/pair";
import { DiscoverStep } from "./steps/discover";
import { TestStep } from "./steps/test";

const steps = ["Install", "Pair", "Discover", "Test"] as const;

export default function OnboardPage() {
  const [step, setStep] = useState(0);
  const [agentId, setAgentId] = useState<string | null>(null);

  return (
    <div className="max-w-2xl mx-auto p-8">
      <ol className="flex gap-2 mb-8">
        {steps.map((s, i) => (
          <li key={s} className={`flex-1 text-center py-2 rounded ${i === step ? "bg-[#1E90FF] text-white" : "bg-[#1a1a1a] text-gray-400"}`}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>
      {step === 0 && <InstallStep onNext={() => setStep(1)} />}
      {step === 1 && <PairStep onPaired={(id) => { setAgentId(id); setStep(2); }} />}
      {step === 2 && <DiscoverStep agentId={agentId!} onNext={() => setStep(3)} />}
      {step === 3 && <TestStep agentId={agentId!} />}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/onboard/page.tsx
git commit -m "feat(frontend): /onboard wizard shell"
```

---

## Task 20: Frontend — install step

**Files:**
- Create: `frontend/app/onboard/steps/install.tsx`

```tsx
// frontend/app/onboard/steps/install.tsx
"use client";
export function InstallStep({ onNext }: { onNext: () => void }) {
  const cmd = `docker run -d --name nightwatch-agent --restart=always \\
  --net=host \\
  -v nightwatch-agent-data:/var/lib/nightwatch-agent \\
  -e BACKEND_URL=${process.env.NEXT_PUBLIC_API_URL} \\
  ghcr.io/nightwatch/agent:latest`;
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Install the Nightwatch Agent</h2>
      <p>Run this on a device on the same network as your NVR (NAS / Router with Docker / Raspberry Pi):</p>
      <pre className="bg-[#0a0a0a] p-4 rounded overflow-x-auto text-sm">{cmd}</pre>
      <button onClick={() => navigator.clipboard.writeText(cmd)} className="px-4 py-2 bg-[#1a1a1a] rounded">Copy</button>
      <p className="text-sm text-gray-400">Once running, open <code>http://&lt;device-ip&gt;:8765</code> in your browser.</p>
      <button onClick={onNext} className="px-6 py-2 bg-[#1E90FF] rounded">I've installed it →</button>
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/app/onboard/steps/install.tsx
git commit -m "feat(frontend): onboard install step"
```

---

## Task 21: Frontend — pair step

**Files:**
- Create: `frontend/app/onboard/steps/pair.tsx`

```tsx
// frontend/app/onboard/steps/pair.tsx
"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function PairStep({ onPaired }: { onPaired: (agentId: string) => void }) {
  const [code, setCode] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.post("/api/agents/pair-codes", {})
      .then((r) => { setCode(r.data.code); setExpiresAt(new Date(r.data.expires_at)); })
      .catch((e) => setError(e?.response?.data?.detail ?? "failed to mint code"));
  }, []);

  useEffect(() => {
    const t = setInterval(async () => {
      const r = await api.get("/api/agents");
      const fresh = r.data.agents.find((a: any) => new Date(a.created_at) > new Date(Date.now() - 5 * 60 * 1000));
      if (fresh) { clearInterval(t); onPaired(fresh.id); }
    }, 3000);
    return () => clearInterval(t);
  }, [onPaired]);

  if (error) return <p className="text-red-400">{error}</p>;
  if (!code) return <p>Generating code…</p>;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Pair your agent</h2>
      <p>Open the agent's web UI (<code>http://&lt;device-ip&gt;:8765</code>) and enter this code:</p>
      <div className="text-6xl font-mono tracking-widest text-center py-8 bg-[#1a1a1a] rounded">{code}</div>
      <p className="text-sm text-gray-400">Expires in 10 minutes. Waiting for agent…</p>
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/app/onboard/steps/pair.tsx
git commit -m "feat(frontend): onboard pair step"
```

---

## Task 22: Frontend — discover step (with brand-picker fallback)

**Files:**
- Create: `frontend/app/onboard/steps/discover.tsx`
- Create: `frontend/app/onboard/lib/brands.ts`

```ts
// frontend/app/onboard/lib/brands.ts
export const BRANDS = [
  { name: "CP Plus",    template: "rtsp://{user}:{pass}@{host}:554/cam/realmonitor?channel={ch}&subtype=0" },
  { name: "Hikvision",  template: "rtsp://{user}:{pass}@{host}:554/Streaming/Channels/{ch}01" },
  { name: "Dahua",      template: "rtsp://{user}:{pass}@{host}:554/cam/realmonitor?channel={ch}&subtype=0" },
  { name: "Reolink",    template: "rtsp://{user}:{pass}@{host}:554/h264Preview_{ch}_main" },
  { name: "Tapo",       template: "rtsp://{user}:{pass}@{host}:554/stream1" },
  { name: "Generic ONVIF", template: "rtsp://{user}:{pass}@{host}:554/onvif1" },
];
```

```tsx
// frontend/app/onboard/steps/discover.tsx
"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BRANDS } from "../lib/brands";

type Discovered = { uuid: string; name: string; xaddr: string };

export function DiscoverStep({ agentId, onNext }: { agentId: string; onNext: () => void }) {
  const [found, setFound] = useState<Discovered[] | null>(null);
  const [manual, setManual] = useState(false);

  useEffect(() => {
    api.post(`/api/agents/${agentId}/discover`, {})
      .then((r) => setFound(r.data.devices))
      .catch(() => setManual(true));
  }, [agentId]);

  if (manual || (found && found.length === 0)) {
    return <ManualEntry agentId={agentId} onNext={onNext} />;
  }
  if (!found) return <p>Scanning your network for NVRs…</p>;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Cameras found</h2>
      {found.map((d) => (
        <CameraEnable key={d.uuid} agentId={agentId} discovered={d} />
      ))}
      <button onClick={onNext} className="px-6 py-2 bg-[#1E90FF] rounded">Done →</button>
      <button onClick={() => setManual(true)} className="text-sm underline text-gray-400">I don't see my camera</button>
    </div>
  );
}

function CameraEnable({ agentId, discovered }: { agentId: string; discovered: Discovered }) {
  const [user, setU] = useState(""); const [pass, setP] = useState(""); const [name, setN] = useState(discovered.name);
  return (
    <div className="border border-[#333] p-4 rounded space-y-2">
      <input value={name} onChange={(e) => setN(e.target.value)} placeholder="Camera name" className="bg-[#1a1a1a] p-2 w-full rounded" />
      <input value={user} onChange={(e) => setU(e.target.value)} placeholder="NVR username" className="bg-[#1a1a1a] p-2 w-full rounded" />
      <input type="password" value={pass} onChange={(e) => setP(e.target.value)} placeholder="NVR password" className="bg-[#1a1a1a] p-2 w-full rounded" />
      <button onClick={() => api.post(`/api/agents/${agentId}/cameras`, { name, onvif_xaddr: discovered.xaddr, user, pass })} className="px-4 py-2 bg-[#1E90FF] rounded">Enable</button>
    </div>
  );
}

function ManualEntry({ agentId, onNext }: { agentId: string; onNext: () => void }) {
  const [brand, setBrand] = useState(BRANDS[0].name);
  const [host, setHost] = useState(""); const [user, setU] = useState(""); const [pass, setP] = useState("");
  const [ch, setCh] = useState("1"); const [name, setN] = useState("Front door");
  const tpl = BRANDS.find((b) => b.name === brand)!.template;
  const url = tpl.replace("{user}", user).replace("{pass}", pass).replace("{host}", host).replace("{ch}", ch);
  return (
    <div className="space-y-3">
      <h2 className="text-xl font-semibold">Enter your camera URL</h2>
      <select value={brand} onChange={(e) => setBrand(e.target.value)} className="bg-[#1a1a1a] p-2 w-full rounded">
        {BRANDS.map((b) => <option key={b.name}>{b.name}</option>)}
      </select>
      <input value={name} onChange={(e) => setN(e.target.value)} placeholder="Camera name" className="bg-[#1a1a1a] p-2 w-full rounded" />
      <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="NVR IP (e.g. 192.168.1.50)" className="bg-[#1a1a1a] p-2 w-full rounded" />
      <input value={user} onChange={(e) => setU(e.target.value)} placeholder="username" className="bg-[#1a1a1a] p-2 w-full rounded" />
      <input type="password" value={pass} onChange={(e) => setP(e.target.value)} placeholder="password" className="bg-[#1a1a1a] p-2 w-full rounded" />
      <input value={ch} onChange={(e) => setCh(e.target.value)} placeholder="channel" className="bg-[#1a1a1a] p-2 w-full rounded" />
      <pre className="text-xs text-gray-400 break-all">{url}</pre>
      <button onClick={async () => { await api.post(`/api/agents/${agentId}/cameras`, { name, rtsp_url: url }); onNext(); }} className="px-6 py-2 bg-[#1E90FF] rounded">Save & test</button>
    </div>
  );
}
```

> `POST /api/agents/{agent_id}/discover` and `POST /api/agents/{agent_id}/cameras` are two more thin routes that delegate to the agent (via the relay's existing control channel) and persist a row in the existing `cameras` table with `agent_id` set. Spec them as Tasks 22a/22b in a follow-up if needed; their implementation pattern matches Tasks 8-10. Mark these as TODO at the top of `backend/app/api/agents.py` so they don't get forgotten.

- [ ] Commit:
```bash
git add frontend/app/onboard/steps/discover.tsx frontend/app/onboard/lib/brands.ts
git commit -m "feat(frontend): onboard discover + manual brand-picker fallback"
```

---

## Task 23: Frontend — test step (stream confirmation)

**Files:**
- Create: `frontend/app/onboard/steps/test.tsx`

```tsx
// frontend/app/onboard/steps/test.tsx
"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

export function TestStep({ agentId }: { agentId: string }) {
  const [status, setStatus] = useState<"waiting" | "ok" | "fail">("waiting");
  const router = useRouter();

  useEffect(() => {
    const t = setInterval(async () => {
      const r = await api.get(`/api/agents/${agentId}`);
      if (r.data.cameras_streaming > 0) { setStatus("ok"); clearInterval(t); }
    }, 3000);
    const fail = setTimeout(() => setStatus((s) => (s === "waiting" ? "fail" : s)), 60_000);
    return () => { clearInterval(t); clearTimeout(fail); };
  }, [agentId]);

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Testing the stream</h2>
      {status === "waiting" && <p>Waiting for the first frame from your camera…</p>}
      {status === "ok" && <>
        <p className="text-green-400">Frame received. You're all set.</p>
        <button onClick={() => router.push("/dashboard")} className="px-6 py-2 bg-[#1E90FF] rounded">Go to dashboard</button>
      </>}
      {status === "fail" && <p className="text-red-400">No frames received in 60s. Check NVR password and try again.</p>}
    </div>
  );
}
```

- [ ] Commit:
```bash
git add frontend/app/onboard/steps/test.tsx
git commit -m "feat(frontend): onboard test step"
```

---

## Task 24: Pair-code rate limit (5/hour per user)

**Files:**
- Modify: `backend/app/api/agents.py`
- Test: `backend/tests/api/test_agents_rate_limit.py`

- [ ] **Step 1: Failing test**

```python
@pytest.mark.asyncio
async def test_six_codes_in_hour_returns_429(client, auth_headers):
    for _ in range(5):
        assert (await client.post("/api/agents/pair-codes", headers=auth_headers)).status_code == 201
    r = await client.post("/api/agents/pair-codes", headers=auth_headers)
    assert r.status_code == 429
```

- [ ] **Step 2: Run — fail (returns 201 sixth time)**

- [ ] **Step 3: Add Redis sliding-window check in handler**

```python
# inside create_pair_code, before mint
from app.core.redis import redis
key = f"paircode:rate:{user.id}"
count = await redis.incr(key)
if count == 1:
    await redis.expire(key, 3600)
if count > 5:
    raise HTTPException(429, "too many pairing codes — try again in an hour")
```

- [ ] **Step 4: Run + commit**

```bash
pytest backend/tests/api/test_agents_rate_limit.py -v
git add backend/app/api/agents.py backend/tests/api/test_agents_rate_limit.py
git commit -m "feat(backend): rate-limit pair-code minting to 5/hour/user"
```

---

## Task 25: Integration test — full pair → tunnel → relay flow

**Files:**
- Create: `backend/tests/integration/test_onboarding_e2e.py`

- [ ] **Step 1: Write end-to-end test**

```python
# backend/tests/integration/test_onboarding_e2e.py
import pytest

@pytest.mark.asyncio
async def test_pair_then_use_token_with_relay_verify(client, auth_headers, settings):
    # 1. user mints code
    code = (await client.post("/api/agents/pair-codes", headers=auth_headers)).json()["code"]
    # 2. agent pairs
    pair = (await client.post("/api/agents/pair", json={
        "code": code, "machine_id": "m12345678", "pubkey": "p" * 16, "version": "0.1.0",
    })).json()
    token = pair["device_token"]
    # 3. relay calls verify-token internal endpoint
    r = await client.post("/internal/agents/verify-token", json={"token": token},
                         headers={"X-Worker-Key": settings.WORKER_API_KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["org_id"] == pair["org_id"]
    assert body["agent_id"] == pair["agent_id"]
    # 4. agent appears in user's list
    listing = await client.get("/api/agents", headers=auth_headers)
    assert any(a["id"] == pair["agent_id"] for a in listing.json()["agents"])
```

- [ ] **Step 2: Run + commit**

```bash
pytest backend/tests/integration/test_onboarding_e2e.py -v
git add backend/tests/integration/test_onboarding_e2e.py
git commit -m "test(backend): onboarding end-to-end happy path"
```

---

## Self-Review

**Spec coverage check:**
- ✅ `agents` + `agent_pair_codes` tables (Tasks 1, 2)
- ✅ `cameras.agent_id`, `organizations.timezone/whatsapp_number` (Task 3)
- ✅ Mint code endpoint with 6-digit, 10-min TTL (Tasks 4, 8)
- ✅ Redeem code with all error paths (Task 5)
- ✅ Argon2id-hashed device tokens (Task 6)
- ✅ `POST /api/agents/pair` returns token + relay URL (Task 9)
- ✅ Relay device-token verification (Tasks 12, 13)
- ✅ Single-use codes (covered by Task 5 `consumed_at`)
- ✅ Per-user 5/hour rate limit (Task 24)
- ✅ Onboarding wizard 4 steps (Tasks 19-23)
- ✅ ONVIF auto-discover + manual brand-picker fallback (Tasks 16, 22)

**Known follow-ups (intentionally deferred, marked TODO in code):**
- `POST /api/agents/{id}/discover` and `POST /api/agents/{id}/cameras` thin routes referenced by Task 22 — pattern matches Tasks 8-10; specced in code but not tasked. Add when implementing Task 22 if not extant.
- Agent's `runTunnel(tok)` in Task 18 is the entry point from the [tunnel-subsystem](./2026-05-28-tunnel-subsystem.md) plan. Wire-up depends on that plan being merged first.
- Linear scan in `get_agent_from_token` (Task 11) and `verify_agent_token` (Task 12) — fine until ~10k agents. Switch to a token-id prefix index later.
- ed25519 keypair generation helper (`ensurePubkey`) in Task 18 left as inline 10-20 lines; if it grows, extract to `agent/internal/store/keypair.go`.

**Type consistency:** `device_token`, `relay_url`, `org_id`, `agent_id` are spelled identically in the Pydantic schema (Task 7), Go pairing client (Task 15), and store (Task 14). ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-28-onboarding-subsystem.md`.

All three subsystem plans are now written:
1. `2026-05-28-digest-subsystem.md` — backend digest service + scheduler + WhatsApp
2. `2026-05-28-tunnel-subsystem.md` — Go agent + Go relay + gRPC/WebRTC
3. `2026-05-28-onboarding-subsystem.md` — pairing, ONVIF discovery, /onboard wizard (this file)

**Suggested execution order:** tunnel → onboarding → digest. (Tunnel's static `X-Agent-Key` is replaced by onboarding; digest is independent and can run in parallel.)

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.

Which approach?
