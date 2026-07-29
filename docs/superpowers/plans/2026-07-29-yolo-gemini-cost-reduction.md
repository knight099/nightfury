# YOLO Local Detection to Reduce Gemini API Calls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a local YOLOv8n (ONNX, CPU) detection stage between the worker's existing frame sampler and its Gemini Vision call, so frames with no relevant object are dropped without an API call, and high-confidence simple detections (person/vehicle/animal/intrusion) are emitted directly without one either.

**Architecture:** New pure-logic module `worker/yolo_detector.py` holds the ONNX wrapper (`YoloDetector`), the COCO→event_type mapping, the point-in-zone intrusion check, and a pure `decide()` function implementing the gate/emit/escalate three-way branch. `camera_worker.py` wires it into `_run_loop()` right before the existing Gemini call, falling through to the unchanged Gemini path whenever `decide()` says `"escalate"`.

**Tech Stack:** `onnxruntime` (CPU build) for inference, `opencv-python-headless` (already a dependency) for letterbox resize + NMS (`cv2.dnn.NMSBoxes`) — no PyTorch, no new heavy dependency.

## Global Constraints

- No PyTorch/ultralytics runtime — CPU-only `onnxruntime` + a committed/downloaded `yolov8n.onnx`.
- Fail-soft: if the model file is missing or fails to load, the worker must behave exactly as it does today (every sampled frame goes to Gemini) — never crash, never silently drop all frames.
- Only `person`, `vehicle`, `animal`, `intrusion` get the local fast path; any other `enabled_events` type on a camera disables YOLO gating for that camera entirely (every frame escalates), per the spec.
- Per user's standing preference: implement directly, no TDD/pytest step-by-step ceremony in this plan — each task ends with a self-contained implementation, a quick manual sanity check, and a commit. A dedicated final task does a full self-review pass instead of per-task test suites.

---

### Task 1: YOLO config settings

**Files:**
- Modify: `worker/config.py`

**Interfaces:**
- Produces: `config.yolo_enabled: bool`, `config.yolo_model_path: str`, `config.yolo_input_size: int`, `config.yolo_fastpath_confidence: float`, `config.yolo_escalate_floor: float` — consumed by Task 2 (`YoloDetector`) and Task 3 (`camera_worker.py`).

- [ ] **Step 1: Add the settings block**

In `worker/config.py`, add after the `# Sampling` block (after `no_motion_timeout: float = 10.0`):

```python
    # YOLO local detection (gates + short-circuits Gemini calls)
    yolo_enabled: bool = True
    yolo_model_path: str = "models/yolov8n.onnx"
    yolo_input_size: int = 640
    yolo_fastpath_confidence: float = 0.75
    yolo_escalate_floor: float = 0.35
```

- [ ] **Step 2: Verify it loads**

Run: `cd worker && .venv/bin/python3 -c "from config import config; print(config.yolo_enabled, config.yolo_model_path)"`
Expected output: `True models/yolov8n.onnx`

- [ ] **Step 3: Commit**

```bash
git add worker/config.py
git commit -m "Add YOLO config settings for local detection gate"
```

---

### Task 2: Pure detection logic — COCO mapping, intrusion zone check, three-way decision

**Files:**
- Create: `worker/yolo_detector.py` (this task writes the non-ONNX half of the file: dataclasses, mapping, decision logic; Task 3 appends the ONNX wrapper to the same file)

**Interfaces:**
- Consumes: `BoundingBox`, `CameraConfig`, `DetectedEvent` from `worker/models.py` (existing).
- Produces: `YoloDetection` dataclass, `COCO_TO_EVENT_TYPE: dict[str, str]`, `FASTPATH_EVENT_TYPES: set[str]`, `point_in_polygon(x, y, points) -> bool`, `map_detections(detections, camera_config) -> list[tuple[str, YoloDetection, str | None]]`, `Decision` dataclass (`action: str`, `events: list[DetectedEvent]`), `decide(detections, camera_config, fastpath_confidence, escalate_floor) -> Decision` — all consumed by Task 3 (ONNX wrapper appended to same file) and Task 4 (`camera_worker.py`).

