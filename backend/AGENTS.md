# Nightwatch Backend — Agent Rules

## What's Already Built
- 45 API routes fully implemented and loading (`python3 -c "from app.main import app"` passes)
- Auth: login/signup/logout/invite with Argon2id + AES-256-GCM Redis sessions
- 7 SQLAlchemy models: organizations, users (username-based), sites, cameras, events, alert_rules, alert_history
- Alert engine: evaluates rules on event ingestion, sends WhatsApp/email/webhook notifications
- WebSocket: real-time event broadcast per org
- Super admin: full CRUD on everything, change passwords, force-logout, view sessions
- Docker compose: Postgres 16 + Redis 7 for local dev
- NOT yet done: Alembic migrations (using create_all), rate limiting, GCS signed URLs, full tests

## What This Service Does
REST API + WebSocket server for the Nightwatch platform. Handles auth, camera management, event storage, alert rule evaluation, notifications, and real-time event push.

## Tech Stack
- Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, Redis
- Auth: Argon2id + AES-256-GCM sessions (NOT JWT)
- Notifications: Gupshup (WhatsApp), SendGrid (email), httpx (webhooks)

## Key Decisions Already Made — Don't Change
- Username-based auth (no email field on User model)
- Server-side sessions in Redis (not stateless tokens)
- super_admin has org_id=None and bypasses all tenant filters
- Worker auth via static API key header (X-Worker-Key)
- Alert rules evaluated synchronously on event ingestion
- WebSocket authenticated via same session token (query param)

## How to Add a New Endpoint
1. Add Pydantic schema in `app/schemas/`
2. Add route in `app/api/` with `Depends(get_current_user)` for auth
3. Put business logic in `app/services/` (not in the route handler)
4. For super_admin-only routes: call `_require_super_admin(user)` at start
5. Filter by `user.org_id` unless `user.role == "super_admin"`

## How to Add a New Model
1. Create file in `app/models/` with SQLAlchemy declarative model
2. Add UUID primary key, org_id FK, TimestampMixin
3. Import in `app/models/__init__.py`
4. Create Alembic migration: `alembic revision --autogenerate -m "description"`

## Testing
```bash
docker compose up db redis -d
python3 -m pytest tests/ -v
```

## Common Mistakes to Avoid
- Forgetting org_id filter (data leak across tenants)
- Using `= Depends()` with Annotated types (FastAPI 0.116+ breaks this)
- Putting password/token values in log messages
- Forgetting to `await db.flush()` after mutations
- Not handling the case where super_admin has org_id=None
