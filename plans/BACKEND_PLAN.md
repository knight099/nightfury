# NIGHTWATCH — Backend API Plan

---

| Field | Value |
|-------|-------|
| **Plan Name** | Backend API Service |
| **Version** | 1.0.0 |
| **Parent Plan** | MVP_PLAN.md |
| **Date Generated** | 2026-05-26 |
| **Estimated Effort** | 15 person-days |
| **Tech Stack** | Python 3.11, FastAPI, SQLAlchemy 2.0, PostgreSQL 15, Redis, Firebase Auth |
| **Deployment** | GCP Cloud Run (asia-south1) |

---

## Objective

Build the REST API that powers the Nightwatch platform — handles auth, camera management, event storage, alert rule evaluation, notifications, and real-time WebSocket delivery.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        BACKEND SERVICE                                    │
│                        FastAPI on Cloud Run                               │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                         MIDDLEWARE LAYER                              ││
│  │  • CORS (frontend origins)                                           ││
│  │  • Rate limiting (Redis-backed, per-tenant)                          ││
│  │  • Request ID injection                                               ││
│  │  • Firebase JWT verification                                          ││
│  │  • Tenant context injection (org_id from token)                      ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Auth     │ │ Cameras  │ │ Events   │ │ Alerts   │ │ Sites/Users  │ │
│  │ Router   │ │ Router   │ │ Router   │ │ Router   │ │ Router       │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘ │
│       │             │             │             │              │          │
│  ┌────▼─────────────▼─────────────▼─────────────▼──────────────▼───────┐│
│  │                      SERVICE LAYER                                    ││
│  │                                                                       ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  ││
│  │  │ AuthService  │  │ CameraService│  │ EventService             │  ││
│  │  │ • signup     │  │ • CRUD       │  │ • create (from worker)   │  ││
│  │  │ • login      │  │ • status     │  │ • list/filter            │  ││
│  │  │ • invite     │  │ • assign     │  │ • feedback               │  ││
│  │  │ • roles      │  │   worker     │  │ • stats                  │  ││
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘  ││
│  │                                                                       ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  ││
│  │  │ AlertService │  │ NotifyService│  │ WebSocketManager         │  ││
│  │  │ • rule CRUD  │  │ • WhatsApp   │  │ • per-org rooms          │  ││
│  │  │ • evaluate   │  │ • Email      │  │ • push events real-time  │  ││
│  │  │ • cooldown   │  │ • Webhook    │  │ • connection management  │  ││
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘  ││
│  └───────────────────────────────────────────────────────────────────────┘│
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────────┐│
│  │                      DATA LAYER                                        ││
│  │  SQLAlchemy 2.0 (async) → Cloud SQL PostgreSQL                        ││
│  │  Redis (Memorystore) → sessions, rate limits, pub/sub                 ││
│  │  GCS → signed URLs for snapshots/clips                                ││
│  └───────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory, startup/shutdown
│   ├── config.py                  # Settings from env vars (pydantic-settings)
│   │
│   ├── models/                    # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── base.py               # Base model with id, timestamps, org_id
│   │   ├── organization.py
│   │   ├── user.py
│   │   ├── site.py
│   │   ├── camera.py
│   │   ├── event.py
│   │   ├── alert_rule.py
│   │   └── alert_history.py
│   │
│   ├── schemas/                   # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── camera.py
│   │   ├── event.py
│   │   ├── alert.py
│   │   └── site.py
│   │
│   ├── api/                       # Route handlers
│   │   ├── __init__.py
│   │   ├── router.py             # Main router aggregating all sub-routers
│   │   ├── auth.py
│   │   ├── cameras.py
│   │   ├── events.py
│   │   ├── alerts.py
│   │   ├── sites.py
│   │   ├── users.py
│   │   └── internal.py           # Worker-facing endpoints (events ingest, heartbeat)
│   │
│   ├── services/                  # Business logic
│   │   ├── __init__.py
│   │   ├── auth_service.py
│   │   ├── camera_service.py
│   │   ├── event_service.py
│   │   ├── alert_service.py      # Rule evaluation engine
│   │   ├── notification_service.py
│   │   └── worker_scheduler.py   # Assigns cameras to stream workers
│   │
│   ├── core/                      # Cross-cutting concerns
│   │   ├── __init__.py
│   │   ├── database.py           # Async SQLAlchemy engine + session factory
│   │   ├── redis.py              # Redis connection pool
│   │   ├── security.py           # Firebase token verification, API key validation
│   │   ├── dependencies.py       # FastAPI Depends: get_db, get_current_user, get_org
│   │   ├── exceptions.py         # Custom exception handlers
│   │   └── middleware.py         # Rate limit, request ID, tenant context
│   │
│   └── ws/                        # WebSocket handling
│       ├── __init__.py
│       └── events.py             # Real-time event push to connected clients
│
├── alembic/                       # Database migrations
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── tests/
│   ├── conftest.py               # Fixtures: test DB, test client, auth mocking
│   ├── test_auth.py
│   ├── test_cameras.py
│   ├── test_events.py
│   ├── test_alerts.py
│   └── test_notifications.py
│
├── Dockerfile
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

