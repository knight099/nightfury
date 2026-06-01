# NIGHTWATCH — Cloud SaaS MVP Plan

---

| Field | Value |
|-------|-------|
| **Plan Name** | Cloud SaaS MVP — Stream-to-Events |
| **Version** | 1.1.0 |
| **Parent Plan** | MASTER_PLAN.md |
| **Date Generated** | 2026-05-26 |
| **Last Updated** | 2026-05-26 |
| **Estimated Effort** | 45 person-days (~30 calendar days, team of 2-3) |
| **Infra** | GCP Mumbai (asia-south1) |
| **Feed Ingestion** | RTSP pull + RTMP/SRT push (both supported) |
| **AI Scope** | Configurable event types per client from a detection menu |

---

## Implementation Status

### ✅ DONE — Backend (100% of MVP scope)
- FastAPI app with 45 routes, verified loading
- Auth: username + password (Argon2id + AES-256-GCM Redis sessions) — replaced planned Firebase Auth with much stronger custom auth
- Brute-force lockout (5 attempts → 15min), session binding (IP+UA), idle/absolute expiry
- 7 database models with multi-tenant isolation (org_id)
- Super admin: full CRUD on all orgs/users, change passwords, force-logout, view sessions
- Camera CRUD with RTSP pull + RTMP push stream key generation
- Event storage + paginated/filtered listing + feedback (approve/reject/reclassify)
- Alert rules engine: evaluates on event ingestion, matches by type/severity/camera/time/zone, cooldown via Redis
- Notifications: WhatsApp (Gupshup), Email (SendGrid), Webhook (HMAC-signed)
- WebSocket /ws/events for real-time push
- Internal worker endpoints: event ingestion + heartbeat
- Docker compose (Postgres + Redis) for local dev

### ✅ DONE — Worker (100% of MVP scope)
- 12 source files, full pipeline implemented
- FFmpeg stream ingest (RTSP pull + RTMP push), auto-reconnect (5 attempts)
- Motion detection gate (saves ~80% Gemini cost)
- Adaptive frame sampling (1fps idle → 5fps active) with deduplication
- Gemini 2.0 Flash client with circuit breaker (10 failures → 30s pause)
- Camera-config-driven prompt builder with zone awareness
- Event packaging: annotated WebP snapshots + 10s H.264 clips
- GCS upload + backend POST
- Supervisor: multi-camera management, health reporting, auto-restart
- 10 unit tests passing (motion detector, ring buffer, prompt builder)

