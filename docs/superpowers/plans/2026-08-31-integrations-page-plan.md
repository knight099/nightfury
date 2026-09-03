# Integrations Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a category-grouped Integrations directory page (`/app/integrations`) backed by a generic `integrations` catalog + per-org `integration_connections` registry, covering 9 categories (ACS, PACS, VMS, ERP, IWMS, POS, KDS, CRM, HRIS) with real seed data, where only the ERP/Tally row is ever wired to a real connector — every other row is bookkeeping only.

**Architecture:** Two new tables. `integrations` is a small admin-seeded catalog (never written to by users). `integration_connections` is the only table user actions touch — one row per (org, site-or-null, integration), storing opaque `config` JSONB no generic code reads. Four new API endpoints follow the existing `camera_setup.py` tenant-scoping pattern exactly. One new frontend route with four category-group sections of cards, reusing Settings' visual language.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + PostgreSQL (backend); Next.js App Router + TypeScript + Tailwind + shadcn/ui + TanStack Query (frontend).

**Spec:** `docs/superpowers/specs/2026-08-31-integrations-page-spec.md` — read Section 0 before starting; it defines the (one-directional, optional) seam with Camera-to-Books.

## Global Constraints

Every task's requirements implicitly include this section.

- **No `tenant_id`.** This codebase uses `org_id` (FK to `organizations.id`), plus `site_id` where a site is knowable.
- **Every read query needs both halves of tenant isolation:** an `org_id` filter (skipped only for `role == "super_admin"`) *plus* `scope_to_sites(query, <Model>.site_id, user)` where the model has a `site_id`. Copy the pattern from `backend/app/api/camera_setup.py:38-58` (`_load_site`, `_load_run`).
- **Never trust `org_id` from a request body.** Derive it from `get_current_user`.
- **Mutating routes require `require_role(user, "admin")`**, matching `camera_setup.py`'s `start_setup_run`.
- **`integrations` is admin-seeded, not user-writable.** No API in this plan creates or edits catalog rows — only a data migration does (Task 1).
- **`config` on `integration_connections` is opaque.** No generic route or frontend code branches on its contents. Only a real connector (Tally, later others) interprets its own `config` shape.
- **No test files.** The repo owner's standing preference is direct implementation plus structured self-review. Every task ends with an explicit manual verification step and a self-review checklist.
- **Dark mode only** on the frontend, using the existing hex palette (`#0D0D0D`, `#111111`, `#1A1A1A`, `#2A2A2A`, `#F5F5F5`, `#A3A3A3`, `#1E90FF`) already used in `settings/page.tsx` and `sidebar.tsx`. No light-mode styles, no new component primitives.
- **`npm run build` must pass** in `frontend/` before any frontend task is considered done.
- **`python3 -c "from app.main import app"` must pass** from `backend/` before any backend task is considered done.
- **Alembic head resolution (do this once, in Task 0, before writing the migration):** as of this plan's writing the head is `80f8c57dc838` (`backend/alembic/versions/80f8c57dc838_assistant_proposals.py`). If Camera-to-Books Phase 1 has landed by the time this task runs, its migrations (`a1b2c3d4e5f6_camera_role`, `b2c3d4e5f6a7_workflow_tables`) will be ahead of it — chain off whichever is the actual current head, found by running the check in Task 0 Step 1. Do not create a second head.
- **Commit after every task**, using the message given in the task's final step. This applies to code files only — do not commit anything under `docs/` as part of this plan; the spec and plan documents are already in place and are the repo owner's to commit.

---

## File Structure

**Backend — created**

| File | Responsibility |
|---|---|
| `backend/app/models/integration.py` | `Integration`, `IntegrationConnection` models |
| `backend/app/schemas/integration.py` | Request/response models for the integrations API |
| `backend/app/api/integrations.py` | The four endpoints: list catalog, list connections, connect, disconnect |
| `backend/alembic/versions/<rev>_integrations.py` | Task 1 migration — creates both tables and seeds the 9-row catalog |

**Backend — modified**

| File | Change |
|---|---|
| `backend/app/models/__init__.py` | registers `Integration`, `IntegrationConnection` |
| `backend/app/main.py` | registers `integrations_router` |

**Frontend — created**

| File | Change |
|---|---|
| `frontend/src/app/integrations/layout.tsx` | Wraps page in `AppShell`, same as `settings/layout.tsx` |
| `frontend/src/app/integrations/page.tsx` | The directory page: 4 group sections, cards, connect/disconnect dialogs |
| `frontend/src/components/integrations/integration-card.tsx` | One category card: name, description, vendors, status pill, action |
| `frontend/src/components/integrations/connect-dialog.tsx` | Config form + connect/disconnect actions |

**Frontend — modified**

| File | Change |
|---|---|
| `frontend/src/lib/api.ts` | four new client methods |
| `frontend/src/types/index.ts` | `Integration`, `IntegrationConnection`, `IntegrationCategory` types |
| `frontend/src/components/layout/sidebar.tsx` | new "Integrations" nav entry |
| `frontend/src/components/layout/app-shell.tsx` | same nav entry for the `/app` shell |

---

### Task 0: Resolve the current alembic head

**Files:** none modified — this is a read-only check that determines a value Task 1 needs.

**Interfaces:**
- Consumes: nothing.
- Produces: the exact `down_revision` string Task 1's migration must use.

- [ ] **Step 1: Find the actual current head**