## Detailed API Specification

### Authentication

```yaml
POST /api/auth/signup:
  body:
    email: string (required)
    password: string (required, min 8 chars)
    org_name: string (required)
    name: string (required)
  response: 201
    user: {id, email, name, role: "owner"}
    org: {id, name, slug}
    token: string (Firebase custom token)

POST /api/auth/login:
  # Client authenticates via Firebase SDK, sends ID token
  headers:
    Authorization: "Bearer <firebase_id_token>"
  response: 200
    user: {id, email, name, role, org_id}
    access_token: string (our JWT, 24h expiry)

POST /api/auth/invite:
  auth: owner or admin
  body:
    email: string
    role: "admin" | "operator" | "viewer"
    sites: [uuid] (optional, empty = all)
  response: 201
    invite_id: uuid
    invite_url: string
```

### Cameras

```yaml
GET /api/cameras:
  auth: any role
  query: ?site_id=uuid&status=online
  response: 200
    cameras: [{id, name, site_id, ingest_mode, status, last_frame_at, enabled_events}]

POST /api/cameras:
  auth: admin+
  body:
    name: string
    site_id: uuid
    ingest_mode: "rtsp_pull" | "rtmp_push" | "srt_push"
    rtsp_url: string (required if rtsp_pull)
    enabled_events: ["person","vehicle","intrusion","loitering","crowd","fire_smoke","ppe","object_left"]
    sensitivity: "low" | "medium" | "high"
    detection_zones: [{name: string, points: [[x,y]...]}]
  response: 201
    camera: {id, name, ...}
    ingest_endpoint: string (if push mode: "rtmp://ingest.nightwatch.ai/live")
    stream_key: string (if push mode: "nw_cam_<uuid>")

PATCH /api/cameras/:id:
  auth: admin+
  body: (partial update — any camera fields)
  response: 200

DELETE /api/cameras/:id:
  auth: admin+
  response: 204

GET /api/cameras/:id/status:
  auth: any
  response: 200
    status: "online" | "offline" | "error"
    last_frame_at: datetime
    worker_id: string
    fps: float
    events_today: int
    error_message: string | null

POST /api/cameras/:id/snapshot:
  auth: admin+
  description: "Request current frame from stream worker for zone drawing"
  response: 200
    snapshot_url: string (signed GCS URL, 5-min expiry)
```

### Events

```yaml
GET /api/events:
  auth: any
  query:
    ?camera_id=uuid
    &site_id=uuid
    &event_type=intrusion
    &severity=high,critical
    &feedback=pending
    &start=2026-05-20T00:00:00Z
    &end=2026-05-26T23:59:59Z
    &search=person+loading+dock  (text search in description)
    &page=1
    &per_page=50
  response: 200
    events: [{id, camera_id, site_id, timestamp, event_type, confidence,
              severity, description, snapshot_url, clip_url, feedback, ...}]
    total: int
    page: int
    pages: int

GET /api/events/:id:
  auth: any
  response: 200
    event: {full event object with signed media URLs}

POST /api/events/:id/feedback:
  auth: operator+
  body:
    feedback: "approved" | "rejected" | "reclassified"
    label: string (required if reclassified)
  response: 200

GET /api/events/stats:
  auth: any
  query: ?period=24h|7d|30d &site_id=uuid
  response: 200
    total_events: int
    by_type: {person: 42, intrusion: 5, ...}
    by_severity: {low: 30, medium: 12, high: 5, critical: 0}
    by_hour: [{hour: 0, count: 3}, ...]
    feedback_rate: float (% events with feedback)
    false_positive_rate: float (% rejected / total reviewed)

# Internal endpoint (called by stream workers)
POST /internal/events:
  auth: API key (worker service account)
  body:
    camera_id: uuid
    timestamp: datetime
    event_type: string
    confidence: float
    severity: string
    description: string
    bounding_boxes: [{x1,y1,x2,y2,label}]
    snapshot_url: string (GCS path, already uploaded by worker)
    clip_url: string (GCS path)
    ai_model: string
    ai_response_raw: object
  response: 201
    event_id: uuid
    alerts_triggered: int
```

