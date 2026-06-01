# Nightwatch Worker — Agent Rules

## What's Already Built
- 12 source files implementing the full stream-to-event pipeline
- Stream ingest: FFmpeg subprocess decoding to 720p raw frames, RTSP pull + RTMP push, auto-reconnect
- Motion detection: frame differencing gate (saves ~80% of Gemini API cost)
- Frame sampling: adaptive IDLE/ACTIVE state machine with deduplication
- Gemini Vision: async client with circuit breaker, structured JSON parsing, confidence filtering
- Event packaging: annotated snapshots (WebP), 10s H.264 clips, GCS upload, backend POST
- Supervisor: multi-camera management, health reporting, auto-restart dead workers
- 10 unit tests passing (motion detector, ring buffer, prompt builder)
- NOT yet done: nginx-rtmp config, SQLite offline queue, integration tests, GCE deployment

## What This Service Does
Processes camera streams: decodes video → detects motion → calls Gemini Vision AI → packages events (snapshot + clip) → uploads to GCS → posts to backend API.

## Tech Stack
- Python 3.11+, asyncio, FFmpeg (subprocess), OpenCV, google-genai SDK, httpx
- Runs on GCE VMs or any Linux/Mac machine with FFmpeg

## Key Decisions Already Made — Don't Change
- FFmpeg subprocess for stream decoding (not OpenCV VideoCapture — unreliable for RTSP)
- Motion detection gates ALL Gemini calls (no motion = no cost)
- Ring buffer is a simple deque of numpy arrays (not disk-based)
- One CameraWorker per camera (isolated asyncio task, not process)
- Supervisor manages all workers + handles restarts
- Camera configs from JSON file (not pulled from backend API in MVP)
- Circuit breaker on Gemini: 10 failures → 30s pause
- Gemini auth: Vertex AI ADC primary; falls back to `GEMINI_API_KEY` (AI Studio) on auth failure if set

## Pipeline Order (Never Reorder)
```
1. FFmpeg decode (720p) → 2. Ring buffer → 3. Motion detect → 4. Frame sample
  → 5. Gemini Vision → 6. Filter by config → 7. Annotate + clip → 8. Upload → 9. POST to API
```

## How to Add a New Detection Feature
1. Add event type to prompt in `prompt_builder.py`
2. Add to the enabled_events list in cameras.json
3. No code changes needed — Gemini handles the detection, we just parse the response

## How to Add a New Stream Protocol
1. Add new branch in `StreamIngest._build_ffmpeg_cmd()`
2. Handle in `CameraConfig.ingest_mode` validation
3. Same output format: raw BGR24 frames at 720p

## Critical Cost Rules
- ALWAYS gate Gemini calls behind motion detection
- NEVER send >5 frames/second to Gemini per camera
- NEVER send frames larger than 720p (resize first)
- Use gemini-2.0-flash (not pro) — 10x cheaper
- Circuit breaker prevents runaway costs on API errors

## Common Mistakes to Avoid
- Forgetting to use `-rtsp_transport tcp` (UDP drops frames on lossy networks)
- Blocking the asyncio event loop with FFmpeg reads (must use `asyncio.to_thread`)
- Not handling malformed Gemini JSON (it WILL return garbage sometimes)
- Letting ring buffer grow unbounded (always use `maxlen`)
- Logging camera RTSP URLs with credentials
