# NIGHTWATCH — Stream Worker Plan

---

| Field | Value |
|-------|-------|
| **Plan Name** | Stream Processing Worker |
| **Version** | 1.0.0 |
| **Parent Plan** | MVP_PLAN.md |
| **Date Generated** | 2026-05-26 |
| **Estimated Effort** | 15 person-days |
| **Tech Stack** | Python 3.11, FFmpeg, OpenCV, google-genai SDK, aiohttp |
| **Deployment** | GCE VMs (asia-south1), managed instance group |

---

## Objective

Build the stream processing workers that ingest camera feeds (RTSP pull or RTMP/SRT push), sample frames intelligently, run Gemini Vision for event detection, package events (snapshot + clip + metadata), and push them to the backend API.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                     GCE VM (e2-standard-4: 4 vCPU, 16 GB RAM)                │
│                     OS: Ubuntu 22.04 LTS                                      │
│                     Runs: supervisor managing N camera worker processes        │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │                    WORKER SUPERVISOR (Python)                              ││
│  │    • Polls backend API for camera assignments                             ││
│  │    • Spawns/kills CameraWorker processes                                  ││
│  │    • Reports VM-level health to backend                                   ││
│  │    • Handles graceful shutdown on SIGTERM                                 ││
│  └────────────────────────────┬─────────────────────────────────────────────┘│
│                               │ spawns                                        │
│         ┌─────────────────────┼─────────────────────┐                        │
│         │                     │                     │                         │
│         ▼                     ▼                     ▼                         │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                │
│  │CameraWorker 1│     │CameraWorker 2│     │CameraWorker N│                │
│  │(Process)     │     │(Process)     │     │(Process)     │                │
│  │              │     │              │     │              │                │
│  │ camera_id: X │     │ camera_id: Y │     │ camera_id: Z │                │
│  └──────────────┘     └──────────────┘     └──────────────┘                │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐│
│  │                    NGINX-RTMP (for push-mode cameras)                      ││
│  │    • Listens on rtmp://0.0.0.0:1935/live/{stream_key}                    ││
│  │    • Validates stream key against backend API                             ││
│  │    • Workers read from local RTMP as if it were RTSP                      ││
│  └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## CameraWorker Process — Detailed Pipeline

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    CAMERA WORKER PROCESS                                       │
│                    One per camera, isolated process                            │
│                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ STAGE 1: STREAM INGEST                                                  │  │
│  │                                                                          │  │
│  │  FFmpeg subprocess (decoded frames → shared memory / pipe)              │  │
│  │                                                                          │  │
│  │  RTSP Pull mode:                                                         │  │
│  │    ffmpeg -rtsp_transport tcp -i {rtsp_url} -f rawvideo -pix_fmt bgr24  │  │
│  │           -s 1280x720 -r 10 pipe:1                                      │  │
│  │                                                                          │  │
│  │  RTMP Push mode (read from local nginx-rtmp):                           │  │
│  │    ffmpeg -i rtmp://localhost/live/{stream_key} -f rawvideo ...          │  │
│  │                                                                          │  │
│  │  • Decodes to 720p (resize if needed — saves Gemini tokens)             │  │
│  │  • Outputs raw frames at source fps (capped at 10fps)                   │  │
│  │  • Auto-reconnect on stream drop (3 retries, 5s backoff)                │  │
│  └────────────────────────────┬───────────────────────────────────────────┘  │
│                               │ raw frames (720p BGR)                         │
│                               ▼                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ STAGE 2: RING BUFFER                                                    │  │
│  │                                                                          │  │
│  │  • Circular buffer holding last 30 seconds of frames                    │  │
│  │  • Size: 30s × 10fps = 300 frames × 1280×720×3 = ~830 MB              │  │
│  │  • Actually store as compressed JPEG (quality 80) → ~15 MB/camera       │  │
│  │  • Used for: clip generation (5s before + 5s after event)               │  │
│  │  • Implemented as collections.deque with maxlen                         │  │
│  └────────────────────────────┬───────────────────────────────────────────┘  │
│                               │                                               │
│                               ▼                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ STAGE 3: MOTION DETECTOR                                                │  │
│  │                                                                          │  │
│  │  Fast pixel-difference motion detection:                                 │  │
│  │  1. Convert frame to grayscale                                           │  │
│  │  2. Gaussian blur (reduce noise)                                         │  │
│  │  3. Absolute difference with previous frame                             │  │
│  │  4. Threshold (>25 pixel value = motion pixel)                          │  │
│  │  5. Count motion pixels / total pixels = motion_ratio                   │  │
│  │  6. motion_ratio > 0.01 (1% of frame) → MOTION DETECTED                │  │
│  │                                                                          │  │
│  │  Cost: <1ms per frame on CPU (trivial)                                  │  │
│  │                                                                          │  │
│  │  Output:                                                                 │  │
│  │  • No motion → skip (don't call Gemini) → sample at idle_fps (1/sec)   │  │
│  │  • Motion → sample at active_fps (5/sec) → send to AI                  │  │
│  └────────────────────────────┬───────────────────────────────────────────┘  │
│                               │ frames with motion                            │
│                               ▼                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ STAGE 4: FRAME SAMPLER                                                  │  │
│  │                                                                          │  │
│  │  Controls rate of frames sent to Gemini (cost control):                 │  │
│  │                                                                          │  │
│  │  State machine:                                                          │  │
│  │  ┌────────┐  motion detected   ┌────────┐                              │  │
│  │  │  IDLE  │ ──────────────────▶ │ ACTIVE │                              │  │
│  │  │ 1 fps  │ ◀────────────────── │ 5 fps  │                              │  │
│  │  └────────┘  no motion for 10s  └────────┘                              │  │
│  │                                                                          │  │
│  │  Deduplication: skip if frame too similar to last sent (SSIM > 0.98)    │  │
│  │  Max Gemini calls: configurable budget per camera (default: 5/sec max)  │  │
│  └────────────────────────────┬───────────────────────────────────────────┘  │
│                               │ sampled frames (JPEG encoded)                 │
│                               ▼                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ STAGE 5: GEMINI VISION CLIENT                                           │  │
│  │                                                                          │  │
│  │  1. Build prompt from camera config:                                     │  │
│  │     - enabled_events list                                                │  │
│  │     - detection_zones description                                        │  │
│  │     - sensitivity level                                                  │  │
│  │     - current timestamp + timezone                                       │  │
│  │     - site context                                                       │  │
│  │                                                                          │  │
│  │  2. Call Gemini 2.0 Flash:                                              │  │
│  │     model.generate_content([prompt, frame_image])                       │  │
│  │                                                                          │  │
│  │  3. Parse JSON response (with fallback regex extraction)                │  │
│  │                                                                          │  │
│  │  4. Filter results:                                                      │  │
│  │     - Discard events not in camera's enabled_events list                │  │
│  │     - Discard below confidence threshold:                               │  │
│  │       low sensitivity: < 0.85                                           │  │
│  │       medium: < 0.70                                                     │  │
│  │       high: < 0.50                                                       │  │
│  │                                                                          │  │
│  │  Error handling:                                                         │  │
│  │  • Timeout: 10s per call, skip frame on timeout                         │  │
│  │  • Rate limit (429): exponential backoff 1s→2s→4s→8s, max 30s          │  │
│  │  • 500 errors: retry 3x then skip                                       │  │
│  │  • Malformed response: log, skip frame                                  │  │
│  │  • Circuit breaker: if >10 failures in 60s, pause Gemini for 30s       │  │
│  └────────────────────────────┬───────────────────────────────────────────┘  │
│                               │ detected events                               │
│                               ▼                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ STAGE 6: EVENT PACKAGER                                                 │  │
│  │                                                                          │  │
│  │  For each detected event:                                                │  │
│  │                                                                          │  │
│  │  1. ANNOTATE SNAPSHOT                                                    │  │
│  │     - Draw bounding boxes on frame (OpenCV)                             │  │
│  │     - Add label + confidence text                                        │  │
│  │     - Encode as WebP (quality 85, ~50-100KB)                            │  │
│  │                                                                          │  │
│  │  2. CUT CLIP                                                             │  │
│  │     - Extract 5s before + 5s after event from ring buffer               │  │
│  │     - Encode H.264 MP4 (FFmpeg, 720p, CRF 28)                          │  │
│  │     - Duration: 10 seconds                                               │  │
│  │     - Size: ~500KB–1.5MB                                                │  │
│  │                                                                          │  │
│  │  3. UPLOAD TO GCS                                                        │  │
│  │     - Path: gs://nightwatch-events/{org_id}/{date}/{camera_id}/{event_id}/│
│  │     - Files: snapshot.webp, clip.mp4                                    │  │
│  │     - Async upload (non-blocking)                                        │  │
│  │                                                                          │  │
│  │  4. POST TO BACKEND API                                                  │  │
│  │     - POST /internal/events with full metadata                          │  │
│  │     - Retry 3x with backoff on failure                                  │  │
│  │     - Queue locally if backend unreachable (SQLite fallback)            │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │ STAGE 7: HEALTH REPORTER                                                │  │
│  │                                                                          │  │
│  │  Every 30 seconds, POST to /internal/heartbeat:                         │  │
│  │  {                                                                       │  │
│  │    "worker_id": "vm-xyz",                                               │  │
│  │    "camera_id": "uuid",                                                 │  │
│  │    "status": "online",                                                  │  │
│  │    "fps_actual": 9.8,                                                   │  │
│  │    "motion_ratio_avg": 0.03,                                            │  │
│  │    "gemini_calls_per_min": 12,                                          │  │
│  │    "events_per_hour": 8,                                                │  │
│  │    "errors": [],                                                         │  │
│  │    "last_frame_at": "2026-05-26T14:30:00.123Z",                        │  │
│  │    "memory_mb": 450,                                                    │  │
│  │    "cpu_percent": 23.5                                                  │  │
│  │  }                                                                       │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
worker/
├── main.py                    # Entry point: WorkerSupervisor
├── supervisor.py              # Manages camera worker processes
├── camera_worker.py           # Main per-camera process loop
├── stream_ingest.py           # FFmpeg subprocess management
├── ring_buffer.py             # Circular frame buffer (30s)
├── motion_detector.py         # Fast frame-diff motion detection
├── frame_sampler.py           # Adaptive sampling state machine
├── gemini_client.py           # Gemini Vision API client with retries
├── prompt_builder.py          # Builds camera-specific prompts
├── event_packager.py          # Annotate, clip, upload, post
├── clip_cutter.py             # FFmpeg clip extraction from buffer
├── gcs_uploader.py            # Async GCS upload
├── api_client.py              # Backend API client (events, heartbeat)
├── health_reporter.py         # Periodic health reporting
├── config.py                  # Environment-based configuration
├── models.py                  # Data classes (Event, Frame, CameraConfig)
├── Dockerfile
├── requirements.txt
└── tests/
    ├── test_motion_detector.py
    ├── test_frame_sampler.py
    ├── test_gemini_client.py
    ├── test_prompt_builder.py
    └── test_event_packager.py
```

---

## Key Component Specifications

### Stream Ingest (stream_ingest.py)

```python
class StreamIngest:
    """Manages FFmpeg subprocess for frame decoding."""
    
    def __init__(self, camera_config: CameraConfig):
        self.config = camera_config
        self.process: subprocess.Popen | None = None
        self.reconnect_attempts = 0
        self.max_reconnects = 3
    
    async def start(self):
        """Start FFmpeg subprocess."""
        cmd = self._build_ffmpeg_cmd()
        self.process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0
        )
    
    def _build_ffmpeg_cmd(self) -> list[str]:
        source = self._get_source_url()
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", source,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", "1280x720",
            "-r", "10",  # cap at 10fps decode
            "-an",  # no audio
            "pipe:1"
        ]
    
    def _get_source_url(self) -> str:
        if self.config.ingest_mode == "rtsp_pull":
            return self.config.rtsp_url
        else:  # rtmp_push or srt_push
            return f"rtmp://localhost/live/{self.config.stream_key}"
    
    async def read_frame(self) -> np.ndarray | None:
        """Read one frame (1280*720*3 = 2,764,800 bytes)."""
        raw = self.process.stdout.read(1280 * 720 * 3)
        if len(raw) != 1280 * 720 * 3:
            return None  # stream error
        return np.frombuffer(raw, dtype=np.uint8).reshape((720, 1280, 3))
    
    async def reconnect(self):
        """Kill and restart FFmpeg on stream drop."""
        self.reconnect_attempts += 1
        if self.reconnect_attempts > self.max_reconnects:
            raise StreamLostError(f"Camera {self.config.camera_id}: max reconnects exceeded")
        await asyncio.sleep(5 * self.reconnect_attempts)  # backoff
        await self.stop()
        await self.start()
