# NIGHTWATCH — Master Project Architecture Plan

---

| Field | Value |
|-------|-------|
| **Plan Name** | NIGHTWATCH Master Architecture Plan |
| **Version** | 1.0.0 |
| **Parent Plan** | None (Root) |
| **Stage** | MASTER |
| **Date Generated** | 2026-05-26 |
| **Estimated Total Effort** | 420 person-days (14 months, team of 6–10) |
| **Dependencies** | None (greenfield) |

---

## Objective

Define the complete architecture, security posture, AI pipeline, and go-to-market structure for an event-based AI CCTV intelligence SaaS platform that connects to existing camera infrastructure, generates intelligent event alerts (not video streams), and progressively trains client-specific models using human feedback — all while detecting and resisting camera tampering and video loop attacks.

---

## Platform Identity

- **Working Name:** NIGHTWATCH
- **Theme:** Matte black (#0D0D0D), white text (#F5F5F5), accent deep electric blue (#1E90FF)
- **Font:** Comic Relief (Google Fonts)
- **Tagline:** TBD (Stage 4 — Branding)
- **Architecture Philosophy:** Zero-stream, edge-first, feedback-driven, open-camera

---

## Architecture Diagram (System-Level)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           NIGHTWATCH — SYSTEM OVERVIEW                           │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────── CLIENT PREMISES (EDGE) ──────────────────────────────┐
│                                                                                  │
│  ┌──────────┐   RTSP/ONVIF    ┌────────────────────────────────────────────┐    │
│  │ Camera 1 │────────────────▶│                                            │    │
│  └──────────┘                  │         NIGHTWATCH EDGE AGENT             │    │
│  ┌──────────┐   RTSP/ONVIF    │                                            │    │
│  │ Camera 2 │────────────────▶│  ┌─────────┐  ┌──────────┐  ┌─────────┐  │    │
│  └──────────┘                  │  │ Ingest  │─▶│ Motion   │─▶│Anti-Tamp│  │    │
│  ┌──────────┐   OEM API       │  │ Worker  │  │ Filter   │  │ Monitor │  │    │
│  │ Camera N │────────────────▶│  └─────────┘  └──────────┘  └─────────┘  │    │
│  └──────────┘                  │       │                          │         │    │
│                                │       ▼                          ▼         │    │
│                                │  ┌─────────┐  ┌──────────┐  ┌─────────┐  │    │
│                                │  │ Frame   │─▶│Local YOLO│─▶│ Gemini  │  │    │
│                                │  │ Sampler │  │ Inference│  │ Escalate│  │    │
│                                │  └─────────┘  └──────────┘  └─────────┘  │    │
│                                │                      │                     │    │
│                                │                      ▼                     │    │
│                                │  ┌──────────────────────────────────────┐ │    │
│                                │  │   EVENT PACKAGER                     │ │    │
│                                │  │   (snapshot + clip + metadata JSON)  │ │    │
│                                │  └──────────────────┬───────────────────┘ │    │
│                                │                     │                      │    │
│                                │  ┌──────────────────▼───────────────────┐ │    │
│                                │  │   SECURE UPLOADER (mTLS, offline Q)  │ │    │
│                                │  └──────────────────┬───────────────────┘ │    │
│                                └─────────────────────┼──────────────────────┘    │
│                                                      │                           │
└──────────────────────────────────────────────────────┼───────────────────────────┘
                                                       │ Events only
                                                       │ (JSON + JPEG + H.264 clips)
                                                       │ mTLS / TLS 1.3
                                                       ▼
┌─────────────────────────── NIGHTWATCH CLOUD ────────────────────────────────────┐
│                                                                                  │
│  ┌────────────┐    ┌─────────────────────────────────────────────────────────┐  │
│  │ API Gateway│───▶│                    EVENT BUS (Kafka)                     │  │
│  │ (Kong)     │    │  Topics: raw_events | processed | feedback | alerts     │  │
│  └────────────┘    └───────┬──────────────┬──────────────┬───────────────────┘  │
│                            │              │              │                        │
│                            ▼              ▼              ▼                        │
│  ┌────────────────┐ ┌───────────┐ ┌────────────┐ ┌──────────────┐              │
│  │ Event Ingestion│ │ AI/ML Svc │ │ Feedback   │ │ Notification │              │
│  │ Service (Go)   │ │ (Python)  │ │ Collector  │ │ Engine       │              │
│  └───────┬────────┘ └─────┬─────┘ └─────┬──────┘ └──────┬───────┘              │
│          │                 │             │                │                       │
│          ▼                 ▼             ▼                ▼                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                         DATA LAYER                                       │    │
│  │  PostgreSQL 16 + TimescaleDB │ pgvector │ Redis 7 │ S3 │ OpenSearch     │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                      ML TRAINING PIPELINE                                │    │
│  │  Feedback → Label Store → Auto-retrain → MLflow → Model Sign → OTA Push │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────── USER INTERFACES ─────────────────────────────────────┐
│                                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Web Dashboard│  │ Mobile App   │  │ WhatsApp Bot │  │ Telegram Bot     │   │
│  │ (Next.js 14) │  │ (React Native│  │ (Business    │  │ (Bot API)        │   │
│  │              │  │  + Expo)     │  │  API)        │  │                  │   │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────────┘   │
│                                                                                  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## STAGE 0 — FOUNDATION & SECURITY ARCHITECTURE

### 0.1 Camera Integration Layer

#### Architecture: Plugin Adapter Pattern (Strategy)

```
┌──────────────────────────────────────────────────────────────┐
│                   CameraIntegrationManager                     │
│                                                                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │           ICameraAdapter (Interface)                      │ │
│  │  connect() | authenticate() | getStream() | sendPTZ()    │ │
│  │  getCapabilities() | healthCheck() | disconnect()        │ │
│  └───────────┬────────────┬────────────┬───────────────────┘ │
│              │            │            │                       │
│  ┌───────────▼──┐ ┌──────▼──────┐ ┌──▼────────────────┐    │
│  │ONVIFAdapter  │ │HikvisionISAPI│ │CPPlusAdapter      │    │
│  │(Profile S/T/G)│ │Adapter      │ │(Aditya Infotech)  │    │
│  └──────────────┘ └─────────────┘ └───────────────────┘    │
│              │            │            │                       │
│  ┌───────────▼──┐ ┌──────▼──────┐ ┌──▼────────────────┐    │
│  │DahuaSDK     │ │AxisVAPIX    │ │GenericRTSP        │    │
│  │Adapter      │ │Adapter      │ │Adapter            │    │
│  └──────────────┘ └─────────────┘ └───────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

**Protocol Support:**
| Protocol | Auth Method | Encryption | Notes |
|----------|------------|------------|-------|
| ONVIF Profile S | WS-UsernameToken | TLS 1.3 mandatory | Streaming config |
| ONVIF Profile T | WS-UsernameToken | TLS 1.3 mandatory | Analytics config |
| ONVIF Profile G | WS-UsernameToken | TLS 1.3 mandatory | Storage/replay |
| RTSP | Digest Auth | RTSPS (TLS) | Fallback: TCP interleaved |
| Hikvision ISAPI | Basic/Digest | HTTPS | SDK v6.1+ |
| CP Plus (Aditya) | OAuth2.0 | mTLS | Cloud gateway |
| Dahua SDK | Proprietary | TLS | NetSDK wrapper |
| Axis VAPIX | Digest | HTTPS | REST-based |

**Credential Management:**
- All camera credentials stored in HashiCorp Vault (dev/staging) or AWS Secrets Manager (production)
- Zero plaintext credentials in config files, environment variables, or code
- Credential rotation: automated 90-day cycle with Vault dynamic secrets
- Access audit: every credential read logged with requestor identity and timestamp

### 0.2 Anti-Tamper & Anti-Loop Detection System

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ANTI-TAMPER DETECTION ENGINE                       │
│                                                                       │
│  INPUT: Raw frames from RTSP ingest (1 fps minimum for tamper check) │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │ LAYER 1: Perceptual Hash Analysis (pHash + dHash)               ││
│  │ • Sliding window: 30 frames                                      ││
│  │ • Hamming distance threshold: < 3 bits over 30 consecutive = LOOP││
│  │ • Dual hash (pHash 64-bit + dHash 64-bit) for false-positive    ││
│  │   reduction                                                       ││
│  └──────────────────────────────┬──────────────────────────────────┘│
│                                 │ PASS                               │
│  ┌──────────────────────────────▼──────────────────────────────────┐│
│  │ LAYER 2: Temporal Variance Analysis                              ││
│  │ • Compute pixel variance σ² over 60-second sliding window        ││
│  │ • Natural scenes: σ² typically 0.05–0.3 (normalized)            ││
│  │ • Loop threshold: σ² < 0.02 sustained for 60 seconds = SUSPECT  ││
│  │ • Dead camera threshold: σ² < 0.001 for 10 seconds = OFFLINE    ││
│  └──────────────────────────────┬──────────────────────────────────┘│
│                                 │ PASS                               │
│  ┌──────────────────────────────▼──────────────────────────────────┐│
│  │ LAYER 3: Background Model Drift (GMM)                           ││
│  │ • Gaussian Mixture Model (K=5) learns scene background           ││
│  │ • Real scenes: background model evolves (lighting, shadows)      ││
│  │ • Loop: background model converges to fixed state after 5 min    ││
│  │ • Metric: KL-divergence of GMM params vs 10-min-ago snapshot    ││
│  │ • Threshold: KL-div < 0.001 for 5 min = SUSPECT                ││
│  └──────────────────────────────┬──────────────────────────────────┘│
│                                 │ PASS                               │
│  ┌──────────────────────────────▼──────────────────────────────────┐│
│  │ LAYER 4: Optical Flow Consistency                                ││
│  │ • Real scenes have micro-motion: sensor noise, JPEG artifacts,  ││
│  │   compression jitter, foliage, dust particles                    ││
│  │ • Compute dense optical flow (Farneback) every 5 seconds         ││
│  │ • Perfect loops: optical flow becomes periodic with exact period ││
│  │ • Detect periodicity via autocorrelation on flow magnitude       ││
│  │ • Period detected with r > 0.95 = CONFIRMED LOOP                ││
│  └──────────────────────────────┬──────────────────────────────────┘│
│                                 │ PASS                               │
│  ┌──────────────────────────────▼──────────────────────────────────┐│
│  │ LAYER 5: Active Challenge-Response (PTZ-capable cameras only)   ││
│  │ • Every 15 minutes: send micro PTZ move (0.1° pan)              ││
│  │ • Expect scene shift in next 2 frames                            ││
│  │ • No shift detected = TAMPER CONFIRMED                           ││
│  │ • Restore original position immediately after test               ││
│  └──────────────────────────────┬──────────────────────────────────┘│
│                                 │ PASS                               │
│  ┌──────────────────────────────▼──────────────────────────────────┐│
│  │ LAYER 6: Sensor Fusion (if available)                           ││
│  │ • Cross-validate PIR/IR sensor data with video motion           ││
│  │ • PIR triggers + no video motion = OCCLUSION/TAMPER             ││
│  │ • Video motion + no PIR = DIGITAL INJECTION suspected           ││
│  └─────────────────────────────────────────────────────────────────┘│
│                                                                       │
│  OUTPUT:                                                              │
│  • TAMPER_NONE → normal operation                                    │
│  • TAMPER_SUSPECTED → increase monitoring frequency, alert L2        │
│  • TAMPER_CONFIRMED → TAMPER_DETECTED event, freeze last-good frame, │
│    immediate alert ALL channels, forensic log entry                   │
│  • CAMERA_OFFLINE → distinct from tamper, connectivity issue          │
└─────────────────────────────────────────────────────────────────────┘
```

**Forensic Audit Log (per frame decision):**
```json
{
  "timestamp_utc": "2026-05-26T14:30:00.123Z",
  "camera_id": "cam_abc123",
  "frame_seq": 45892,
  "frame_hash_sha256": "a1b2c3...",
  "tamper_layers_evaluated": [1, 2, 3, 4],
  "tamper_scores": {
    "phash_hamming_avg": 2.1,
    "temporal_variance": 0.12,
    "gmm_kl_divergence": 0.045,
    "optical_flow_autocorr": 0.23
  },
  "verdict": "TAMPER_NONE",
  "signed_hash": "RSA-2048 signature of above fields"
}
```

### 0.3 Platform Security Architecture

#### Zero-Trust Network Model

```
┌─────────────────────────────────────────────────────────────────┐
│                    ZERO-TRUST ARCHITECTURE                        │
│                                                                   │
│  Principle: Never trust, always verify. Every request             │
│  authenticated regardless of network position.                    │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ IDENTITY LAYER                                               ││
│  │ • Service mesh: Istio with mTLS between all pods            ││
│  │ • Service identity: SPIFFE/SPIRE for workload attestation   ││
│  │ • User identity: JWT RS256 (15-min access + 7-day refresh)  ││
│  │ • Device fingerprint bound to refresh token                  ││
│  │ • MFA: TOTP/WebAuthn mandatory for Admin/Manager roles      ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ DATA ISOLATION                                               ││
│  │ • PostgreSQL RLS: tenant_id on every row, enforced at DB    ││
│  │ • Envelope encryption: data key per tenant, master key in KMS│
│  │ • S3: tenant-scoped prefixes with bucket policy enforcement ││
│  │ • Kafka: tenant-prefixed topics with ACL enforcement        ││
│  │ • Redis: key namespace isolation per tenant                  ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ ACCESS CONTROL (RBAC + ABAC)                                 ││
│  │                                                               ││
│  │ Roles:                                                        ││
│  │ • SuperAdmin — platform operator (internal only)             ││
│  │ • OrgAdmin — customer org administrator                      ││
│  │ • SiteManager — manages specific site(s)                     ││
│  │ • Operator — responds to alerts, provides feedback           ││
│  │ • Viewer — read-only dashboard access                        ││
│  │ • Auditor — read-only + audit log + export access            ││
│  │                                                               ││
│  │ ABAC attributes: time-of-day, IP range, site assignment,    ││
│  │ camera group, event severity level                            ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ ENCRYPTION                                                    ││
│  │ • At rest: AES-256-GCM (clips, snapshots, database)         ││
│  │ • In transit: TLS 1.3 (all HTTP), DTLS 1.2 (WebRTC)        ││
│  │ • Key hierarchy: AWS KMS CMK → Tenant DEK → Object          ││
│  │ • Key rotation: CMK annual, DEK 90-day automated            ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ COMPLIANCE MATRIX                                             ││
│  │ • SOC 2 Type II — audit controls, access logs, encryption   ││
│  │ • ISO 27001 — ISMS framework alignment                      ││
│  │ • DPDP Act 2023 (India) — data localisation, consent,       ││
│  │   PII minimisation, DPO appointment, breach notification    ││
│  │ • GDPR — for international deployments                      ││
│  │ • NDAA Section 889 — flag Hikvision/Dahua cameras in UI,    ││
│  │   warn on US government contract deployments                 ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ IMMUTABLE AUDIT LOG                                           ││
│  │ • Append-only: PostgreSQL + pgaudit extension                ││
│  │ • WORM backup: S3 Object Lock (Governance mode, 7-year)     ││
│  │ • Hash chain: each entry includes hash of previous entry    ││
│  │ • Legal hold: API to lock specific time ranges              ││
│  │ • Export: CSV/JSON for legal proceedings                      ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

**Threat Model (STRIDE):**

| Threat | Category | Mitigation |
|--------|----------|-----------|
| Attacker replays camera feed | Spoofing | Anti-loop detection (6 layers) |
| Unauthorized event access | Tampering | RLS + envelope encryption + audit |
| Insider exfiltrates video | Information Disclosure | Zero-stream (video never leaves edge) |
| DDoS on cloud API | Denial of Service | WAF + Shield + rate limiting + offline-first edge |
| Guard disables edge agent | Elevation of Privilege | Watchdog + tamper heartbeat + physical lock |
| Compromised model pushed to edge | Tampering | Model signing (SHA-256) + version pinning |

---

## STAGE 1 — EDGE AGENT

### Component Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     NIGHTWATCH EDGE AGENT                                  │
│                     Runtime: Python 3.11 + asyncio                         │
│                     Process Model: multiprocessing + async I/O             │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ PROCESS 1: INGEST SUPERVISOR (main process)                        │  │
│  │                                                                      │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │  │
│  │  │ Camera 1     │  │ Camera 2     │  │ Camera N     │             │  │
│  │  │ RTSP Worker  │  │ RTSP Worker  │  │ RTSP Worker  │             │  │
│  │  │ (FFmpeg sub) │  │ (FFmpeg sub) │  │ (FFmpeg sub) │             │  │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘             │  │
│  │         │                  │                  │                      │  │
│  │         ▼                  ▼                  ▼                      │  │
│  │  ┌─────────────────────────────────────────────────────────────┐   │  │
│  │  │           SHARED RING BUFFER (per camera, 300 frames)        │   │  │
│  │  └─────────────────────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ PROCESS 2: ANALYSIS PIPELINE                                       │  │
│  │                                                                      │  │
│  │  ┌──────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐ │  │
│  │  │ Frame    │───▶│ Motion    │───▶│ Anti-Tamp │───▶│ AI Router │ │  │
│  │  │ Sampler  │    │ Pre-filter│    │ Monitor   │    │           │ │  │
│  │  │ Adaptive │    │ (MOG2)   │    │ (6 layers)│    │ YOLO local│ │  │
│  │  │ 1-10 fps │    │           │    │           │    │ or Gemini │ │  │
│  │  └──────────┘    └───────────┘    └───────────┘    └─────┬─────┘ │  │
│  │                                                           │        │  │
│  │                                                           ▼        │  │
│  │  ┌─────────────────────────────────────────────────────────────┐  │  │
│  │  │ EVENT PACKAGER                                               │  │  │
│  │  │ • Annotate frame with bounding boxes                         │  │  │
│  │  │ • Cut 5-15s clip from ring buffer (pre + post event)         │  │  │
│  │  │ • Generate metadata JSON (Pydantic model)                    │  │  │
│  │  │ • Encode clip H.264 (hardware NVENC if available)            │  │  │
│  │  └─────────────────────────────────┬───────────────────────────┘  │  │
│  └────────────────────────────────────┼───────────────────────────────┘  │
│                                       │                                   │
│  ┌────────────────────────────────────▼───────────────────────────────┐  │
│  │ PROCESS 3: UPLOADER & COMMS                                        │  │
│  │                                                                      │  │
│  │  ┌──────────────┐    ┌──────────────┐    ┌───────────────────┐    │  │
│  │  │ Local Queue  │───▶│ Secure       │───▶│ Cloud API         │    │  │
│  │  │ (SQLite WAL) │    │ Uploader     │    │ (mTLS, retry,     │    │  │
│  │  │ 72hr buffer  │    │ (aiohttp)    │    │  circuit breaker) │    │  │
│  │  └──────────────┘    └──────────────┘    └───────────────────┘    │  │
│  │                                                                      │  │
│  │  ┌──────────────┐    ┌──────────────┐                              │  │
│  │  │ OTA Updater  │    │ Heartbeat    │  (every 60s: health metrics) │  │
│  │  │ (signed pkg) │    │ Reporter     │                              │  │
│  │  └──────────────┘    └──────────────┘                              │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ PROCESS 4: LOCAL DASHBOARD (optional, technician access)           │  │
│  │ FastAPI + Jinja2 templates, port 8443, TLS self-signed             │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │ WATCHDOG (systemd service, separate binary)                        │  │
│  │ • Monitor agent process health                                      │  │
│  │ • Auto-restart on crash (max 3 attempts, then alert)               │  │
│  │ • Hardware health: GPU temp, disk space, memory                     │  │
│  │ • Tamper detection: alert if agent binary modified                  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Hardware Sizing Matrix:**

| Tier | Hardware | Cameras | TOPS | Inference | Price Point |
|------|----------|---------|------|-----------|-------------|
| Lite | Raspberry Pi 5 (8GB) | 1–4 | CPU only | ONNX CPU | ~$80 |
| Standard | Jetson Orin Nano Super 8GB | 4–8 | 67 | TensorRT | ~$249 |
| Professional | Jetson Orin NX 16GB | 8–20 | 100 | TensorRT | ~$599 |
| Enterprise | Mini-PC + RTX A2000 | 20–48 | 200+ | TensorRT | ~$1,500 |
| Software-only | Client's existing server | 1–16 | Varies | ONNX CPU/CUDA | $0 hardware |

**Key Design Decisions:**
- All video stays on-premises; only event packages (JSON + snapshot + clip) are uploaded
- Offline-first: SQLite WAL queue holds 72 hours of events before risk of loss
- Adaptive frame sampling: 1 fps idle → 10 fps on motion → 30 fps on confirmed event (for clip)
- Model versioning: semver, A/B testing new vs old model with configurable traffic split
- Remote diagnostics heartbeat: GPU temp, CPU%, memory, disk, camera count, events/hour, tamper status

---

## STAGE 2 — CLOUD PLATFORM

### Service Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        NIGHTWATCH CLOUD PLATFORM                              │
│                        Region: ap-south-1 (Mumbai) primary                    │
│                        DR: me-central-1 (UAE) secondary                       │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                         INGRESS LAYER                                    │ │
│  │  CloudFront (CDN for static) → ALB → Kong API Gateway                   │ │
│  │  • Rate limiting (per-tenant, per-endpoint)                              │ │
│  │  • JWT validation                                                         │ │
│  │  • Request routing                                                        │ │
│  │  • WAF rules (OWASP, geo-blocking, bot detection)                        │ │
│  └────────────────────────────────────┬────────────────────────────────────┘ │
│                                       │                                       │
│  ┌────────────────────────────────────▼────────────────────────────────────┐ │
│  │                      SERVICE MESH (EKS + Istio)                          │ │
│  │                                                                           │ │
│  │  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐     │ │
│  │  │ event-ingest-svc│  │ auth-svc          │  │ notification-svc   │     │ │
│  │  │ (Go/Fiber)      │  │ (Go/Gin)          │  │ (Python/FastAPI)   │     │ │
│  │  │ High-throughput  │  │ JWT issue/verify  │  │ WhatsApp/Email/    │     │ │
│  │  │ event receiver   │  │ RBAC/ABAC engine  │  │ SMS/Telegram/Hook  │     │ │
│  │  └─────────────────┘  └──────────────────┘  └────────────────────┘     │ │
│  │                                                                           │ │
│  │  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐     │ │
│  │  │ ai-pipeline-svc │  │ feedback-svc      │  │ camera-mgmt-svc    │     │ │
│  │  │ (Python/FastAPI) │  │ (Go/Gin)          │  │ (Go/Gin)           │     │ │
│  │  │ Gemini proxy,    │  │ Label collection, │  │ Camera registry,   │     │ │
│  │  │ model orchestrate│  │ retrain trigger   │  │ health, config     │     │ │
│  │  └─────────────────┘  └──────────────────┘  └────────────────────┘     │ │
│  │                                                                           │ │
│  │  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐     │ │
│  │  │ search-svc      │  │ billing-svc       │  │ edge-mgmt-svc      │     │ │
│  │  │ (Python/FastAPI) │  │ (Go/Gin)          │  │ (Go/Gin)           │     │ │
│  │  │ OpenSearch +     │  │ Stripe/Razorpay,  │  │ OTA, heartbeat,    │     │ │
│  │  │ pgvector semantic│  │ usage metering    │  │ fleet management   │     │ │
│  │  └─────────────────┘  └──────────────────┘  └────────────────────┘     │ │
│  │                                                                           │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                         EVENT BUS (Kafka)                                 │ │
│  │  Topics:                                                                   │ │
│  │  • raw_events (from edge agents)                                          │ │
│  │  • processed_events (enriched, classified)                                │ │
│  │  • feedback (human labels)                                                 │ │
│  │  • alerts (to notification engine)                                         │ │
│  │  • audit_log (immutable event trail)                                      │ │
│  │  • model_updates (training triggers)                                       │ │
│  │  • edge_heartbeats (health telemetry)                                     │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                         DATA LAYER                                        │ │
│  │                                                                           │ │
│  │  ┌──────────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │ │
│  │  │ PostgreSQL 16    │  │ Redis 7      │  │ S3 (event storage)      │   │ │
│  │  │ + TimescaleDB    │  │ Cluster mode │  │ /tenant_id/YYYY/MM/DD/  │   │ │
│  │  │ + pgvector       │  │ • Sessions   │  │   /camera_id/event_id/  │   │ │
│  │  │ + pgaudit        │  │ • Rate limit │  │   ├── snapshot.webp     │   │ │
│  │  │ RLS enforced     │  │ • Pub/Sub    │  │   ├── clip.mp4          │   │ │
│  │  │                  │  │ • Cache      │  │   └── metadata.json     │   │ │
│  │  └──────────────────┘  └──────────────┘  └─────────────────────────┘   │ │
│  │                                                                           │ │
│  │  ┌──────────────────┐  ┌──────────────────────────────────────────┐    │ │
│  │  │ OpenSearch       │  │ MLflow + Model Registry                   │    │ │
│  │  │ Full-text +      │  │ • Experiment tracking                     │    │ │
│  │  │ analytics        │  │ • Model versioning                        │    │ │
│  │  │                  │  │ • Artifact storage (S3)                   │    │ │
│  │  └──────────────────┘  └──────────────────────────────────────────┘    │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    INFRASTRUCTURE (Terraform + ArgoCD)                    │ │
│  │  • EKS with Karpenter (auto-scaling, spot instances for training)        │ │
│  │  • Prometheus + Grafana + Loki (observability)                            │ │
│  │  • Vault (secrets management)                                             │ │
│  │  • cert-manager (auto TLS certificate rotation)                           │ │
│  │  • Velero (backup/disaster recovery)                                      │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Key Database Schema (PostgreSQL):**

```sql
-- Core multi-tenant schema
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('starter','pro','enterprise','government')),
    encryption_key_id TEXT NOT NULL, -- AWS KMS key ARN
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE sites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    name TEXT NOT NULL,
    address TEXT,
    geo_location POINT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE cameras (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    site_id UUID NOT NULL REFERENCES sites(id),
    name TEXT NOT NULL,
    stream_url_vault_ref TEXT NOT NULL, -- Vault path, never plaintext
    protocol TEXT NOT NULL CHECK (protocol IN ('onvif','rtsp','hikvision','cpplus','dahua','axis','generic')),
    capabilities JSONB DEFAULT '{}', -- PTZ, IR, audio, resolution
    status TEXT DEFAULT 'offline' CHECK (status IN ('online','offline','tamper_suspected','tamper_confirmed')),
    last_heartbeat TIMESTAMPTZ,
    zones JSONB DEFAULT '[]', -- detection zones drawn on frame
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- TimescaleDB hypertable for events
CREATE TABLE events (
    id UUID DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    camera_id UUID NOT NULL REFERENCES cameras(id),
    site_id UUID NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    severity TEXT CHECK (severity IN ('low','medium','high','critical')),
    description TEXT, -- natural language from AI
    description_embedding vector(768), -- pgvector for semantic search
    bounding_boxes JSONB,
    snapshot_url TEXT,
    clip_url TEXT,
    clip_duration_seconds REAL,
    ai_source TEXT CHECK (ai_source IN ('gemini','yolo_local','yolo_escalated','hybrid')),
    model_version TEXT,
    feedback_status TEXT DEFAULT 'pending' CHECK (feedback_status IN ('pending','approved','rejected','reclassified')),
    feedback_label TEXT, -- reclassified label if changed
    feedback_by UUID, -- user who gave feedback
    feedback_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    PRIMARY KEY (id, timestamp)
);
SELECT create_hypertable('events', 'timestamp');

-- Row-level security
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON events
    USING (tenant_id = current_setting('app.current_tenant')::UUID);

-- Users and RBAC
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, -- argon2id
    role TEXT NOT NULL CHECK (role IN ('super_admin','org_admin','site_manager','operator','viewer','auditor')),
    mfa_secret_vault_ref TEXT,
    sites_access UUID[] DEFAULT '{}', -- empty = all sites
    last_login TIMESTAMPTZ,
    device_fingerprints JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Immutable audit log
CREATE TABLE audit_log (
    id BIGSERIAL,
    tenant_id UUID NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_id UUID,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    details JSONB,
    ip_address INET,
    prev_hash TEXT, -- hash chain
    entry_hash TEXT NOT NULL,
    PRIMARY KEY (id, timestamp)
);
SELECT create_hypertable('audit_log', 'timestamp');

-- Edge agent registry
CREATE TABLE edge_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    site_id UUID NOT NULL REFERENCES sites(id),
    hardware_type TEXT,
    agent_version TEXT,
    model_version TEXT,
    last_heartbeat TIMESTAMPTZ,
    health JSONB, -- CPU, GPU temp, memory, disk, camera count
    status TEXT DEFAULT 'offline',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Model registry
CREATE TABLE models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    version TEXT NOT NULL,
    model_type TEXT NOT NULL, -- 'yolov8n', 'yolov8s', 'classification_head'
    vertical TEXT, -- 'retail', 'manufacturing', etc.
    metrics JSONB, -- mAP, precision, recall, F1
    training_samples INTEGER,
    artifact_url TEXT NOT NULL, -- S3 path
    signature_sha256 TEXT NOT NULL,
    status TEXT DEFAULT 'training' CHECK (status IN ('training','validating','active','deprecated','rollback')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## STAGE 3 — AI PIPELINE & PROGRESSIVE LEARNING

### Pipeline Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    AI PIPELINE — THREE-PHASE ARCHITECTURE                      │
│                                                                                │
│  ╔══════════════════════════════════════════════════════════════════════════╗  │
│  ║ PHASE 1: GEMINI-POWERED (MVP, Day 1)                                    ║  │
│  ║                                                                          ║  │
│  ║  Motion → Frame → ┌──────────────────────────────┐ → Event             ║  │
│  ║  Detect   Sample   │ Gemini Vision API            │   Package           ║  │
│  ║                     │ (gemini-2.0-flash)           │                     ║  │
│  ║                     │                              │                     ║  │
│  ║                     │ Structured prompt per        │                     ║  │
│  ║                     │ vertical (retail/mfg/etc)    │                     ║  │
│  ║                     │                              │                     ║  │
│  ║                     │ Output: event_type,          │                     ║  │
│  ║                     │ confidence, description,     │                     ║  │
│  ║                     │ bboxes, risk_level,         │                     ║  │
│  ║                     │ recommended_action           │                     ║  │
│  ║                     └──────────────────────────────┘                     ║  │
│  ╚══════════════════════════════════════════════════════════════════════════╝  │
│                                                                                │
│  ╔══════════════════════════════════════════════════════════════════════════╗  │
│  ║ PHASE 2: HYBRID (Month 2-3, after initial feedback collected)           ║  │
│  ║                                                                          ║  │
│  ║  Motion → Frame → ┌──────────┐                                          ║  │
│  ║  Detect   Sample   │ Local    │                                          ║  │
│  ║                     │ YOLOv8   │                                          ║  │
│  ║                     └────┬─────┘                                          ║  │
│  ║                          │                                                ║  │
│  ║              ┌───────────┼───────────┐                                   ║  │
│  ║              │           │           │                                    ║  │
│  ║         conf > 0.85  0.5-0.85   conf < 0.5                              ║  │
│  ║              │           │           │                                    ║  │
│  ║              ▼           ▼           ▼                                    ║  │
│  ║         ┌────────┐ ┌─────────┐ ┌──────────┐                            ║  │
│  ║         │DIRECT  │ │ESCALATE │ │ DISCARD  │                            ║  │
│  ║         │EVENT   │ │to Gemini│ │ or human │                            ║  │
│  ║         │(no API │ │for conf │ │ review   │                            ║  │
│  ║         │ cost)  │ │         │ │ queue    │                            ║  │
│  ║         └────────┘ └─────────┘ └──────────┘                            ║  │
│  ║                                                                          ║  │
│  ║  Cost saving: ~70% fewer Gemini API calls                               ║  │
│  ╚══════════════════════════════════════════════════════════════════════════╝  │
│                                                                                │
│  ╔══════════════════════════════════════════════════════════════════════════╗  │
│  ║ PHASE 3: CLIENT-SPECIFIC FINE-TUNED MODEL (Month 4+)                   ║  │
│  ║                                                                          ║  │
│  ║  ┌────────────────────────────────────────────────────────────────────┐ ║  │
│  ║  │              FEEDBACK FLYWHEEL                                      │ ║  │
│  ║  │                                                                      │ ║  │
│  ║  │  Event Alert → Human Feedback → Label Store → Training Trigger     │ ║  │
│  ║  │       ▲              │                              │               │ ║  │
│  ║  │       │              │                              ▼               │ ║  │
│  ║  │       │              │         ┌──────────────────────────────┐    │ ║  │
│  ║  │       │              │         │ Auto-retrain Pipeline         │    │ ║  │
│  ║  │       │              │         │ Trigger: feedback > 500       │    │ ║  │
│  ║  │       │              │         │ OR accuracy_delta > 5%        │    │ ║  │
│  ║  │       │              │         │                               │    │ ║  │
│  ║  │       │              │         │ 1. Export labels (CVAT fmt)   │    │ ║  │
│  ║  │       │              │         │ 2. Fine-tune YOLOv8 + head   │    │ ║  │
│  ║  │       │              │         │ 3. Validate (held-out 20%)   │    │ ║  │
│  ║  │       │              │         │ 4. MLflow log metrics        │    │ ║  │
│  ║  │       │              │         │ 5. Sign model (SHA-256)      │    │ ║  │
│  ║  │       │              │         │ 6. A/B deploy (80/20 split)  │    │ ║  │
│  ║  │       │              │         │ 7. Monitor 48hr              │    │ ║  │
│  ║  │       │              │         │ 8. Promote or rollback       │    │ ║  │
│  ║  │  Improved Model ◀───┘         └──────────────────────────────┘    │ ║  │
│  ║  │  pushed via OTA                                                     │ ║  │
│  ║  └────────────────────────────────────────────────────────────────────┘ ║  │
│  ╚══════════════════════════════════════════════════════════════════════════╝  │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Vertical AI Packs (pre-trained, shipped with MVP):**

| Vertical | Detection Classes | Model Base |
|----------|------------------|-----------|
| Retail | person_count, dwell_time, queue_depth, theft_posture, staff_zone_compliance, shoplifting_gesture | YOLOv8s + ResNet-18 classifier |
| Manufacturing | ppe_helmet, ppe_vest, ppe_gloves, ppe_goggles, forklift_proximity, restricted_area, fire, smoke | YOLOv8m + custom heads |
| Banking/BFSI | loitering, crowd_density, suspicious_object, guard_sleeping, atm_crowd, tailgating | YOLOv8s + temporal classifier |
| School | afterhours_intrusion, crowd_panic, vehicle_nogo_zone, fight_detection, unattended_bag | YOLOv8s + action recognition |
| Perimeter | line_cross, zone_enter, object_left, person_down, vehicle_type, person_running | YOLOv8n (fast) + tracker |

**Gemini Prompt Library (versioned in Git, example):**

```yaml
# prompts/retail_v1.yaml
vertical: retail
version: "1.0.0"
system_prompt: |
  You are a retail security AI analyst. Analyze the surveillance camera frame.
  The camera is positioned in a {location_type} area of a {store_type} store.
  Active zones: {zones_description}
  Current time: {timestamp}, Store hours: {store_hours}

user_prompt: |
  Analyze this frame for security-relevant events. Respond ONLY in this JSON format:
  {
    "events_detected": [
      {
        "event_type": "string (one of: person_detected, theft_posture, loitering, queue_buildup, staff_missing, suspicious_behavior, nothing_notable)",
        "confidence": 0.0-1.0,
        "description": "One sentence natural language description",
        "bounding_boxes": [{"x1": int, "y1": int, "x2": int, "y2": int, "label": "string"}],
        "risk_level": "low|medium|high|critical",
        "recommended_action": "string"
      }
    ],
    "scene_summary": "Brief scene description",
    "person_count": int,
    "anomaly_score": 0.0-1.0
  }
  If nothing notable, return events_detected as empty array with anomaly_score 0.
```

---

## STAGE 4 — FRONTEND & MOBILE

### Design System

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                     NIGHTWATCH DESIGN SYSTEM                                  │
│                                                                                │
│  Colors:                                                                       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│  │ #0D0D0D │ │ #111111 │ │ #1A1A1A │ │ #F5F5F5 │ │ #1E90FF │              │
│  │ bg-base │ │ bg-card │ │ bg-elev │ │ text    │ │ accent  │              │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘              │
│                                                                                │
│  Severity Indicators:                                                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                           │
│  │ #4ADE80 │ │ #FBBF24 │ │ #F97316 │ │ #EF4444 │                           │
│  │ low     │ │ medium  │ │ high    │ │critical │                           │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘                           │
│                                                                                │
│  Typography: Comic Relief (Google Fonts)                                       │
│  • H1: 2rem/bold  • H2: 1.5rem/bold  • Body: 0.875rem/regular               │
│  • Mono (code/timestamps): JetBrains Mono                                     │
│                                                                                │
│  Components: Shadcn/ui (dark theme) + custom overrides                        │
│  Icons: Lucide React                                                           │
│  Charts: Recharts (dark theme)                                                 │
│  Maps: Mapbox GL JS (dark style)                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Screen Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         SCREEN MAP                                             │
│                                                                                │
│  ┌─── App Shell ───────────────────────────────────────────────────────────┐ │
│  │ ┌─────────┐                                                              │ │
│  │ │ Sidebar │  ┌──────────────────────────────────────────────────────┐   │ │
│  │ │         │  │                                                        │   │ │
│  │ │ [Logo]  │  │  1. DASHBOARD (default)                               │   │ │
│  │ │         │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐             │   │ │
│  │ │ Dashboard│  │  │ Alert    │ │ Camera   │ │ Model    │             │   │ │
│  │ │ Events  │  │  │ Counters │ │ Health   │ │ Accuracy │             │   │ │
│  │ │ Cameras │  │  │ by sev.  │ │ Grid     │ │ Trend    │             │   │ │
│  │ │ Alerts  │  │  └──────────┘ └──────────┘ └──────────┘             │   │ │
│  │ │ Sites   │  │  ┌──────────────────────────────────────────┐        │   │ │
│  │ │ Analytics│  │  │ REAL-TIME EVENT FEED                     │        │   │ │
│  │ │ Audit   │  │  │ [timestamp] [camera] [type] [confidence] │        │   │ │
│  │ │ Settings│  │  │ ┌─ snapshot preview ─┐ [approve][reject] │        │   │ │
│  │ │         │  │  │ │                     │                   │        │   │ │
│  │ │         │  │  │ └─────────────────────┘                   │        │   │ │
│  │ │         │  │  └──────────────────────────────────────────┘        │   │ │
│  │ │         │  │                                                        │   │ │
│  │ │         │  │  2. EVENT VIEWER                                      │   │ │
│  │ │         │  │  ┌──────────────────────────────────────────┐        │   │ │
│  │ │         │  │  │ Timeline (horizontal scroll)              │        │   │ │
│  │ │         │  │  │ ●──●──●──●──●──●──●──●──●──●──●        │        │   │ │
│  │ │         │  │  │ Snapshot Gallery │ Clip Player            │        │   │ │
│  │ │         │  │  │ AI Reasoning Panel (why this alert)       │        │   │ │
│  │ │         │  │  │ [Approve] [Reject] [Reclassify ▾]        │        │   │ │
│  │ │         │  │  └──────────────────────────────────────────┘        │   │ │
│  │ │         │  │                                                        │   │ │
│  │ │         │  │  3. CAMERA MAP                                        │   │ │
│  │ │         │  │  ┌──────────────────────────────────────────┐        │   │ │
│  │ │         │  │  │ Floor plan / geo-map with camera icons    │        │   │ │
│  │ │         │  │  │ ● Online (green) ○ Offline (gray)        │        │   │ │
│  │ │         │  │  │ ⚠ Tamper (red pulse)                     │        │   │ │
│  │ │         │  │  │ Click camera → live status + last event   │        │   │ │
│  │ │         │  │  └──────────────────────────────────────────┘        │   │ │
│  │ │         │  │                                                        │   │ │
│  │ │         │  │  4. ALERT MANAGER                                     │   │ │
│  │ │         │  │  ┌──────────────────────────────────────────┐        │   │ │
│  │ │         │  │  │ Natural language rule input:               │        │   │ │
│  │ │         │  │  │ ┌────────────────────────────────────┐   │        │   │ │
│  │ │         │  │  │ │ "Alert me if someone enters Zone B │   │        │   │ │
│  │ │         │  │  │ │  after 10pm on weekdays"           │   │        │   │ │
│  │ │         │  │  │ └────────────────────────────────────┘   │        │   │ │
│  │ │         │  │  │ → Parsed rule preview → [Save Rule]      │        │   │ │
│  │ │         │  │  │                                           │        │   │ │
│  │ │         │  │  │ Active Rules list with toggle/edit/delete │        │   │ │
│  │ │         │  │  └──────────────────────────────────────────┘        │   │ │
│  │ │         │  │                                                        │   │ │
│  │ │         │  │  5-9. (Sites, Analytics, Audit, Settings, Mobile)    │   │ │
│  │ └─────────┘  └──────────────────────────────────────────────────────┘   │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Tech Stack:**
- Next.js 14 (App Router, Server Components for initial load)
- TypeScript (strict mode)
- Tailwind CSS (dark theme, custom design tokens)
- Shadcn/ui (component library)
- React Query (TanStack Query v5) for server state
- Zustand for client state
- Socket.io client for real-time events
- React Native (Expo) for iOS + Android
- Shared design tokens via Tailwind preset

---

## STAGE 5 — MVP FEATURE SET & USP DEFINITION

### MVP Scope (90-day delivery)

| # | Feature | Priority | Effort (days) |
|---|---------|----------|---------------|
| 1 | Camera connect (RTSP/ONVIF/CP Plus) | P0 | 15 |
| 2 | Anti-tamper/loop detection | P0 | 20 |
| 3 | Event alerts (snapshot + timestamp + AI desc) | P0 | 10 |
| 4 | 5 core events (person, vehicle, intrusion, loiter, crowd) | P0 | 12 |
| 5 | WhatsApp + Email + in-app alerts | P0 | 8 |
| 6 | Human feedback (approve/reject/reclassify) | P0 | 5 |
| 7 | 7-day clip retention | P0 | 3 |
| 8 | Dashboard (event feed + camera status) | P0 | 12 |
| 9 | Multi-user RBAC (3 roles) | P0 | 5 |
| 10 | Gemini Vision with vertical prompts | P0 | 10 |
| 11 | Natural language alert rules | P1 | 8 |
| **Total** | | | **108 days** (parallel team reduces to ~60 calendar days) |

### Unique Selling Propositions

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    COMPETITIVE DIFFERENTIATION MATRIX                          │
│                                                                                │
│  Feature              │ NIGHTWATCH │ Wobot │ Staqu │ Verkada │ Videonetics  │
│  ─────────────────────┼────────────┼───────┼───────┼─────────┼──────────────│
│  Anti-loop detection  │ ★★★★★      │ ✗     │ ✗     │ ✗       │ partial      │
│  Zero-stream (no vid  │            │       │       │         │              │
│    to cloud)          │ ★★★★★      │ ✗     │ ✗     │ ✗       │ partial      │
│  Progressive model    │ ★★★★★      │ ✗     │ ✗     │ ✗       │ ✗            │
│  NL rule builder      │ ★★★★★      │ ✗     │ ✗     │ ✗       │ ✗            │
│  Open camera (BYOC)   │ ★★★★★      │ ★★★   │ ★★★   │ ✗       │ ★★★★         │
│  Feedback flywheel    │ ★★★★★      │ ★★    │ ✗     │ ✗       │ ✗            │
│  India-first pricing  │ ★★★★★      │ ★★★★  │ ★★★★  │ ✗       │ ★★★★         │
│  DPDP compliance      │ ★★★★★      │ ★★    │ ★★    │ ✗       │ ★★★          │
│  Edge-first (low BW)  │ ★★★★★      │ ★★★   │ ★★    │ ✗       │ ★★★★         │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Hero USP Messaging (for landing page):**

1. **ANTI-LOOP DETECTION** — "Your guards can't fool our AI. We detect video loops, frozen feeds, and signal tampering in real-time. The industry's first anti-tamper intelligence layer."

2. **ZERO-STREAM ARCHITECTURE** — "Your video never leaves your building. Only smart alerts do. Full DPDP compliance, works on 10 Mbps connections, no cloud bandwidth bills."

3. **SELF-IMPROVING AI** — "Every time you approve or reject an alert, our AI gets smarter — for YOUR specific environment. Watch your false positive rate drop week over week."

4. **PLAIN ENGLISH RULES** — "Type 'Alert me if anyone enters the warehouse after 9pm' and it just works. No coding. No complex VMS menus."

5. **BRING YOUR OWN CAMERAS** — "Works with CP Plus, Hikvision, Dahua, Axis — any IP camera you already have. Zero hardware investment."

---

## STAGE 6 — FUTURE ROADMAP

| Phase | Feature | Target Quarter | Dependencies |
|-------|---------|---------------|--------------|
| 6.1 | LPR + VAHAN/SARATHI integration | Q2 2027 | Camera with >2MP, clear lane view |
| 6.2 | Face recognition (opt-in, consent-managed) | Q3 2027 | Legal review, DPDP consent flow |
| 6.3 | Audio analytics (gunshot, glass-break, scream) | Q2 2027 | Cameras with audio, edge mic |
| 6.4 | Digital Evidence Locker | Q3 2027 | Chain-of-custody design, legal consult |
| 6.5 | AI Shift Report Generator | Q1 2027 | Sufficient event history per site |
| 6.6 | Insurance API integration (Acko, Go Digit) | Q4 2027 | Partnership agreements |
| 6.7 | WhatsApp Bot Interface | Q1 2027 | WhatsApp Business API approval |
| 6.8 | Hardware Bundle (CP Plus / Sparsh) | Q3 2027 | Channel partnerships |
| 6.9 | Third-party AI Model Marketplace | Q1 2028 | Sufficient platform scale |
| 6.10 | Maritime/Defence plugin (Seecore) | Q4 2027 | Security clearance, custom models |

---

## STAGE 7 — SECURITY HARDENING CHECKLIST

### Infrastructure Security
- [ ] VPC with private subnets (services), public subnets (ALB only)
- [ ] NAT Gateway for outbound from private subnets
- [ ] Security groups: minimal ports, no 0.0.0.0/0 ingress
- [ ] AWS WAF with OWASP managed rules + custom rate rules
- [ ] AWS Shield Standard (upgrade to Advanced for high-value tenants)
- [ ] DDoS response runbook documented and tested
- [ ] VPC Flow Logs enabled, shipped to SIEM
- [ ] GuardDuty enabled, findings routed to PagerDuty

### Application Security
- [ ] OWASP Top 10 mitigated (see per-item checklist below)
- [ ] Content Security Policy headers (strict, no inline scripts)
- [ ] CORS: allowlist of known frontends only
- [ ] SQL injection: parameterised queries only (sqlx for Go, SQLAlchemy for Python)
- [ ] XSS: output encoding, React default escaping, DOMPurify for rich text
- [ ] CSRF: SameSite=Strict cookies + CSRF token for state-changing requests
- [ ] Rate limiting: 100 req/min/user (configurable per endpoint)
- [ ] Input validation: Pydantic (Python), go-playground/validator (Go)
- [ ] Dependency scanning: Snyk/Dependabot, fail CI on critical CVEs
- [ ] SAST: Semgrep in CI pipeline
- [ ] Container scanning: Trivy on all Docker images

### Camera Stream Security
- [ ] RTSPS (TLS) mandatory in enterprise tier
- [ ] Warn on unencrypted RTSP in starter/pro (allow with acknowledgement)
- [ ] Camera credential rotation: 90-day policy, automated via Vault
- [ ] Camera firmware version tracking and CVE alerting
- [ ] Network segmentation: cameras on isolated VLAN (recommended deployment guide)

### Data Security
- [ ] Encryption at rest: AES-256-GCM (RDS, S3, EBS)
- [ ] Encryption in transit: TLS 1.3 (enforce, no fallback)
- [ ] Key management: AWS KMS with CMK per tenant (envelope encryption)
- [ ] PII handling: faces blurred by default, opt-in for FR with consent log
- [ ] Data retention: automated deletion per tier policy (7/30/90 days)
- [ ] Right to deletion: tenant data purge within 72 hours of request
- [ ] Backup encryption: same key hierarchy as primary data

### Access Security
- [ ] MFA enforced: all OrgAdmin and above roles
- [ ] SSO: SAML 2.0 and OIDC support (enterprise tier)
- [ ] Session timeout: 30-min idle, 24-hour absolute
- [ ] IP allowlisting: optional for admin panel (enterprise)
- [ ] Brute-force protection: account lockout after 5 failed attempts (15-min)
- [ ] Password policy: min 12 chars, breach database check (HaveIBeenPwned API)
- [ ] Device fingerprinting: alert on new device login

### Compliance
- [ ] DPDP Act 2023: data localisation (ap-south-1), consent management, DPO contact
- [ ] PII minimisation: only store what's needed, auto-delete after retention
- [ ] Consent audit trail: every opt-in/opt-out logged with timestamp
- [ ] Breach notification: <72 hour notification workflow
- [ ] Annual penetration test: schedule with CERT-IN empaneled vendor
- [ ] SOC 2 Type II: evidence collection automated via Vanta/Drata

### Incident Response
- [ ] Auth failure alerting: >5 failures/min → PagerDuty
- [ ] Geo-anomaly: login from new country → force re-auth + alert
- [ ] Breach runbook: documented, role-assigned, tested quarterly
- [ ] Forensic readiness: logs retained 1 year, immutable, exportable
- [ ] Kill switch: per-tenant service disable capability for compromise containment

---

## STAGE 8 — MONETISATION & PRICING

### Pricing Schema

```typescript
// billing-service/src/models/pricing.ts

interface PricingTier {
  id: string;
  name: 'starter' | 'pro' | 'enterprise' | 'government';
  pricePerCameraMonthINR: number;
  features: {
    maxCamerasPerSite: number;
    maxSites: number;
    maxUsers: number;
    retentionDays: number;
    eventTypes: string[]; // 'all' or specific list
    alertChannels: string[];
    modelTraining: boolean;
    apiAccess: boolean;
    sso: boolean;
    slaUptime: number; // percentage
    support: 'community' | 'email' | 'priority' | 'dedicated';
    edgeDeployment: boolean;
    customModels: boolean;
    auditGradeLogs: boolean;
  };
}

interface AddOnModule {
  id: string;
  name: string;
  pricePerCameraMonthINR: number; // 0 if per-site pricing
  pricePerSiteMonthINR: number; // 0 if per-camera pricing
  description: string;
  requiredTier: 'starter' | 'pro' | 'enterprise' | 'any';
}

const TIERS: PricingTier[] = [
  {
    id: 'starter',
    name: 'starter',
    pricePerCameraMonthINR: 299,
    features: {
      maxCamerasPerSite: 16,
      maxSites: 3,
      maxUsers: 2,
      retentionDays: 7,
      eventTypes: ['person_detected', 'vehicle_detected', 'intrusion'],
      alertChannels: ['whatsapp', 'email', 'in_app'],
      modelTraining: false,
      apiAccess: false,
      sso: false,
      slaUptime: 99.0,
      support: 'email',
      edgeDeployment: false, // cloud-only inference
      customModels: false,
      auditGradeLogs: false,
    },
  },
  {
    id: 'pro',
    name: 'pro',
    pricePerCameraMonthINR: 599,
    features: {
      maxCamerasPerSite: 48,
      maxSites: 10,
      maxUsers: 10,
      retentionDays: 30,
      eventTypes: ['all'],
      alertChannels: ['whatsapp', 'email', 'sms', 'telegram', 'webhook', 'in_app'],
      modelTraining: true,
      apiAccess: false,
      sso: false,
      slaUptime: 99.5,
      support: 'priority',
      edgeDeployment: true,
      customModels: false,
      auditGradeLogs: false,
    },
  },
  {
    id: 'enterprise',
    name: 'enterprise',
    pricePerCameraMonthINR: 999,
    features: {
      maxCamerasPerSite: 500,
      maxSites: -1, // unlimited
      maxUsers: -1, // unlimited
      retentionDays: 90,
      eventTypes: ['all'],
      alertChannels: ['all'],
      modelTraining: true,
      apiAccess: true,
      sso: true,
      slaUptime: 99.9,
      support: 'dedicated',
      edgeDeployment: true,
      customModels: true,
      auditGradeLogs: true,
    },
  },
  {
    id: 'government',
    name: 'government',
    pricePerCameraMonthINR: 0, // custom quote
    features: {
      maxCamerasPerSite: 1000,
      maxSites: -1,
      maxUsers: -1,
      retentionDays: 365,
      eventTypes: ['all'],
      alertChannels: ['all'],
      modelTraining: true,
      apiAccess: true,
      sso: true,
      slaUptime: 99.9,
      support: 'dedicated',
      edgeDeployment: true,
      customModels: true,
      auditGradeLogs: true,
    },
  },
];

const ADD_ONS: AddOnModule[] = [
  { id: 'lpr', name: 'License Plate Recognition', pricePerCameraMonthINR: 200, pricePerSiteMonthINR: 0, description: 'ANPR with VAHAN/SARATHI lookup', requiredTier: 'pro' },
  { id: 'face_recognition', name: 'Face Recognition', pricePerCameraMonthINR: 300, pricePerSiteMonthINR: 0, description: 'Opt-in FR with consent management', requiredTier: 'enterprise' },
  { id: 'audio_analytics', name: 'Audio Analytics', pricePerCameraMonthINR: 150, pricePerSiteMonthINR: 0, description: 'Gunshot, glass-break, scream detection', requiredTier: 'pro' },
  { id: 'evidence_locker', name: 'Digital Evidence Locker', pricePerCameraMonthINR: 99, pricePerSiteMonthINR: 0, description: 'Tamper-proof legal-grade storage', requiredTier: 'pro' },
  { id: 'extended_retention', name: 'Extended Retention (+30 days)', pricePerCameraMonthINR: 49, pricePerSiteMonthINR: 0, description: 'Additional 30-day retention block', requiredTier: 'any' },
  { id: 'whatsapp_bot', name: 'WhatsApp Bot Interface', pricePerCameraMonthINR: 0, pricePerSiteMonthINR: 499, description: 'Full system control via WhatsApp', requiredTier: 'pro' },
];
```

### Usage Metering

```
┌──────────────────────────────────────────────────────────────────┐
│                    BILLING DIMENSIONS                              │
│                                                                    │
│  Primary: Camera-month (base subscription)                        │
│                                                                    │
│  Metered overages:                                                 │
│  • Gemini API calls beyond tier budget → ₹0.50 per 1000 calls   │
│  • Storage beyond retention → ₹2 per GB/month                    │
│  • Model retraining beyond 1/quarter (starter) → ₹999/retrain   │
│  • API calls beyond rate limit → ₹0.10 per 1000 calls           │
│                                                                    │
│  Billing: Monthly, auto-debit (Razorpay)                          │
│  Enterprise: Annual contract, invoice (NET-30)                    │
│  Government: PO-based, milestone billing                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## DATA FLOW — PRIMARY USE CASE (Event Detection to Alert)

```
Step 1:  Camera streams RTSP to Edge Agent RTSP Worker
Step 2:  Frame Sampler pulls frame at adaptive rate (1-10 fps based on motion)
Step 3:  MOG2 motion pre-filter: no motion → skip (save compute)
Step 4:  Anti-tamper monitor evaluates frame (parallel path, every frame at 1fps)
Step 5:  IF motion detected → frame sent to AI Router
Step 6:  AI Router: Local YOLO inference first
Step 7:  IF YOLO confidence > 0.85 → direct event (no Gemini call)
         IF YOLO confidence 0.5-0.85 → escalate to Gemini Vision API
         IF YOLO confidence < 0.5 → discard
Step 8:  Event Packager: annotate frame, cut 5-15s clip from ring buffer
Step 9:  Generate event JSON (timestamp, type, confidence, description, bbox)
Step 10: Store in local SQLite queue
Step 11: Secure Uploader sends to Cloud via mTLS (retry with backoff)
Step 12: Cloud Event Ingestion Service receives, publishes to Kafka raw_events
Step 13: Event processor enriches (tenant context, zone matching, rule evaluation)
Step 14: Publishes to processed_events topic
Step 15: Alert Rules Engine evaluates against tenant's configured rules
Step 16: IF rule matches → publish to alerts topic
Step 17: Notification Engine delivers alert via configured channels:
         - WhatsApp Business API (template message with snapshot)
         - Email (HTML with inline snapshot)
         - In-app WebSocket push
         - SMS (for critical severity only)
Step 18: User sees alert → taps → opens Event Viewer
Step 19: User provides feedback: approve / reject / reclassify
Step 20: Feedback stored → when threshold reached → trigger model retrain
```

**Latency Budget (30-second end-to-end target):**

| Step | Component | Budget |
|------|-----------|--------|
| 1-3 | Frame capture + motion filter | 1s |
| 4-7 | AI inference (YOLO + optional Gemini) | 3-8s |
| 8-9 | Event packaging (clip encoding) | 2-5s |
| 10-11 | Upload to cloud | 2-5s (10 Mbps link) |
| 12-16 | Cloud processing + rule eval | 1-2s |
| 17 | Notification delivery | 2-5s (WhatsApp API) |
| **Total** | | **11-26s** (within 30s budget) |

---

## DEPLOYMENT ARCHITECTURE

```yaml
# kubernetes/base/kustomization.yaml structure
namespaces:
  - nightwatch-prod
  - nightwatch-staging

services:
  event-ingest:
    replicas: 3 (HPA: 3-20, target CPU 70%)
    resources: { cpu: "500m", memory: "512Mi" }
    health: /health (liveness), /ready (readiness)

  ai-pipeline:
    replicas: 2 (HPA: 2-10, target queue depth)
    resources: { cpu: "1000m", memory: "2Gi" }
    gpu: optional (for local inference cache)
    health: /health

  notification:
    replicas: 2
    resources: { cpu: "250m", memory: "256Mi" }
    health: /health

  auth:
    replicas: 2
    resources: { cpu: "250m", memory: "256Mi" }
    health: /health

  web-frontend:
    replicas: 2
    resources: { cpu: "100m", memory: "128Mi" }
    cdn: CloudFront

databases:
  postgresql:
    instance: db.r6g.xlarge (prod), db.t4g.medium (staging)
    multi-az: true
    storage: gp3, encrypted

  redis:
    instance: cache.r6g.large
    cluster-mode: enabled, 3 shards

  kafka:
    brokers: 3 (MSK)
    retention: 7 days (raw_events), 30 days (audit)

  opensearch:
    nodes: 3 (r6g.large.search)
    storage: 500GB per node

storage:
  s3:
    bucket: nightwatch-events-{env}
    lifecycle: transition to IA after 30 days, Glacier after 90
    encryption: SSE-KMS with per-tenant CMK
```

---

## TEST STRATEGY (Cross-Stage)

| Level | Scope | Tools | Coverage Target |
|-------|-------|-------|-----------------|
| Unit | Individual functions, classes | pytest (Python), go test (Go), Jest (TS) | 80% line coverage |
| Integration | Service-to-service, DB queries | testcontainers, docker-compose | Critical paths |
| E2E | Full user flows | Playwright (web), Detox (mobile) | Top 10 user journeys |
| Load | Throughput, latency under load | k6, Locust | 1000 events/sec sustained |
| Security | OWASP, pentest, SAST | Semgrep, ZAP, Snyk | Zero critical/high |
| Chaos | Resilience, failover | Litmus (K8s), custom | Monthly chaos days |
| Anti-tamper | Loop detection accuracy | Custom test harness with known loops | >99% detection rate |
| AI accuracy | Detection precision/recall | Custom eval suite per vertical | mAP@0.5 > 0.7 (MVP) |

---

## RISK REGISTER

| # | Risk | Probability | Impact | Mitigation |
|---|------|------------|--------|-----------|
| 1 | Gemini API cost escalation at scale | High | High | Hybrid model (Phase 2) reduces calls 70%; per-tenant token budget; fallback to local YOLO |
| 2 | Indian broadband unreliability (edge-to-cloud) | High | Medium | Offline-first design; 72hr local buffer; adaptive compression; event prioritisation |
| 3 | Camera manufacturer API breaking changes | Medium | Medium | Adapter pattern isolates changes; ONVIF as universal fallback; version pinning with gradual migration |
| 4 | False positive fatigue (users ignore alerts) | Medium | High | Feedback flywheel reduces FP over time; configurable sensitivity; "Model Accuracy" graph shows improvement |
| 5 | Competitor copies anti-tamper feature | Medium | Medium | First-mover advantage; 6-layer detection depth is hard to replicate; patent filing for method |
| 6 | DPDP Act regulatory uncertainty | Medium | High | Privacy-by-design (zero-stream, blur-by-default); DPO appointment; legal counsel retained |
| 7 | Edge hardware supply chain (Jetson availability) | Low | High | Multi-hardware support; software-only mode; Raspberry Pi as low-end fallback |
| 8 | Team scaling (specialised CV/ML engineers in India) | Medium | Medium | Remote-first; competitive comp; open-source contribution for employer brand |

---

## CHILD PLANS TO GENERATE

| Plan ID | Name | Description | Priority |
|---------|------|-------------|----------|
| STAGE-0-A | Camera Adapter Framework | Detailed design of plugin architecture, ONVIF/RTSP implementation, credential vault integration | P0 |
| STAGE-0-B | Anti-Tamper Engine | Algorithm specifications, threshold tuning methodology, test harness design | P0 |
| STAGE-0-C | Security Architecture Implementation | IAM, encryption, RLS, audit log implementation details | P0 |
| STAGE-1-A | Edge Agent Core | Process architecture, FFmpeg integration, ring buffer, watchdog | P0 |
| STAGE-1-B | Edge AI Runtime | YOLO/TensorRT integration, Gemini client, model hot-swap | P0 |
| STAGE-1-C | Edge Networking | mTLS uploader, offline queue, OTA updater, heartbeat | P0 |
| STAGE-2-A | Cloud Infra (Terraform) | VPC, EKS, RDS, MSK, S3 — full IaC | P0 |
| STAGE-2-B | Event Ingestion Pipeline | Go service, Kafka consumers, PostgreSQL write path | P0 |
| STAGE-2-C | Auth & RBAC Service | JWT, ABAC engine, MFA, SSO integration | P0 |
| STAGE-2-D | Notification Engine | WhatsApp/Email/SMS/Telegram/Webhook delivery | P1 |
| STAGE-3-A | Gemini Prompt Engineering | Prompt library per vertical, response parsing, cost optimization | P0 |
| STAGE-3-B | Model Training Pipeline | Feedback collection, auto-retrain, MLflow, OTA push | P1 |
| STAGE-4-A | Frontend Design System | Component library, theme, responsive layout | P1 |
| STAGE-4-B | Dashboard & Event Viewer | Core web screens implementation | P1 |
| STAGE-4-C | Mobile App | React Native implementation | P2 |
| STAGE-5-A | MVP Integration & QA | End-to-end integration, load testing, security audit | P0 |
| STAGE-8-A | Billing Service | Razorpay integration, usage metering, invoice generation | P1 |

---

## SUGGESTED PLATFORM NAMES

| # | Name | Vibe |
|---|------|------|
| 1 | **Tessera** | Mosaic tile — many cameras forming one picture |
| 2 | **Kestrel** | Sharp-eyed bird of prey, fast and precise |
| 3 | **Umbra** | Shadow/darkness — watching from the dark |
| 4 | **Nullpoint** | Technical, precise, zero-tolerance for blind spots |
| 5 | **Vigilus** | Latin-inspired — vigilance without the cliche |
| 6 | **Flintcore** | Hard, sparking, foundational — industrial strength |
| 7 | **Greymark** | Subtle, professional, audit/intelligence tone |
| 8 | **Lumeniq** | Light + IQ — intelligent illumination of events |
| 9 | **Caldus** | Latin for "sharp/clever" — understated intelligence |
| 10 | **Sentara** | Sentinel + aura — protective presence |

---

## DEFINITION OF DONE (Master Plan)

- [x] All 9 stages defined with clear scope and boundaries
- [x] Architecture diagrams for system, edge, cloud, and AI pipeline
- [x] Security architecture covers zero-trust, encryption, compliance
- [x] Database schema covers multi-tenancy, events, RBAC, audit
- [x] Anti-tamper system designed with 6-layer detection
- [x] Pricing model defined with code schema
- [x] Competitive differentiation articulated (6 USPs)
- [x] Risk register with mitigations
- [x] Child plan list enables recursive planning
- [x] Hardware sizing matrix for edge deployments
- [x] Latency budget fits 30-second delivery target
- [ ] **NEXT:** Generate first child plan (recommended: STAGE-0-B Anti-Tamper Engine)

---

*This is a living document. Each child plan generated from this master plan must reference back to this document and follow the same 13-section output format.*

**Document Hash:** To be computed on final version
**Next Review:** After Stage 0 child plans complete