- [ ] **Step 1: Write `worker/yolo_detector.py`**

```python
import logging
from dataclasses import dataclass, field

from models import BoundingBox, CameraConfig, DetectedEvent

logger = logging.getLogger(__name__)

COCO_TO_EVENT_TYPE = {
    "person": "person",
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "motorcycle": "vehicle",
    "dog": "animal",
    "cat": "animal",
    "bird": "animal",
    "horse": "animal",
}

FASTPATH_EVENT_TYPES = {"person", "vehicle", "animal", "intrusion"}


@dataclass
class YoloDetection:
    coco_class: str
    confidence: float
    bbox: BoundingBox


def point_in_polygon(x: float, y: float, points: list) -> bool:
    """Ray-casting point-in-polygon test. points is a list of [x, y] pairs."""
    if len(points) < 3:
        return False
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i][0], points[i][1]
        xj, yj = points[j][0], points[j][1]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _zone_containing(bbox: BoundingBox, zones: list) -> str | None:
    cx = (bbox.x1 + bbox.x2) / 2
    cy = (bbox.y1 + bbox.y2) / 2
    for zone in zones:
        points = zone.get("points", [])
        if point_in_polygon(cx, cy, points):
            return zone.get("name", "unnamed")
    return None


def map_detections(detections: list, camera_config: CameraConfig) -> list:
    """Maps raw YOLO detections to (event_type, detection, zone_name) candidates."""
    results = []
    for d in detections:
        event_type = COCO_TO_EVENT_TYPE.get(d.coco_class)
        if event_type is None:
            continue
        results.append((event_type, d, None))
        if event_type == "person":
            zone = _zone_containing(d.bbox, camera_config.detection_zones)
            if zone is not None:
                results.append(("intrusion", d, zone))
    return results


@dataclass
class Decision:
    action: str  # "drop", "escalate", or "emit"
    events: list = field(default_factory=list)


def decide(
    detections: list,
    camera_config: CameraConfig,
    fastpath_confidence: float,
    escalate_floor: float,
) -> Decision:
    """Three-way decision: drop (no relevant detection), escalate to Gemini,
    or emit events directly from YOLO output."""
    enabled = set(camera_config.enabled_events)
    if not enabled.issubset(FASTPATH_EVENT_TYPES):
        return Decision(action="escalate")

    candidates = [c for c in map_detections(detections, camera_config) if c[0] in enabled]
    if not candidates:
        return Decision(action="drop")

    best_confidence = max(c[1].confidence for c in candidates)
    if best_confidence < escalate_floor:
        return Decision(action="drop")
    if best_confidence < fastpath_confidence:
        return Decision(action="escalate")

    qualifying = [c for c in candidates if c[1].confidence >= fastpath_confidence]
    return Decision(action="emit", events=_build_events(qualifying))


def _build_events(qualifying: list) -> list:
    events = []

    for event_type in ("person", "vehicle", "animal"):
        group = [c for c in qualifying if c[0] == event_type]
        if not group:
            continue
        count = len(group)
        confidence = max(c[1].confidence for c in group)
        bboxes = [
            BoundingBox(x1=c[1].bbox.x1, y1=c[1].bbox.y1, x2=c[1].bbox.x2, y2=c[1].bbox.y2, label=c[1].coco_class)
            for c in group
        ]
        events.append(DetectedEvent(
            event_type=event_type,
            confidence=confidence,
            severity="low",
            description=f"{count} {event_type} detected",
            bounding_boxes=bboxes,
        ))

    intrusions = [c for c in qualifying if c[0] == "intrusion"]
    zones = {}
    for c in intrusions:
        zones.setdefault(c[2], []).append(c)
    for zone_name, group in zones.items():
        count = len(group)
        confidence = max(c[1].confidence for c in group)
        bboxes = [
            BoundingBox(x1=c[1].bbox.x1, y1=c[1].bbox.y1, x2=c[1].bbox.x2, y2=c[1].bbox.y2, label=c[1].coco_class)
            for c in group
        ]
        description = (
            f"Person detected in {zone_name} zone" if count == 1
            else f"{count} people detected in {zone_name} zone"
        )
        events.append(DetectedEvent(
            event_type="intrusion",
            confidence=confidence,
            severity="medium",
            description=description,
            bounding_boxes=bboxes,
            zone=zone_name,
        ))

    return events
```

