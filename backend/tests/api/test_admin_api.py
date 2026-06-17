"""Tests for /api/admin/ — orgs + users management (super_admin only)."""
import uuid

import pytest

from app.models.organization import Organization
from app.models.user import User
from app.core.security import hash_password


def _make_org(name=None):
    slug = uuid.uuid4().hex[:8]
    return Organization(name=name or f"Org {slug}", slug=slug)


def _make_user(org_id, role="owner"):
    return User(
        org_id=org_id,
        username=f"user-{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("pass"),
        name="Test",
        role=role,
    )


# ── Org endpoints ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_list_orgs(admin_client, db_session):
    org1 = _make_org("Alpha")
    org2 = _make_org("Beta")
    db_session.add_all([org1, org2])
    await db_session.flush()

    resp = await admin_client.get("/api/admin/orgs")
    assert resp.status_code == 200
    names = [o["name"] for o in resp.json()]
    assert "Alpha" in names
    assert "Beta" in names


@pytest.mark.asyncio
async def test_admin_create_org(admin_client):
    resp = await admin_client.post(
        "/api/admin/orgs",
        json={"name": "New Org", "plan": "starter"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "New Org"
    assert "slug" in body
    assert "id" in body


@pytest.mark.asyncio
async def test_admin_update_org(admin_client, db_session):
    org = _make_org("Before")
    db_session.add(org)
    await db_session.flush()

    resp = await admin_client.patch(
        f"/api/admin/orgs/{org.id}",
        json={"name": "After"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "After"


@pytest.mark.asyncio
async def test_admin_delete_org(admin_client, db_session):
    org = _make_org()
    db_session.add(org)
    await db_session.flush()

    resp = await admin_client.delete(f"/api/admin/orgs/{org.id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_orgs_requires_super_admin(auth_client):
    resp = await auth_client.get("/api/admin/orgs")
    assert resp.status_code == 403


# ── User endpoints ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_list_users(admin_client, db_session):
    org = _make_org()
    db_session.add(org)
    await db_session.flush()

    u1 = _make_user(org.id)
    u2 = _make_user(org.id)
    db_session.add_all([u1, u2])
    await db_session.flush()

    resp = await admin_client.get("/api/admin/users")
    assert resp.status_code == 200
    ids = [u["id"] for u in resp.json()]
    assert str(u1.id) in ids
    assert str(u2.id) in ids


@pytest.mark.asyncio
async def test_admin_list_users_filter_by_org(admin_client, db_session):
    org1 = _make_org()
    org2 = _make_org()
    db_session.add_all([org1, org2])
    await db_session.flush()

    u1 = _make_user(org1.id)
    u2 = _make_user(org2.id)
    db_session.add_all([u1, u2])
    await db_session.flush()

    resp = await admin_client.get(f"/api/admin/users?org_id={org1.id}")
    assert resp.status_code == 200
    ids = [u["id"] for u in resp.json()]
    assert str(u1.id) in ids
    assert str(u2.id) not in ids


@pytest.mark.asyncio
async def test_admin_create_user_in_org(admin_client, db_session):
    org = _make_org()
    db_session.add(org)
    await db_session.flush()

    uname = f"newuser-{uuid.uuid4().hex[:6]}"
    resp = await admin_client.post(
        "/api/admin/users/create",
        json={
            "username": uname,
            "password": "testpass123",
            "name": "Created User",
            "role": "operator",
            "org_id": str(org.id),
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == uname
    assert body["role"] == "operator"


@pytest.mark.asyncio
async def test_admin_update_user_role(admin_client, db_session):
    org = _make_org()
    db_session.add(org)
    await db_session.flush()

    user = _make_user(org.id, role="viewer")
    db_session.add(user)
    await db_session.flush()

    resp = await admin_client.patch(
        f"/api/admin/users/{user.id}",
        json={"role": "operator"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "operator"


@pytest.mark.asyncio
async def test_admin_change_user_password(admin_client, db_session):
    org = _make_org()
    db_session.add(org)
    await db_session.flush()

    user = _make_user(org.id)
    db_session.add(user)
    await db_session.flush()

    resp = await admin_client.post(
        f"/api/admin/users/{user.id}/change-password",
        json={"new_password": "newpass456"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_delete_user(admin_client, db_session):
    org = _make_org()
    db_session.add(org)
    await db_session.flush()

    user = _make_user(org.id)
    db_session.add(user)
    await db_session.flush()

    resp = await admin_client.delete(f"/api/admin/users/{user.id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_admin_users_requires_super_admin(auth_client):
    resp = await auth_client.get("/api/admin/users")
    assert resp.status_code == 403
