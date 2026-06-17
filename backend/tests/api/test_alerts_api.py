"""Tests for /api/alerts/rules — CRUD + enable/disable."""
import uuid

import pytest

from app.models.alert_rule import AlertRule


def _make_rule(org_id, **kwargs):
    defaults = dict(
        org_id=org_id,
        name="Test Rule",
        event_types=["person"],
        min_severity="medium",
        notify_channels=["email"],
        notify_contacts=[{"type": "email", "value": "ops@example.com"}],
        cooldown_seconds=60,
        enabled=True,
    )
    defaults.update(kwargs)
    return AlertRule(**defaults)


@pytest.mark.asyncio
async def test_list_rules_empty(auth_client):
    resp = await auth_client.get("/api/alerts/rules")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_create_rule(auth_client, test_org):
    resp = await auth_client.post(
        "/api/alerts/rules",
        json={
            "name": "Intruder Alert",
            "event_types": ["person", "intrusion"],
            "min_severity": "high",
            "notify_channels": ["whatsapp", "email"],
            "notify_contacts": [{"type": "email", "value": "security@example.com"}],
            "cooldown_seconds": 300,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Intruder Alert"
    assert body["min_severity"] == "high"
    assert body["enabled"] is True


@pytest.mark.asyncio
async def test_list_rules_org_scoped(auth_client, db_session, test_org):
    my_rule = _make_rule(test_org.id, name="My Rule")
    db_session.add(my_rule)
    await db_session.flush()

    other_org = __import__("app.models.organization", fromlist=["Organization"]).Organization(
        name="Other", slug=f"other-{uuid.uuid4().hex[:6]}"
    )
    db_session.add(other_org)
    await db_session.flush()

    other_rule = _make_rule(other_org.id, name="Their Rule")
    db_session.add(other_rule)
    await db_session.flush()

    resp = await auth_client.get("/api/alerts/rules")
    assert resp.status_code == 200
    names = [r["name"] for r in resp.json()]
    assert "My Rule" in names
    assert "Their Rule" not in names


@pytest.mark.asyncio
async def test_update_rule(auth_client, db_session, test_org):
    rule = _make_rule(test_org.id, name="Old Name")
    db_session.add(rule)
    await db_session.flush()

    resp = await auth_client.patch(
        f"/api/alerts/rules/{rule.id}",
        json={"name": "New Name", "cooldown_seconds": 120},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["cooldown_seconds"] == 120


@pytest.mark.asyncio
async def test_enable_disable_rule_via_patch(auth_client, db_session, test_org):
    rule = _make_rule(test_org.id, enabled=True)
    db_session.add(rule)
    await db_session.flush()

    resp = await auth_client.patch(f"/api/alerts/rules/{rule.id}", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    resp = await auth_client.patch(f"/api/alerts/rules/{rule.id}", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


@pytest.mark.asyncio
async def test_delete_rule(auth_client, db_session, test_org):
    rule = _make_rule(test_org.id)
    db_session.add(rule)
    await db_session.flush()

    resp = await auth_client.delete(f"/api/alerts/rules/{rule.id}")
    assert resp.status_code == 204

    # Verify deleted — list should no longer include it
    resp2 = await auth_client.get("/api/alerts/rules")
    assert resp2.status_code == 200
    ids = [r["id"] for r in resp2.json()]
    assert str(rule.id) not in ids


@pytest.mark.asyncio
async def test_rules_unauthenticated(client):
    # Required Authorization header missing → 422 Unprocessable Entity
    resp = await client.get("/api/alerts/rules")
    assert resp.status_code == 422