### ✅ DONE — Frontend (90% of MVP scope)
- Next.js 14 + TypeScript + Tailwind + shadcn/ui, builds clean
- Dark theme (#0D0D0D bg, #1E90FF accent, Comic Relief font)
- Login/signup (username + password)
- Dashboard: stats + real-time event feed (polling) + camera grid
- Events: paginated list with type/severity filters, inline approve/reject
- Cameras: grid + add form (RTSP pull + RTMP push), event type picker, sensitivity, delete
- Alerts: rules list + create form + enable/disable + delete
- 11-step onboarding tour (driver.js, auto on first login)
- Help widget: floating chat with 6 troubleshooting topics + keyword matching
- Typed API client + Zustand auth store + TanStack Query

### ⬜ NOT DONE — Remaining Items
| Item | Priority | Effort | Notes |
|------|----------|--------|-------|
| Alembic migration files | P1 | 0.5d | Currently using create_all — needs migration before prod |
| Event detail page (/events/[id]) | P1 | 1d | Snapshot viewer + clip player + full feedback UI |
| Zone drawing editor | P2 | 2d | Canvas polygon tool on camera snapshot |
| WebSocket real-time feed | P2 | 1d | Currently polling every 10s — upgrade to WS push |
| Rate limiting middleware | P1 | 0.5d | Redis sliding window, per-tenant |
| GCS signed URLs | P1 | 0.5d | Snapshots/clips currently return gs:// paths |
| Nginx-RTMP server config | P2 | 1d | For cloud-hosted push mode receiving |
| Admin UI page | P2 | 1.5d | Orgs/users management for super_admin |
| Loading skeletons | P3 | 0.5d | Currently shows "Loading..." text |
| Mobile responsive | P3 | 1d | Sidebar collapses, cards stack |
| End-to-end test with real camera | P0 | 0.5d | Connect CP Plus RTSP → verify events flow |
| Production deployment (GCP) | P1 | 2d | Terraform, Cloud Run, GCE worker VMs |
| Full test suite | P2 | 3d | Backend integration tests, worker e2e |

### Changed from Original Plan
| Original Plan | What We Did Instead | Why |
|---|---|---|
| Firebase Auth | Custom Argon2id + AES-256-GCM Redis sessions | Much more secure, no external dependency, instant revocation, session binding |
| Email-based login | Username-based login | Simpler, more secure (no email enumeration attacks), faster signup |
| JWT tokens | Server-side encrypted sessions | Can't be decoded, instantly revocable, device-bound |
| Firebase Auth SDK (frontend) | Custom login form + Zustand store | No SDK bloat, simpler, matches backend custom auth |
| No onboarding | 11-step guided tour + help chatbot | Better first-run experience, reduces support burden |

---

## Objective

A cloud SaaS platform where clients point their existing camera feeds (RTSP or push via RTMP/SRT) to our platform. We ingest the feed, run Gemini Vision AI on sampled frames, detect events based on client-configured alert rules, store event snapshots/clips, and notify via WhatsApp/email/webhook.

**What this is NOT:**
- No edge agent / on-prem software
- No local model training (future phase)
- No anti-tamper/loop detection (future phase)
- No proprietary hardware

---

## How It Works (User Story)

```
1. Client signs up → creates an org → adds a site
2. Client adds a camera:
   Option A: Provides RTSP URL (we pull the stream)
   Option B: Gets an RTMP/SRT ingest endpoint (they push to us)
3. Client selects event types to detect from a menu:
   ☑ Person detected    ☑ Intrusion (zone entry)
   ☑ Vehicle detected   ☑ Loitering (>N minutes)
   ☑ Crowd spike        ☐ Fire/smoke
   ☐ PPE violation      ☐ Object left behind
4. Client draws detection zones on a camera frame (optional)
5. Client configures alert rules:
   - "Notify me on all HIGH severity events"
   - "Alert if person enters Zone A after 10pm"
   - Channels: WhatsApp / Email / Webhook
6. System runs 24/7:
   - Samples frames (adaptive: 1fps idle, 5fps on motion)
   - Runs Gemini Vision on frames with client's configured prompts
   - Detects events → stores snapshot + 10s clip + metadata
   - Evaluates alert rules → sends notifications
7. Client reviews events in dashboard:
   - Approve / Reject / Reclassify (builds training data for future)
8. Client sees event history, analytics, camera health
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CLIENT SIDE                                        │
│                                                                           │
│  ┌──────────┐         ┌──────────┐         ┌──────────┐                │
│  │ Camera 1 │─RTSP──▶ │   NVR /  │─RTMP───▶│ Our Cloud│                │
│  │ Camera 2 │         │   VMS    │  or SRT  │ Endpoint │                │
│  │ Camera N │         └──────────┘         └──────────┘                │
│  └──────────┘              OR                                            │
│       │                                                                   │
│       └──── Direct RTSP URL provided to our platform ────────────────── │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  GCP Cloud (Mumbai) │
                    └─────────┬──────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────────┐
│                     NIGHTWATCH CLOUD PLATFORM                             │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    INGESTION LAYER                                    ││
│  │                                                                       ││
│  │  ┌───────────────────┐    ┌───────────────────┐                     ││
│  │  │ RTSP Pull Workers │    │ RTMP/SRT Ingest   │                     ││
│  │  │ (GCE VMs, FFmpeg) │    │ (Media Server)    │                     ││
│  │  │                   │    │ Nginx-RTMP or     │                     ││
│  │  │ Pulls client RTSP │    │ SRT Listener      │                     ││
│  │  │ streams on demand │    │                   │                     ││
│  │  └────────┬──────────┘    └────────┬──────────┘                     ││
│  │           │                         │                                 ││
│  │           └────────────┬────────────┘                                ││
│  │                        ▼                                              ││
│  │  ┌─────────────────────────────────────────┐                        ││
│  │  │         FRAME SAMPLER                    │                        ││
│  │  │  • Decodes stream (FFmpeg)               │                        ││
│  │  │  • Motion detection (frame diff, fast)   │                        ││
│  │  │  • Adaptive sampling: 1fps idle → 5fps   │                        ││
│  │  │  • Maintains 30s ring buffer for clips   │                        ││
│  │  └──────────────────┬──────────────────────┘                        ││
│  └──────────────────────┼──────────────────────────────────────────────┘│
│                         │ Sampled frames                                  │
│                         ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    AI LAYER                                           ││
│  │                                                                       ││
│  │  ┌─────────────────────────────────────────┐                        ││
│  │  │        GEMINI VISION API                 │                        ││
│  │  │  (gemini-2.0-flash — fast + cheap)       │                        ││
│  │  │                                          │                        ││
│  │  │  Input: frame + client config prompt     │                        ││
│  │  │  Output: structured JSON                 │                        ││
│  │  │    - event_type                          │                        ││
│  │  │    - confidence                          │                        ││
│  │  │    - description (natural language)      │                        ││
│  │  │    - bounding_boxes                      │                        ││
│  │  │    - risk_level                          │                        ││
│  │  └──────────────────┬──────────────────────┘                        ││
│  │                     │ Events detected                                 ││
│  │                     ▼                                                 ││
│  │  ┌─────────────────────────────────────────┐                        ││
│  │  │        EVENT PROCESSOR                   │                        ││
│  │  │  • Validate against client's enabled     │                        ││
│  │  │    event types                           │                        ││
│  │  │  • Check zone rules (if configured)      │                        ││
│  │  │  • Cut 10s clip from ring buffer         │                        ││
│  │  │  • Annotate snapshot with bboxes         │                        ││
│  │  │  • Store: GCS (snapshot + clip)          │                        ││
│  │  │  • Store: PostgreSQL (metadata)          │                        ││
│  │  └──────────────────┬──────────────────────┘                        ││
│  └──────────────────────┼──────────────────────────────────────────────┘│
│                         │ Stored events                                   │
│                         ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    ALERT & NOTIFY LAYER                               ││
│  │                                                                       ││
│  │  ┌─────────────────────────────────────────┐                        ││
│  │  │        ALERT RULES ENGINE               │                        ││
│  │  │  • Match event against client rules      │                        ││
│  │  │  • Time-based rules (after hours, etc.)  │                        ││
│  │  │  • Severity threshold rules              │                        ││
│  │  │  • Zone-based rules                      │                        ││
│  │  │  • Rate limiting (no spam)               │                        ││
│  │  └──────────────────┬──────────────────────┘                        ││
│  │                     │ Triggered alerts                                ││
│  │                     ▼                                                 ││
│  │  ┌─────────────────────────────────────────┐                        ││
│  │  │        NOTIFICATION ENGINE              │                        ││
│  │  │  • WhatsApp (Business API via Gupshup)  │                        ││
│  │  │  • Email (SendGrid)                      │                        ││
│  │  │  • Webhook (POST to client URL)          │                        ││
│  │  │  • In-app (WebSocket push)               │                        ││
│  │  └─────────────────────────────────────────┘                        ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    APPLICATION LAYER                                  ││
│  │                                                                       ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐     ││
│  │  │ Web App      │  │ REST API     │  │ Auth (Firebase Auth   │     ││
│  │  │ (Next.js 14) │  │ (Python      │  │  or Supabase Auth)    │     ││
│  │  │              │  │  FastAPI)    │  │                       │     ││
│  │  └──────────────┘  └──────────────┘  └───────────────────────┘     ││
│  │                                                                       ││
│  │  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐     ││
│  │  │ PostgreSQL   │  │ GCS Bucket   │  │ Redis (sessions,      │     ││
│  │  │ (Cloud SQL)  │  │ (clips/snaps)│  │  rate limiting)       │     ││
│  │  └──────────────┘  └──────────────┘  └───────────────────────┘     ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack (Lean MVP)

| Layer | Technology | Why |
|-------|-----------|-----|
| **Stream Ingestion** | FFmpeg (RTSP pull) + Nginx-RTMP (push ingest) on GCE | Battle-tested, handles both protocols |
| **Frame Sampling** | Python 3.11 + OpenCV + asyncio | Fast prototyping, good CV ecosystem |
| **AI** | Gemini 2.0 Flash (google-genai SDK) | Native GCP, fast, cheap (~$0.01/100 frames), vision-native |
| **Backend API** | Python FastAPI | Fast to build, async, great for AI workloads |
| **Database** | Cloud SQL PostgreSQL 15 | Managed, reliable, good enough for MVP scale |
| **Object Storage** | GCS (Google Cloud Storage) | Native, cheap, CDN-ready |
| **Cache/Pub-Sub** | Redis (Memorystore) | Sessions, real-time WebSocket fan-out, rate limiting |
| **Task Queue** | Cloud Tasks or Pub/Sub | Decouple ingestion from processing |
| **Frontend** | Next.js 14 + Tailwind + shadcn/ui | Fast UI dev, SSR, dark theme ready |
| **Auth** | Firebase Auth (or Supabase Auth) | Quick multi-tenant auth, Google/email login |
| **Notifications** | Gupshup (WhatsApp) + SendGrid (email) | India-focused WhatsApp delivery |
| **Deployment** | Cloud Run (API + web) + GCE (stream workers) | Serverless where possible, VMs for streams |
| **IaC** | Terraform | Reproducible infrastructure |

---

## Database Schema (MVP)

```sql
-- Organizations (tenants)
CREATE TABLE organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    owner_id UUID NOT NULL,
    plan TEXT DEFAULT 'starter',
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('owner','admin','operator','viewer')),
    firebase_uid TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sites (locations)