```

### Motion Detector (motion_detector.py)

```python
class MotionDetector:
    """Fast frame-difference based motion detection."""
    
    def __init__(self, threshold: float = 0.01, pixel_threshold: int = 25):
        self.threshold = threshold  # 1% of pixels must change
        self.pixel_threshold = pixel_threshold
        self.prev_gray: np.ndarray | None = None
    
    def detect(self, frame: np.ndarray) -> tuple[bool, float]:
        """Returns (has_motion, motion_ratio)."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
        
        if self.prev_gray is None:
            self.prev_gray = gray
            return False, 0.0
        
        diff = cv2.absdiff(self.prev_gray, gray)
        _, thresh = cv2.threshold(diff, self.pixel_threshold, 255, cv2.THRESH_BINARY)
        
        motion_pixels = np.count_nonzero(thresh)
        total_pixels = thresh.shape[0] * thresh.shape[1]
        motion_ratio = motion_pixels / total_pixels
        
        self.prev_gray = gray
        return motion_ratio > self.threshold, motion_ratio
```

### Gemini Client (gemini_client.py)

```python
import google.genai as genai
from google.genai.types import GenerateContentConfig

class GeminiClient:
    """Gemini Vision API client with retry, circuit breaker, rate limiting."""
    
    def __init__(self, config: Config):
        self.client = genai.Client()
        self.model = "gemini-2.0-flash"
        self.failure_count = 0
        self.circuit_open_until: float = 0
        self.semaphore = asyncio.Semaphore(5)  # max concurrent calls
    
    async def analyze_frame(
        self, frame_jpeg: bytes, camera_config: CameraConfig
    ) -> list[DetectedEvent]:
        """Send frame to Gemini, get structured event detection."""
        
        # Circuit breaker check
        if time.time() < self.circuit_open_until:
            return []
        
        prompt = self.prompt_builder.build(camera_config)
        
        async with self.semaphore:
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=[prompt, {"mime_type": "image/jpeg", "data": frame_jpeg}],
                    config=GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,  # deterministic
                    ),
                )
                self.failure_count = 0
                return self._parse_response(response.text, camera_config)
                
            except Exception as e:
                self.failure_count += 1
                if self.failure_count > 10:
                    self.circuit_open_until = time.time() + 30  # pause 30s
                    self.failure_count = 0
                raise
    
    def _parse_response(self, text: str, config: CameraConfig) -> list[DetectedEvent]:
        """Parse Gemini JSON response, filter by camera config."""
        data = json.loads(text)
        events = []
        
        confidence_threshold = {
            "low": 0.85, "medium": 0.70, "high": 0.50
        }[config.sensitivity]
        
        for event_data in data.get("events", []):
            if event_data["event_type"] not in config.enabled_events:
                continue
            if event_data["confidence"] < confidence_threshold:
                continue
            events.append(DetectedEvent(**event_data))
        
        return events
```

### Prompt Builder (prompt_builder.py)

```python
class PromptBuilder:
    """Builds camera-specific prompts for Gemini Vision."""
    
    SYSTEM_TEMPLATE = """You are a surveillance AI analyst. Analyze the camera frame for security events.

