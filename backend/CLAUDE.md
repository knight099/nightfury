# Nightwatch Backend — Development Rules

## What's Already Built (Current State)

### Completed
- **Full project scaffold:** FastAPI app with docker-compose (Postgres + Redis), Dockerfile, .env.example
- **Auth system:** Username + password login, Argon2id hashing, AES-256-GCM encrypted session tokens, Redis session store, brute-force lockout (5 attempts → 15min), session binding (IP + User-Agent), idle timeout (1hr), absolute timeout (24hr), logout (single + all devices)
- **Database models (7 tables):** organizations, users, sites, cameras, events, alert_rules, alert_history — all with UUID PKs, org_id multi-tenancy, timestamps
- **Super admin:** Seeded on first boot from env vars, org_id=None, bypasses all filters, full CRUD on all orgs/users, change any password, force-logout any user, view sessions
- **API routes (45 total):**
  - Auth: login, signup, logout, logout-all, me, sessions, invite
  - Cameras: CRUD + status + stream key generation for push mode
  - Events: list (paginated + filtered), detail, feedback (approve/reject/reclassify), stats
  - Alert rules: CRUD + enable/disable toggle
  - Alert history: list with filters
  - Sites: CRUD
  - Internal (worker): event ingestion (triggers alert evaluation), heartbeat
  - Admin: orgs CRUD, users CRUD, change-password, force-logout, view-sessions, create-user-in-any-org
  - WebSocket: /ws/events (real-time event push per org, super_admin sees all)
- **Alert engine:** Evaluates all active rules on event ingestion — matches by event_type, severity, camera, time window, zone; cooldown via Redis; triggers notification delivery
- **Notification service:** WhatsApp (Gupshup API), Email (SendGrid), Webhook (HMAC-signed POST)
- **Middleware:** Request ID injection, response timing, CORS

### Not Yet Built (Planned)
- Alembic migration files (currently using create_all on startup for dev)
- Rate limiting middleware (Redis-backed, per-tenant)
- GCS signed URL generation for snapshot/clip access
- Full test suite (conftest.py exists with fixtures but no test files yet)
- Production deployment config (Cloud Run, Terraform)
- Proper error logging / structured logging
- API pagination metadata on all list endpoints (events has it, others return plain lists)

## Identity
- **Service:** Nightwatch API (FastAPI)
- **Language:** Python 3.11+
- **Framework:** FastAPI + SQLAlchemy 2.0 (async) + Redis
- **Database:** PostgreSQL 15+
- **Auth:** Argon2id passwords + AES-256-GCM encrypted session tokens + Redis sessions

## Architecture Rules

### API Design
- All routes under `/api/` prefix with versioning-ready structure
- Internal worker routes under `/internal/` with `X-Worker-Key` header auth
- Admin routes under `/api/admin/` — require `super_admin` role
- Every endpoint that returns user-scoped data MUST filter by `org_id` (unless super_admin)
- Use `Depends(get_current_user)` on every authenticated route — no exceptions
- Response models must use Pydantic `model_validate` with `from_attributes = True`

### Auth & Security
- NEVER use JWT — we use server-side Redis sessions with encrypted opaque tokens
- Passwords hashed with Argon2id (memory=64MB, time=3, parallelism=4)
- Session tokens encrypted with AES-256-GCM (not decodable without server key)
- Sessions bound to IP + User-Agent fingerprint — mismatch = invalid
- Brute-force: 5 failed attempts = 15-min account lockout (Redis-tracked)
- Session expiry: 1hr idle (sliding), 24hr absolute max
- super_admin has `org_id = None` and bypasses all org filters
- Worker endpoints use static API key auth (not sessions)
- NEVER store plaintext passwords, tokens, or secrets in code/config files
- NEVER log sensitive data (passwords, tokens, session IDs)

### Database
- All tables have `org_id` for multi-tenancy (except `users` where super_admin has null)
- Use UUID primary keys everywhere (never auto-increment integers)
- Always use parameterized queries via SQLAlchemy ORM — NEVER raw SQL strings
- Migrations via Alembic — never use `create_all` in production
- Index on: `(org_id, timestamp DESC)` for events, `(org_id)` for all tenant tables
- `username` field is unique globally (not per-org) — enforced at DB level

### Code Style
- Async everywhere — all DB operations use `async/await`
- Services layer holds business logic (not in route handlers)
- Route handlers: validate input → call service → return response
- No circular imports — dependencies flow: routes → services → models
- Config via `pydantic-settings` from environment variables only
- No hardcoded values — everything configurable via env

### Error Handling
- Use `HTTPException` with clear detail messages
- 400 = client error (bad input), 401 = not authenticated, 403 = not authorized, 404 = not found, 429 = rate limited
- Never expose internal errors to client — log them, return generic message
- All service-layer functions should catch and handle their own exceptions

### Testing
- Tests use `pytest-asyncio` against a real Postgres database at `TEST_DATABASE_URL` — **not testcontainers** (despite older docs claiming otherwise; verify against `tests/conftest.py` before trusting doc text on this)
- `TEST_DATABASE_URL` is **required** and must be a separate, disposable database from `DATABASE_URL` — `tests/conftest.py` hard-fails at collection time if it's unset or identical to `DATABASE_URL`, because the `db_session` fixture runs `create_all`/`drop_all` around every single test
- **Never copy a `.env` file between environments/worktrees without checking `TEST_DATABASE_URL` is still a distinct, throwaway database** — a copied `.env` missing this distinction caused a 2026-08-01 incident that dropped every table in a real database
- Mock external services (Gupshup, SendGrid, GCS) in tests
- Test auth flows: valid login, wrong password, lockout, session expiry

## File Layout
```
app/
├── main.py          # App factory, lifespan, router registration
├── config.py        # All settings from env vars
├── core/            # Security, DB, Redis, middleware, dependencies
├── models/          # SQLAlchemy ORM models (one per file)
├── schemas/         # Pydantic request/response models
├── api/             # Route handlers (thin — delegate to services)
├── services/        # Business logic (alert engine, notifications)
└── ws/              # WebSocket handlers
```

## Running
```bash
docker compose up db redis -d
python3 -m uvicorn app.main:app --reload --port 8080
```

## Key Endpoints
- `POST /api/auth/login` — username + password → encrypted session token
- `POST /api/auth/logout` — revokes session in Redis
- `POST /internal/events` — worker posts detected events (triggers alerts)
- `GET /api/admin/users` — super_admin lists all users cross-tenant
- `POST /api/admin/users/{id}/change-password` — super_admin resets any password
- `POST /api/admin/users/{id}/force-logout` — kills all sessions for a user
