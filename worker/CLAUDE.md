# Nightwatch Worker — Development Rules

## What's Already Built (Current State)

### Completed
- **Full project scaffold:** Dockerfile (Python 3.11 + FFmpeg), requirements.txt, .env.example, cameras.json.example
- **Stream ingest (stream_ingest.py):** FFmpeg subprocess management, RTSP pull + RTMP push support, auto-reconnect with exponential backoff (5 attempts), raw BGR24 frame output at 720p
- **Ring buffer (ring_buffer.py):** Circular deque holding 30s of timestamped frames, window extraction for clip cutting
- **Motion detector (motion_detector.py):** Frame differencing (grayscale + blur + absdiff + threshold), 1% pixel change threshold, <1ms per frame
- **Frame sampler (frame_sampler.py):** Adaptive state machine (IDLE 1fps / ACTIVE 5fps), 10s no-motion timeout, frame deduplication via correlation check (>98% similar = skip)
- **Gemini client (gemini_client.py):** google-genai SDK async calls, gemini-2.0-flash model, structured JSON response, circuit breaker (10 failures → 30s pause), semaphore concurrency limit, confidence filtering per sensitivity level
- **Prompt builder (prompt_builder.py):** Camera-config-driven prompt generation with enabled events, detection zones, sensitivity, timestamp/timezone
- **Event packager (event_packager.py):** OpenCV bounding box annotation (#1E90FF blue), WebP snapshot encoding (quality 85), 10s H.264 clip cutting via FFmpeg subprocess (CRF 28), GCS upload, POST to backend API
- **GCS uploader (gcs_uploader.py):** google-cloud-storage SDK, async upload to configurable bucket
- **API client (api_client.py):** httpx async client, posts events to `/internal/events`, sends heartbeats to `/internal/heartbeat`, X-Worker-Key auth
- **Camera worker (camera_worker.py):** Full pipeline orchestration per camera (ingest → buffer → motion → sample → AI → package), stats tracking, heartbeat reporting, error recovery
- **Supervisor (supervisor.py):** Manages multiple camera workers, loads config from cameras.json, health checks every 30s, auto-restarts dead workers, Gemini stats logging
- **Latest-frame periodic uploader:** encode current frame as WebP q70 every 2s and upload to GCS at `latest/{camera_id}.webp` for live-view polling.
- **Main entry (main.py):** asyncio runner, SIGTERM/SIGINT graceful shutdown
- **Unit tests (10 passing):** motion_detector (4 tests), ring_buffer (4 tests), prompt_builder (2 tests)

### Not Yet Built (Planned)
- Nginx-RTMP server config (for RTMP push mode receiving)
- Local event queue (SQLite fallback when backend unreachable)
- Model hot-swap / OTA update capability
- GCE instance template / auto-scaling config
- Integration tests with real RTSP streams
- Monitoring / metrics export (Prometheus)
- Multi-process mode (currently single-process with async tasks per camera)

## Identity
- **Service:** Stream Processing Worker
- **Language:** Python 3.11+
- **Key Deps:** FFmpeg (subprocess), OpenCV, google-genai SDK, httpx
- **Deployment:** GCE VMs or any Linux machine with FFmpeg installed

## Architecture Rules

### Pipeline Design
- Each camera gets its own `CameraWorker` instance (isolated processing)
- Pipeline stages are sequential per camera: Ingest → Buffer → Motion → Sample → AI → Package → Upload
- `WorkerSupervisor` manages all camera workers on a single machine
- Workers are async (asyncio) — FFmpeg frame reads are offloaded with `asyncio.to_thread`
- Never block the event loop — all I/O is async or threaded

### Stream Handling
- RTSP pulled via FFmpeg subprocess piping raw frames to stdout
- RTMP push mode: read from local nginx-rtmp as if it were RTSP
- Decode to exactly 720p BGR24 — NEVER send full-res to Gemini (waste of tokens)
- Ring buffer holds last 30 seconds of frames (for clip extraction)
- Ring buffer stores raw numpy arrays in a `deque(maxlen=N)` — simple and fast
- Auto-reconnect on stream drop: 5 attempts with exponential backoff (5s, 10s, 15s, 20s, 25s)
- After max reconnects → mark camera "error" via heartbeat, stop trying

### Motion Detection
- Gate ALL Gemini calls behind motion detection — no motion = no API call = no cost
- Use simple frame differencing (grayscale + blur + absdiff + threshold)
- Threshold: 1% of pixels changed = motion detected
- Cost: <1ms per frame — negligible
- This is the #1 cost-saving measure — without it, Gemini bills explode

### YOLO Local Detection Gate
- After motion + frame sampling, a local YOLOv8n ONNX model (`yolo_detector.py`, CPU-only via onnxruntime) runs before any Gemini call
- No relevant object (mapped from `enabled_events`) in frame → drop, no Gemini call at all
- High-confidence person/vehicle/animal/intrusion (>= `YOLO_FASTPATH_CONFIDENCE`, default 0.75) → event emitted directly from YOLO, no Gemini call
- Mid-confidence (between `YOLO_ESCALATE_FLOOR` and fastpath threshold) or any other enabled event type (loitering, custom types) → escalates to Gemini exactly as before
- Model file lives at `models/yolov8n.onnx` (path configurable via `YOLO_MODEL_PATH`); if missing or fails to load, `YoloDetector.available` is `False` and every frame escalates to Gemini — fail-soft, never crashes the worker
- To (re)generate the model: `pip install ultralytics && python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"`, then move the resulting `yolov8n.onnx` into `models/`

### Pose-Based Step-Sequence Tracking
- For cameras with a non-empty `step_sequence` configured, a local YOLOv8-pose ONNX model (`pose_detector.py`, CPU-only via onnxruntime) runs after the YOLO gate stage, independent of its drop/emit/escalate decision
- Detected people are tracked frame-to-frame with a greedy IoU tracker (`person_tracker.py`, no re-identification — a lost track starts a fresh sequence on reappearance)
- Each tracked person's (zone, pose label) is checked against the camera's ordered `step_sequence` by `sequence_engine.py`; skipping ahead, stalling past a step's `max_seconds`, or completing all steps emits a `step_skipped` / `step_timeout` / `sequence_completed` event directly — no Gemini call
- Pose labels are geometric heuristics on 17 COCO keypoints: `standing`, `bending`, `crouching`, `sitting`, `reaching`, `unknown` (see `classify_pose` in `pose_detector.py`)
- Model file lives at `models/yolov8n-pose.onnx` (path configurable via `POSE_MODEL_PATH`); if missing or fails to load, `PoseDetector.available` is `False` and the stage is skipped entirely — fail-soft, never crashes the worker
- To (re)generate the model: `pip install ultralytics && python3 -c "from ultralytics import YOLO; YOLO('yolov8n-pose.pt').export(format='onnx')"`, then move the resulting `yolov8n-pose.onnx` into `models/`

### Frame Sampling
- Two states: IDLE (1 fps to AI) and ACTIVE (5 fps to AI)
- Transition: motion detected → ACTIVE; no motion for 10s → IDLE
- Deduplication: skip if frame >98% similar to last sampled (SSIM/correlation check)
- Never exceed `gemini_max_concurrent` simultaneous API calls (semaphore-controlled)
- Max budget: 5 calls/second/camera (configurable)

### Gemini Vision API
- Model: `gemini-2.0-flash` (fast, cheap, vision-native)
- Auth: Vertex AI via Application Default Credentials (`gcloud auth application-default login`) is the primary path
- Fallback: if Vertex client init fails OR a call returns an auth error (401/403/credential), and `GEMINI_API_KEY` is set, the client transparently switches to `genai.Client(api_key=...)` (AI Studio endpoint) and retries once. If no key is set, behavior is unchanged.
- ALWAYS request `response_mime_type="application/json"` for structured output
- Temperature: 0.1 (near-deterministic for consistent detections)
- Timeout: 10 seconds per call — skip frame on timeout, don't retry
- Circuit breaker: >10 failures in 60s → pause all Gemini calls for 30s
- Parse response as JSON — if malformed, log and skip (don't crash)
- Filter events by camera's `enabled_events` list AND `sensitivity` threshold:
  - low: confidence > 0.85
  - medium: confidence > 0.70
  - high: confidence > 0.50

### Event Packaging
- Annotate snapshot with bounding boxes (OpenCV, blue color #1E90FF)
- Encode snapshot as WebP quality 85 (~50-100KB)
- Cut 10s clip from ring buffer (5s before + 5s after event)
- Encode clip as H.264 MP4 via FFmpeg subprocess (CRF 28, fast preset)
- Upload snapshot + clip to GCS asynchronously
- POST event to backend `/internal/events` endpoint
- On backend unreachable: log locally, retry on next heartbeat cycle

### Live MJPEG stream server
- `MJPEGServer` (mjpeg_server.py) serves `GET /stream/{camera_id}?token=...` on `MJPEG_SERVER_PORT` (default 8090), streaming each camera's latest decoded frame as `multipart/x-mixed-replace` JPEG at `MJPEG_FPS`
- This is the primary live-view path; the frontend falls back to snapshot polling (`/latest-frame`) if it errors
- If `STREAM_TOKEN_SECRET` is set, every request must include a valid `?token=` issued by the backend's `GET /api/cameras/{id}/stream-url` (HMAC-SHA256, `{camera_id}:{expires_at}`, shared secret) — invalid/expired/mismatched tokens get 403. `STREAM_TOKEN_SECRET` must match the backend's setting
- Empty `STREAM_TOKEN_SECRET` disables auth — local dev only, never in production
- NEVER expose this server outside the LAN/worker network without the token check enabled

### Live snapshot upload
- Each camera worker uploads its latest decoded frame as WebP q70 to GCS `latest/{camera_id}.webp` every 2s
- Skip upload if frame unchanged since last iteration
- Fail-soft: GCS errors are logged WARNING, never crash the worker
- Encoding offloaded to asyncio.to_thread to avoid blocking the loop
- Configurable via LATEST_FRAME_INTERVAL_SECONDS and LATEST_FRAME_QUALITY env vars

### Health & Monitoring
- Heartbeat every 30 seconds to backend `/internal/heartbeat`
- Report: camera status, frames processed, events detected, Gemini call count, errors
- If worker process dies, supervisor auto-restarts it (max 5 restarts)
- Log at INFO level for events, WARNING for retries, ERROR for failures

### Configuration
- All config via environment variables (pydantic-settings)
- Camera assignments via `cameras.json` file (path configurable via `CAMERAS_CONFIG` env)
- NEVER hardcode camera credentials in code — always from config file
- GCS credentials via `GOOGLE_APPLICATION_CREDENTIALS` env var
- Worker identity via `WORKER_ID` env var (unique per VM)

## Code Style
- Flat file structure (no nested packages) — small service, keep it simple
- Dataclasses for models (`CameraConfig`, `DetectedEvent`, `BoundingBox`)
- No classes for simple functions — use module-level functions for stateless logic
- Classes for stateful components (StreamIngest, RingBuffer, MotionDetector, GeminiClient)
- Type hints on all function signatures
- Docstrings only on public class methods — not on obvious internal helpers

## File Layout
```
worker/
├── main.py              # Entry point, signal handling
├── supervisor.py        # Manages camera workers, health checks
├── camera_worker.py     # Full pipeline per camera
├── stream_ingest.py     # FFmpeg subprocess management
├── ring_buffer.py       # Circular frame buffer
├── motion_detector.py   # Frame-diff motion gate
├── frame_sampler.py     # Adaptive rate control
├── gemini_client.py     # Gemini API with circuit breaker
├── prompt_builder.py    # Camera-config-driven prompts
├── event_packager.py    # Annotate, clip, upload, post
├── gcs_uploader.py      # GCS upload
├── api_client.py        # Backend HTTP client
├── config.py            # Environment config
├── models.py            # Dataclasses
└── cameras.json         # Camera assignments
```

## Running
```bash
# Ensure FFmpeg is installed
ffmpeg -version

# Configure
cp cameras.json.example cameras.json
# Edit cameras.json with your RTSP URLs

# Set env
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-key.json
export WORKER_API_KEY=your-backend-worker-key
export BACKEND_URL=http://localhost:8080

# Run
python3 main.py
```

## Critical Rules
- NEVER send frames to Gemini without motion detection gate
- NEVER store full video — only event snapshots + 10s clips
- NEVER expose camera credentials in logs or API responses
- ALWAYS validate Gemini JSON response before processing (may be malformed)
- ALWAYS use circuit breaker — runaway API calls = massive cost
- ALWAYS encode frames to 720p before sending — 4K frames waste tokens
- ALWAYS run FFmpeg with `-rtsp_transport tcp` for reliability over UDP
