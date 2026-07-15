# WhatsApp Instant Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an org owner register up to 4 WhatsApp numbers in a new Settings tab, each independently toggleable, so enabled numbers instantly start receiving real-time event alerts.

**Architecture:** Store up to 4 `{id, number, enabled}` contacts as a JSONB column on `Organization`. A sync helper keeps a single auto-provisioned, fixed-name `AlertRule` ("WhatsApp Instant Alerts", no camera/event-type/zone filters) in lockstep with whichever contacts are currently enabled — the existing alert engine (`alert_service.py`, `notification_service.py`) delivers messages with zero changes. The Settings page is converted from stacked sections to a shadcn `Tabs` layout to hold the new "WhatsApp Alerts" tab alongside the existing Organization/Sites/Team sections.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend), Next.js App Router + TypeScript + TanStack Query + shadcn/ui `Tabs`/`Switch` (frontend).

## Global Constraints

- Max 4 WhatsApp contacts per org, enforced server-side (400 on the 5th).
- Phone numbers validated as `^\+\d{8,15}$` (E.164-ish), server-side.
- Duplicate numbers within an org rejected with 400.
- New contacts are created with `enabled: false` — owner must explicitly toggle on.
- All mutating endpoints are owner-only (`require_role(user, "owner")`).
- The digest feature's `organizations.whatsapp_number` column and `whatsapp_enabled` digest preference are untouched — this is a separate JSONB column and a separate concern.
- No changes to `alert_service.py` or `notification_service.py` — the feature only ever produces/updates a normal `AlertRule` row.
- Frontend: dark theme only, Nightwatch hex tokens (see `frontend/CLAUDE.md`), no `any` types, TanStack Query for all server data, invalidate on mutation.

---

### Task 1: Organization model column + migration

**Files:**
- Modify: `backend/app/models/organization.py`
- Create: `backend/alembic/versions/d4a9c2e8f1b6_whatsapp_alert_contacts.py`
- Test: `backend/tests/models/test_organization_whatsapp_contacts.py`

**Interfaces:**
- Produces: `Organization.whatsapp_alert_contacts: list[dict]` (SQLAlchemy `Mapped[list]`, JSONB, default `[]`). Later tasks read/write this column directly (list of `{"id": str, "number": str, "enabled": bool}` dicts).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/models/test_organization_whatsapp_contacts.py`:

```python
import pytest

from app.models.organization import Organization


@pytest.mark.asyncio
async def test_org_whatsapp_alert_contacts_defaults_empty(db_session):
    org = Organization(name="Test Co", slug="test-co-wa")
    db_session.add(org)
    await db_session.flush()

    assert org.whatsapp_alert_contacts == []