CREATE TABLE sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    address TEXT,
    timezone TEXT DEFAULT 'Asia/Kolkata',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Cameras
CREATE TABLE cameras (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    site_id UUID NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    -- Ingestion config
    ingest_mode TEXT NOT NULL CHECK (ingest_mode IN ('rtsp_pull', 'rtmp_push', 'srt_push')),
    rtsp_url TEXT, -- encrypted, for pull mode
    ingest_key TEXT UNIQUE, -- for push mode (client uses this as stream key)
    -- Detection config
    enabled_events TEXT[] DEFAULT '{}', -- ['person','vehicle','intrusion','loitering','crowd']
    detection_zones JSONB DEFAULT '[]', -- [{name, polygon_points}]
    sensitivity TEXT DEFAULT 'medium' CHECK (sensitivity IN ('low','medium','high')),
    -- Status
    status TEXT DEFAULT 'offline' CHECK (status IN ('online','offline','error')),
    last_frame_at TIMESTAMPTZ,
    -- Sampling config
    idle_fps REAL DEFAULT 1.0,
    active_fps REAL DEFAULT 5.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Events (the core product output)
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    camera_id UUID NOT NULL REFERENCES cameras(id),
    site_id UUID NOT NULL REFERENCES sites(id),
    -- Event data
    timestamp TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    severity TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    description TEXT NOT NULL, -- AI-generated natural language
    bounding_boxes JSONB DEFAULT '[]',
    -- Media
    snapshot_url TEXT NOT NULL, -- GCS path
    clip_url TEXT, -- GCS path (10s clip)
    -- AI metadata
    ai_model TEXT DEFAULT 'gemini-2.0-flash',
    ai_response_raw JSONB, -- full Gemini response for debugging
    -- Feedback
    feedback TEXT CHECK (feedback IN ('approved','rejected','reclassified')),
    feedback_label TEXT,
    feedback_by UUID REFERENCES users(id),
    feedback_at TIMESTAMPTZ,
    -- Indexing
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_org_time ON events(org_id, timestamp DESC);
CREATE INDEX idx_events_camera_time ON events(camera_id, timestamp DESC);
CREATE INDEX idx_events_type ON events(org_id, event_type, timestamp DESC);

-- Alert Rules
CREATE TABLE alert_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    -- Conditions
    cameras UUID[] DEFAULT '{}', -- empty = all cameras
    event_types TEXT[] DEFAULT '{}', -- empty = all types
    min_severity TEXT DEFAULT 'low',
    time_window JSONB, -- {start: "22:00", end: "06:00", days: ["mon","tue"...]}
    zones TEXT[] DEFAULT '{}', -- zone names to match
    -- Actions
    notify_channels TEXT[] NOT NULL, -- ['whatsapp','email','webhook']
    notify_contacts JSONB NOT NULL, -- [{type,value}] e.g. [{type:"whatsapp",value:"+91..."}]
    webhook_url TEXT,
    -- Rate limiting
    cooldown_seconds INTEGER DEFAULT 60, -- don't re-alert same type within N seconds
    -- Status
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Alert History (sent notifications)
CREATE TABLE alert_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES organizations(id),
    rule_id UUID REFERENCES alert_rules(id),
    event_id UUID NOT NULL REFERENCES events(id),
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    status TEXT DEFAULT 'sent' CHECK (status IN ('sent','delivered','failed')),
    sent_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## API Endpoints (MVP)

```yaml
# Auth
POST   /api/auth/signup          # Create org + first user
POST   /api/auth/login           # Firebase token exchange
POST   /api/auth/invite          # Invite user to org

# Cameras
GET    /api/cameras              # List cameras for org
POST   /api/cameras              # Add camera (returns ingest endpoint if push mode)
PATCH  /api/cameras/:id          # Update config (events, zones, sensitivity)
DELETE /api/cameras/:id          # Remove camera
GET    /api/cameras/:id/status   # Live status + last frame preview
POST   /api/cameras/:id/snapshot # Get current frame (for zone drawing)

# Events
GET    /api/events               # List events (paginated, filterable)
GET    /api/events/:id           # Single event detail
POST   /api/events/:id/feedback  # Submit approve/reject/reclassify
GET    /api/events/stats         # Counts by type, severity, time

# Alert Rules
GET    /api/alerts/rules         # List rules
POST   /api/alerts/rules         # Create rule
PATCH  /api/alerts/rules/:id     # Update rule
DELETE /api/alerts/rules/:id     # Delete rule
GET    /api/alerts/history       # Sent alert history

# Sites
GET    /api/sites
POST   /api/sites
PATCH  /api/sites/:id

# Ingest (internal — stream workers call this)
POST   /internal/events          # Stream worker posts detected events
POST   /internal/heartbeat       # Stream worker health check

# WebSocket
WS     /ws/events                # Real-time event feed for dashboard
```

---

## Stream Worker Architecture

Each camera gets assigned to a stream worker process. Workers run on GCE VMs (auto-scaled).

```
┌──────────────────────────────────────────────────────────────────┐
│                    STREAM WORKER (per camera)                      │
│                    Python process, managed by supervisor           │
│                                                                    │
│  1. CONNECT                                                        │
│     ├─ RTSP Pull: FFmpeg subprocess → raw frames                  │
│     └─ RTMP/SRT Push: read from local media server                │
│                                                                    │
│  2. RING BUFFER (30 seconds of raw frames in memory)              │
│                                                                    │
│  3. FRAME SAMPLER                                                  │
│     ├─ Compute frame diff (simple pixel diff, fast)               │
│     ├─ No motion: sample at idle_fps (default 1/sec)              │
│     └─ Motion detected: sample at active_fps (default 5/sec)     │
│                                                                    │
│  4. GEMINI VISION CALL                                             │
│     ├─ Build prompt from camera config (enabled_events, zones)    │
│     ├─ Send frame to Gemini 2.0 Flash                             │
│     ├─ Parse structured JSON response                             │
│     └─ Filter: only keep confidence > threshold (per sensitivity) │
│         - low sensitivity: conf > 0.85                            │
│         - medium: conf > 0.70                                      │
│         - high: conf > 0.50                                        │
│                                                                    │
│  5. EVENT PACKAGING (if event detected)                            │
│     ├─ Annotate snapshot with bounding boxes (PIL/OpenCV)         │
│     ├─ Cut 10s clip from ring buffer (5s before + 5s after)       │
│     ├─ Encode clip (FFmpeg, H.264, 720p max)                      │
│     ├─ Upload snapshot + clip to GCS                              │
│     └─ POST event to /internal/events API                         │
│                                                                    │
│  6. HEALTH                                                         │
│     ├─ Heartbeat every 30s to /internal/heartbeat                 │
│     ├─ Report: fps, last_frame_time, gemini_calls/min, errors     │
│     └─ Auto-reconnect on stream drop (3 retries, then mark error)│
└──────────────────────────────────────────────────────────────────┘
```

**Worker Scaling:**
- 1 GCE VM (e2-standard-4: 4 vCPU, 16GB) handles ~10-15 camera streams
- Auto-scale VM group based on camera count
- Worker assignment managed by a simple scheduler service
- If a VM dies, its cameras get reassigned to healthy VMs within 60s

---

## Gemini Prompt Strategy

```python
# Per-camera prompt built dynamically from config

SYSTEM_PROMPT = """You are a surveillance AI analyst. Analyze the camera frame and detect events.

Camera: {camera_name}
Location: {site_name}
Current time: {timestamp} ({timezone})
Enabled detections: {enabled_events_list}
Detection zones: {zones_description}
Sensitivity: {sensitivity}

Respond ONLY with valid JSON. No other text."""

USER_PROMPT = """Analyze this surveillance frame. Detect any of these event types: {enabled_events}.

Rules:
- Only report events from the enabled list
- Confidence must reflect your certainty (0.0-1.0)
- Description should be one clear sentence a security guard would understand
- If nothing notable: return empty events array

Response format:
{
  "events": [
    {
      "event_type": "person_detected|vehicle_detected|intrusion|loitering|crowd_spike|fire_smoke|ppe_violation|object_left",
      "confidence": 0.0-1.0,
      "severity": "low|medium|high|critical",
      "description": "A person entered the restricted loading dock area",
      "bounding_boxes": [{"x1": 0, "y1": 0, "x2": 100, "y2": 100, "label": "person"}],
      "zone": "zone_name_if_applicable"
    }
  ],
  "scene_summary": "Brief scene description",
  "person_count": 0
}"""
```

**Cost Estimation:**
- Gemini 2.0 Flash: ~$0.10 per 1000 image inputs
- At 1 fps average per camera: 86,400 frames/day → ~$8.64/camera/day
- With motion gating (assume 20% of frames have activity): ~$1.73/camera/day → **~₹144/camera/month** in AI cost
- Leaves healthy margin on ₹299/camera/month starter plan

---

## Notification Templates

**WhatsApp (via Gupshup/Interakt):**
```
🚨 *{severity} Alert — {site_name}*

📷 Camera: {camera_name}
🕐 Time: {timestamp}
⚡ Event: {event_type_readable}
📝 {description}

Confidence: {confidence}%

[View Event →] {event_url}
```

**Email (SendGrid):**
- HTML template with inline snapshot image
- Subject: `[{severity}] {event_type} detected at {site_name} — {camera_name}`
- CTA button: "View in Dashboard"

**Webhook:**
```json
POST {client_webhook_url}
Content-Type: application/json
X-Nightwatch-Signature: HMAC-SHA256

{
  "event_id": "uuid",
  "event_type": "intrusion",
  "severity": "high",
  "confidence": 0.89,
  "description": "A person entered Zone A after hours",
  "camera": {"id": "uuid", "name": "Loading Dock Cam 1"},
  "site": {"id": "uuid", "name": "Warehouse Mumbai"},
  "timestamp": "2026-05-26T22:15:03.456Z",
  "snapshot_url": "https://storage.../snapshot.webp",
  "clip_url": "https://storage.../clip.mp4",
  "dashboard_url": "https://app.nightwatch.ai/events/uuid"
}
```

---

## MVP Screens (Web Dashboard)

```
┌─────────────────────────────────────────────────────────────────┐
│  SCREEN 1: DASHBOARD (Home)                                      │
│                                                                   │
│  ┌─── Header ────────────────────────────────────────────────┐  │
│  │ [NIGHTWATCH logo]     Site: [Dropdown]     [User avatar]   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─── Stats Row ─────────────────────────────────────────────┐  │
│  │ [Events Today: 47] [Critical: 3] [Cameras: 8/8 online]    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─── Live Event Feed ───────────────────────────────────────┐  │
│  │                                                             │  │
│  │  22:15:03  Loading Dock  INTRUSION  HIGH  ●●●●○  [View]   │  │
│  │  22:14:51  Entrance      PERSON     LOW   ●●○○○  [View]   │  │
│  │  22:12:20  Parking       VEHICLE    LOW   ●●●○○  [View]   │  │
│  │  22:10:05  Warehouse     LOITERING  MED   ●●●○○  [View]   │  │
│  │  ...                                                        │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌─── Camera Grid ───────────────────────────────────────────┐  │
│  │  [Cam 1: ●Online]  [Cam 2: ●Online]  [Cam 3: ○Offline]   │  │
│  │  [Cam 4: ●Online]  [Cam 5: ●Online]  [Cam 6: ●Online]    │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  SCREEN 2: EVENT DETAIL                                          │
│                                                                   │
│  ┌─── Event Card ────────────────────────────────────────────┐  │
│  │                                                             │  │
│  │  ┌─────────────────────┐  Event: INTRUSION                │  │
│  │  │                     │  Camera: Loading Dock Cam 1       │  │
│  │  │   [Annotated        │  Time: 22:15:03 IST              │  │
│  │  │    Snapshot]        │  Confidence: 89%                  │  │
│  │  │                     │  Severity: HIGH                   │  │
│  │  │                     │                                   │  │
│  │  └─────────────────────┘  "A person entered the           │  │
│  │                            restricted loading dock area    │  │
│  │  [▶ Play 10s Clip]        after business hours."          │  │
│  │                                                             │  │
│  │  ┌──────────────────────────────────────────────────────┐ │  │
│  │  │ [✓ Approve]  [✗ Reject]  [↻ Reclassify ▾]          │ │  │
│  │  └──────────────────────────────────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  SCREEN 3: CAMERA SETUP                                          │
│                                                                   │
│  Add Camera:                                                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Name: [_______________]                                     │  │
│  │                                                             │  │
│  │ Ingestion Mode:                                             │  │
│  │ ○ I'll provide an RTSP URL (you pull my stream)            │  │
│  │   URL: [rtsp://_______________]                            │  │
│  │                                                             │  │
│  │ ○ Give me an endpoint (I'll push my stream)                │  │
│  │   → Your RTMP endpoint: rtmp://ingest.nightwatch.ai/live  │  │
│  │   → Stream key: nw_cam_a8f3k2...                          │  │
│  │                                                             │  │
│  │ Detect Events: (check all that apply)                       │  │
│  │ ☑ Person detected    ☑ Intrusion                           │  │
│  │ ☑ Vehicle detected   ☑ Loitering                           │  │
│  │ ☐ Crowd spike        ☐ Fire/Smoke                          │  │
│  │ ☐ PPE violation      ☐ Object left behind                  │  │
│  │                                                             │  │
│  │ Sensitivity: [●○○ Low] [○●○ Medium] [○○● High]            │  │
│  │                                                             │  │
│  │ [Draw Detection Zones →] (opens zone editor on frame)      │  │
│  │                                                             │  │
│  │                              [Save Camera]                  │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  SCREEN 4: ALERT RULES                                           │
│                                                                   │
│  ┌─── Rule Builder ──────────────────────────────────────────┐  │
│  │                                                             │  │
│  │ Rule name: [After-hours intrusion alert_____]              │  │
│  │                                                             │  │
│  │ When: [Event type ▾] is [intrusion ▾]                     │  │
│  │ And:  severity >= [HIGH ▾]                                 │  │
│  │ And:  time is between [22:00] and [06:00]                  │  │
│  │ On cameras: [All ▾] or [specific cameras...]              │  │
│  │                                                             │  │
│  │ Notify via:                                                 │  │
│  │ ☑ WhatsApp: [+91 98765 43210]                             │  │
│  │ ☑ Email: [security@client.com]                             │  │
│  │ ☐ Webhook: [https://...]                                   │  │
│  │                                                             │  │
│  │ Cooldown: [60] seconds (don't repeat same alert)           │  │
│  │                                                             │  │
│  │                              [Save Rule]                    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  Active Rules:                                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ ● After-hours intrusion — HIGH+ — 22:00-06:00 — WhatsApp │  │
│  │ ● All critical events — CRITICAL — 24/7 — All channels    │  │
│  │ ○ Crowd alert (disabled) — crowd_spike — WhatsApp          │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  SCREEN 5: EVENT HISTORY & SEARCH                                │
│                                                                   │
│  Filters: [Date range] [Camera ▾] [Event type ▾] [Severity ▾]  │
│  Search: [___________________________________] (text search)     │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ [thumb] 22:15 Loading Dock  Intrusion  HIGH  89% Approved  │  │
│  │ [thumb] 22:14 Entrance      Person     LOW   72% Pending   │  │
│  │ [thumb] 22:12 Parking       Vehicle    LOW   81% Rejected  │  │
│  │ ...                                                         │  │
│  │                              [< 1 2 3 4 5 >]               │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
nightwatch/
├── terraform/                # GCP infrastructure
│   ├── main.tf
│   ├── network.tf
│   ├── cloud-sql.tf
│   ├── gcs.tf
│   ├── cloud-run.tf
│   ├── gce-workers.tf
│   └── variables.tf
├── backend/                  # FastAPI backend
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── api/
│   │   │   ├── auth.py
│   │   │   ├── cameras.py
│   │   │   ├── events.py
│   │   │   ├── alerts.py
│   │   │   └── sites.py
│   │   ├── services/
│   │   │   ├── notification.py
│   │   │   ├── alert_engine.py
│   │   │   └── gemini.py
│   │   └── core/
│   │       ├── auth.py
│   │       ├── database.py
│   │       └── security.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── alembic/              # DB migrations
├── worker/                   # Stream processing workers
│   ├── stream_worker.py      # Main worker process
│   ├── frame_sampler.py
│   ├── motion_detector.py
│   ├── gemini_client.py
│   ├── event_packager.py
│   ├── clip_cutter.py
│   ├── uploader.py
│   ├── config.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                 # Next.js web app
│   ├── src/
│   │   ├── app/
│   │   │   ├── dashboard/
│   │   │   ├── events/
│   │   │   ├── cameras/
│   │   │   ├── alerts/
│   │   │   └── settings/
│   │   ├── components/
│   │   ├── lib/
│   │   └── styles/
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   └── package.json
├── nginx-rtmp/               # RTMP/SRT ingest server config
│   ├── nginx.conf
│   └── Dockerfile
└── docker-compose.yml        # Local dev environment
```

---

## Implementation Phases (30-day Sprint)

### Week 1: Foundation (Days 1-7) ✅ COMPLETE
- [x] PostgreSQL schema (7 models with multi-tenancy)
- [x] FastAPI skeleton with auth (custom Argon2id + AES-256-GCM sessions — stronger than planned Firebase)
- [x] Camera CRUD API with stream key generation
- [x] Basic stream worker: connect to RTSP, decode frames via FFmpeg
- [x] Docker compose for local dev (Postgres + Redis)
- [ ] GCP project setup + Terraform — DEFERRED to production phase
- [ ] RTMP ingest server (Nginx-RTMP) — DEFERRED (worker reads local RTMP for now)

### Week 2: AI Core (Days 8-14) ✅ COMPLETE
- [x] Frame sampler with motion detection (adaptive 1fps/5fps + deduplication)
- [x] Gemini Vision integration (prompt builder per camera config, circuit breaker)
- [x] Event packager (annotated WebP snapshot, 10s H.264 clip, GCS upload)
- [x] Event storage API (internal endpoint for workers)
- [x] Alert rules engine (evaluate rules, cooldown, time windows, severity matching)
- [x] Notification service: WhatsApp (Gupshup) + Email (SendGrid) + Webhook (HMAC-signed)
- [x] WebSocket real-time event push (backend → connected dashboards)

### Week 3: Frontend (Days 15-21) ✅ COMPLETE
- [x] Next.js project with dark theme (shadcn/ui, custom Nightwatch design system)
- [x] Auth flow (login/signup with username + password)
- [x] Dashboard: live event feed (10s polling) + camera status grid + stats row
- [x] Camera setup page (add camera, RTSP/RTMP mode, event types, sensitivity)
- [x] Alert rules page (create/edit/delete/toggle rules)
- [x] Event history with filters and pagination + inline feedback
- [x] Onboarding tour (11 steps, auto on first login) + help chatbot widget
- [ ] Event detail page (snapshot viewer, clip player) — NEXT
- [ ] WebSocket real-time push (currently polling) — NEXT

### Week 4: Polish & Ship (Days 22-30) ⬜ NOT STARTED
- [ ] Event detail page with snapshot + clip player
- [ ] Zone drawing tool (canvas on camera frame snapshot)
- [ ] Alembic migrations (replace create_all)
- [ ] Rate limiting middleware (Redis-backed)
- [ ] GCS signed URL generation for media access
- [ ] Admin UI page (super_admin: manage orgs/users)
- [ ] End-to-end testing with real CP Plus camera
- [ ] Cloud Run deployment (API + frontend)
- [ ] GCE worker VM setup with auto-scaling
- [ ] Monitoring: uptime checks, error alerting
- [ ] Mobile responsive adjustments
- [ ] Loading skeletons + error boundaries

---

## Cost Estimate (10 cameras, single client pilot)

| Resource | Monthly Cost |
|----------|-------------|
| GCE stream worker (e2-standard-4) | ~₹5,000 |
| Cloud SQL (db-f1-micro → db-g1-small) | ~₹2,500 |
| GCS storage (50GB clips/month) | ~₹100 |
| Redis (Memorystore basic) | ~₹2,500 |
| Cloud Run (API + frontend) | ~₹1,000 |
| Gemini API (10 cams × ₹144/cam) | ~₹1,440 |
| WhatsApp (Gupshup, ~1000 msgs) | ~₹500 |
| SendGrid (free tier) | ₹0 |
| **Total platform cost** | **~₹13,000/month** |
| **Revenue (10 cams × ₹299)** | **₹2,990/month** |
| **Revenue (10 cams × ₹599)** | **₹5,990/month** |

**Note:** First few clients will be subsidized. Break-even at ~25-30 cameras on Pro plan. Gemini cost drops significantly with smart motion gating.

---

## Key Risks & Mitigations (MVP-specific)

| Risk | Mitigation |
|------|-----------|
| Client's RTSP not reachable from cloud (NAT/firewall) | Push mode (RTMP/SRT) as alternative; setup guide with port forwarding |
| Gemini API latency spikes | Timeout + retry; skip frame if >5s; don't block stream |
| High false positive rate initially | Start at medium sensitivity; feedback buttons prominent; tune prompts fast |
| Bandwidth cost for client (uploading stream) | H.264 720p at 1Mbps = ~330GB/month/camera; document this clearly in onboarding |
| Stream worker crashes | Supervisor auto-restart; health checks; reassignment within 60s |
| WhatsApp Business API approval delay | Start with Gupshup sandbox; email as fallback until approved |

---

## What This MVP Proves

1. **Value hypothesis:** Clients will pay for AI-generated event alerts from their existing cameras
2. **Technical hypothesis:** Gemini Vision can reliably detect security events from surveillance frames
3. **Delivery hypothesis:** Cloud-only architecture works for Indian enterprise broadband
4. **Feedback hypothesis:** Clients will provide approve/reject feedback (data for future local model)

## What Comes After (feeds back into Master Plan)

- Proven demand → build edge agent (Stage 1) for clients with bandwidth constraints
- Collected feedback data → train local YOLO models (Stage 3, Phase 3)
- Scale issues → add Kafka, split services, auto-scaling (Stage 2 full)
- Anti-tamper → add as premium feature once base product proven (Stage 0-B)
- Natural language rules → LLM-powered rule builder (Stage 5, USP 4)

---

*This plan is designed to get to first paying customer in 30 days with a team of 2-3 engineers.*