```bash
cd backend && python3 - <<'EOF'
import os, re
d = "alembic/versions"
revs, downs = {}, {}
for f in os.listdir(d):
    if not f.endswith(".py"):
        continue
    txt = open(os.path.join(d, f)).read()
    r = re.search(r'revision:.*=\s*["\'](\w+)["\']', txt)
    dr = re.search(r'down_revision.*=\s*["\']?(\w+)["\']?', txt)
    if r:
        revs[r.group(1)] = f
        downs[r.group(1)] = dr.group(1) if dr else None
heads = set(revs) - set(v for v in downs.values() if v)
print("HEAD(S):", heads)
for h in heads:
    print(h, revs[h])
EOF
```

Expected: exactly one head printed. If it is `80f8c57dc838`, use that as Task 1's `down_revision`. If Camera-to-Books has landed and the head is `b2c3d4e5f6a7` (its `workflow_tables` migration) or later, use that value instead. If more than one head prints, stop — a branch exists and must be resolved (an `alembic merge`) before continuing; do not guess.

- [ ] **Step 2: Record the value**

Write the resolved head string down — Task 1 Step 2 references it as `<RESOLVED_HEAD>`.

---

### Task 1: Data model + seed migration

**Files:**
- Create: `backend/app/models/integration.py`
- Create: `backend/alembic/versions/<rev>_integrations.py` (pick a fresh 12-hex-char revision id, e.g. `c3d4e5f6a7b8`)
- Modify: `backend/app/models/__init__.py`

**Interfaces:**
- Consumes: Task 0's `<RESOLVED_HEAD>`.
- Produces:
  - `Integration`: `id, category, name, vendor, status, description, created_at`
  - `IntegrationConnection`: `id, org_id, site_id, integration_id, status, config, error_message, connected_at, connected_by, created_at, updated_at`
  - `INTEGRATION_CATEGORIES` and `CONNECTION_STATUSES` tuples, importable from `app.models.integration`, that Task 2's schemas and Task 3's routes both import rather than re-declaring.

- [ ] **Step 1: Write the models**

`backend/app/models/integration.py`:

```python
"""The Integrations directory: a category-grouped catalog of external
systems a site may run, and a per-org record of which ones it says it uses.

`Integration` is a small admin-seeded catalog — never written to by a user
request in this codebase. `IntegrationConnection` is the only table a user
action touches, and its `config` column is opaque here: no code in this
module ever reads a key out of it. Only a specific connector (Tally today,
under category `erp`) interprets its own `config` shape. Every other
category's `config` is bookkeeping only until that category gets a real
connector, at which point that connector's code — not this module — starts
reading it.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Closed on purpose — this list renders as section headers on a customer-
# facing page. Adding a 10th category is a migration, which is the right
# cost for something users read by name.
INTEGRATION_CATEGORIES = (
    "acs",
    "pacs",
    "vms",
    "erp",
    "iwms",
    "pos",
    "kds",
    "crm",
    "hris",
)

INTEGRATION_STATUSES = ("available", "coming_soon")
CONNECTION_STATUSES = ("not_connected", "pending", "connected", "error")


def _sql_in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Integration(Base):
    """One connectable system in the catalog. Not per-org.

    Seeded by the Task 1 migration, not by any API in this codebase. A row
    with status='coming_soon' renders in the UI but is not clickable to
    connect.
    """

    __tablename__ = "integrations"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({_sql_in(INTEGRATION_CATEGORIES)})", name="ck_integrations_category"
        ),
        CheckConstraint(
            f"status IN ({_sql_in(INTEGRATION_STATUSES)})", name="ck_integrations_status"
        ),
        Index("ix_integrations_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="coming_soon")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IntegrationConnection(Base):
    """One org's (or org+site's) connection state for one catalog entry.

    The only table a user action writes to. `site_id` is nullable because
    some integrations (an org-wide CRM, for instance) are not site-scoped;
    when it is null the connection applies org-wide.
    """

    __tablename__ = "integration_connections"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_in(CONNECTION_STATUSES)})", name="ck_integration_connections_status"
        ),
        UniqueConstraint(
            "org_id", "site_id", "integration_id", name="uq_integration_connection_scope"
        ),
        Index("ix_integration_connections_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id"), nullable=True
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_connected")
    # Opaque to every route in this module. Shape is whatever the eventual
    # connector for this integration needs — a base URL for Tally, an API
    # key for a CRM, or nothing at all for a not-yet-built one.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 2: Register the models**

In `backend/app/models/__init__.py`, add the import after the last existing model import:

```python
from app.models.integration import Integration, IntegrationConnection
```

and add `"Integration"`, `"IntegrationConnection"` to `__all__`.

- [ ] **Step 3: Write the migration, chaining off `<RESOLVED_HEAD>` from Task 0**

`backend/alembic/versions/c3d4e5f6a7b8_integrations.py` (replace `<RESOLVED_HEAD>` with the value Task 0 found):

```python
"""integrations directory — catalog + per-org connection registry

Revision ID: c3d4e5f6a7b8
Revises: <RESOLVED_HEAD>
Create Date: 2026-08-31

Purely additive. Seeds the 9-category catalog with real display data so the
page is demoable immediately; no existing table is touched.
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "<RESOLVED_HEAD>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORIES_SQL = "'acs','pacs','vms','erp','iwms','pos','kds','crm','hris'"
STATUSES_SQL = "'available','coming_soon'"
CONN_STATUSES_SQL = "'not_connected','pending','connected','error'"

# (category, name, vendor, status, description)
SEED_ROWS = [
    ("acs", "Access Control System", "Brivo, Verkada, + your own",
     "coming_soon",
     "24/7 keyless entry that checks a live membership and catches "
     "tailgating with nobody at the desk."),
    ("pacs", "Physical Access Control System", "Genetec, Avigilon, Brivo, + your own",
     "coming_soon",
     "Enterprise door controllers, credential readers, and on-prem "
     "servers, managed across every site."),
    ("vms", "Visitor Management System", None,
     "coming_soon",
     "Sign-in kiosks and expected-visitor lists, so an unscheduled "
     "arrival is flagged instead of assumed normal."),
    ("erp", "Tally", "Tally Solutions",
     "available",
     "Purchase orders, GRNs, invoices, and stock data — the system of "
     "record the Camera-to-Books workflow layer reconciles against."),
    ("erp", "Enterprise Resource Planning", "SAP B1, Zoho Books, + your own",
     "coming_soon",
     "Purchase/inventory/finance system of record, beyond Tally."),
    ("iwms", "Integrated Workplace Management System", None,
     "coming_soon",
     "Space, asset, and facilities management for office and campus sites."),
    ("pos", "Point of Sale", None,
     "coming_soon",
     "Transaction data for retail and food-service sites."),
    ("kds", "Kitchen Display System", None,
     "coming_soon",
     "Order and prep timing for quick-service and restaurant sites."),
    ("crm", "Customer Relationship Management", None,
     "coming_soon",
     "Customer and lead records."),
    ("hris", "Human Resource Information System", None,
     "coming_soon",
     "Employee roster and shift schedules."),
]

integrations_table = sa.table(
    "integrations",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("category", sa.String),
    sa.column("name", sa.String),
    sa.column("vendor", sa.String),
    sa.column("status", sa.String),
    sa.column("description", sa.Text),
)


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("vendor", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="coming_soon"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_integrations_category", "integrations", f"category IN ({CATEGORIES_SQL})"
    )
    op.create_check_constraint(
        "ck_integrations_status", "integrations", f"status IN ({STATUSES_SQL})"
    )
    op.create_index("ix_integrations_category", "integrations", ["category"])

    op.create_table(
        "integration_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("site_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sites.id"), nullable=True),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("integrations.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="not_connected"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        "ck_integration_connections_status",
        "integration_connections",
        f"status IN ({CONN_STATUSES_SQL})",
    )
    op.create_unique_constraint(
        "uq_integration_connection_scope",
        "integration_connections",
        ["org_id", "site_id", "integration_id"],
    )
    op.create_index("ix_integration_connections_org", "integration_connections", ["org_id"])

    op.bulk_insert(
        integrations_table,
        [
            {
                "id": uuid.uuid4(),
                "category": category,
                "name": name,
                "vendor": vendor,
                "status": status,
                "description": description,
            }
            for category, name, vendor, status, description in SEED_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_table("integration_connections")
    op.drop_table("integrations")
```

- [ ] **Step 4: Apply and verify**

```bash
cd backend && uv run alembic upgrade head
```

```bash
psql "$POSTGRES_URL" -c "select category, name, status from integrations order by category;"
```

Expected: 10 rows (2 under `erp`, one per other category), `erp`/`Tally` the only `available` row.

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Self-review**

- Does the CHECK constraint actually reject a bad category? Verify: `psql "$POSTGRES_URL" -c "insert into integrations (id, category, name, status) values (gen_random_uuid(), 'not_a_category', 'x', 'coming_soon');"` — expect a constraint violation.
- Does `uq_integration_connection_scope` correctly allow the same `integration_id` for two different orgs, and reject a duplicate within one org+site? (Verify by hand with two inserts once Task 3's connect route exists — note this check as still-pending if verified only by reading the constraint definition now.)
- Is `config` read anywhere in this file? (It must not be — grep `config\[` and `config.get` in `integration.py`, expect no output.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/integration.py backend/app/models/__init__.py backend/alembic/versions/c3d4e5f6a7b8_integrations.py
git commit -m "feat(integrations): add catalog + connection tables, seed 9 categories"
```

---

### Task 2: Schemas

**Files:**
- Create: `backend/app/schemas/integration.py`

**Interfaces:**
- Consumes: Task 1's `Integration`, `IntegrationConnection` models and `INTEGRATION_CATEGORIES`/`CONNECTION_STATUSES` tuples.
- Produces: `IntegrationResponse`, `IntegrationConnectionResponse`, `ConnectRequest`, `IntegrationsCatalogResponse` — Task 3's routes import all four by these exact names.

- [ ] **Step 1: Write the schemas**

`backend/app/schemas/integration.py`:

```python
"""Wire shapes for the Integrations directory API."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    name: str
    vendor: str | None = None
    status: str
    description: str | None = None


class IntegrationsCatalogResponse(BaseModel):
    integrations: list[IntegrationResponse] = Field(default_factory=list)


class IntegrationConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    site_id: uuid.UUID | None = None
    integration_id: uuid.UUID
    status: str
    error_message: str | None = None
    connected_at: datetime | None = None
    connected_by: uuid.UUID | None = None
    updated_at: datetime


class ConnectionsListResponse(BaseModel):
    connections: list[IntegrationConnectionResponse] = Field(default_factory=list)


class ConnectRequest(BaseModel):
    site_id: uuid.UUID | None = None
    # Opaque bag of whatever fields that integration's connect form
    # collected. Never inspected by the route — see integration.py's
    # module docstring for why.
    config: dict = Field(default_factory=dict)