### Alert Rules

```yaml
GET /api/alerts/rules:
  auth: any
  response: 200
    rules: [{id, name, event_types, min_severity, cameras, time_window,
             notify_channels, enabled, ...}]

POST /api/alerts/rules:
  auth: admin+
  body:
    name: string
    cameras: [uuid] (empty = all)
    event_types: [string] (empty = all)
    min_severity: "low" | "medium" | "high" | "critical"
    time_window: {start: "22:00", end: "06:00", days: ["mon","tue","wed","thu","fri","sat","sun"]} | null
    zones: [string] (zone names)
    notify_channels: ["whatsapp", "email", "webhook"]
    notify_contacts: [{type: "whatsapp", value: "+919876543210"}, {type: "email", value: "a@b.com"}]
    webhook_url: string | null
    cooldown_seconds: int (default 60)
  response: 201

PATCH /api/alerts/rules/:id:
  auth: admin+
  body: (partial)
  response: 200

DELETE /api/alerts/rules/:id:
  auth: admin+
  response: 204

GET /api/alerts/history:
  auth: any
  query: ?rule_id=uuid &start=datetime &end=datetime &page=1
  response: 200
    alerts: [{id, rule_id, event_id, channel, recipient, status, sent_at}]
```

### Sites & Users

```yaml
GET /api/sites:
  response: 200 [{id, name, address, timezone, camera_count}]

POST /api/sites:
  auth: admin+
  body: {name, address, timezone}
  response: 201

GET /api/users:
  auth: admin+
  response: 200 [{id, email, name, role, last_login}]

PATCH /api/users/:id:
  auth: owner only
  body: {role, sites_access}
  response: 200
```

---

## Alert Rules Engine (Core Logic)

```python
# services/alert_service.py — pseudocode

class AlertService:
    async def evaluate_event(self, event: Event) -> list[AlertTriggered]:
        """Called when a new event is stored. Checks all active rules for this org."""
        
        rules = await self.get_active_rules(event.org_id)
        triggered = []
        
        for rule in rules:
            if not self._matches(rule, event):
                continue
            
            if await self._is_in_cooldown(rule, event):
                continue
            
            # Rule matches — trigger notifications
            for contact in rule.notify_contacts:
                alert = await self._send_notification(rule, event, contact)
                triggered.append(alert)
            
            # Set cooldown
            await self._set_cooldown(rule, event)
        
        # Push to WebSocket for real-time dashboard
        await self.ws_manager.broadcast_event(event.org_id, event)
        
        return triggered
    
    def _matches(self, rule: AlertRule, event: Event) -> bool:
        # Event type filter
        if rule.event_types and event.event_type not in rule.event_types:
            return False
        
        # Severity filter
        severity_order = ['low', 'medium', 'high', 'critical']
        if severity_order.index(event.severity) < severity_order.index(rule.min_severity):
            return False
        
        # Camera filter
        if rule.cameras and event.camera_id not in rule.cameras:
            return False
        
        # Time window filter
        if rule.time_window:
            if not self._is_in_time_window(event.timestamp, rule.time_window):
                return False
        
        # Zone filter
        if rule.zones and event metadata zone not in rule.zones:
            return False
        
        return True
    
    async def _is_in_cooldown(self, rule: AlertRule, event: Event) -> bool:
        """Check Redis for recent alert of same rule + event_type + camera."""
        key = f"cooldown:{rule.id}:{event.camera_id}:{event.event_type}"
        return await self.redis.exists(key)
    
    async def _set_cooldown(self, rule: AlertRule, event: Event):
        key = f"cooldown:{rule.id}:{event.camera_id}:{event.event_type}"
        await self.redis.setex(key, rule.cooldown_seconds, "1")
```

