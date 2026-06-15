# NIGHTWATCH — Identity & Activity Intelligence Plan

**Status:** Draft — not in MVP. Target vertical: warehouses, manufacturing plants,
construction sites, logistics hubs.

**Goal:** Upgrade from "something moved → alert" to:
- *Who* is in the frame (named person, enrolled per org)
- *What* they are doing (activity classification)
- *Summaries* per worker / shift / zone ("Ramesh spent 4.2h at packing station 2,
  loaded 31 pallets, idle 38 min, 1 PPE violation")

---

## 0. Hard constraints (read first)

### 0.1 Detector license — NO Ultralytics YOLO without sign-off
Ultralytics YOLOv8/v11 is **AGPL-3.0**. For a closed-source SaaS this requires the
paid Ultralytics Enterprise License. Apache-2.0 alternatives with equivalent or
better accuracy and full fine-tuning support:

| Model | License | Notes |
|---|---|---|
| **RF-DETR** (Roboflow) | Apache-2.0 | SOTA real-time DETR, easy fine-tune, recommended default |
| **RT-DETRv2** | Apache-2.0 | Strong, HF `transformers` support |
| **D-FINE** | Apache-2.0 | Top COCO numbers, newer |
| **YOLOX** | Apache-2.0 | Older but battle-tested, true "YOLO" if the name matters |

**Decision:** default to **RF-DETR** for the trainable detector; keep it behind the
existing `DetectorBackend` abstraction in `worker/nightwatch_locate.py` so it's
swappable. "YOLO" in marketing copy ≠ Ultralytics in the stack.

### 0.2 Face recognition is biometric data — compliance gate
- InsightFace **code** is MIT but its **pretrained models are non-commercial** —
  do not ship them. Options: train ArcFace from scratch on licensed data, license
  a commercial SDK (Paravision, Luxand), or use cloud APIs (AWS Rekognition) —
  note cloud APIs violate our "video never leaves the worker" rule unless we send
  face crops only (acceptable: crops are already event data).
- Workplace face recognition requires **explicit employee consent** (GDPR Art. 9,
  Illinois BIPA, India DPDP). Must be:
  - Opt-in **per org** (feature flag, off by default)
  - Enrollment requires the employee's own action or documented consent record
  - Embeddings stored encrypted, deletable on request (right to erasure)
  - Per-org data isolation (existing org_id pattern)
- **Fallback for orgs that decline biometrics:** appearance-based re-ID
  (clothing/build embedding, no face) + badge/helmet color zones — gives "Worker A
  / Worker B" track continuity without identity, still enables activity summaries.

### 0.3 Video stays at the edge
All inference (detect, track, face embed) runs on the **worker**. Only metadata,
crops, embeddings, and 10s event clips go to cloud — unchanged from current rules.

---

## 1. Architecture overview

```
                         ┌──────────────────────── WORKER (edge GPU) ────────────────────────┐
RTSP frame ─► Detector (RF-DETR, fine-tuned per-org classes: person, forklift,    │
              pallet, box, PPE-helmet, PPE-vest, ...)                              │
                │                                                                  │
                ▼                                                                  │
              Tracker (ByteTrack — Apache-2.0) ─► persistent track_id per object   │
                │                                                                  │
                ├─► Face-ID head (only if org opted in): detect face in person     │
                │   box → embed → match against org gallery → person_id + name     │
                │                                                                  │
                ├─► Zone engine (existing EventRule zones): which station/aisle    │
                │   each track is in, dwell timers                                 │
                │                                                                  │
                └─► Activity sampler: every N sec per active track, crop + short   │
                    clip → Gemini Vision: "what is this person doing?" →           │
                    structured activity label {working|idle|walking|lifting|       │
                    operating_machine|violation:<type>|unknown} + free description │
                └──────────────────┬───────────────────────────────────────────────┘
                                   │  activity_events (metadata only)
                                   ▼
                              BACKEND (existing /internal/events, extended)
                                   │
              ┌────────────────────┼──────────────────────┐
              ▼                    ▼                       ▼
        events table        activity_log table      Digest service (existing)
        (alerts as today)   (track-level samples)   + per-worker / per-shift
                                                    summaries via Gemini text
```

Key idea: **Gemini stays the "understanding" layer** (already in the pipeline,
already cost-capped); the trainable detector + tracker + face-ID are the new
"perception" layer that gives Gemini *who* and *where* context, so its outputs
become attributable per person and aggregable over time.

---

## 2. New components

### 2.1 Worker (Python, edge)
| Module | Purpose |
|---|---|
| `worker/detect/rfdetr_backend.py` | `DetectorBackend` impl, loads per-org fine-tuned weights, multi-class |
| `worker/track/bytetrack.py` | ByteTrack association → stable `track_id` across frames |
| `worker/identity/face_id.py` | Face detect (SCRFD-class, license-check) → embed → cosine match vs org gallery (FAISS, local) |
| `worker/identity/reid.py` | Non-biometric fallback: appearance embedding for track re-association |
| `worker/activity/sampler.py` | Per-track crop/clip sampling, rate-limited Gemini activity calls |
| `worker/activity/schema.py` | Structured activity output (Pydantic): label, confidence, description, ppe flags |

Gemini call budget: activity sampling is gated like motion-gating today —
only sample when a track is in a watched zone AND (state changed OR dwell timer
fires, e.g. every 60–120s per track), not per frame.

### 2.2 Backend (FastAPI)
New models:
- `persons` — org_id, name, role, consent_status, enrolled_at, active
- `person_embeddings` — person_id, embedding (encrypted bytea), source_image ref
- `activity_log` — org_id, camera_id, track_id, person_id (nullable), zone,
  activity_label, confidence, description, started_at, ended_at
- `training_jobs` — org_id, dataset snapshot ref, base model, status, metrics, weights URI
- `annotations` — org_id, event_id/snapshot ref, boxes+labels (user-drawn), labeler_id

New routes (all org-scoped):
- `POST /api/persons` + enrollment flow (`POST /api/persons/{id}/enroll` with face images)
- `GET/DELETE /api/persons/{id}/embeddings` (erasure support)
- `GET /api/activity` — filterable log (person, camera, zone, time range)
- `GET /api/activity/summary?person_id=&range=` — aggregates for dashboard
- `POST /api/annotations` — label submissions from the UI
- `POST /api/training-jobs` + status polling — kicks off fine-tune
- Worker-internal: `POST /internal/activity` (batched), `GET /internal/models/{org_id}/latest`
  (signed URL to current fine-tuned weights), `GET /internal/gallery/{org_id}` (embeddings sync)

### 2.3 Training pipeline ("user trains the model")
Users don't train face models — they **enroll** people (10–20 face crops each;
embedding gallery, no training). What users *train* is the **detector** on their
site-specific classes (their forklifts, their pallet types, their PPE colors):