- [ ] **Step 2: Manual sanity check of the decision branches**

Run: `cd worker && .venv/bin/python3 <<'EOF'
from models import CameraConfig
from yolo_detector import YoloDetection, decide
from models import BoundingBox

cfg = CameraConfig(camera_id="c1", org_id="o1", name="cam", ingest_mode="rtsp_pull",
                    enabled_events=["person", "vehicle", "intrusion"],
                    detection_zones=[{"name": "Driveway", "points": [[0,0],[100,0],[100,100],[0,100]]}])

# No detections -> drop
print(decide([], cfg, 0.75, 0.35).action)  # drop

# High-confidence person inside the zone -> emit (person + intrusion)
det = YoloDetection(coco_class="person", confidence=0.9, bbox=BoundingBox(x1=10,y1=10,x2=20,y2=20,label="person"))
d = decide([det], cfg, 0.75, 0.35)
print(d.action, [e.event_type for e in d.events])  # emit ['person', 'intrusion']

# Mid-confidence -> escalate
det2 = YoloDetection(coco_class="person", confidence=0.5, bbox=BoundingBox(x1=10,y1=10,x2=20,y2=20,label="person"))
print(decide([det2], cfg, 0.75, 0.35).action)  # escalate

# Camera with an unmapped enabled type -> always escalate
cfg2 = CameraConfig(camera_id="c2", org_id="o1", name="cam2", ingest_mode="rtsp_pull",
                     enabled_events=["person", "loitering"])
print(decide([det], cfg2, 0.75, 0.35).action)  # escalate
EOF`

Expected output (4 lines): `drop`, `emit ['person', 'intrusion']`, `escalate`, `escalate`

- [ ] **Step 3: Commit**

```bash
git add worker/yolo_detector.py
git commit -m "Add YOLO decision logic: COCO mapping, intrusion zone check, gate/emit/escalate"
```

---

### Task 3: ONNX inference wrapper

**Files:**
- Modify: `worker/yolo_detector.py` (append `YoloDetector` class + `COCO_CLASSES` constant to the file created in Task 2)
- Modify: `worker/requirements.txt`

**Interfaces:**
- Consumes: `config.yolo_model_path`, `config.yolo_input_size` from Task 1; `YoloDetection`, `BoundingBox` from Task 2.
- Produces: `YoloDetector` class with `.available: bool` and `.detect(frame: np.ndarray) -> list[YoloDetection]` — consumed by Task 4 (`camera_worker.py`).

- [ ] **Step 1: Add `onnxruntime` to requirements**

In `worker/requirements.txt`, add a new line:

```
onnxruntime>=1.18.0
```

- [ ] **Step 2: Append the COCO class list and `YoloDetector` to `worker/yolo_detector.py`**

Add `import cv2` and `import numpy as np` to the top of `worker/yolo_detector.py` (alongside the existing `logging`/`dataclasses` imports), and add `from config import config` there too. Then append at the end of the file:

```python
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]

YOLO_NMS_SCORE_THRESHOLD = 0.25
YOLO_NMS_IOU_THRESHOLD = 0.45


class YoloDetector:
    """ONNX-based YOLOv8n inference, CPU-only, fail-soft if the model is unavailable."""

    def __init__(self):
        self.available = False
        self.session = None
        self.input_name = None
        try:
            import onnxruntime as ort
            self.session = ort.InferenceSession(
                config.yolo_model_path, providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            self.available = True
            logger.info(f"YOLO model loaded from {config.yolo_model_path}")
        except Exception as e:
            logger.error(
                f"YOLO model failed to load ({e}); YOLO gating disabled, "
                "all frames will escalate to Gemini as before"
            )

    def detect(self, frame) -> list:
        if not self.available:
            return []
        size = config.yolo_input_size
        letterboxed, scale, pad_x, pad_y = self._letterbox(frame, size)
        blob = self._preprocess(letterboxed)

        try:
            outputs = self.session.run(None, {self.input_name: blob})
        except Exception as e:
            logger.warning(f"YOLO inference failed: {e}")
            return []

        return self._postprocess(outputs[0], frame.shape, scale, pad_x, pad_y)

    def _letterbox(self, frame, size: int):
        h, w = frame.shape[:2]
        scale = min(size / h, size / w)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        resized = cv2.resize(frame, (nw, nh))
        pad_x = (size - nw) // 2
        pad_y = (size - nh) // 2
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        return canvas, scale, pad_x, pad_y

    def _preprocess(self, letterboxed):
        rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
        normalized = rgb.astype(np.float32) / 255.0
        chw = normalized.transpose(2, 0, 1)
        return np.expand_dims(chw, axis=0)

    def _postprocess(self, output, frame_shape, scale, pad_x, pad_y) -> list:
        # output shape: (1, 84, N) -> (N, 84): 4 bbox coords (cx,cy,w,h) + 80 class scores
        preds = output[0].transpose(1, 0)
        boxes_cxcywh = preds[:, :4]
        class_scores = preds[:, 4:]
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(len(class_scores)), class_ids]

        keep = confidences >= YOLO_NMS_SCORE_THRESHOLD
        boxes_cxcywh = boxes_cxcywh[keep]
        class_ids = class_ids[keep]
        confidences = confidences[keep]

        if len(boxes_cxcywh) == 0:
            return []

        x1 = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
        y1 = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
        nms_boxes = np.stack([x1, y1, boxes_cxcywh[:, 2], boxes_cxcywh[:, 3]], axis=1)

        indices = cv2.dnn.NMSBoxes(
            nms_boxes.tolist(), confidences.tolist(),
            YOLO_NMS_SCORE_THRESHOLD, YOLO_NMS_IOU_THRESHOLD,
        )
        if len(indices) == 0:
            return []
        indices = np.array(indices).flatten()

        frame_h, frame_w = frame_shape[0], frame_shape[1]
        detections = []
        for i in indices:
            bx1, by1, bw, bh = nms_boxes[i]
            bx2, by2 = bx1 + bw, by1 + bh
            fx1 = max(0, min(frame_w, (bx1 - pad_x) / scale))
            fy1 = max(0, min(frame_h, (by1 - pad_y) / scale))
            fx2 = max(0, min(frame_w, (bx2 - pad_x) / scale))
            fy2 = max(0, min(frame_h, (by2 - pad_y) / scale))

            class_id = int(class_ids[i])
            coco_class = COCO_CLASSES[class_id] if class_id < len(COCO_CLASSES) else "unknown"
            detections.append(YoloDetection(
                coco_class=coco_class,
                confidence=float(confidences[i]),
                bbox=BoundingBox(x1=int(fx1), y1=int(fy1), x2=int(fx2), y2=int(fy2), label=coco_class),
            ))
        return detections
```

- [ ] **Step 3: Install onnxruntime and verify fail-soft behavior (no model file present yet)**

Run: `cd worker && .venv/bin/pip install onnxruntime>=1.18.0`
Run: `.venv/bin/python3 -c "from yolo_detector import YoloDetector; d = YoloDetector(); print('available:', d.available); print('detect on missing model:', d.detect(__import__('numpy').zeros((720,1280,3), dtype='uint8')))"`
Expected: an ERROR log line about the model failing to load (no `models/yolov8n.onnx` exists yet), `available: False`, `detect on missing model: []` — confirms the fail-soft path works with no model present.