Camera: {camera_name}
Location: {site_name}
Time: {timestamp} {timezone}
Enabled detections: {enabled_events}
{zones_section}
Sensitivity: {sensitivity}

Respond ONLY with valid JSON matching this schema:
{{
  "events": [
    {{
      "event_type": "<one of: {enabled_events}>",
      "confidence": <0.0-1.0>,
      "severity": "<low|medium|high|critical>",
      "description": "<one sentence a security guard would understand>",
      "bounding_boxes": [{{"x1": <int>, "y1": <int>, "x2": <int>, "y2": <int>, "label": "<string>"}}],
      "zone": "<zone name if event is in a defined zone, else null>"
    }}
  ],
  "person_count": <int>,
  "scene_summary": "<brief scene description>"
}}

Rules:
- Only detect events from the enabled list
- If nothing notable, return empty events array
- Confidence must reflect true certainty
- Severity guide: low=routine, medium=attention needed, high=immediate response, critical=emergency
- Bounding box coordinates are pixel values for 1280x720 frame"""

    def build(self, config: CameraConfig) -> str:
        zones_section = ""
        if config.detection_zones:
            zone_descs = [f"- {z['name']}: polygon at {z['points']}" for z in config.detection_zones]
            zones_section = "Detection zones:\n" + "\n".join(zone_descs)
        
        return self.SYSTEM_TEMPLATE.format(
            camera_name=config.name,
            site_name=config.site_name,
            timestamp=datetime.now(tz=ZoneInfo(config.timezone)).strftime("%Y-%m-%d %H:%M:%S"),
            timezone=config.timezone,
            enabled_events=", ".join(config.enabled_events),
            zones_section=zones_section,
            sensitivity=config.sensitivity,
        )
```

### Event Packager (event_packager.py)

```python
class EventPackager:
    """Packages detected events: annotate, clip, upload, post."""
    
    async def package_and_send(
        self,
        event: DetectedEvent,
        frame: np.ndarray,
        ring_buffer: RingBuffer,
        camera_config: CameraConfig,
    ):
        event_id = str(uuid.uuid4())
        timestamp = datetime.now(tz=timezone.utc)
        
        # 1. Annotate snapshot
        snapshot = self._annotate_frame(frame, event)
        snapshot_bytes = cv2.imencode('.webp', snapshot, [cv2.IMWRITE_WEBP_QUALITY, 85])[1].tobytes()
        
        # 2. Cut clip (5s before + 5s after = 10s)
        clip_bytes = await self._cut_clip(ring_buffer, timestamp)
        
        # 3. Upload to GCS
        base_path = f"{camera_config.org_id}/{timestamp.strftime('%Y/%m/%d')}/{camera_config.camera_id}/{event_id}"
        snapshot_url = await self.gcs.upload(f"{base_path}/snapshot.webp", snapshot_bytes, "image/webp")
        clip_url = await self.gcs.upload(f"{base_path}/clip.mp4", clip_bytes, "video/mp4") if clip_bytes else None
        
        # 4. Post to backend
        await self.api_client.post_event({
            "camera_id": camera_config.camera_id,
            "timestamp": timestamp.isoformat(),
            "event_type": event.event_type,
            "confidence": event.confidence,
            "severity": event.severity,
            "description": event.description,
            "bounding_boxes": [asdict(bb) for bb in event.bounding_boxes],
            "snapshot_url": snapshot_url,
            "clip_url": clip_url,
            "ai_model": "gemini-2.0-flash",
        })
    
    def _annotate_frame(self, frame: np.ndarray, event: DetectedEvent) -> np.ndarray:
        annotated = frame.copy()
        for bbox in event.bounding_boxes:
            cv2.rectangle(annotated, (bbox.x1, bbox.y1), (bbox.x2, bbox.y2), (30, 144, 255), 2)
            label = f"{bbox.label} {event.confidence:.0%}"
            cv2.putText(annotated, label, (bbox.x1, bbox.y1 - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 144, 255), 2)
        return annotated
    
    async def _cut_clip(self, ring_buffer: RingBuffer, event_time: datetime) -> bytes | None:
        """Extract 10s clip from ring buffer, encode as H.264 MP4."""
        frames = ring_buffer.get_window(seconds_before=5, seconds_after=5)
        if len(frames) < 20:  # need at least 2 seconds
            return None
        
        # Write frames to temp file, encode with FFmpeg
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
                '-s', '1280x720', '-r', '10',
                '-i', 'pipe:0',
                '-c:v', 'libx264', '-crf', '28', '-preset', 'fast',
                '-movflags', '+faststart',
                tmp.name,
                stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            frame_data = b''.join(f.tobytes() for f in frames)
            await process.communicate(input=frame_data)
            
            with open(tmp.name, 'rb') as f:
                return f.read()
```

### Ring Buffer (ring_buffer.py)

```python
from dataclasses import dataclass
from collections import deque
import time

@dataclass
class TimestampedFrame:
    frame: np.ndarray
    timestamp: float  # time.time()

class RingBuffer:
    """Circular buffer holding last 30 seconds of frames."""
    
    def __init__(self, max_seconds: int = 30, fps: int = 10):
        self.max_frames = max_seconds * fps
        self.buffer: deque[TimestampedFrame] = deque(maxlen=self.max_frames)
    
    def add(self, frame: np.ndarray):
        self.buffer.append(TimestampedFrame(frame=frame, timestamp=time.time()))
    
    def get_window(self, seconds_before: int = 5, seconds_after: int = 5) -> list[np.ndarray]:
        """Get frames from N seconds before now to N seconds after (best effort)."""
        now = time.time()
        start = now - seconds_before
        # seconds_after is best-effort (we may not have future frames yet)
        
        return [
            tf.frame for tf in self.buffer
            if tf.timestamp >= start
        ]
```

### Worker Supervisor (supervisor.py)

```python
class WorkerSupervisor:
    """Manages camera worker processes on this VM."""
    
    def __init__(self, config: Config):
        self.config = config
        self.worker_id = f"vm-{uuid.uuid4().hex[:8]}"
        self.workers: dict[str, multiprocessing.Process] = {}  # camera_id → process
        self.api_client = ApiClient(config)
    
    async def run(self):
        """Main loop: poll assignments, manage processes, report health."""
        while True:
            try:
                # Get assigned cameras from backend
                assignments = await self.api_client.get_assignments(self.worker_id)
                assigned_ids = {a["camera_id"] for a in assignments}
                current_ids = set(self.workers.keys())
                
                # Start new workers
                for assignment in assignments:
                    if assignment["camera_id"] not in current_ids:
                        self._start_worker(assignment)
                
                # Stop removed workers
                for camera_id in current_ids - assigned_ids:
                    self._stop_worker(camera_id)
                
                # Restart crashed workers
                for camera_id, process in list(self.workers.items()):
                    if not process.is_alive():
                        self._restart_worker(camera_id)
                
                # Report health
                await self._report_health()
                
            except Exception as e:
                logging.error(f"Supervisor error: {e}")
            
            await asyncio.sleep(10)  # poll every 10 seconds
    
    def _start_worker(self, camera_config: dict):
        process = multiprocessing.Process(
            target=run_camera_worker,
            args=(camera_config, self.config),
            daemon=True
        )
        process.start()
        self.workers[camera_config["camera_id"]] = process
    
    def _stop_worker(self, camera_id: str):
        process = self.workers.pop(camera_id, None)
        if process and process.is_alive():
            process.terminate()
            process.join(timeout=5)
```

---

## Nginx-RTMP Configuration (for push mode)

```nginx
# nginx.conf for RTMP ingest

worker_processes auto;
events { worker_connections 1024; }

rtmp {
    server {
        listen 1935;
        chunk_size 4096;
        
        application live {
            live on;
            record off;
            
            # Validate stream key against backend API
            on_publish http://localhost:8080/rtmp/auth;
            
            # Notify backend when stream starts/stops
            on_publish_done http://localhost:8080/rtmp/disconnect;
            
            # Allow reading by local workers only
            allow play 127.0.0.1;
            deny play all;
        }
    }
}

http {
    server {
        listen 8080;
        
        location /rtmp/auth {
            # Simple auth endpoint — validates stream key exists in DB
            proxy_pass http://localhost:9000/internal/rtmp-auth;
        }
        
        location /rtmp/disconnect {
            proxy_pass http://localhost:9000/internal/rtmp-disconnect;
        }
    }
}
```

---

## Resource Sizing

| Cameras per VM | VM Type | vCPU | RAM | Cost/month |
|---------------|---------|------|-----|-----------|
| 5-8 | e2-standard-4 | 4 | 16 GB | ~₹5,000 |
| 10-15 | e2-standard-8 | 8 | 32 GB | ~₹10,000 |
| 20+ | c2-standard-8 | 8 | 32 GB | ~₹12,000 |

**Per-camera resource estimate:**
- Memory: ~100-150 MB (ring buffer + frame processing)
- CPU: ~0.3-0.5 vCPU (FFmpeg decode + motion detection + encoding)
- Network: ~1-3 Mbps inbound per camera (720p stream)
- Gemini calls: 1-5 per second per camera (when active)

---

## Error Handling & Resilience

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Stream drops | FFmpeg exits / zero bytes read | Reconnect 3x with 5s backoff, then mark camera "error" |
| Gemini API down | Timeout / 5xx responses | Circuit breaker: pause 30s after 10 failures, skip frames |
| Gemini rate limit | 429 response | Exponential backoff: 1→2→4→8s, reduce sampling rate |
| Backend API down | Connection refused / timeout | Queue events locally (SQLite), retry every 30s |
| GCS upload fails | Exception from SDK | Retry 3x, queue locally if persistent |
| Worker process crash | Process.is_alive() = False | Supervisor auto-restarts, limit 5 restarts then alert |
| VM memory pressure | psutil monitoring | Kill lowest-priority camera workers, alert |
| Disk full (clips) | Disk usage > 90% | Delete oldest queued clips, alert |

---

## Configuration

```python
# config.py

class Config:
    # Backend API
    backend_url: str = "https://api.nightwatch.ai"
    worker_api_key: str  # for /internal/* endpoints
    
    # GCS
    gcs_bucket: str = "nightwatch-events"
    gcs_project: str = "nightwatch-prod"
    
    # Gemini
    gemini_model: str = "gemini-2.0-flash"
    gemini_max_concurrent: int = 5
    gemini_timeout_seconds: int = 10
    
    # Stream
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    frame_width: int = 1280
    frame_height: int = 720
    max_decode_fps: int = 10
    ring_buffer_seconds: int = 30
    
    # Motion detection
    motion_threshold: float = 0.01  # 1% of pixels
    motion_pixel_threshold: int = 25
    
    # Sampling
    idle_fps: float = 1.0
    active_fps: float = 5.0
    no_motion_timeout: int = 10  # seconds before going back to idle
    
    # Worker
    max_cameras_per_vm: int = 12
    health_report_interval: int = 30  # seconds
    assignment_poll_interval: int = 10  # seconds
```

---

## Deployment

```dockerfile
# Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    nginx \
    libnginx-mod-rtmp \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 1935 8080

CMD ["supervisord", "-c", "supervisord.conf"]
```

```ini
# supervisord.conf
[supervisord]
nodaemon=true

[program:nginx]
command=/usr/sbin/nginx -g "daemon off;"
autorestart=true

[program:worker]
command=python main.py
autorestart=true
startretries=5
```

**GCE Instance Template (Terraform):**
```hcl
resource "google_compute_instance_template" "worker" {
  name_prefix  = "nightwatch-worker-"
  machine_type = "e2-standard-4"
  region       = "asia-south1"

  disk {
    source_image = "ubuntu-2204-lts"
    disk_size_gb = 50
    disk_type    = "pd-ssd"
  }

  network_interface {
    network = google_compute_network.main.id
    access_config {} # external IP for RTSP pull
  }

  metadata_startup_script = file("startup.sh")

  service_account {
    scopes = ["cloud-platform"]
  }

  tags = ["worker", "rtmp-ingest"]
}

resource "google_compute_instance_group_manager" "workers" {
  name               = "nightwatch-workers"
  base_instance_name = "worker"
  zone               = "asia-south1-a"
  target_size        = 1  # start with 1, scale manually initially

  version {
    instance_template = google_compute_instance_template.worker.id
  }
}
```

---

## Test Strategy

| Type | What | Tool |
|------|------|------|
| Unit | Motion detector accuracy | pytest + sample frames (motion / no motion) |
| Unit | Prompt builder output | pytest (validate prompt structure) |
| Unit | Gemini response parser | pytest + mock responses (valid, malformed, empty) |
| Unit | Ring buffer correctness | pytest (add frames, get window, overflow) |
| Integration | Full pipeline with mock Gemini | pytest + recorded RTSP stream |
| Load | N cameras on single VM | Manual test: measure CPU/mem at 5, 10, 15 cameras |
| Resilience | Stream drop + recovery | Kill FFmpeg, verify reconnect |
| Resilience | Gemini timeout | Inject delays, verify circuit breaker |

---

## Implementation Order

| Day | Task |
|-----|------|
| 1 | Project scaffold, config, Docker with FFmpeg + nginx-rtmp |
| 2 | StreamIngest: FFmpeg subprocess, frame reading, reconnect logic |
| 3 | RingBuffer + MotionDetector + FrameSampler |
| 4 | GeminiClient: API call, retry, circuit breaker |
| 5 | PromptBuilder: camera-config-driven prompt generation |
| 6 | EventPackager: annotate snapshot (OpenCV bboxes) |
| 7 | EventPackager: clip cutting from ring buffer (FFmpeg encode) |
| 8 | GCS uploader (async) + Backend API client |
| 9 | CameraWorker: full pipeline integration (stages 1-6) |
| 10 | WorkerSupervisor: process management, assignment polling |
| 11 | Nginx-RTMP: push mode setup, stream key auth |
| 12 | Health reporter + error handling + local queue fallback |
| 13 | Testing: unit tests for motion, sampler, Gemini parser |
| 14 | Integration test: end-to-end with real RTSP stream |
| 15 | GCE deployment: instance template, startup script, monitoring |

---

## Definition of Done

- [ ] RTSP pull mode: connects to camera URL, decodes frames at 720p
- [ ] RTMP push mode: nginx-rtmp accepts streams, workers read them
- [ ] Motion detection gates Gemini calls (verified: no motion = no API calls)
- [ ] Gemini Vision returns structured events, parsed correctly
- [ ] Confidence filtering works per sensitivity level
- [ ] Snapshots annotated with bounding boxes, uploaded to GCS
- [ ] 10s clips cut from ring buffer, encoded H.264, uploaded to GCS
- [ ] Events posted to backend API successfully
- [ ] Circuit breaker prevents Gemini call storms on API issues
- [ ] Supervisor manages multiple camera processes per VM
- [ ] Health reporting every 30s to backend
- [ ] Handles stream drops gracefully (reconnect + mark error)
- [ ] Single VM handles 10 cameras at <70% CPU utilization
- [ ] End-to-end latency: frame capture to event stored < 15 seconds