---

## Notification Service

```python
# services/notification_service.py

class NotificationService:
    
    async def send_whatsapp(self, phone: str, event: Event, rule: AlertRule):
        """Send via Gupshup WhatsApp Business API."""
        # Uses pre-approved template message
        payload = {
            "channel": "whatsapp",
            "source": WHATSAPP_BUSINESS_NUMBER,
            "destination": phone,
            "message": {
                "type": "template",
                "template": {
                    "name": "event_alert_v1",
                    "language": {"code": "en"},
                    "components": [
                        {"type": "header", "parameters": [
                            {"type": "image", "image": {"link": event.snapshot_url}}
                        ]},
                        {"type": "body", "parameters": [
                            {"type": "text", "text": event.severity.upper()},
                            {"type": "text", "text": event.camera.site.name},
                            {"type": "text", "text": event.camera.name},
                            {"type": "text", "text": event.timestamp.strftime("%H:%M:%S")},
                            {"type": "text", "text": event.event_type.replace("_", " ").title()},
                            {"type": "text", "text": event.description},
                        ]}
                    ]
                }
            }
        }
        await self.gupshup_client.post("/wa/api/v1/msg", json=payload)
    
    async def send_email(self, email: str, event: Event, rule: AlertRule):
        """Send via SendGrid with HTML template."""
        # HTML template with inline snapshot, event details, CTA button
        ...
    
    async def send_webhook(self, url: str, event: Event, rule: AlertRule):
        """POST event payload to client's webhook URL with HMAC signature."""
        payload = event.to_webhook_dict()
        signature = hmac.new(rule.webhook_secret, json.dumps(payload), 'sha256').hexdigest()
        headers = {"X-Nightwatch-Signature": signature}
        await self.http_client.post(url, json=payload, headers=headers, timeout=10)
```

---

## Database Migrations

```python
# alembic/versions/001_initial_schema.py

def upgrade():
    # organizations
    op.create_table('organizations',
        sa.Column('id', UUID, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('slug', sa.Text, unique=True, nullable=False),
        sa.Column('owner_id', UUID, nullable=False),
        sa.Column('plan', sa.Text, server_default='starter'),
        sa.Column('settings', JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )
    
    # users
    op.create_table('users', ...)
    
    # sites
    op.create_table('sites', ...)
    
    # cameras
    op.create_table('cameras', ...)
    
    # events (with indexes)
    op.create_table('events', ...)
    op.create_index('idx_events_org_time', 'events', ['org_id', sa.text('timestamp DESC')])
    op.create_index('idx_events_camera_time', 'events', ['camera_id', sa.text('timestamp DESC')])
    op.create_index('idx_events_type', 'events', ['org_id', 'event_type', sa.text('timestamp DESC')])
    
    # alert_rules
    op.create_table('alert_rules', ...)
    
    # alert_history
    op.create_table('alert_history', ...)
```

---

## Configuration

```python
# app/config.py

from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    app_name: str = "nightwatch-api"
    debug: bool = False
    api_version: str = "v1"
    
    # Database
    database_url: str  # postgresql+asyncpg://user:pass@host/db
    db_pool_size: int = 10
    db_max_overflow: int = 20
    
    # Redis
    redis_url: str  # redis://host:6379/0
    
    # Firebase
    firebase_project_id: str
    firebase_credentials_path: str = ""  # or use GOOGLE_APPLICATION_CREDENTIALS
    
    # GCS
    gcs_bucket: str = "nightwatch-events"
    gcs_signed_url_expiry: int = 3600  # 1 hour
    
    # Notifications
    gupshup_api_key: str = ""
    gupshup_app_name: str = ""
    whatsapp_business_number: str = ""
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "alerts@nightwatch.ai"
    
    # Worker auth
    worker_api_key: str  # shared secret for internal endpoints
    
    # Rate limiting
    rate_limit_per_minute: int = 100
    
    class Config:
        env_file = ".env"
```