- [ ] **Step 4: Commit**

```bash
git add worker/yolo_detector.py worker/requirements.txt
git commit -m "Add ONNX YOLOv8n inference wrapper with fail-soft loading"
```

---

### Task 4: Wire into camera_worker.py, obtain the model, update docs

**Files:**
- Modify: `worker/camera_worker.py`
- Modify: `worker/CLAUDE.md`
- Create (if network access available; otherwise document the step): `worker/models/yolov8n.onnx`

**Interfaces:**
- Consumes: `YoloDetector`, `decide` from `worker/yolo_detector.py` (Tasks 2–3); `config.yolo_enabled`, `config.yolo_fastpath_confidence`, `config.yolo_escalate_floor` from Task 1.
- Produces: `CameraWorker.yolo_calls`, `CameraWorker.yolo_gated_frames`, `CameraWorker.yolo_fastpath_events` stats fields, included in the heartbeat payload.

- [ ] **Step 1: Import and instantiate `YoloDetector` in `camera_worker.py`**

Add to the imports at the top of `worker/camera_worker.py`:

```python
from yolo_detector import YoloDetector, decide
```

In `CameraWorker.__init__`, after `self.gemini = gemini` add:

```python
        self.yolo = YoloDetector()
```

In the `# Stats` block, after `self.gemini_calls = 0` add:

```python
        self.yolo_calls = 0
        self.yolo_gated_frames = 0
        self.yolo_fastpath_events = 0
```

- [ ] **Step 2: Insert the decision branch in `_run_loop`**

In `worker/camera_worker.py`, replace this block:

```python
                # Encode frame as JPEG for Gemini
                _, jpeg_buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                frame_jpeg = jpeg_buffer.tobytes()

                # Send to Gemini Vision
                self.gemini_calls += 1
                events = await self.gemini.analyze_frame(frame_jpeg, self.camera_config)

                # Package and send each detected event
                for event in events:
                    self.events_detected += 1
                    await self.packager.package_and_send(
                        event, frame, self.ring_buffer, self.camera_config
                    )
```

with:

```python
                if config.yolo_enabled and self.yolo.available:
                    self.yolo_calls += 1
                    yolo_detections = await asyncio.to_thread(self.yolo.detect, frame)
                    decision = decide(
                        yolo_detections, self.camera_config,
                        config.yolo_fastpath_confidence, config.yolo_escalate_floor,
                    )

                    if decision.action == "drop":
                        self.yolo_gated_frames += 1
                        continue

                    if decision.action == "emit":
                        self.yolo_fastpath_events += len(decision.events)
                        for event in decision.events:
                            self.events_detected += 1
                            await self.packager.package_and_send(
                                event, frame, self.ring_buffer, self.camera_config
                            )
                        continue

                    # decision.action == "escalate" -> fall through to Gemini below

                # Encode frame as JPEG for Gemini
                _, jpeg_buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                frame_jpeg = jpeg_buffer.tobytes()

                # Send to Gemini Vision
                self.gemini_calls += 1
                events = await self.gemini.analyze_frame(frame_jpeg, self.camera_config)

                # Package and send each detected event
                for event in events:
                    self.events_detected += 1
                    await self.packager.package_and_send(
                        event, frame, self.ring_buffer, self.camera_config
                    )
```

- [ ] **Step 3: Add the new stats to the heartbeat payload**

In `CameraWorker.send_heartbeat`, in the `metrics` dict, after `"gemini_calls": self.gemini_calls,` add:

```python
            "yolo_calls": self.yolo_calls,
            "yolo_gated_frames": self.yolo_gated_frames,
            "yolo_fastpath_events": self.yolo_fastpath_events,
```

- [ ] **Step 4: Obtain the model file**

Try: `cd worker && mkdir -p models && .venv/bin/pip install ultralytics --quiet && .venv/bin/python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')" && mv yolov8n.onnx models/yolov8n.onnx && .venv/bin/pip uninstall -y ultralytics torch torchvision --quiet`

