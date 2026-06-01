"""Tests for /api/chat (ask-Gemini endpoint).

Gemini calls and the spend-tracker are mocked so tests don't depend on a
real API key or accumulated Redis state.
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app.api import chat as chat_api
from app.models.camera import Camera
from app.models.chat_message import ChatMessage
from app.models.event import Event
from app.models.organization import Organization
from app.models.site import Site
from app.models.user import User
from app.services.chat_service import ChatResult


# ─── Helpers / fixtures ──────────────────────────────────────────────────────


class _StubChatClient:
    """Always returns a canned reply, recording the prompt for assertions."""

    def __init__(self, reply: str = "stubbed reply"):
        self.reply_text = reply
        self.calls: list[dict] = []

    async def reply(self, *, history, user_message, context_blocks=()):
        self.calls.append(
            {
                "history": list(history),
                "user_message": user_message,
                "context_blocks": list(context_blocks),
            }
        )
        return ChatResult(text=self.reply_text, cost_usd=0.005)


class _FailingChatClient:
    async def reply(self, *, history, user_message, context_blocks=()):
        raise RuntimeError("boom")


class _AlwaysAllowSpend:
    async def try_charge(self, org_id, cost_usd):
        return True


class _NeverAllowSpend:
    async def try_charge(self, org_id, cost_usd):
        return False


@pytest.fixture
def stub_chat_client():
    return _StubChatClient()


@pytest_asyncio.fixture
async def patched_deps(stub_chat_client):
    """Override chat client + spend tracker dependencies on the FastAPI app."""
    from app.main import app

    app.dependency_overrides[chat_api.get_chat_client_dep] = lambda: stub_chat_client
    app.dependency_overrides[chat_api._get_spend_tracker] = lambda: _AlwaysAllowSpend()
    yield
    app.dependency_overrides.pop(chat_api.get_chat_client_dep, None)
    app.dependency_overrides.pop(chat_api._get_spend_tracker, None)


@pytest_asyncio.fixture
async def site(db_session, test_org):
    s = Site(org_id=test_org.id, name="Site A", address="x")
    db_session.add(s)
    await db_session.flush()
    return s


@pytest_asyncio.fixture
async def camera(db_session, test_org, site):
    cam = Camera(
        org_id=test_org.id,
        site_id=site.id,
        name="Front Door",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://x",
        enabled_events=[],
        detection_zones=[],
    )
    db_session.add(cam)
    await db_session.flush()
    return cam


@pytest_asyncio.fixture
async def event(db_session, test_org, site, camera):
    e = Event(
        org_id=test_org.id,
        camera_id=camera.id,
        site_id=site.id,
        timestamp=datetime.now(timezone.utc),
        event_type="person",
        confidence=0.9,
        severity="medium",
        description="A person at the door",
        snapshot_url="gs://x/snap.webp",
    )
    db_session.add(e)
    await db_session.flush()
    return e


# ─── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_creates_new_conversation(auth_client, patched_deps, stub_chat_client):
    resp = await auth_client.post("/api/chat", json={"message": "hello there"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "assistant"
    assert body["content"] == "stubbed reply"
    assert uuid.UUID(body["conversation_id"])
    # One Gemini call made
    assert len(stub_chat_client.calls) == 1


@pytest.mark.asyncio
async def test_post_appends_to_existing_conversation(
    auth_client, patched_deps, stub_chat_client
):
    r1 = await auth_client.post("/api/chat", json={"message": "first"})
    assert r1.status_code == 200
    conv_id = r1.json()["conversation_id"]

    r2 = await auth_client.post(
        "/api/chat", json={"message": "second", "conversation_id": conv_id}
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["conversation_id"] == conv_id

    # Second call's history should include the first user+assistant turns
    second_call = stub_chat_client.calls[1]
    assert len(second_call["history"]) >= 2


@pytest.mark.asyncio
async def test_post_rejects_camera_from_other_org(
    auth_client, patched_deps, db_session
):
    other = Organization(name="Other", slug=f"o-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    await db_session.flush()
    other_site = Site(org_id=other.id, name="S", address="x")
    db_session.add(other_site)
    await db_session.flush()
    other_cam = Camera(
        org_id=other.id,
        site_id=other_site.id,
        name="Other Cam",
        ingest_mode="rtsp_pull",
        rtsp_url="rtsp://y",
        enabled_events=[],
        detection_zones=[],
    )
    db_session.add(other_cam)
    await db_session.flush()

    resp = await auth_client.post(
        "/api/chat",
        json={"message": "tell me about this", "camera_id": str(other_cam.id)},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_returns_429_when_over_daily_cap(
    auth_client, stub_chat_client
):
    from app.main import app

    app.dependency_overrides[chat_api.get_chat_client_dep] = lambda: stub_chat_client
    app.dependency_overrides[chat_api._get_spend_tracker] = lambda: _NeverAllowSpend()
    try:
        resp = await auth_client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 429
        assert "quota" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(chat_api.get_chat_client_dep, None)
        app.dependency_overrides.pop(chat_api._get_spend_tracker, None)


@pytest.mark.asyncio
async def test_get_conversations_lists_only_own(
    auth_client, patched_deps, db_session, test_org, test_user
):
    # User's own conversation
    r = await auth_client.post("/api/chat", json={"message": "mine"})
    assert r.status_code == 200
    own_conv = r.json()["conversation_id"]

    # Plant another user's conversation in the same org
    other_user = User(
        org_id=test_org.id,
        username=f"u-{uuid.uuid4().hex[:6]}",
        password_hash="x",
        name="Other",
        role="viewer",
    )
    db_session.add(other_user)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            org_id=test_org.id,
            user_id=other_user.id,
            conversation_id=uuid.uuid4(),
            role="user",
            content="not mine",
        )
    )
    await db_session.flush()

    resp = await auth_client.get("/api/chat/conversations")
    assert resp.status_code == 200
    convs = resp.json()
    assert len(convs) == 1
    assert convs[0]["conversation_id"] == own_conv


@pytest.mark.asyncio
async def test_get_messages_enforces_ownership(
    auth_client, patched_deps, db_session, test_org
):
    # Plant a conversation owned by a different user.
    other_user = User(
        org_id=test_org.id,
        username=f"u-{uuid.uuid4().hex[:6]}",
        password_hash="x",
        name="Other",
        role="viewer",
    )
    db_session.add(other_user)
    await db_session.flush()
    conv_id = uuid.uuid4()
    db_session.add(
        ChatMessage(
            org_id=test_org.id,
            user_id=other_user.id,
            conversation_id=conv_id,
            role="user",
            content="not mine",
        )
    )
    await db_session.flush()

    resp = await auth_client.get(f"/api/chat/conversations/{conv_id}/messages")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_messages_returns_chronological(
    auth_client, patched_deps
):
    r = await auth_client.post("/api/chat", json={"message": "first"})
    conv_id = r.json()["conversation_id"]
    await auth_client.post(
        "/api/chat", json={"message": "second", "conversation_id": conv_id}
    )

    resp = await auth_client.get(f"/api/chat/conversations/{conv_id}/messages")
    assert resp.status_code == 200
    msgs = resp.json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "first"


@pytest.mark.asyncio
async def test_delete_conversation(auth_client, patched_deps, db_session):
    r = await auth_client.post("/api/chat", json={"message": "hi"})
    conv_id = r.json()["conversation_id"]

    resp = await auth_client.delete(f"/api/chat/conversations/{conv_id}")
    assert resp.status_code == 204

    # Verify gone
    follow = await auth_client.get(f"/api/chat/conversations/{conv_id}/messages")
    assert follow.status_code == 404


@pytest.mark.asyncio
async def test_delete_other_users_conversation_forbidden(
    auth_client, patched_deps, db_session, test_org
):
    other = User(
        org_id=test_org.id,
        username=f"u-{uuid.uuid4().hex[:6]}",
        password_hash="x",
        name="Other",
        role="viewer",
    )
    db_session.add(other)
    await db_session.flush()
    conv_id = uuid.uuid4()
    db_session.add(
        ChatMessage(
            org_id=test_org.id,
            user_id=other.id,
            conversation_id=conv_id,
            role="user",
            content="x",
        )
    )
    await db_session.flush()

    resp = await auth_client.delete(f"/api/chat/conversations/{conv_id}")
    assert resp.status_code == 404