---

## Security

| Concern | Implementation |
|---------|---------------|
| Auth | Firebase Auth (handles password hashing, MFA, OAuth providers) |
| Token verification | Every request: verify Firebase ID token → extract uid → load user + org |
| Tenant isolation | All queries filter by `org_id` from authenticated user context |
| Internal endpoints | `/internal/*` routes require `X-Worker-Key` header matching `worker_api_key` |
| Rate limiting | Redis sliding window: 100 req/min per user, 1000 req/min per org |
| Input validation | Pydantic schemas with strict types, max lengths, enum constraints |
| SQL injection | SQLAlchemy ORM only, no raw queries |
| CORS | Allow only frontend domain(s) |
| Secrets | All in GCP Secret Manager, injected via env vars at deploy |

---

## WebSocket (Real-time Events)

```python
# app/ws/events.py

class WebSocketManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}  # org_id → connections
    
    async def connect(self, websocket: WebSocket, org_id: str):
        await websocket.accept()
        self.connections.setdefault(org_id, []).append(websocket)
    
    async def disconnect(self, websocket: WebSocket, org_id: str):
        self.connections[org_id].remove(websocket)
    
    async def broadcast_event(self, org_id: str, event: Event):
        """Push new event to all connected clients for this org."""
        if org_id not in self.connections:
            return
        message = event.to_ws_dict()
        for ws in self.connections[org_id]:
            try:
                await ws.send_json(message)
            except:
                await self.disconnect(ws, org_id)

# Route
@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket, token: str = Query(...)):
    user = await verify_ws_token(token)
    await ws_manager.connect(websocket, user.org_id)
    try:
        while True:
            await websocket.receive_text()  # keepalive
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, user.org_id)
```

---

## Deployment (Cloud Run)

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]
```

```yaml
# Cloud Run service config
service: nightwatch-api
region: asia-south1
cpu: 2
memory: 1Gi
max_instances: 10
min_instances: 1
concurrency: 100
env_vars:
  - from: Secret Manager
```

---

## Test Strategy

| Type | What | Tool |
|------|------|------|
| Unit | Service layer logic (alert matching, cooldown) | pytest + pytest-asyncio |
| Integration | API endpoints with real DB | pytest + httpx + testcontainers (Postgres) |
| Auth | Token verification, role-based access | Mock Firebase tokens |
| Load | Event ingestion throughput | locust (target: 100 events/sec) |

---

## Implementation Order

| Day | Task |
|-----|------|
| 1 | Project scaffold, config, Docker, docker-compose (Postgres + Redis) |
| 2 | Database models + Alembic migration + base dependencies |
| 3 | Auth: Firebase verification, signup/login, user/org creation |
| 4 | Camera CRUD API + ingest key generation |
| 5 | Events: internal ingest endpoint + list/filter/stats |
| 6 | Events: feedback endpoint + event detail |
| 7 | Alert rules: CRUD API |
| 8 | Alert engine: rule evaluation on event creation |
| 9 | Notification service: WhatsApp (Gupshup) + Email (SendGrid) |
| 10 | Notification service: Webhook delivery |
| 11 | WebSocket: real-time event push |
| 12 | Worker scheduler: assign cameras to workers, status tracking |
| 13 | Rate limiting, CORS, error handling, input validation hardening |
| 14 | Tests: unit + integration for core flows |
| 15 | Cloud Run deployment + Secret Manager + CI pipeline |

---

## Definition of Done

- [ ] All API endpoints functional and returning correct responses
- [ ] Firebase auth integration working (signup → login → protected routes)
- [ ] Events stored from internal endpoint, queryable with filters
- [ ] Alert rules evaluate correctly against events (time, severity, type, camera)
- [ ] WhatsApp + Email notifications delivered on rule match
- [ ] WebSocket pushes events to connected dashboard clients
- [ ] Rate limiting active (Redis-backed)
- [ ] Deployed on Cloud Run, accessible via HTTPS
- [ ] Integration tests passing for auth, cameras, events, alerts
- [ ] <200ms p95 response time for list endpoints (paginated)