This downloads the standard `yolov8n.pt` checkpoint, exports it to ONNX, moves it into place, then removes the heavyweight `ultralytics`/`torch` packages again (they were only needed for the one-time export, and Task 3's Global Constraint is no PyTorch in the running worker).

If this fails in a sandboxed/offline environment: leave `worker/models/` empty. `YoloDetector.available` will be `False`, every frame will escalate to Gemini exactly as before the change (verified in Task 3 Step 3), and the model can be dropped into `worker/models/yolov8n.onnx` later without any code change. Note this explicitly in the commit message either way.

- [ ] **Step 5: Update `worker/CLAUDE.md`**

In the "Motion Detection" section, add a new subsection right after it:

```markdown
### YOLO Local Detection Gate
- After motion + frame sampling, a local YOLOv8n ONNX model (`yolo_detector.py`, CPU-only via onnxruntime) runs before any Gemini call
- No relevant object (mapped from `enabled_events`) in frame → drop, no Gemini call at all
- High-confidence person/vehicle/animal/intrusion (>= `YOLO_FASTPATH_CONFIDENCE`, default 0.75) → event emitted directly from YOLO, no Gemini call
- Mid-confidence (between `YOLO_ESCALATE_FLOOR` and fastpath threshold) or any other enabled event type (loitering, custom types) → escalates to Gemini exactly as before
- Model file lives at `models/yolov8n.onnx` (path configurable via `YOLO_MODEL_PATH`); if missing or fails to load, `YoloDetector.available` is `False` and every frame escalates to Gemini — fail-soft, never crashes the worker
- To (re)generate the model: `pip install ultralytics && python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx')"`, then move the resulting `yolov8n.onnx` into `models/`
```

- [ ] **Step 6: Verify the worker still imports cleanly**

Run: `cd worker && .venv/bin/python3 -c "import camera_worker"`
Expected: no output, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add worker/camera_worker.py worker/CLAUDE.md
git add worker/models/yolov8n.onnx 2>/dev/null || true
git commit -m "Wire YOLO gate into camera_worker pipeline; document model acquisition"
```

---

### Task 5: Self-review

Per user preference, this replaces a formal test suite pass with a direct review of the changes for correctness, simplicity, SOLID boundaries, and end-to-end flow.

- [ ] **Step 1: Re-read the full diff**

Run: `git diff a143efa -- worker/ 2>/dev/null; git log --oneline -6 -- worker/`
(Or simply `git diff HEAD~5 -- worker/` if the 5 commits above are the most recent worker changes.)

Check for:
- Correctness: does `decide()`'s branch order exactly match the spec's 5-step decision list (per-camera eligibility → no candidates → best confidence vs. floor → vs. fastpath threshold → emit)? Re-trace `worker/yolo_detector.py:decide` against `docs/superpowers/specs/2026-07-29-yolo-gemini-cost-reduction-design.md`.
- Simplicity: is there any dead code path in `camera_worker.py`'s new branch (e.g. the `continue` statements correctly skip the old Gemini path on `drop`/`emit`, and only `escalate` or `yolo_enabled=False`/`not available` fall through)?
- SOLID/boundaries: `yolo_detector.py` has zero dependency on `camera_worker.py`, `gemini_client.py`, or asyncio — confirm it's still true after Task 3's edits (only imports `models`, `config`, `cv2`, `numpy`, `logging`).
- Flow: confirm `self.yolo_calls` increments once per frame that reaches the YOLO stage (not per detection), and `yolo_gated_frames` + `yolo_fastpath_events` + frames that fall through to Gemini together account for every frame that passed the frame sampler.

- [ ] **Step 2: Fix anything found inline, re-run the Task 4 Step 6 import check, and commit any fixes**

```bash
git add -A worker/
git commit -m "Self-review fixes for YOLO gate integration"
```
(Skip this commit if nothing needed fixing.)