1. **Label** — dashboard shows recent snapshots; user draws boxes + assigns class
   (reuses the planned P2 zone-drawing canvas). Pre-label with the current model
   so the user only corrects (active learning loop).
2. **Dataset** — backend snapshots annotations → COCO-format dataset in GCS per org.
3. **Fine-tune** — `training_jobs` row → GPU job (Cloud Run job / GCE spot with GPU)
   fine-tunes RF-DETR from the base checkpoint. ~30 min on one L4 for a few
   hundred images.
4. **Eval + deploy** — job reports mAP per class; user clicks "deploy"; worker
   polls `/internal/models/{org_id}/latest` and hot-swaps weights.
5. **Feedback loop** — existing event thumbs-up/down feeds back as hard examples.

Minimum viable dataset: ~150–300 labeled frames per org for site-tuning
(base model already knows person/vehicle/box generically).

### 2.4 Frontend (Next.js)
- `/people` — enroll/manage persons, consent status, per-person activity timeline
- `/activity` — live board: who is where now, doing what (per camera/zone)
- `/training` — labeling canvas, dataset stats, train button, job status, deploy
- Digest page additions: shift summary cards per worker
- Alert rules extended: "alert when **person X** enters zone Y", "alert on
  unknown person in restricted zone", "PPE violation", "idle > N min in zone"

### 2.5 Digest / summaries (existing service, extended)
- New digest type `shift_summary`: per org per shift, aggregates `activity_log` →
  one Gemini **text** call (same pattern as existing digests, metadata only):
  per-worker hours by zone, activity mix, exceptions (violations, unknown persons,
  long idle), narrative paragraph.
- On-demand: "what did worker X do today?" → `GET /api/activity/summary` + Gemini.

---

## 3. Phasing

### Phase 1 — Tracking + zones + activity (no identity) ~3–4 wks
ByteTrack on top of current detector, zone dwell, Gemini activity sampling,
`activity_log` + `/activity` page, anonymous "Worker A/B" summaries.
**Ships value without any biometric/compliance work.**

### Phase 2 — Trainable detector ~3–4 wks
RF-DETR backend, labeling UI, dataset pipeline, fine-tune job, model deploy/hot-swap.
Per-org classes (forklift, pallet, PPE).

### Phase 3 — Identity (opt-in) ~3–4 wks
Consent flow, enrollment, face embedding + gallery match on worker, named
activity logs and alerts, erasure endpoints. Legal review **before** build.

### Phase 4 — Vertical packaging ~2 wks
Shift summary digests, warehouse rule templates (restricted zone, PPE, idle,
unknown person), analytics dashboard, pricing tier ("Nightwatch Industrial").

---

## 4. Open decisions
1. **Face stack:** commercial SDK vs self-trained ArcFace vs face-crops-to-cloud-API.
   (Cost vs accuracy vs the "video stays local" promise — crops-only may be acceptable.)
2. **Edge GPU requirement:** detector+tracker+face on CPU is feasible at 1–2 fps
   for ≤4 cameras; beyond that the worker box needs a GPU (Jetson Orin / RTX A2000).
   Affects the hardware story for industrial customers.
3. **Training compute:** per-org fine-tune jobs on demand (spot GPU) vs scheduled batch.
4. **LocateAnything/OWLv2 role:** keep as zero-shot fallback for classes the
   fine-tuned model wasn't trained on (rare-event prompts), behind the same
   `DetectorBackend` interface.

## 5. Explicitly out of scope
- Ultralytics YOLO without an enterprise license decision
- Continuous video upload to cloud for activity analysis
- Emotion/demographic inference (legal + ethical no-go)
- Real-time pose-based action recognition (Phase 5+, only if Gemini sampling
  proves too coarse)
