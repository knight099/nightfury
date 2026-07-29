# YOLO Local Detection to Reduce Gemini API Calls — Design

## Problem

The worker already gates Gemini Vision calls behind frame-diff motion detection (`motion_detector.py`) and adaptive frame sampling (`frame_sampler.py`). This catches "nothing changed" but not "something changed that isn't relevant" — rain, shadows, swaying trees, or a cat when only `person` is enabled all pass the motion gate and burn a Gemini call. Every sampled frame that has *any* motion currently gets a full Gemini Vision request, even when a cheap local model could tell in ~30-50ms that there's nothing worth asking Gemini about — or, for the simplest cases, could answer the question itself.

## Goal

Add a YOLO-based local object-detection stage between the existing frame sampler and the Gemini call that:
1. **Gates** Gemini calls further — skip the call entirely if no class relevant to the camera's `enabled_events` is present.
2. **Replaces** Gemini for simple, unambiguous detections — emit the event directly from YOLO's output when confidence is high and the event type has a clean local equivalent.
3. **Escalates** to Gemini as today for anything ambiguous, low-confidence, or semantically richer than YOLO can judge.

## Non-goals

- Loitering or other temporally-reasoned event types (YOLO here is single-frame, stateless).
- Custom/unmapped `enabled_events` values — always escalate to Gemini. **Consequence:** a camera with even one unmapped type in its `enabled_events` (e.g. `person` + `loitering`) gets no gating benefit at all — every sampled frame still goes to Gemini, since YOLO can't rule out `loitering` on its own. Only cameras whose `enabled_events` is entirely within `{person, vehicle, animal, intrusion}` benefit from the gate/fast-path.
- Per-camera severity overrides for fast-path events — fixed defaults only.
- Any change to backend, frontend, or digest — this is worker-pipeline-only; no other part of the app does image inference.
- GPU inference / ultralytics+PyTorch runtime — CPU-only ONNX to keep the worker lean.

## Architecture

```
ingest → ring buffer → motion detect → frame sampler → YOLO detect → decision → Gemini (conditional) → package
```

New component: `worker/yolo_detector.py`

```python
@dataclass
class YoloDetection:
    coco_class: str      # raw COCO label, e.g. "car"
    confidence: float
    bbox: BoundingBox     # rescaled to frame coordinates (1280x720)

class YoloDetector:
    def __init__(self):
        # onnxruntime.InferenceSession over config.yolo_model_path
        ...

    def detect(self, frame: np.ndarray) -> list[YoloDetection]:
        # letterbox resize to yolo_input_size, run inference,
        # standard YOLOv8 postprocessing (confidence filter + NMS),
        # rescale boxes back to original frame size
        ...
```

Model: `yolov8n.onnx` (COCO-80 classes), exported once from the standard Ultralytics YOLOv8n checkpoint (`yolo export model=yolov8n.pt format=onnx`) and committed to the worker as a binary asset (`worker/models/yolov8n.onnx`, ~12MB). Runtime dependency: `onnxruntime` (CPU build) — no PyTorch, no CUDA.

### COCO → app event_type mapping

```python
COCO_TO_EVENT_TYPE = {
    "person": "person",
    "car": "vehicle", "truck": "vehicle", "bus": "vehicle", "motorcycle": "vehicle",
    "dog": "animal", "cat": "animal", "bird": "animal", "horse": "animal",
}
```

Classes not in this map are ignored for the purposes of the gate/fast-path/escalate decision. `intrusion` is not a COCO class — it's derived: a `person` detection whose bbox center falls inside one of `camera_config.detection_zones` (point-in-polygon on the existing zone point lists, same pixel space Gemini already assumes: 1280x720).

### Decision logic (in `camera_worker.py`, replacing the direct "encode + call Gemini" step)

For each frame that passes `frame_sampler.should_sample()`:

0. **First, per-camera, once (not per-frame):** if `camera_config.enabled_events` contains any type outside `{person, vehicle, animal, intrusion}` (e.g. `loitering`, or a custom type), YOLO cannot rule that type out on its own — this camera gets no gating benefit and every sampled frame escalates straight to Gemini, exactly as today. The steps below only apply to cameras whose `enabled_events` is a subset of `{person, vehicle, animal, intrusion}`.
1. Run `yolo_detector.detect(frame)`.
2. Map detections to event types via `COCO_TO_EVENT_TYPE`, filter to `camera_config.enabled_events`.
3. Also check for `intrusion`: any `person` detection whose bbox center is inside a configured zone counts as a candidate `intrusion` detection (only relevant if `"intrusion"` is in `enabled_events`).
4. **No relevant candidates** → drop the frame. No Gemini call. (Counts toward `yolo_gated_frames`.)
5. Otherwise, take the highest-confidence relevant candidate:
   - **confidence ≥ `yolo_fastpath_confidence`** (default `0.75`) → emit a `DetectedEvent` directly from YOLO (see below). No Gemini call.
   - **`yolo_escalate_floor` ≤ confidence < `yolo_fastpath_confidence`** (default floor `0.35`) → escalate to Gemini as today (full prompt + frame).
   - **confidence < `yolo_escalate_floor`** → treat as no relevant detection, drop the frame (case 4).

### Fast-path event construction

Fixed defaults, no new config surface:

| event_type | severity | description template |
|---|---|---|
| `person` | `low` | `"{n} person detected"` (n = count of person detections above threshold) |
| `vehicle` | `low` | `"{n} vehicle detected"` |
| `animal` | `low` | `"{n} animal detected"` |
| `intrusion` | `medium` | `"Person detected in {zone_name} zone"` |

`bounding_boxes` on the emitted `DetectedEvent` are populated straight from the YOLO detections (already in frame pixel coordinates, same format `event_packager.py` already consumes from Gemini's output — no downstream changes needed).

### Config additions (`config.py`)

```python
# YOLO local detection (gates + short-circuits Gemini calls)
yolo_enabled: bool = True
yolo_model_path: str = "models/yolov8n.onnx"
yolo_input_size: int = 640
yolo_fastpath_confidence: float = 0.75
yolo_escalate_floor: float = 0.35
```

### Fail-soft behavior

If the ONNX model fails to load at `YoloDetector.__init__` (missing file, bad weights, onnxruntime import error), log a single ERROR and set an internal `self.available = False`. `CameraWorker` checks this once at startup: if unavailable, `yolo_enabled` is treated as `False` for that run and every sampled frame goes straight to Gemini — today's behavior, unchanged. If inference throws mid-run on a specific frame, catch, log a WARNING (not spamming — same pattern as the GCS upload fail-soft), and treat that frame as "escalate to Gemini" (fail toward the existing safe path, not toward silently dropping frames).

### Stats / observability

`CameraWorker` already tracks `gemini_calls` for the heartbeat payload. Add:
- `yolo_calls` — frames YOLO ran inference on
- `yolo_gated_frames` — frames dropped with no Gemini call at all
- `yolo_fastpath_events` — events emitted directly from YOLO, no Gemini call

These ride along in the existing `send_heartbeat()` metrics dict — no backend schema change required (metrics dict is already free-form JSON).

## Testing

Following the existing `motion_detector`/`prompt_builder` unit test style (no real model inference in tests):
- `test_yolo_detector.py`: COCO→event_type mapping correctness; point-in-polygon intrusion check (person bbox center inside/outside a zone polygon) using synthetic detections, not real inference.
- `test_camera_worker.py` (extend if it exists, else new): the three-way decision logic (gate / fast-path emit / escalate) driven by a fake `YoloDetector.detect()` returning canned `YoloDetection` lists — verifies each of the 6 decision-logic branches above independently of real YOLO or Gemini calls.

## Rollout

- `yolo_enabled` defaults to `True` but is a single config flag — can be flipped off per-deployment (env var) without a code change if the model causes problems in the field.
- No backend or frontend changes; no migration; no API contract change.