@pytest.mark.asyncio
async def test_org_whatsapp_alert_contacts_round_trips(db_session):
    org = Organization(
        name="Test Co 2",
        slug="test-co-wa-2",
        whatsapp_alert_contacts=[{"id": "abc", "number": "+911234567890", "enabled": True}],
    )
    db_session.add(org)
    await db_session.flush()
    await db_session.refresh(org)

    assert org.whatsapp_alert_contacts == [{"id": "abc", "number": "+911234567890", "enabled": True}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/models/test_organization_whatsapp_contacts.py -v`
Expected: FAIL with `AttributeError: 'Organization' object has no attribute 'whatsapp_alert_contacts'` (or similar — the column doesn't exist yet)

- [ ] **Step 3: Add the column to the model**

In `backend/app/models/organization.py`, add the new column right after the existing `whatsapp_number` line:

```python
    whatsapp_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    whatsapp_alert_contacts: Mapped[list] = mapped_column(JSONB, default=list)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
```

(`JSONB` is already imported at the top of this file — it's used by `settings` on the same model.)

- [ ] **Step 4: Write the Alembic migration**

Create `backend/alembic/versions/d4a9c2e8f1b6_whatsapp_alert_contacts.py`:

```python
"""whatsapp_alert_contacts

Revision ID: d4a9c2e8f1b6
Revises: b7e2f1a3c9d5
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4a9c2e8f1b6"
down_revision: Union[str, None] = "b7e2f1a3c9d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "whatsapp_alert_contacts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "whatsapp_alert_contacts")
```

- [ ] **Step 5: Apply the migration to the test/dev database**

Run: `cd backend && uv run alembic upgrade head`
Expected: Output ends with `Running upgrade b7e2f1a3c9d5 -> d4a9c2e8f1b6, whatsapp_alert_contacts`

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/models/test_organization_whatsapp_contacts.py -v`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/organization.py backend/alembic/versions/d4a9c2e8f1b6_whatsapp_alert_contacts.py backend/tests/models/test_organization_whatsapp_contacts.py
git commit -m "feat: add whatsapp_alert_contacts column to organizations"
```

---

### Task 2: Pydantic schemas for WhatsApp alert contacts

**Files:**
- Create: `backend/app/schemas/whatsapp_alerts.py`

**Interfaces:**
- Consumes: nothing (pure schema definitions).
- Produces: `WhatsAppAlertContact`, `CreateWhatsAppAlertContactRequest`, `UpdateWhatsAppAlertContactRequest` — imported by Task 3's route file.

- [ ] **Step 1: Create the schema file**

Create `backend/app/schemas/whatsapp_alerts.py`:

```python
from pydantic import BaseModel


class WhatsAppAlertContact(BaseModel):
    id: str
    number: str
    enabled: bool


class CreateWhatsAppAlertContactRequest(BaseModel):
    number: str


class UpdateWhatsAppAlertContactRequest(BaseModel):
    number: str | None = None
    enabled: bool | None = None
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `cd backend && uv run python3 -c "from app.schemas.whatsapp_alerts import WhatsAppAlertContact, CreateWhatsAppAlertContactRequest, UpdateWhatsAppAlertContactRequest; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/whatsapp_alerts.py
git commit -m "feat: add pydantic schemas for whatsapp alert contacts"
```

---

### Task 3: Sync helper + API endpoints

**Files:**
- Modify: `backend/app/api/settings.py`
- Test: `backend/tests/api/test_whatsapp_alerts_api.py`

**Interfaces:**
- Consumes: `Organization.whatsapp_alert_contacts` (Task 1), `WhatsAppAlertContact`/`CreateWhatsAppAlertContactRequest`/`UpdateWhatsAppAlertContactRequest` (Task 2), `AlertRule` model (existing), `require_role`/`get_current_user`/`get_db` (existing).
- Produces: `GET/POST /api/settings/whatsapp-alerts`, `PATCH/DELETE /api/settings/whatsapp-alerts/{contact_id}` — consumed by Task 4's frontend API client.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/test_whatsapp_alerts_api.py`:

```python
"""Tests for /api/settings/whatsapp-alerts — CRUD + sync to the catch-all AlertRule."""
import pytest
from sqlalchemy import select

from app.models.alert_rule import AlertRule

WHATSAPP_RULE_NAME = "WhatsApp Instant Alerts"


@pytest.mark.asyncio
async def test_list_contacts_empty(auth_client):
    resp = await auth_client.get("/api/settings/whatsapp-alerts")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_add_contact_defaults_disabled(auth_client):
    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "+911234567890"})
    assert resp.status_code == 201
    body = resp.json()
    assert len(body) == 1
    assert body[0]["number"] == "+911234567890"
    assert body[0]["enabled"] is False
    assert body[0]["id"]


@pytest.mark.asyncio
async def test_add_fifth_contact_rejected(auth_client):
    for i in range(4):
        resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": f"+9112345678{i:02d}"})
        assert resp.status_code == 201

    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "+919999999999"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_add_duplicate_number_rejected(auth_client):
    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "+911234567890"})
    assert resp.status_code == 201

    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "+911234567890"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_add_invalid_format_rejected(auth_client):
    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "not-a-number"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_toggle_on_creates_and_enables_catch_all_rule(auth_client, db_session, test_org):
    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "+911234567890"})
    contact_id = resp.json()[0]["id"]

    resp = await auth_client.patch(f"/api/settings/whatsapp-alerts/{contact_id}", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()[0]["enabled"] is True

    result = await db_session.execute(
        select(AlertRule).where(AlertRule.org_id == test_org.id, AlertRule.name == WHATSAPP_RULE_NAME)
    )
    rule = result.scalar_one()
    assert rule.enabled is True
    assert rule.notify_channels == ["whatsapp"]
    assert rule.notify_contacts == [{"type": "whatsapp", "value": "+911234567890"}]
    assert rule.cameras == []
    assert rule.event_types == []
    assert rule.min_severity == "low"


@pytest.mark.asyncio
async def test_toggle_off_only_enabled_contact_disables_rule(auth_client, db_session, test_org):
    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "+911234567890"})
    contact_id = resp.json()[0]["id"]
    await auth_client.patch(f"/api/settings/whatsapp-alerts/{contact_id}", json={"enabled": True})

    resp = await auth_client.patch(f"/api/settings/whatsapp-alerts/{contact_id}", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()[0]["enabled"] is False

    result = await db_session.execute(
        select(AlertRule).where(AlertRule.org_id == test_org.id, AlertRule.name == WHATSAPP_RULE_NAME)
    )
    rule = result.scalar_one()
    assert rule.enabled is False


@pytest.mark.asyncio
async def test_edit_number_while_enabled_updates_rule_contacts(auth_client, db_session, test_org):
    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "+911111111111"})
    contact_id = resp.json()[0]["id"]
    await auth_client.patch(f"/api/settings/whatsapp-alerts/{contact_id}", json={"enabled": True})

    resp = await auth_client.patch(f"/api/settings/whatsapp-alerts/{contact_id}", json={"number": "+912222222222"})
    assert resp.status_code == 200
    assert resp.json()[0]["number"] == "+912222222222"

    result = await db_session.execute(
        select(AlertRule).where(AlertRule.org_id == test_org.id, AlertRule.name == WHATSAPP_RULE_NAME)
    )
    rule = result.scalar_one()
    assert rule.notify_contacts == [{"type": "whatsapp", "value": "+912222222222"}]


@pytest.mark.asyncio
async def test_delete_enabled_contact_removes_from_rule(auth_client, db_session, test_org):
    resp = await auth_client.post("/api/settings/whatsapp-alerts", json={"number": "+911234567890"})
    contact_id = resp.json()[0]["id"]
    await auth_client.patch(f"/api/settings/whatsapp-alerts/{contact_id}", json={"enabled": True})

    resp = await auth_client.delete(f"/api/settings/whatsapp-alerts/{contact_id}")
    assert resp.status_code == 200
    assert resp.json() == []

    result = await db_session.execute(
        select(AlertRule).where(AlertRule.org_id == test_org.id, AlertRule.name == WHATSAPP_RULE_NAME)
    )
    rule = result.scalar_one()
    assert rule.enabled is False
    assert rule.notify_contacts == []


@pytest.mark.asyncio
async def test_patch_unknown_contact_404(auth_client):
    resp = await auth_client.patch("/api/settings/whatsapp-alerts/does-not-exist", json={"enabled": True})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_owner_forbidden(client, db_session, test_org):
    from app.core.security import hash_password
    from app.models.user import User

    viewer = User(
        org_id=test_org.id,
        username="viewer1",
        password_hash=hash_password("password123"),
        name="Viewer",
        role="viewer",
    )
    db_session.add(viewer)
    await db_session.flush()

    login_resp = await client.post("/api/auth/login", json={"username": "viewer1", "password": "password123"})
    token = login_resp.json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"

    resp = await client.post("/api/settings/whatsapp-alerts", json={"number": "+911234567890"})
    assert resp.status_code == 403
```

Note: if `client`/`auth_client`/`test_org`/`db_session` fixtures differ slightly from this shape (e.g. `User` requires more fields), match `backend/tests/conftest.py` exactly — read it before running.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/api/test_whatsapp_alerts_api.py -v`
Expected: FAIL — 404s, since none of these routes exist yet.

- [ ] **Step 3: Implement the sync helper and routes**

In `backend/app/api/settings.py`, add these imports near the top (alongside the existing ones):

```python
import re
from uuid import uuid4

from app.models.alert_rule import AlertRule
from app.schemas.whatsapp_alerts import (
    CreateWhatsAppAlertContactRequest,
    UpdateWhatsAppAlertContactRequest,
    WhatsAppAlertContact,
)
```

Then append this section at the end of `backend/app/api/settings.py`:

```python
# ── WhatsApp Instant Alerts (owner) ─────────────────────────────────────────

WHATSAPP_RULE_NAME = "WhatsApp Instant Alerts"
PHONE_RE = re.compile(r"^\+\d{8,15}$")


async def _get_org_or_404(db: AsyncSession, user: User) -> Organization:
    if not user.org_id:
        raise HTTPException(status_code=400, detail="No organization associated")
    result = await db.execute(select(Organization).where(Organization.id == user.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


async def _sync_whatsapp_alert_rule(org: Organization, db: AsyncSession) -> None:
    enabled_numbers = [c["number"] for c in org.whatsapp_alert_contacts if c["enabled"]]

    result = await db.execute(
        select(AlertRule).where(AlertRule.org_id == org.id, AlertRule.name == WHATSAPP_RULE_NAME)
    )
    rule = result.scalar_one_or_none()

    if not enabled_numbers:
        if rule:
            rule.enabled = False
            rule.notify_contacts = []
        return

    contacts = [{"type": "whatsapp", "value": n} for n in enabled_numbers]
    if rule:
        rule.notify_contacts = contacts
        rule.enabled = True
    else:
        db.add(
            AlertRule(
                org_id=org.id,
                name=WHATSAPP_RULE_NAME,
                cameras=[],
                event_types=[],
                min_severity="low",
                zones=[],
                notify_channels=["whatsapp"],
                notify_contacts=contacts,
                cooldown_seconds=60,
                enabled=True,
            )
        )


@router.get("/whatsapp-alerts", response_model=list[WhatsAppAlertContact])
async def list_whatsapp_alert_contacts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    org = await _get_org_or_404(db, user)
    return [WhatsAppAlertContact(**c) for c in org.whatsapp_alert_contacts]


@router.post("/whatsapp-alerts", response_model=list[WhatsAppAlertContact], status_code=201)
async def add_whatsapp_alert_contact(
    body: CreateWhatsAppAlertContactRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "owner")
    org = await _get_org_or_404(db, user)

    if len(org.whatsapp_alert_contacts) >= 4:
        raise HTTPException(status_code=400, detail="Maximum of 4 WhatsApp numbers per organization")
    if not PHONE_RE.match(body.number):
        raise HTTPException(status_code=400, detail="Number must be in +<countrycode><number> format")
    if any(c["number"] == body.number for c in org.whatsapp_alert_contacts):
        raise HTTPException(status_code=400, detail="This number is already added")

    org.whatsapp_alert_contacts = org.whatsapp_alert_contacts + [
        {"id": str(uuid4()), "number": body.number, "enabled": False}
    ]
    await _sync_whatsapp_alert_rule(org, db)
    await db.flush()
    return [WhatsAppAlertContact(**c) for c in org.whatsapp_alert_contacts]


@router.patch("/whatsapp-alerts/{contact_id}", response_model=list[WhatsAppAlertContact])
async def update_whatsapp_alert_contact(
    contact_id: str,
    body: UpdateWhatsAppAlertContactRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "owner")
    org = await _get_org_or_404(db, user)

    contacts = org.whatsapp_alert_contacts
    idx = next((i for i, c in enumerate(contacts) if c["id"] == contact_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    updated = dict(contacts[idx])
    if body.number is not None:
        if not PHONE_RE.match(body.number):
            raise HTTPException(status_code=400, detail="Number must be in +<countrycode><number> format")
        if any(c["number"] == body.number for c in contacts if c["id"] != contact_id):
            raise HTTPException(status_code=400, detail="This number is already added")
        updated["number"] = body.number
    if body.enabled is not None:
        updated["enabled"] = body.enabled

    new_contacts = list(contacts)
    new_contacts[idx] = updated
    org.whatsapp_alert_contacts = new_contacts

    await _sync_whatsapp_alert_rule(org, db)
    await db.flush()
    return [WhatsAppAlertContact(**c) for c in org.whatsapp_alert_contacts]


@router.delete("/whatsapp-alerts/{contact_id}", response_model=list[WhatsAppAlertContact])
async def delete_whatsapp_alert_contact(
    contact_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "owner")
    org = await _get_org_or_404(db, user)

    contacts = org.whatsapp_alert_contacts
    if not any(c["id"] == contact_id for c in contacts):
        raise HTTPException(status_code=404, detail="Contact not found")

    org.whatsapp_alert_contacts = [c for c in contacts if c["id"] != contact_id]
    await _sync_whatsapp_alert_rule(org, db)
    await db.flush()
    return [WhatsAppAlertContact(**c) for c in org.whatsapp_alert_contacts]
```

Also add `from app.models.organization import Organization` to the imports at the top of `backend/app/api/settings.py` if it isn't already there (it is — `get_my_org` already uses `Organization`).

**Important SQLAlchemy JSONB mutation note:** reassigning `org.whatsapp_alert_contacts = <new list>` (rather than mutating the existing list in place) is required for SQLAlchemy to detect the change on a plain JSONB column — this is why every write above builds a new list/dict instead of `.append()`/`in-place edit`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/api/test_whatsapp_alerts_api.py -v`
Expected: all tests PASS

- [ ] **Step 5: Run the full backend test suite to check for regressions**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS (no regressions in `test_alerts_api.py` or elsewhere)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/settings.py backend/tests/api/test_whatsapp_alerts_api.py
git commit -m "feat: add whatsapp alert contacts CRUD API with alert-rule sync"
```

---

### Task 4: Frontend types + API client methods

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: `GET/POST /api/settings/whatsapp-alerts`, `PATCH/DELETE /api/settings/whatsapp-alerts/{contact_id}` (Task 3).
- Produces: `WhatsAppAlertContact` type, `api.getWhatsAppAlertContacts()`, `api.addWhatsAppAlertContact(number)`, `api.updateWhatsAppAlertContact(id, data)`, `api.deleteWhatsAppAlertContact(id)` — consumed by Task 5.

- [ ] **Step 1: Add the type**

In `frontend/src/types/index.ts`, add after the `DigestPreferences` interface (around line 191):

```ts
export interface WhatsAppAlertContact {
  id: string;
  number: string;
  enabled: boolean;
}
```

- [ ] **Step 2: Add the API client methods**

In `frontend/src/lib/api.ts`, add after `resetTeamMemberPassword` (around line 242), still inside the `// Settings (org owner)` section:

```ts
  async getWhatsAppAlertContacts() {
    return this.request<WhatsAppAlertContact[]>("/api/settings/whatsapp-alerts");
  }

  async addWhatsAppAlertContact(number: string) {
    return this.request<WhatsAppAlertContact[]>("/api/settings/whatsapp-alerts", {
      method: "POST",
      body: JSON.stringify({ number }),
    });
  }

  async updateWhatsAppAlertContact(id: string, data: { number?: string; enabled?: boolean }) {
    return this.request<WhatsAppAlertContact[]>(`/api/settings/whatsapp-alerts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  }

  async deleteWhatsAppAlertContact(id: string) {
    return this.request<WhatsAppAlertContact[]>(`/api/settings/whatsapp-alerts/${id}`, { method: "DELETE" });
  }
```

Add `WhatsAppAlertContact` to the `import type { ... } from "@/types"` statement at the top of `frontend/src/lib/api.ts`.

- [ ] **Step 3: Verify the build compiles**

Run: `cd frontend && npm run build`
Expected: build succeeds with zero type errors (these are unused exports at this point, which is fine — Task 5 wires them up)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/lib/api.ts
git commit -m "feat: add whatsapp alert contact type and api client methods"
```

---

### Task 5: Settings page — convert to tabs, add WhatsApp Alerts tab

**Files:**
- Modify: `frontend/src/app/settings/page.tsx`

**Interfaces:**
- Consumes: `api.getWhatsAppAlertContacts`, `api.addWhatsAppAlertContact`, `api.updateWhatsAppAlertContact`, `api.deleteWhatsAppAlertContact` (Task 4); shadcn `Tabs`/`TabsList`/`TabsTrigger`/`TabsContent` from `@/components/ui/tabs`; `Switch` from `@/components/ui/switch` (both already installed per `frontend/CLAUDE.md`'s component list).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Convert the page body to Tabs, keeping existing sections intact**

Read the current `frontend/src/app/settings/page.tsx` in full before editing (192 lines from the file map earlier — `OrgSection`, `SiteSection`, `SiteEditor`, `TeamSection`, `InviteForm` are unchanged helper components below the page function).

Replace the `SettingsPage` function body (currently lines 9–64) with:

```tsx
export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuthStore();
  const isOwner = user?.role === "owner";
  const isSuperAdmin = user?.role === "super_admin";
  const canViewTeam = !!user?.org_id;

  const { data: org } = useQuery({
    queryKey: ["settings", "org"],
    queryFn: () => api.getMyOrg(),
    enabled: !!user?.org_id,
  });

  const { data: team } = useQuery({
    queryKey: ["settings", "team"],
    queryFn: () => api.getTeam(),
    enabled: canViewTeam,
  });

  const { data: sites } = useQuery({
    queryKey: ["settings", "sites"],
    queryFn: () => api.getSites(),
    enabled: !!user?.org_id,
  });

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-[#F5F5F5]">Settings</h1>

      {isSuperAdmin && (
        <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg">
          <p className="text-sm text-[#F5F5F5] mb-1">You are signed in as <span className="text-[#EF4444]">super_admin</span> (no org).</p>
          <p className="text-xs text-[#A3A3A3]">Use the <a href="/admin" className="text-[#1E90FF] hover:underline">Admin Panel</a> to manage all organizations and users across the platform.</p>
        </div>
      )}

      {user?.org_id && (
        <Tabs defaultValue="organization" className="w-full">
          <TabsList className="bg-[#111111] border border-[#2A2A2A]">
            <TabsTrigger value="organization">Organization</TabsTrigger>
            <TabsTrigger value="sites">Sites</TabsTrigger>
            <TabsTrigger value="team">Team</TabsTrigger>
            <TabsTrigger value="whatsapp-alerts">WhatsApp Alerts</TabsTrigger>
          </TabsList>

          <TabsContent value="organization" className="pt-4">
            {org && <OrgSection org={org} canEdit={isOwner} />}
          </TabsContent>

          <TabsContent value="sites" className="pt-4">
            {org && sites && isOwner && (
              <SiteSection
                sites={sites}
                onMutate={() => queryClient.invalidateQueries({ queryKey: ["settings", "sites"] })}
              />
            )}
          </TabsContent>

          <TabsContent value="team" className="pt-4">
            {canViewTeam && team && (
              <TeamSection
                team={team}
                currentUserId={user?.id || ""}
                canManage={isOwner}
                onMutate={() => queryClient.invalidateQueries({ queryKey: ["settings", "team"] })}
              />
            )}
          </TabsContent>

          <TabsContent value="whatsapp-alerts" className="pt-4">
            <WhatsAppAlertsSection canManage={isOwner} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
```

Add these imports at the top of the file, alongside the existing ones:

```tsx
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import type { WhatsAppAlertContact } from "@/types";
```

- [ ] **Step 2: Add the `WhatsAppAlertsSection` component**

Append this new component to the end of `frontend/src/app/settings/page.tsx` (after `InviteForm`):

```tsx
function WhatsAppAlertsSection({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: contacts } = useQuery({
    queryKey: ["settings", "whatsapp-alerts"],
    queryFn: () => api.getWhatsAppAlertContacts(),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["settings", "whatsapp-alerts"] });

  const addMutation = useMutation({
    mutationFn: (number: string) => api.addWhatsAppAlertContact(number),
    onSuccess: () => { setErrorMsg(null); setShowAdd(false); invalidate(); },
    onError: (e: Error) => setErrorMsg(e.message || "Could not add number."),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { number?: string; enabled?: boolean } }) =>
      api.updateWhatsAppAlertContact(id, data),
    onSuccess: () => { setErrorMsg(null); setEditingId(null); invalidate(); },
    onError: (e: Error) => setErrorMsg(e.message || "Could not update number."),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteWhatsAppAlertContact(id),
    onSuccess: () => { setErrorMsg(null); invalidate(); },
    onError: (e: Error) => setErrorMsg(e.message || "Could not remove number."),
  });

  const atMax = (contacts?.length ?? 0) >= 4;

  return (
    <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-[#F5F5F5]">WhatsApp Alerts</h2>
          <p className="text-xs text-[#A3A3A3]">Enabled numbers instantly receive every real-time event alert.</p>
        </div>
        {canManage && (
          <button
            onClick={() => setShowAdd((v) => !v)}
            disabled={atMax}
            className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded-md hover:bg-[#3BA0FF] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {showAdd ? "Close" : "+ Add Number"}
          </button>
        )}
      </div>

      {showAdd && canManage && (
        <WhatsAppContactForm
          onCancel={() => setShowAdd(false)}
          onSave={(number) => addMutation.mutate(number)}
          loading={addMutation.isPending}
        />
      )}

      {errorMsg && (
        <div className="text-xs text-red-400 bg-[#1A1A1A] border border-[#2A2A2A] rounded-md p-2">
          {errorMsg}
        </div>
      )}

      <div className="space-y-2">
        {!contacts || contacts.length === 0 ? (
          <div className="text-sm text-[#A3A3A3] border border-dashed border-[#2A2A2A] rounded-lg p-4">
            No WhatsApp numbers added yet.
          </div>
        ) : (
          contacts.map((contact: WhatsAppAlertContact) => (
            <div key={contact.id} className="p-3 rounded-lg border border-[#2A2A2A] bg-[#1A1A1A]">
              {editingId === contact.id ? (
                <WhatsAppContactForm
                  initialNumber={contact.number}
                  onCancel={() => setEditingId(null)}
                  onSave={(number) => updateMutation.mutate({ id: contact.id, data: { number } })}
                  loading={updateMutation.isPending}
                />
              ) : (
                <div className="flex items-center justify-between gap-4">
                  <span className="text-sm font-mono text-[#F5F5F5]">{contact.number}</span>
                  <div className="flex items-center gap-3">
                    {canManage && (
                      <Switch
                        checked={contact.enabled}
                        onCheckedChange={(checked) => updateMutation.mutate({ id: contact.id, data: { enabled: checked } })}
                      />
                    )}
                    {canManage && (
                      <>
                        <button
                          onClick={() => setEditingId(contact.id)}
                          className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#1E90FF] transition-colors"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => { if (window.confirm(`Remove ${contact.number} from instant alerts?`)) deleteMutation.mutate(contact.id); }}
                          className="text-xs px-2 py-1 text-[#A3A3A3] hover:text-[#EF4444] transition-colors"
                        >
                          Delete
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function WhatsAppContactForm({
  initialNumber,
  onSave,
  onCancel,
  loading,
}: {
  initialNumber?: string;
  onSave: (number: string) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [number, setNumber] = useState(initialNumber ?? "");

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); onSave(number.trim()); }}
      className="flex gap-2"
    >
      <input
        value={number}
        onChange={(e) => setNumber(e.target.value)}
        placeholder="+911234567890"
        pattern="^\+\d{8,15}$"
        title="Format: + followed by country code and number, e.g. +911234567890"
        className="flex-1 px-3 py-1.5 text-sm bg-[#1F1F1F] border border-[#2A2A2A] rounded text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
        required
      />
      <button type="submit" disabled={loading} className="px-3 py-1.5 bg-[#1E90FF] text-white text-sm rounded hover:bg-[#3BA0FF] disabled:opacity-50">
        {loading ? "Saving..." : "Save"}
      </button>
      <button type="button" onClick={onCancel} className="px-3 py-1.5 text-sm text-[#666666] hover:text-[#F5F5F5]">
        Cancel
      </button>
    </form>
  );
}
```

- [ ] **Step 3: Verify the build compiles**

Run: `cd frontend && npm run build`
Expected: build succeeds with zero type errors, `/settings` route compiles.

- [ ] **Step 4: Manual verification in the browser**

Run: `cd frontend && npm run dev` (with backend also running per the root `CLAUDE.md`'s "Running Locally" section)

1. Log in as an owner, go to `/settings`.
2. Confirm four tabs render: Organization, Sites, Team, WhatsApp Alerts.
3. On the WhatsApp Alerts tab, click "+ Add Number", enter `+911234567890`, save — row appears with the toggle **off**.
4. Flip the toggle on — no error shown, toggle stays on after a page refresh.
5. Add 3 more numbers (4 total) — confirm "+ Add Number" becomes disabled at 4.
6. Try adding a 5th — button should already be disabled (server would 400 if forced).
7. Click Edit on a row, change the number, save — row updates.
8. Click Delete on a row, confirm the browser confirm dialog, row disappears.
9. Log in as a non-owner (e.g. admin/operator) — confirm the Add/Edit/Delete/Switch controls are hidden (read-only `canManage=false` path).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/settings/page.tsx
git commit -m "feat: add WhatsApp Alerts tab to Settings with enable/disable toggles"
```

---

## Self-Review Notes

- **Spec coverage:** JSONB column + migration (Task 1), schemas (Task 2), 4 CRUD endpoints + sync helper + owner-only + validation + tests (Task 3), frontend types/API client (Task 4), Tabs conversion + WhatsAppAlertsSection with edit-in-place form + toggle (Task 5) — all spec sections covered. No worker/relay/agent changes, matching the spec's explicit non-goal.
- **Type consistency:** `WhatsAppAlertContact { id, number, enabled }` matches across backend schema (Task 2), backend route responses (Task 3), and frontend type/usage (Tasks 4–5). `_sync_whatsapp_alert_rule` and `WHATSAPP_RULE_NAME` names are consistent wherever referenced (Task 3 implementation and its own tests).
- **No placeholders:** every step ships complete, runnable code — no TODOs or "add validation here" left in any task.