```

- [ ] **Step 2: Verify imports resolve**

```bash
cd backend && uv run python3 -c "from app.schemas.integration import IntegrationResponse, IntegrationsCatalogResponse, IntegrationConnectionResponse, ConnectionsListResponse, ConnectRequest; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Self-review**

- Does `ConnectRequest.config` have any field-level validation that would reject a legitimate but unanticipated key from a future connector's form? (It must not — `dict` with no nested model, confirm.)
- Are all response models using `from_attributes=True` so they can validate directly off the ORM objects Task 3 returns? (Confirm both response classes have it.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/integration.py
git commit -m "feat(integrations): add API schemas"
```

---

### Task 3: API routes

**Files:**
- Create: `backend/app/api/integrations.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: Task 1's models, Task 2's schemas, `app.core.dependencies.get_current_user`, `require_role`, `scope_to_sites` (pattern from `camera_setup.py:38-58`).
- Produces:
  - `GET /api/integrations` → `IntegrationsCatalogResponse` — full catalog, no auth beyond being logged in, no org filter (the catalog is not per-org).
  - `GET /api/integrations/connections?site_id=` → `ConnectionsListResponse` — this org's connections, `site_id` optional filter.
  - `POST /api/integrations/{integration_id}/connect` → `IntegrationConnectionResponse`.
  - `POST /api/integrations/{integration_id}/disconnect` → `IntegrationConnectionResponse`.

- [ ] **Step 1: Write the router**

`backend/app/api/integrations.py`:

```python
"""Operator-facing endpoints for the Integrations directory.

Connecting an integration is bookkeeping in this codebase today, except
where a real connector already exists (Tally, under category `erp`) — see
the module docstring on `app.models.integration` for why `config` is never
inspected here.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role, scope_to_sites
from app.models.integration import Integration, IntegrationConnection
from app.models.site import Site
from app.models.user import User
from app.schemas.integration import (
    ConnectionsListResponse,
    ConnectRequest,
    IntegrationConnectionResponse,
    IntegrationResponse,
    IntegrationsCatalogResponse,
)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


async def _load_integration(integration_id: uuid.UUID, db: AsyncSession) -> Integration:
    integration = (
        await db.execute(select(Integration).where(Integration.id == integration_id))
    ).scalar_one_or_none()
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


async def _load_site_if_given(
    site_id: uuid.UUID | None, user: User, db: AsyncSession
) -> Site | None:
    if site_id is None:
        return None
    q = select(Site).where(Site.id == site_id, Site.deleted_at.is_(None))
    if user.role != "super_admin":
        q = q.where(Site.org_id == user.org_id)
    q = scope_to_sites(q, Site.id, user)
    site = (await db.execute(q)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.get("", response_model=IntegrationsCatalogResponse)
async def list_integrations(db: AsyncSession = Depends(get_db)):
    """The full catalog. Not per-org — every org sees the same list."""
    result = await db.execute(select(Integration).order_by(Integration.category, Integration.name))
    return IntegrationsCatalogResponse(
        integrations=[IntegrationResponse.model_validate(i) for i in result.scalars().all()]
    )


@router.get("/connections", response_model=ConnectionsListResponse)
async def list_connections(
    site_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.org_id is None:
        return ConnectionsListResponse(connections=[])
    q = select(IntegrationConnection).where(IntegrationConnection.org_id == user.org_id)
    if site_id is not None:
        q = q.where(IntegrationConnection.site_id == site_id)
    q = scope_to_sites(q, IntegrationConnection.site_id, user)
    result = await db.execute(q)
    return ConnectionsListResponse(
        connections=[
            IntegrationConnectionResponse.model_validate(c) for c in result.scalars().all()
        ]
    )


@router.post("/{integration_id}/connect", response_model=IntegrationConnectionResponse)
async def connect_integration(
    integration_id: uuid.UUID,
    body: ConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")
    if user.org_id is None:
        raise HTTPException(status_code=400, detail="Super admin must act within an org")

    integration = await _load_integration(integration_id, db)
    if integration.status != "available":
        raise HTTPException(
            status_code=400, detail="This integration is not yet available to connect"
        )
    site = await _load_site_if_given(body.site_id, user, db)

    existing = (
        await db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.org_id == user.org_id,
                IntegrationConnection.site_id == (site.id if site else None),
                IntegrationConnection.integration_id == integration.id,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.status = "connected"
        existing.config = body.config
        existing.error_message = None
        existing.connected_at = now
        existing.connected_by = user.id
        connection = existing
    else:
        connection = IntegrationConnection(
            org_id=user.org_id,
            site_id=site.id if site else None,
            integration_id=integration.id,
            status="connected",
            config=body.config,
            connected_at=now,
            connected_by=user.id,
        )
        db.add(connection)

    await db.commit()
    await db.refresh(connection)
    return IntegrationConnectionResponse.model_validate(connection)


@router.post("/{integration_id}/disconnect", response_model=IntegrationConnectionResponse)
async def disconnect_integration(
    integration_id: uuid.UUID,
    site_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_role(user, "admin")
    if user.org_id is None:
        raise HTTPException(status_code=400, detail="Super admin must act within an org")

    site = await _load_site_if_given(site_id, user, db)

    connection = (
        await db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.org_id == user.org_id,
                IntegrationConnection.site_id == (site.id if site else None),
                IntegrationConnection.integration_id == integration_id,
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="No connection found")

    # Bookkeeping reset, not a delete — historical sync data (e.g. Camera-
    # to-Books' connector_sync_log) is untouched, and the row stays as the
    # record that this org once connected and later disconnected it.
    connection.status = "not_connected"
    connection.error_message = None
    await db.commit()
    await db.refresh(connection)
    return IntegrationConnectionResponse.model_validate(connection)
```

- [ ] **Step 2: Register the router**

In `backend/app/main.py`, add the import next to the other routers:

```python
from app.api.integrations import router as integrations_router
```

and add `app.include_router(integrations_router)` next to the other `include_router` calls (after `app.include_router(digests_router)` is a fine spot).

- [ ] **Step 3: Verify imports and routes**

```bash
cd backend && uv run python3 -c "from app.main import app; print('ok')"
```

Expected: `ok`.

Start the backend and confirm the routes exist:

```bash
curl -s localhost:8080/openapi.json | python3 -c "import json,sys; d=json.load(sys.stdin); print([p for p in d['paths'] if 'integrations' in p])"
```

Expected: `['/api/integrations', '/api/integrations/connections', '/api/integrations/{integration_id}/connect', '/api/integrations/{integration_id}/disconnect']`.

- [ ] **Step 4: Verify the full connect/disconnect cycle by hand**

```bash
TOKEN="<a real Bearer token for an admin user — log in via the frontend or /api/auth/login>"
curl -s localhost:8080/api/integrations -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -20
```

Expected: 10 rows, Tally the only `"status": "available"`.

```bash
TALLY_ID=$(curl -s localhost:8080/api/integrations -H "Authorization: Bearer $TOKEN" | python3 -c "import json,sys; d=json.load(sys.stdin); print([i['id'] for i in d['integrations'] if i['name']=='Tally'][0])")
curl -s -X POST "localhost:8080/api/integrations/$TALLY_ID/connect" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"config":{"base_url":"http://localhost:9000"}}' | python3 -m json.tool
```

Expected: `"status": "connected"`.

```bash
curl -s "localhost:8080/api/integrations/connections" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: one connection row, `status: connected`.

```bash
curl -s -X POST "localhost:8080/api/integrations/$TALLY_ID/disconnect" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Expected: `"status": "not_connected"`.

Also confirm a non-`available` integration is rejected:

```bash
POS_ID=$(curl -s localhost:8080/api/integrations -H "Authorization: Bearer $TOKEN" | python3 -c "import json,sys; d=json.load(sys.stdin); print([i['id'] for i in d['integrations'] if i['category']=='pos'][0])")
curl -s -o /dev/null -w '%{http_code}\n' -X POST "localhost:8080/api/integrations/$POS_ID/connect" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"config":{}}'
```

Expected: `400`.

- [ ] **Step 5: Verify tenant isolation**

Log in as a user from a *different* org, list connections, and confirm the first org's Tally connection does not appear. Then, as a non-admin user in the same org, attempt `connect` and confirm `403`.

- [ ] **Step 6: Self-review**

- Does `connect_integration` read any key out of `body.config` before storing it? (It must not — grep `body.config\[` and `body.config.get`, expect no output except the assignment itself.)
- Is `list_integrations` accidentally scoped by org? (It must not be — the catalog is shared. Confirm no `org_id` filter appears in that function.)
- Does `disconnect_integration`'s site lookup use the same `scope_to_sites` + `org_id` pattern as `connect_integration`'s, so a user can't disconnect another org's connection by guessing an `integration_id`? (The `IntegrationConnection` query filters on `org_id == user.org_id` in both — confirm.)
- Does re-connecting an already-connected integration create a duplicate row, or update in place? (It must update in place — the `existing` branch — confirm the unique constraint from Task 1 backs this up rather than relying on the code alone.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/integrations.py backend/app/main.py
git commit -m "feat(integrations): add catalog, connections, connect/disconnect API"
```

---

### Task 4: Frontend types and API client

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: Task 3's response shapes.
- Produces: `Integration`, `IntegrationConnection`, `IntegrationCategory` types; `api.getIntegrations()`, `api.getIntegrationConnections(siteId?)`, `api.connectIntegration(id, body)`, `api.disconnectIntegration(id, siteId?)` — Task 5's page imports all four by these exact names.

- [ ] **Step 1: Add the types**

In `frontend/src/types/index.ts`, add:

```ts
export type IntegrationCategory =
  | "acs"
  | "pacs"
  | "vms"
  | "erp"
  | "iwms"
  | "pos"
  | "kds"
  | "crm"
  | "hris";

export interface Integration {
  id: string;
  category: IntegrationCategory;
  name: string;
  vendor: string | null;
  status: "available" | "coming_soon";
  description: string | null;
}

export interface IntegrationConnection {
  id: string;
  org_id: string;
  site_id: string | null;
  integration_id: string;
  status: "not_connected" | "pending" | "connected" | "error";
  error_message: string | null;
  connected_at: string | null;
  connected_by: string | null;
  updated_at: string;
}
```

- [ ] **Step 2: Add the client methods**

In `frontend/src/lib/api.ts`, add `Integration` and `IntegrationConnection` to the type-only import block at the top, and add these methods on the `ApiClient` class near `getSites`/`getMyOrg`:

```ts
  async getIntegrations() {
    return this.request<{ integrations: Integration[] }>("/api/integrations");
  }

  async getIntegrationConnections(siteId?: string) {
    const qs = siteId ? `?site_id=${siteId}` : "";
    return this.request<{ connections: IntegrationConnection[] }>(
      `/api/integrations/connections${qs}`
    );
  }

  async connectIntegration(
    integrationId: string,
    body: { site_id?: string; config: Record<string, unknown> }
  ) {
    return this.request<IntegrationConnection>(
      `/api/integrations/${integrationId}/connect`,
      { method: "POST", body: JSON.stringify(body) }
    );
  }

  async disconnectIntegration(integrationId: string, siteId?: string) {
    const qs = siteId ? `?site_id=${siteId}` : "";
    return this.request<IntegrationConnection>(
      `/api/integrations/${integrationId}/disconnect${qs}`,
      { method: "POST" }
    );
  }
```

Before writing these, check the exact name and signature of the existing request helper:

```bash
cd frontend && grep -n "private async request\|async request<" src/lib/api.ts | head -5
```

Use whatever that helper is actually called and however it actually takes `method`/`body` — match its real signature rather than the illustrative call above if they differ.

- [ ] **Step 3: Verify the build**

```bash
cd frontend && npm run build
```

Expected: build passes.

- [ ] **Step 4: Self-review**

- Do the four new methods match Task 3's exact routes and HTTP methods? (`GET /api/integrations`, `GET /api/integrations/connections`, `POST .../connect`, `POST .../disconnect` — confirm each.)
- Does `IntegrationConnection.status` in the frontend type list the same four values as `CONNECTION_STATUSES` in `backend/app/models/integration.py`? (Confirm no drift.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/lib/api.ts
git commit -m "feat(integrations): add frontend types and API client methods"
```

---

### Task 5: Integration card component

**Files:**
- Create: `frontend/src/components/integrations/integration-card.tsx`

**Interfaces:**
- Consumes: Task 4's `Integration`, `IntegrationConnection` types.
- Produces: `IntegrationCard` component — `props: { integration: Integration; connection: IntegrationConnection | undefined; onConnectClick: () => void; onDisconnectClick: () => void }`. Task 7's page imports this by this exact name and prop shape.

- [ ] **Step 1: Write the component**

`frontend/src/components/integrations/integration-card.tsx`:

```tsx
"use client";

import type { Integration, IntegrationConnection } from "@/types";

interface IntegrationCardProps {
  integration: Integration;
  connection: IntegrationConnection | undefined;
  onConnectClick: () => void;
  onDisconnectClick: () => void;
}

function statusPill(integration: Integration, connection: IntegrationConnection | undefined) {
  if (integration.status === "coming_soon") {
    return (
      <span className="px-2 py-0.5 text-xs rounded-full bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A]">
        Coming soon
      </span>
    );
  }
  if (connection?.status === "connected") {
    return (
      <span className="px-2 py-0.5 text-xs rounded-full bg-[#16A34A]/10 text-[#16A34A] border border-[#16A34A]/30">
        Connected
      </span>
    );
  }
  if (connection?.status === "error") {
    return (
      <span className="px-2 py-0.5 text-xs rounded-full bg-[#EF4444]/10 text-[#EF4444] border border-[#EF4444]/30">
        Error
      </span>
    );
  }
  return (
    <span className="px-2 py-0.5 text-xs rounded-full bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A]">
      Not connected
    </span>
  );
}

export function IntegrationCard({
  integration,
  connection,
  onConnectClick,
  onDisconnectClick,
}: IntegrationCardProps) {
  const isConnected = connection?.status === "connected";
  const isClickable = integration.status === "available";

  return (
    <div className="p-4 bg-[#111111] border border-[#2A2A2A] rounded-lg flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-[#F5F5F5]">{integration.name}</h3>
          {integration.vendor && (
            <p className="text-xs text-[#A3A3A3] mt-0.5">{integration.vendor}</p>
          )}
        </div>
        {statusPill(integration, connection)}
      </div>

      {integration.description && (
        <p className="text-xs text-[#A3A3A3] leading-relaxed">{integration.description}</p>
      )}

      {isClickable && (
        <button
          onClick={isConnected ? onDisconnectClick : onConnectClick}
          className={`self-start px-3 py-1.5 text-sm rounded-md transition-colors ${
            isConnected
              ? "text-[#EF4444] hover:bg-[#EF4444]/10 border border-[#2A2A2A]"
              : "bg-[#1E90FF] text-white hover:bg-[#1E90FF]/90"
          }`}
        >
          {isConnected ? "Disconnect" : "Connect"}
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify the build**

```bash
cd frontend && npm run build
```

Expected: build passes (the component isn't imported anywhere yet, so this only checks it compiles standalone — a stray import error would still surface as a type error since it's inside `src/`).

- [ ] **Step 3: Self-review**

- Does the card ever render a "Connect" button for a `coming_soon` integration? (It must not — `isClickable` gates the whole button block, confirm.)
- Does the color palette match exactly what `settings/page.tsx` already uses (`#111111`, `#2A2A2A`, `#F5F5F5`, `#A3A3A3`, `#1E90FF`)? (Confirm no new hex values were introduced except the two new semantic ones — green for connected, red for error/disconnect — which don't exist in Settings but are a reasonable, minimal addition; note this as an intentional new addition, not drift.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/integrations/integration-card.tsx
git commit -m "feat(integrations): add integration card component"
```

---

### Task 6: Connect dialog component

**Files:**
- Create: `frontend/src/components/integrations/connect-dialog.tsx`

**Interfaces:**
- Consumes: Task 4's `Integration` type.
- Produces: `ConnectDialog` component — `props: { integration: Integration; open: boolean; onClose: () => void; onSubmit: (config: Record<string, string>) => void; isSubmitting: boolean }`. Task 7's page imports this by this exact name and prop shape.

**Field list rationale (spec Section 4):** a static per-integration field list, not a generic JSON-schema form — there is exactly one real connector (Tally) to design fields for, and a schema-driven form would be designed against a sample size of one.

- [ ] **Step 1: Write the component**

`frontend/src/components/integrations/connect-dialog.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { Integration } from "@/types";

interface ConnectDialogProps {
  integration: Integration;
  open: boolean;
  onClose: () => void;
  onSubmit: (config: Record<string, string>) => void;
  isSubmitting: boolean;
}

// One entry per `available` integration's `name`. Every integration.status
// that isn't `available` never reaches this dialog (the card gates it), so
// this list only needs to cover integrations that are actually connectable
// today.
const CONFIG_FIELDS: Record<string, { key: string; label: string; placeholder: string }[]> = {
  Tally: [
    { key: "base_url", label: "Tally base URL", placeholder: "http://localhost:9000" },
  ],
};

export function ConnectDialog({
  integration,
  open,
  onClose,
  onSubmit,
  isSubmitting,
}: ConnectDialogProps) {
  const fields = CONFIG_FIELDS[integration.name] ?? [
    { key: "notes", label: "Notes (optional)", placeholder: "Anything we should know" },
  ];
  const [values, setValues] = useState<Record<string, string>>({});

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md p-5 bg-[#111111] border border-[#2A2A2A] rounded-lg space-y-4">
        <h2 className="text-base font-medium text-[#F5F5F5]">Connect {integration.name}</h2>
        <div className="space-y-3">
          {fields.map((f) => (
            <div key={f.key} className="space-y-1">
              <label className="text-xs text-[#A3A3A3]">{f.label}</label>
              <input
                type="text"
                placeholder={f.placeholder}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                className="w-full px-3 py-2 text-sm bg-[#0D0D0D] border border-[#2A2A2A] rounded-md text-[#F5F5F5] focus:outline-none focus:border-[#1E90FF]"
              />
            </div>
          ))}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md text-[#A3A3A3] hover:text-[#F5F5F5]"
          >
            Cancel
          </button>
          <button
            onClick={() => onSubmit(values)}
            disabled={isSubmitting}
            className="px-3 py-1.5 text-sm rounded-md bg-[#1E90FF] text-white hover:bg-[#1E90FF]/90 disabled:opacity-50"
          >
            {isSubmitting ? "Connecting..." : "Connect"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the build**

```bash
cd frontend && npm run build
```

Expected: build passes.

- [ ] **Step 3: Self-review**

- Does `onSubmit` ever get called with a key the backend's `ConnectRequest.config` would reject? (It can't — `config` is an unvalidated `dict` in Task 2, confirm.)
- Is there a fallback field set for an `available` integration not in `CONFIG_FIELDS`? (Yes — the `?? [...]` default. Confirm it renders instead of crashing.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/integrations/connect-dialog.tsx
git commit -m "feat(integrations): add connect dialog component"
```

---

### Task 7: Integrations page + nav entry

**Files:**
- Create: `frontend/src/app/integrations/layout.tsx`
- Create: `frontend/src/app/integrations/page.tsx`
- Modify: `frontend/src/components/layout/sidebar.tsx`
- Modify: `frontend/src/components/layout/app-shell.tsx`

**Interfaces:**
- Consumes: Task 4's API client methods and types, Task 5's `IntegrationCard`, Task 6's `ConnectDialog`.
- Produces: the finished `/integrations` route.

- [ ] **Step 1: Write the layout**

`frontend/src/app/integrations/layout.tsx`:

```tsx
import { AppShell } from "@/components/layout/app-shell";

export default function IntegrationsLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
```

- [ ] **Step 2: Write the page**

`frontend/src/app/integrations/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { IntegrationCard } from "@/components/integrations/integration-card";
import { ConnectDialog } from "@/components/integrations/connect-dialog";
import type { Integration, IntegrationCategory } from "@/types";

// Section order and titles match the spec's four groups exactly.
const GROUPS: { title: string; categories: IntegrationCategory[] }[] = [
  { title: "Security & Access", categories: ["acs", "pacs", "vms"] },
  { title: "Enterprise Systems of Record", categories: ["erp", "iwms"] },
  { title: "Retail & Food Service", categories: ["pos", "kds"] },
  { title: "People & Relationships", categories: ["crm", "hris"] },
];

export default function IntegrationsPage() {
  const queryClient = useQueryClient();
  const [dialogTarget, setDialogTarget] = useState<Integration | null>(null);

  const { data: catalog } = useQuery({
    queryKey: ["integrations", "catalog"],
    queryFn: () => api.getIntegrations(),
  });

  const { data: connections } = useQuery({
    queryKey: ["integrations", "connections"],
    queryFn: () => api.getIntegrationConnections(),
  });

  const connectMutation = useMutation({
    mutationFn: ({ id, config }: { id: string; config: Record<string, string> }) =>
      api.connectIntegration(id, { config }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations", "connections"] });
      setDialogTarget(null);
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: (id: string) => api.disconnectIntegration(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["integrations", "connections"] });
    },
  });

  const integrationsByCategory = new Map<IntegrationCategory, Integration[]>();
  for (const integration of catalog?.integrations ?? []) {
    const list = integrationsByCategory.get(integration.category) ?? [];
    list.push(integration);
    integrationsByCategory.set(integration.category, list);
  }

  const connectionByIntegrationId = new Map(
    (connections?.connections ?? []).map((c) => [c.integration_id, c])
  );

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-[#F5F5F5]">Integrations</h1>

      {GROUPS.map((group) => (
        <div key={group.title} className="space-y-3">
          <h2 className="text-sm font-medium text-[#A3A3A3] uppercase tracking-wide">
            {group.title}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {group.categories.flatMap((category) =>
              (integrationsByCategory.get(category) ?? []).map((integration) => (
                <IntegrationCard
                  key={integration.id}
                  integration={integration}
                  connection={connectionByIntegrationId.get(integration.id)}
                  onConnectClick={() => setDialogTarget(integration)}
                  onDisconnectClick={() => disconnectMutation.mutate(integration.id)}
                />
              ))
            )}
          </div>
        </div>
      ))}

      {dialogTarget && (
        <ConnectDialog
          integration={dialogTarget}
          open={!!dialogTarget}
          onClose={() => setDialogTarget(null)}
          isSubmitting={connectMutation.isPending}
          onSubmit={(config) => connectMutation.mutate({ id: dialogTarget.id, config })}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add the nav entry to both shells**

In `frontend/src/components/layout/sidebar.tsx`, add to `navItems` (a `Plug` icon from `lucide-react` fits; add it to the existing icon import list):

```ts
{ href: "/integrations", label: "Integrations", icon: Plug, tourId: "nav-integrations" },
```

Place it after the `/fleet` entry and before `/test-camera` — it's an operator/admin surface like Fleet and Settings, not a daily-driver page like Dashboard/Events.

In `frontend/src/components/layout/app-shell.tsx`, add the matching entry to its own `navItems`-equivalent array (found in Step 3's earlier grep — it's a flat `{ href, label, icon }` list, no `tourId`):

```ts
{ href: "/integrations", label: "Integrations", icon: Plug },
```

Place it after `/usage` and before `/settings`, matching that file's existing ordering convention (operational pages, then Settings last).

- [ ] **Step 4: Verify the build**

```bash
cd frontend && npm run build
```

Expected: build passes.

- [ ] **Step 5: Verify in the browser**

Start backend + frontend (`./start.sh` or independently). Log in as an admin user, navigate to `/integrations`. Expected:
- Four group headers in the order from Section 1 of the spec.
- 10 cards total, Tally the only one with a "Connect" button (everything else shows "Coming soon" and is not clickable).
- Clicking "Connect" on Tally opens the dialog with a "Tally base URL" field; submitting shows the card flip to "Connected" with a red "Disconnect" button.
- Clicking "Disconnect" flips it back.
- Reloading the page preserves the Connected state (confirms it round-trips through the backend, not just local state).

- [ ] **Step 6: Self-review**

- Does the page make exactly two network requests on load (`GET /api/integrations`, `GET /api/integrations/connections`), or does something re-fetch per card? (Both queries are page-level `useQuery` calls, cards are pure — confirm via the Network tab.)
- Is `dialogTarget` cleared correctly after a successful connect, so reopening a different integration's dialog doesn't show stale field values? (The dialog is unmounted when `dialogTarget` is `null` — its `useState` for `values` resets on remount — confirm by connecting one, closing, then opening a different integration's dialog and checking the field is empty.)
- Does a non-admin user see the page at all, and if so, does clicking "Connect" fail gracefully? (The route has no page-level role gate — same as Settings' tabs, which show but individual actions 403 server-side. Confirm the mutation's error is at least visible, even if unstyled — note this as a known minimal-effort spot, not a blocker.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/integrations frontend/src/components/layout/sidebar.tsx frontend/src/components/layout/app-shell.tsx
git commit -m "feat(integrations): add integrations directory page and nav entry"
```

---

## Plan Self-Review

**Spec coverage:**
- Section 1 (9 categories, 4 groups) → Task 1 seed data, Task 7 `GROUPS` constant.
- Section 2 (data model) → Task 1.
- Section 3 (API surface) → Task 3.
- Section 4 (frontend) → Tasks 4-7.
- Section 5 (non-goals) → enforced by Global Constraints (`config` opacity, no schema-driven form in Task 6, no new role gate in Task 7, catalog not user-writable — no create/edit-catalog route exists anywhere in Task 3).
- Section 0 (Camera-to-Books seam) → deliberately no task touches Camera-to-Books code; Task 0 only reads its migration state to avoid an alembic branch. This is intentional per the spec: the seam is Tally's *future* sync job optionally reading `integration_connections`, which is out of scope for this plan.
- Section 6 (testing) → manual verification steps throughout, no test files created.
- Section 7 (seed data) → Task 1's `SEED_ROWS` is the real content, not a placeholder.

**Placeholder scan:** no TBD/TODO; every code block is complete; the one open item (Step 5's "note as pending" line in Task 1) is an explicit deferred verification, not a placeholder implementation.

**Type consistency:** `Integration`/`IntegrationConnection` field names match across `backend/app/models/integration.py` (Task 1), `backend/app/schemas/integration.py` (Task 2), `frontend/src/types/index.ts` (Task 4), and both frontend components (Tasks 5-6) — checked `status`, `category`, `vendor`, `config`, `connected_at`, `connected_by` for spelling drift.
