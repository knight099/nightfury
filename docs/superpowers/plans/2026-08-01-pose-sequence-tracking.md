# Pose-Based Step-Sequence Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-camera-configurable step-sequence engine that tracks a person's pose across zones over time (e.g. retail checkout compliance, airport lane procedures) and fires an event when a step is skipped, stalls past its timeout, or the sequence completes.

**Architecture:** Three new pure-logic worker modules — `worker/pose_detector.py` (ONNX YOLOv8-pose wrapper + geometric pose classifier), `worker/person_tracker.py` (greedy IoU multi-person tracker), `worker/sequence_engine.py` (per-track step-sequence state machine) — wired into `camera_worker.py`'s `_run_loop()` as an independent stage that runs only for cameras with a non-empty `step_sequence` configured. Backend gets a new `step_sequence` JSONB column (mirrors the existing `detection_zones` column) with cross-field validation. Frontend gets a `SequenceEditor.tsx` component mirroring `ZonesEditor.tsx`.

**Tech Stack:** `onnxruntime` (CPU build, already a worker dependency from the YOLO detection gate) for pose inference, `opencv-python-headless` (already a dependency) for letterbox resize + NMS — no PyTorch, no new heavy dependency, no new backend/frontend dependency.

## Global Constraints

- No PyTorch/ultralytics runtime in the running worker — CPU-only `onnxruntime` + a committed/downloaded `yolov8n-pose.onnx`.
- Fail-soft: if the pose model file is missing or fails to load, cameras with a `step_sequence` configured simply skip this stage — never crash, never affect the existing YOLO-gate/Gemini pipeline for that camera.
- This stage only runs for cameras whose `step_sequence` is non-empty — zero overhead otherwise.
- Per user's standing preference (already applied to the merged YOLO local-detection plan): implement directly, no TDD/pytest-first ceremony — each task ends with a self-contained implementation, a quick manual sanity-check script (not a committed pytest file), and a commit. A dedicated final task does a full self-review pass instead of a formal test suite.
- Reuse `point_in_polygon` from the existing `worker/yolo_detector.py` for zone containment checks — do not reimplement point-in-polygon math.
- Prerequisite: the YOLO local-detection gate (`worker/yolo_detector.py`, `camera_worker.py` wiring) already exists on `main` — this plan builds on it and does not modify its decision logic.

---

### Task 1: Worker config settings + `step_sequence` on `CameraConfig`

**Files:**
- Modify: `worker/config.py`
- Modify: `worker/models.py`

**Interfaces:**
- Produces: `config.pose_enabled: bool`, `config.pose_model_path: str`, `config.pose_input_size: int`, `config.pose_keypoint_confidence: float`, `config.track_iou_threshold: float`, `config.track_ttl_seconds: float`; `CameraConfig.step_sequence: list[dict]` — consumed by Tasks 2–6.

- [ ] **Step 1: Add pose/tracking config settings**

In `worker/config.py`, add after the `# YOLO local detection` block (after `yolo_escalate_floor: float = 0.35`):

```python
    # Pose detection + step-sequence tracking
    pose_enabled: bool = True
    pose_model_path: str = "models/yolov8n-pose.onnx"
    pose_input_size: int = 640
    pose_keypoint_confidence: float = 0.3
    track_iou_threshold: float = 0.3
    track_ttl_seconds: float = 5.0
```

- [ ] **Step 2: Add `step_sequence` to `CameraConfig`**

In `worker/models.py`, add a field to `CameraConfig` right after `detection_zones: list[dict] = field(default_factory=list)`:

```python
    step_sequence: list[dict] = field(default_factory=list)
```

And in `CameraConfig.from_assignment`, add a corresponding line right after `detection_zones=a.get("detection_zones", []),`:

```python
            step_sequence=a.get("step_sequence", []),
```

- [ ] **Step 3: Verify it loads**

Run: `cd worker && .venv/bin/python3 -c "from config import config; from models import CameraConfig; print(config.pose_enabled, config.pose_model_path, config.track_ttl_seconds); print(CameraConfig(camera_id='c', org_id='o', name='n', ingest_mode='rtsp_pull').step_sequence)"`
Expected output (2 lines): `True models/yolov8n-pose.onnx 5.0` then `[]`

- [ ] **Step 4: Commit**

```bash
git add worker/config.py worker/models.py
git commit -m "Add pose/tracking config settings and step_sequence on CameraConfig"
```

---

### Task 2: Pose classification — keypoint dataclass and geometric heuristics

**Files:**
- Create: `worker/pose_detector.py` (this task writes the non-ONNX half; Task 3 appends the ONNX wrapper to the same file)

**Interfaces:**
- Consumes: `BoundingBox` from `worker/models.py` (existing); `config.pose_keypoint_confidence` from Task 1.
- Produces: `PersonPose` dataclass, `POSE_LABELS: set[str]`, `KEYPOINT_NAMES: list[str]`, `classify_pose(keypoints, min_confidence) -> str` — consumed by Task 3 (ONNX wrapper appended to same file), Task 4 (tracker), Task 6 (`camera_worker.py`).

- [ ] **Step 1: Write `worker/pose_detector.py`**

```python
import logging
import math
from dataclasses import dataclass, field

from models import BoundingBox

logger = logging.getLogger(__name__)

# COCO-17 keypoint order, as emitted by YOLOv8-pose.
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
KP = {name: i for i, name in enumerate(KEYPOINT_NAMES)}

POSE_LABELS = {"standing", "bending", "crouching", "sitting", "reaching", "unknown"}

STANDING_LEG_ANGLE_DEG = 160.0
CROUCHING_LEG_ANGLE_DEG = 120.0
SITTING_LEG_ANGLE_MIN_DEG = 70.0
SITTING_LEG_ANGLE_MAX_DEG = 110.0
BENDING_TORSO_TILT_DEG = 45.0
REACHING_WRIST_ABOVE_SHOULDER_RATIO = 0.05  # fraction of frame-independent bbox height


@dataclass
class PersonPose:
    bbox: BoundingBox
    keypoints: list  # list[tuple[float, float, float]], (x, y, confidence) x 17, COCO order
    label: str = "unknown"


def _kp(keypoints, name, min_confidence):
    x, y, c = keypoints[KP[name]]
    if c < min_confidence:
        return None
    return (x, y)


def _angle_deg(a, b, c) -> float | None:
    """Angle ABC at vertex b, in degrees. a, b, c are (x, y) tuples."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cos_angle = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    cos_angle = max(-1.0, min(1.0, cos_angle))
    return math.degrees(math.acos(cos_angle))


def _leg_angles(keypoints, min_confidence) -> list:
    angles = []
    for side in ("left", "right"):
        hip = _kp(keypoints, f"{side}_hip", min_confidence)
        knee = _kp(keypoints, f"{side}_knee", min_confidence)
        ankle = _kp(keypoints, f"{side}_ankle", min_confidence)
        if hip and knee and ankle:
            angle = _angle_deg(hip, knee, ankle)
            if angle is not None:
                angles.append(angle)
    return angles


def _torso_tilt_deg(keypoints, min_confidence) -> float | None:
    l_sh = _kp(keypoints, "left_shoulder", min_confidence)
    r_sh = _kp(keypoints, "right_shoulder", min_confidence)
    l_hip = _kp(keypoints, "left_hip", min_confidence)
    r_hip = _kp(keypoints, "right_hip", min_confidence)
    shoulders = [p for p in (l_sh, r_sh) if p]
    hips = [p for p in (l_hip, r_hip) if p]
    if not shoulders or not hips:
        return None
    sx = sum(p[0] for p in shoulders) / len(shoulders)
    sy = sum(p[1] for p in shoulders) / len(shoulders)
    hx = sum(p[0] for p in hips) / len(hips)
    hy = sum(p[1] for p in hips) / len(hips)
    dx, dy = hx - sx, hy - sy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return None
    return math.degrees(math.atan2(abs(dx), abs(dy)))


def _is_reaching(keypoints, min_confidence) -> bool:
    l_sh = _kp(keypoints, "left_shoulder", min_confidence)
    r_sh = _kp(keypoints, "right_shoulder", min_confidence)
    l_hip = _kp(keypoints, "left_hip", min_confidence)
    r_hip = _kp(keypoints, "right_hip", min_confidence)
    shoulders = [p for p in (l_sh, r_sh) if p]
    hips = [p for p in (l_hip, r_hip) if p]
    if not shoulders or not hips:
        return False
    shoulder_y = sum(p[1] for p in shoulders) / len(shoulders)
    torso_height = abs(
        (sum(p[1] for p in hips) / len(hips)) - shoulder_y
    ) or 1.0

    for side in ("left", "right"):
        wrist = _kp(keypoints, f"{side}_wrist", min_confidence)
        if wrist is None:
            continue
        # A wrist meaningfully above shoulder height (smaller y = higher in image).
        if (shoulder_y - wrist[1]) > REACHING_WRIST_ABOVE_SHOULDER_RATIO * torso_height * 2:
            return True
    return False


def classify_pose(keypoints, min_confidence: float = 0.3) -> str:
    """Classify a person's pose from 17 COCO keypoints using geometric heuristics.

    keypoints: list of 17 (x, y, confidence) tuples, COCO order (see KEYPOINT_NAMES).
    Priority order avoids ambiguous double-fires: reaching > bending > crouching > sitting > standing.
    Returns "unknown" if no rule has enough visible keypoints to fire.
    """
    if _is_reaching(keypoints, min_confidence):
        return "reaching"

    tilt = _torso_tilt_deg(keypoints, min_confidence)
    if tilt is not None and tilt > BENDING_TORSO_TILT_DEG:
        return "bending"

    leg_angles = _leg_angles(keypoints, min_confidence)
    if leg_angles:
        best = max(leg_angles)
        if best < CROUCHING_LEG_ANGLE_DEG:
            return "crouching"
        if SITTING_LEG_ANGLE_MIN_DEG <= best <= SITTING_LEG_ANGLE_MAX_DEG:
            return "sitting"
        if best > STANDING_LEG_ANGLE_DEG:
            return "standing"

    return "unknown"
```

- [ ] **Step 2: Manual sanity check of the classification heuristics**

Run: `cd worker && .venv/bin/python3 <<'EOF'
from pose_detector import classify_pose, KP

def kp(overrides):
    base = [(0.0, 0.0, 0.9)] * 17
    for name, val in overrides.items():
        base[KP[name]] = val
    return base

# Straight legs, upright torso -> standing
standing = kp({
    "left_shoulder": (100, 100, 0.9), "right_shoulder": (120, 100, 0.9),
    "left_hip": (100, 200, 0.9), "right_hip": (120, 200, 0.9),
    "left_knee": (100, 300, 0.9), "right_knee": (120, 300, 0.9),
    "left_ankle": (100, 400, 0.9), "right_ankle": (120, 400, 0.9),
})
print(classify_pose(standing))  # standing

# Deeply bent knees, hips near knee height -> crouching
crouching = kp({
    "left_shoulder": (100, 100, 0.9), "right_shoulder": (120, 100, 0.9),
    "left_hip": (100, 200, 0.9), "right_hip": (120, 200, 0.9),
    "left_knee": (90, 210, 0.9), "right_knee": (130, 210, 0.9),
    "left_ankle": (100, 205, 0.9), "right_ankle": (120, 205, 0.9),
})
print(classify_pose(crouching))  # crouching

# Torso tilted far from vertical -> bending
bending = kp({
    "left_shoulder": (50, 150, 0.9), "right_shoulder": (70, 150, 0.9),
    "left_hip": (100, 200, 0.9), "right_hip": (120, 200, 0.9),
})
print(classify_pose(bending))  # bending

# Wrist well above shoulder -> reaching
reaching = kp({
    "left_shoulder": (100, 150, 0.9), "right_shoulder": (120, 150, 0.9),
    "left_hip": (100, 200, 0.9), "right_hip": (120, 200, 0.9),
    "left_wrist": (100, 50, 0.9),
})
print(classify_pose(reaching))  # reaching

# All low confidence -> unknown
unknown = [(0.0, 0.0, 0.05)] * 17
print(classify_pose(unknown))  # unknown
EOF`

Expected output (5 lines): `standing`, `crouching`, `bending`, `reaching`, `unknown`

- [ ] **Step 3: Commit**

```bash
git add worker/pose_detector.py
git commit -m "Add pose classification heuristics: PersonPose, classify_pose geometric rules"
```

---

### Task 3: ONNX pose inference wrapper

**Files:**
- Modify: `worker/pose_detector.py` (append `PoseDetector` class to the file created in Task 2)

**Interfaces:**
- Consumes: `config.pose_model_path`, `config.pose_input_size` from Task 1; `PersonPose`, `classify_pose` from Task 2.
- Produces: `PoseDetector` class with `.available: bool` and `.detect(frame: np.ndarray) -> list[PersonPose] | None` (returns `None` on a mid-run inference error, `[]` if unavailable or no detections) — consumed by Task 6 (`camera_worker.py`).

- [ ] **Step 1: Add imports and append `PoseDetector` to `worker/pose_detector.py`**

Add `import cv2`, `import numpy as np`, and `from config import config` to the top of `worker/pose_detector.py` (alongside the existing `logging`/`math`/`dataclasses` imports). Then append at the end of the file:

```python
POSE_NMS_SCORE_THRESHOLD = 0.25
POSE_NMS_IOU_THRESHOLD = 0.45
NUM_KEYPOINTS = 17


class PoseDetector:
    """ONNX-based YOLOv8-pose inference, CPU-only, fail-soft if the model is unavailable."""

    def __init__(self):
        self.available = False
        self.session = None
        self.input_name = None
        try:
            import onnxruntime as ort
            self.session = ort.InferenceSession(
                config.pose_model_path, providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            self.available = True
            logger.info(f"Pose model loaded from {config.pose_model_path}")
        except Exception as e:
            logger.error(
                f"Pose model failed to load ({e}); pose/sequence tracking disabled "
                "for cameras with a step_sequence configured"
            )

    def detect(self, frame):
        if not self.available:
            return []
        size = config.pose_input_size
        letterboxed, scale, pad_x, pad_y = self._letterbox(frame, size)
        blob = self._preprocess(letterboxed)

        try:
            outputs = self.session.run(None, {self.input_name: blob})
        except Exception as e:
            logger.warning(f"Pose inference failed: {e}")
            return None

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

    def _postprocess(self, output, frame_shape, scale, pad_x, pad_y):
        # output shape: (1, 56, N) -> (N, 56): 4 bbox (cx,cy,w,h) + 1 person-conf + 17*3 keypoints
        preds = output[0].transpose(1, 0)
        boxes_cxcywh = preds[:, :4]
        confidences = preds[:, 4]
        kpts_raw = preds[:, 5:].reshape(-1, NUM_KEYPOINTS, 3)

        keep = confidences >= POSE_NMS_SCORE_THRESHOLD
        boxes_cxcywh = boxes_cxcywh[keep]
        confidences = confidences[keep]
        kpts_raw = kpts_raw[keep]

        if len(boxes_cxcywh) == 0:
            return []

        x1 = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
        y1 = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
        nms_boxes = np.stack([x1, y1, boxes_cxcywh[:, 2], boxes_cxcywh[:, 3]], axis=1)

        indices = cv2.dnn.NMSBoxes(
            nms_boxes.tolist(), confidences.tolist(),
            POSE_NMS_SCORE_THRESHOLD, POSE_NMS_IOU_THRESHOLD,
        )
        if len(indices) == 0:
            return []
        indices = np.array(indices).flatten()

        frame_h, frame_w = frame_shape[0], frame_shape[1]

        def rescale_point(x, y):
            fx = max(0, min(frame_w, (x - pad_x) / scale))
            fy = max(0, min(frame_h, (y - pad_y) / scale))
            return fx, fy

        poses = []
        for i in indices:
            bx1, by1, bw, bh = nms_boxes[i]
            bx2, by2 = bx1 + bw, by1 + bh
            fx1, fy1 = rescale_point(bx1, by1)
            fx2, fy2 = rescale_point(bx2, by2)

            keypoints = []
            for kx, ky, kc in kpts_raw[i]:
                rx, ry = rescale_point(kx, ky)
                keypoints.append((float(rx), float(ry), float(kc)))

            bbox = BoundingBox(x1=int(fx1), y1=int(fy1), x2=int(fx2), y2=int(fy2), label="person")
            label = classify_pose(keypoints, config.pose_keypoint_confidence)
            poses.append(PersonPose(bbox=bbox, keypoints=keypoints, label=label))
        return poses
```

- [ ] **Step 2: Verify fail-soft behavior (no model file present yet)**

Run: `cd worker && .venv/bin/python3 -c "from pose_detector import PoseDetector; d = PoseDetector(); print('available:', d.available); print('detect on missing model:', d.detect(__import__('numpy').zeros((720,1280,3), dtype='uint8')))"`
Expected: an ERROR log line about the model failing to load (no `models/yolov8n-pose.onnx` exists yet), `available: False`, `detect on missing model: []`.

- [ ] **Step 3: Commit**

```bash
git add worker/pose_detector.py
git commit -m "Add ONNX YOLOv8-pose inference wrapper with fail-soft loading"
```

---

### Task 4: Multi-person IoU tracker

**Files:**
- Create: `worker/person_tracker.py`

**Interfaces:**
- Consumes: `PersonPose`, `BoundingBox` from `worker/pose_detector.py`/`worker/models.py`; `SequenceState` from Task 5 (forward reference — see note in Step 1).
- Produces: `Track` dataclass, `PersonTracker` class with `.update(poses: list, now: float) -> list` (returns the list of `Track`s matched to a detection *this call*, each with a fresh `.pose` and a persistent `.sequence_state`) — consumed by Task 6 (`camera_worker.py`).

Note: this task is written and committed *before* Task 5 defines `SequenceState`, so `worker/person_tracker.py` does not import it — instead `Track.sequence_state` is created via a zero-argument callable (`sequence_state_factory`) passed into `PersonTracker.__init__`, keeping `person_tracker.py` decoupled from `sequence_engine.py`. `camera_worker.py` (Task 6) wires the two together by passing `SequenceState` itself as that factory.

- [ ] **Step 1: Write `worker/person_tracker.py`**

```python
import logging
from dataclasses import dataclass, field

from pose_detector import PersonPose

logger = logging.getLogger(__name__)


@dataclass
class Track:
    track_id: int
    pose: PersonPose
    sequence_state: object
    last_seen_at: float
    missed_frames: int = 0


def _iou(a, b) -> float:
    """Intersection-over-union of two BoundingBox-like objects (x1,y1,x2,y2)."""
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    intersection = iw * ih
    if intersection == 0:
        return 0.0
    area_a = max(0, a.x2 - a.x1) * max(0, a.y2 - a.y1)
    area_b = max(0, b.x2 - b.x1) * max(0, b.y2 - b.y1)
    union = area_a + area_b - intersection
    if union <= 0:
        return 0.0
    return intersection / union


class PersonTracker:
    """Greedy IoU-based multi-person tracker. No re-identification: a track
    lost for longer than track_ttl_seconds is dropped, and if that person
    reappears they start a brand-new track (and a fresh sequence_state)."""

    def __init__(self, iou_threshold: float, ttl_seconds: float, sequence_state_factory):
        self.iou_threshold = iou_threshold
        self.ttl_seconds = ttl_seconds
        self.sequence_state_factory = sequence_state_factory
        self._tracks: dict = {}
        self._next_id = 1

    def update(self, poses: list, now: float) -> list:
        unmatched_poses = list(range(len(poses)))
        matched_tracks = []

        # Greedy matching: for each existing track, pick the best remaining IoU match.
        for track_id, track in list(self._tracks.items()):
            best_iou = 0.0
            best_idx = None
            for idx in unmatched_poses:
                iou = _iou(track.pose.bbox, poses[idx].bbox)
                if iou > best_iou:
                    best_iou = iou
                    best_idx = idx
            if best_idx is not None and best_iou >= self.iou_threshold:
                track.pose = poses[best_idx]
                track.last_seen_at = now
                track.missed_frames = 0
                unmatched_poses.remove(best_idx)
                matched_tracks.append(track)
            else:
                track.missed_frames += 1

        # Any pose left over starts a new track.
        for idx in unmatched_poses:
            track = Track(
                track_id=self._next_id,
                pose=poses[idx],
                sequence_state=self.sequence_state_factory(),
                last_seen_at=now,
            )
            self._next_id += 1
            self._tracks[track.track_id] = track
            matched_tracks.append(track)

        # Drop tracks that have aged out.
        for track_id in list(self._tracks.keys()):
            if now - self._tracks[track_id].last_seen_at > self.ttl_seconds:
                del self._tracks[track_id]

        return matched_tracks
```

- [ ] **Step 2: Manual sanity check of tracking + TTL**

Run: `cd worker && .venv/bin/python3 <<'EOF'
from person_tracker import PersonTracker
from pose_detector import PersonPose
from models import BoundingBox

tracker = PersonTracker(iou_threshold=0.3, ttl_seconds=1.0, sequence_state_factory=lambda: "fresh-state")

p1 = PersonPose(bbox=BoundingBox(x1=100, y1=100, x2=200, y2=300, label="person"), keypoints=[], label="standing")
tracks = tracker.update([p1], now=0.0)
print(len(tracks), tracks[0].track_id)  # 1 1

# Same person, slightly moved -> same track ID (IoU still high)
p1_moved = PersonPose(bbox=BoundingBox(x1=105, y1=100, x2=205, y2=300, label="person"), keypoints=[], label="standing")
tracks2 = tracker.update([p1_moved], now=0.1)
print(len(tracks2), tracks2[0].track_id)  # 1 1

# No detections for longer than TTL -> track dropped, new detection gets a new ID
tracks3 = tracker.update([], now=0.2)
print(len(tracks3))  # 0
tracks4 = tracker.update([p1], now=2.0)
print(len(tracks4), tracks4[0].track_id)  # 1 2
EOF`

Expected output (4 lines): `1 1`, `1 1`, `0`, `1 2`

- [ ] **Step 3: Commit**

```bash
git add worker/person_tracker.py
git commit -m "Add greedy IoU multi-person tracker with TTL-based track expiry"
```

---

### Task 5: Sequence engine — state machine and event construction

**Files:**
- Create: `worker/sequence_engine.py`

**Interfaces:**
- Consumes: `BoundingBox`, `DetectedEvent` from `worker/models.py`.
- Produces: `SequenceState` class (usable as `Track.sequence_state`, zero-arg constructible per Task 4's `sequence_state_factory` contract), `SequenceEvent` dataclass, `advance(state, step_sequence, zone_name, pose_label, now) -> SequenceEvent | None`, `build_detected_event(seq_event, bbox) -> DetectedEvent` — consumed by Task 6 (`camera_worker.py`).

- [ ] **Step 1: Write `worker/sequence_engine.py`**

```python
import time
from dataclasses import dataclass, field

from models import BoundingBox, DetectedEvent


class SequenceState:
    """Per-track progress through a camera's step_sequence. Zero-argument
    constructible so PersonTracker can create one per new track without
    depending on this module (see person_tracker.py's sequence_state_factory)."""

    def __init__(self):
        self.current_step_index = 0
        self.step_entered_at = time.monotonic()
        self.completed = False


@dataclass
class SequenceEvent:
    kind: str  # "step_skipped" | "step_timeout" | "sequence_completed"
    step_name: str
    zone: str | None = None
    max_seconds: float | None = None
    all_step_names: list = field(default_factory=list)


def advance(state: SequenceState, step_sequence: list, zone_name, pose_label: str, now: float):
    """Advance a track's sequence state given its current (zone, pose) reading.

    Returns a SequenceEvent the first (and only the first) time a step is
    skipped, a step times out, or the sequence completes. After firing,
    state.completed becomes True and subsequent calls return None — this
    is a terminal state, not re-armed on further frames for this track.
    """
    if state.completed or not step_sequence:
        return None

    current_step = step_sequence[state.current_step_index]
    step_zone = current_step.get("zone")
    step_pose = current_step.get("pose")

    matches_current = zone_name == step_zone and (step_pose is None or pose_label == step_pose)
    if matches_current:
        state.current_step_index += 1
        state.step_entered_at = now
        if state.current_step_index >= len(step_sequence):
            state.completed = True
            return SequenceEvent(
                kind="sequence_completed",
                step_name=current_step.get("name", ""),
                all_step_names=[s.get("name", "") for s in step_sequence],
            )
        return None

    later_zones = {s.get("zone") for s in step_sequence[state.current_step_index + 1:]}
    if zone_name is not None and zone_name in later_zones:
        state.completed = True
        return SequenceEvent(
            kind="step_skipped",
            step_name=current_step.get("name", ""),
            zone=zone_name,
        )

    max_seconds = current_step.get("max_seconds")
    if max_seconds is not None and (now - state.step_entered_at) > max_seconds:
        state.completed = True
        return SequenceEvent(
            kind="step_timeout",
            step_name=current_step.get("name", ""),
            max_seconds=max_seconds,
        )

    return None


def build_detected_event(seq_event: SequenceEvent, bbox: BoundingBox) -> DetectedEvent:
    bboxes = [bbox]
    if seq_event.kind == "step_skipped":
        return DetectedEvent(
            event_type="step_skipped",
            confidence=1.0,
            severity="medium",
            description=f"Skipped step '{seq_event.step_name}' — reached '{seq_event.zone}' early",
            bounding_boxes=bboxes,
            zone=seq_event.zone,
        )
    if seq_event.kind == "step_timeout":
        return DetectedEvent(
            event_type="step_timeout",
            confidence=1.0,
            severity="medium",
            description=f"Stalled at step '{seq_event.step_name}' for over {seq_event.max_seconds}s",
            bounding_boxes=bboxes,
        )
    # sequence_completed
    return DetectedEvent(
        event_type="sequence_completed",
        confidence=1.0,
        severity="low",
        description="Completed sequence: " + " → ".join(seq_event.all_step_names),
        bounding_boxes=bboxes,
    )
```

- [ ] **Step 2: Manual sanity check of the four branches**

Run: `cd worker && .venv/bin/python3 <<'EOF'
from sequence_engine import SequenceState, advance

seq = [
    {"name": "pick_item", "zone": "Shelf", "pose": "reaching", "max_seconds": 30},
    {"name": "go_to_counter", "zone": "Counter", "pose": "standing", "max_seconds": 60},
    {"name": "pay", "zone": "Counter", "pose": "reaching", "max_seconds": 45},
]

# In-order progression -> no event until final step completes
s = SequenceState()
print(advance(s, seq, "Shelf", "reaching", 0.0))       # None (advanced to step 1)
print(advance(s, seq, "Counter", "standing", 1.0))     # None (advanced to step 2)
print(advance(s, seq, "Counter", "reaching", 2.0))     # SequenceEvent(kind='sequence_completed', ...)

# Skip-ahead violation
s2 = SequenceState()
print(advance(s2, seq, "Counter", "reaching", 0.0).kind)  # step_skipped (jumped to step 3's zone)

# Timeout violation
s3 = SequenceState()
print(advance(s3, seq, "Shelf", "standing", 0.0))       # None (wrong pose, no match, no timeout yet)
print(advance(s3, seq, "Shelf", "standing", 31.0).kind) # step_timeout

# Fires once: further calls after a violation return None
print(advance(s2, seq, "Exit", "standing", 5.0))  # None (already completed/terminal)
EOF`

Expected output (6 lines): `None`, `None`, a `SequenceEvent(kind='sequence_completed', ...)` line, `step_skipped`, `None`, `step_timeout`, `None` — (7 print statements, 7 lines; the exact repr of the completed event line will show all its fields).

- [ ] **Step 3: Commit**

```bash
git add worker/sequence_engine.py
git commit -m "Add sequence engine: state machine for step_skipped/step_timeout/sequence_completed"
```

---

### Task 6: Wire pose + tracker + sequence engine into `camera_worker.py`

**Files:**
- Modify: `worker/camera_worker.py`
- Modify: `worker/CLAUDE.md`
- Create (if network access available; otherwise document the step): `worker/models/yolov8n-pose.onnx`

**Interfaces:**
- Consumes: `PoseDetector` (Task 3), `PersonTracker` (Task 4), `SequenceState`/`advance`/`build_detected_event` (Task 5); `config.pose_enabled`, `config.pose_input_size`, `config.track_iou_threshold`, `config.track_ttl_seconds` (Task 1).
- Produces: `CameraWorker.pose_calls`, `CameraWorker.sequence_events` stats fields, included in the heartbeat payload.

- [ ] **Step 1: Add imports and instantiate `PoseDetector`/`PersonTracker` in `camera_worker.py`**

Add to the imports at the top of `worker/camera_worker.py`, after `from yolo_detector import YoloDetector, decide`:

```python
from pose_detector import PoseDetector
from person_tracker import PersonTracker
from sequence_engine import SequenceState, advance, build_detected_event
from yolo_detector import point_in_polygon
```

In `CameraWorker.__init__`, after `self.yolo = YoloDetector()` add:

```python
        self.pose = PoseDetector()
        self.tracker = PersonTracker(
            iou_threshold=config.track_iou_threshold,
            ttl_seconds=config.track_ttl_seconds,
            sequence_state_factory=SequenceState,
        )
```

In the `# Stats` block, after `self.yolo_fastpath_events = 0` add:

```python
        self.pose_calls = 0
        self.sequence_events = 0
```

- [ ] **Step 2: Insert the pose/sequence stage in `_run_loop`**

In `worker/camera_worker.py`, insert this block right after the line `if not self.frame_sampler.should_sample(frame, has_motion):\n                    continue` and its blank line, and *before* the existing `if config.yolo_enabled and self.yolo.available:` block:

```python
                if config.pose_enabled and self.pose.available and self.camera_config.step_sequence:
                    self.pose_calls += 1
                    poses = await asyncio.to_thread(self.pose.detect, frame)
                    if poses is not None:
                        tracks = self.tracker.update(poses, time.time())
                        for track in tracks:
                            zone_name = self._zone_for_bbox(track.pose.bbox)
                            seq_event = advance(
                                track.sequence_state, self.camera_config.step_sequence,
                                zone_name, track.pose.label, time.time(),
                            )
                            if seq_event is not None:
                                self.sequence_events += 1
                                event = build_detected_event(seq_event, track.pose.bbox)
                                self.events_detected += 1
                                await self.packager.package_and_send(
                                    event, frame, self.ring_buffer, self.camera_config
                                )
```

Note: this stage never `continue`s — the frame still proceeds to the YOLO gate and Gemini path below exactly as before, since sequence violations are independent of the person/vehicle/intrusion event flow.

- [ ] **Step 3: Add the `_zone_for_bbox` helper method**

Add this method to `CameraWorker` (near `_encode_webp`):

```python
    def _zone_for_bbox(self, bbox):
        cx = (bbox.x1 + bbox.x2) / 2
        cy = (bbox.y1 + bbox.y2) / 2
        for zone in self.camera_config.detection_zones:
            if point_in_polygon(cx, cy, zone.get("points", [])):
                return zone.get("name")
        return None
```

- [ ] **Step 4: Add the new stats to the heartbeat payload**

In `CameraWorker.send_heartbeat`, in the `metrics` dict, after `"yolo_fastpath_events": self.yolo_fastpath_events,` add:

```python
            "pose_calls": self.pose_calls,
            "sequence_events": self.sequence_events,
```

- [ ] **Step 5: Obtain the pose model file**

Try: `cd worker && .venv/bin/pip install ultralytics --quiet && .venv/bin/python3 -c "from ultralytics import YOLO; YOLO('yolov8n-pose.pt').export(format='onnx')" && mv yolov8n-pose.onnx models/yolov8n-pose.onnx && .venv/bin/pip uninstall -y ultralytics torch torchvision --quiet`

This downloads the standard `yolov8n-pose.pt` checkpoint, exports it to ONNX, moves it into place, then removes `ultralytics`/`torch` again (only needed for the one-time export; the running worker must stay PyTorch-free per Global Constraints).

If this fails in a sandboxed/offline environment: leave the file out. `PoseDetector.available` will be `False`, cameras with a `step_sequence` configured will simply skip this stage (verified in Task 3 Step 2), and the model can be dropped into `worker/models/yolov8n-pose.onnx` later without any code change. Note this explicitly in the commit message either way.

- [ ] **Step 6: Update `worker/CLAUDE.md`**

In the "YOLO Local Detection Gate" section, add a new subsection right after it:

```markdown
### Pose-Based Step-Sequence Tracking
- For cameras with a non-empty `step_sequence` configured, a local YOLOv8-pose ONNX model (`pose_detector.py`, CPU-only via onnxruntime) runs after the YOLO gate stage, independent of its drop/emit/escalate decision
- Detected people are tracked frame-to-frame with a greedy IoU tracker (`person_tracker.py`, no re-identification — a lost track starts a fresh sequence on reappearance)
- Each tracked person's (zone, pose label) is checked against the camera's ordered `step_sequence` by `sequence_engine.py`; skipping ahead, stalling past a step's `max_seconds`, or completing all steps emits a `step_skipped` / `step_timeout` / `sequence_completed` event directly — no Gemini call
- Pose labels are geometric heuristics on 17 COCO keypoints: `standing`, `bending`, `crouching`, `sitting`, `reaching`, `unknown` (see `classify_pose` in `pose_detector.py`)
- Model file lives at `models/yolov8n-pose.onnx` (path configurable via `POSE_MODEL_PATH`); if missing or fails to load, `PoseDetector.available` is `False` and the stage is skipped entirely — fail-soft, never crashes the worker
- To (re)generate the model: `pip install ultralytics && python3 -c "from ultralytics import YOLO; YOLO('yolov8n-pose.pt').export(format='onnx')"`, then move the resulting `yolov8n-pose.onnx` into `models/`
```

- [ ] **Step 7: Verify the worker still imports cleanly**

Run: `cd worker && .venv/bin/python3 -c "import camera_worker"`
Expected: no output, exit code 0.

- [ ] **Step 8: Commit**

```bash
git add worker/camera_worker.py worker/CLAUDE.md
git add worker/models/yolov8n-pose.onnx 2>/dev/null || true
git commit -m "Wire pose/tracker/sequence-engine stage into camera_worker pipeline"
```

---

### Task 7: Backend — `step_sequence` column, schema, and validation

**Files:**
- Create: `backend/alembic/versions/<new_revision>_camera_step_sequence.py`
- Modify: `backend/app/models/camera.py`
- Modify: `backend/app/schemas/camera.py`
- Modify: `backend/app/api/cameras.py`

**Interfaces:**
- Produces: `Camera.step_sequence` DB column; `CreateCameraRequest.step_sequence`, `UpdateCameraRequest.step_sequence`, `CameraResponse.step_sequence` — consumed by the frontend (Task 8).

- [ ] **Step 1: Add the migration**

Create `backend/alembic/versions/a3f7c1d9e6b2_camera_step_sequence.py`:

```python
"""camera_step_sequence

Revision ID: a3f7c1d9e6b2
Revises: e7b3f9a2c5d1
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f7c1d9e6b2"
down_revision: Union[str, None] = "e7b3f9a2c5d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "step_sequence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "step_sequence")
```

- [ ] **Step 2: Add the column to the `Camera` model**

In `backend/app/models/camera.py`, add right after `detection_zones: Mapped[list] = mapped_column(JSONB, default=list)`:

```python
    step_sequence: Mapped[list] = mapped_column(JSONB, default=list)
```

- [ ] **Step 3: Run the migration**

Run: `cd backend && uv run alembic upgrade head`
Expected: migration `a3f7c1d9e6b2` applies with no errors.

- [ ] **Step 4: Add `step_sequence` to the Pydantic schemas**

In `backend/app/schemas/camera.py`, add to `CreateCameraRequest` right after `detection_zones: list[dict] = []`:

```python
    step_sequence: list[dict] = []
```

Add to `UpdateCameraRequest` right after `detection_zones: list[dict] | None = None`:

```python
    step_sequence: list[dict] | None = None
```

Add to `CameraResponse` right after `detection_zones: list[dict]`:

```python
    step_sequence: list[dict]
```

- [ ] **Step 5: Add cross-field validation and wire it into both routes**

In `backend/app/api/cameras.py`, add this validation function near the top of the file (after the existing imports, before the router/route definitions):

```python
VALID_POSE_LABELS = {"standing", "bending", "crouching", "sitting", "reaching", None}


def _validate_step_sequence(step_sequence: list, detection_zones: list) -> None:
    if not step_sequence:
        return
    zone_names = {z.get("name") for z in detection_zones}
    for i, step in enumerate(step_sequence):
        if not step.get("name"):
            raise HTTPException(status_code=400, detail=f"step_sequence[{i}] is missing a name")
        zone = step.get("zone")
        if zone not in zone_names:
            raise HTTPException(
                status_code=400,
                detail=f"step_sequence[{i}] references unknown zone '{zone}' — must match an existing detection_zones name",
            )
        if step.get("pose") not in VALID_POSE_LABELS:
            raise HTTPException(
                status_code=400,
                detail=f"step_sequence[{i}] has invalid pose '{step.get('pose')}' — must be one of {sorted(p for p in VALID_POSE_LABELS if p)} or null",
            )
```

In `create_camera`, call it right before `camera = Camera(`:

```python
    _validate_step_sequence(body.step_sequence, body.detection_zones)
```

And add `step_sequence=body.step_sequence,` to the `Camera(...)` constructor call, right after `detection_zones=body.detection_zones,`.

In `update_camera`, replace:

```python
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(camera, field, value)
```

with:

```python
    updates = body.model_dump(exclude_unset=True)
    effective_zones = updates.get("detection_zones", camera.detection_zones)
    effective_sequence = updates.get("step_sequence", camera.step_sequence)
    _validate_step_sequence(effective_sequence, effective_zones)

    for field, value in updates.items():
        setattr(camera, field, value)
```

- [ ] **Step 6: Verify backend imports cleanly and validation works**

Run: `cd backend && uv run python3 -c "from app.main import app; print('ok')"`
Expected: `ok`

Run: `cd backend && uv run python3 -c "
from app.api.cameras import _validate_step_sequence
from fastapi import HTTPException

zones = [{'name': 'Shelf', 'points': [[0,0],[1,0],[1,1],[0,1]]}]
_validate_step_sequence([], zones)  # no-op, should not raise
_validate_step_sequence([{'name': 'a', 'zone': 'Shelf', 'pose': 'reaching'}], zones)  # valid, should not raise
try:
    _validate_step_sequence([{'name': 'a', 'zone': 'Nope', 'pose': None}], zones)
    print('FAIL: should have raised')
except HTTPException as e:
    print('raised as expected:', e.status_code)
try:
    _validate_step_sequence([{'name': 'a', 'zone': 'Shelf', 'pose': 'flying'}], zones)
    print('FAIL: should have raised')
except HTTPException as e:
    print('raised as expected:', e.status_code)
"`
Expected output (2 lines): `raised as expected: 400`, `raised as expected: 400`

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/a3f7c1d9e6b2_camera_step_sequence.py backend/app/models/camera.py backend/app/schemas/camera.py backend/app/api/cameras.py
git commit -m "Add step_sequence column, schema fields, and zone/pose validation for cameras"
```

---

### Task 8: Frontend — `SequenceEditor` component and camera-detail page wiring

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/components/cameras/SequenceEditor.tsx`
- Modify: `frontend/src/app/cameras/[id]/page.tsx`

**Interfaces:**
- Consumes: `Camera`, `DetectionZone` from `frontend/src/types/index.ts`; `api.updateCamera` from `frontend/src/lib/api.ts` (existing, untyped-payload `Partial<Camera>` — no signature change needed).
- Produces: `StepSequenceStep` type; `SequenceEditor` component mounted alongside `ZonesEditor` on the camera detail page.

- [ ] **Step 1: Add `step_sequence` and `StepSequenceStep` to types**

In `frontend/src/types/index.ts`, add to the `Camera` interface right after `detection_zones: DetectionZone[];`:

```ts
  step_sequence: StepSequenceStep[];
```

Add a new interface right after `DetectionZone`:

```ts
export interface StepSequenceStep {
  name: string;
  zone: string;
  pose: "standing" | "bending" | "crouching" | "sitting" | "reaching" | null;
  max_seconds: number | null;
}
```

- [ ] **Step 2: Write `frontend/src/components/cameras/SequenceEditor.tsx`**

```tsx
"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Camera, StepSequenceStep } from "@/types";

const POSE_OPTIONS: { value: StepSequenceStep["pose"]; label: string }[] = [
  { value: null, label: "any" },
  { value: "standing", label: "standing" },
  { value: "bending", label: "bending" },
  { value: "crouching", label: "crouching" },
  { value: "sitting", label: "sitting" },
  { value: "reaching", label: "reaching" },
];

export function SequenceEditor({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const queryClient = useQueryClient();
  const zoneNames = camera.detection_zones.map((z) => z.name);

  const [steps, setSteps] = useState<StepSequenceStep[]>(
    () => (camera.step_sequence || []).map((s) => ({ ...s }))
  );
  const [saveError, setSaveError] = useState<string | null>(null);

  const dirty = useMemo(
    () => JSON.stringify(steps) !== JSON.stringify(camera.step_sequence || []),
    [steps, camera.step_sequence]
  );

  const validationError = useMemo(() => {
    if (steps.length === 0) return null;
    for (const [i, step] of steps.entries()) {
      if (!step.name.trim()) return `Step ${i + 1} needs a name.`;
      if (!zoneNames.includes(step.zone)) return `Step ${i + 1}: zone "${step.zone}" doesn't exist. Draw it in Edit Zones first.`;
    }
    return null;
  }, [steps, zoneNames]);

  const saveMutation = useMutation({
    mutationFn: () => api.updateCamera(camera.id, { step_sequence: steps }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      onClose();
    },
    onError: (err: Error) => setSaveError(err.message),
  });

  const addStep = () => {
    setSteps([...steps, { name: `Step ${steps.length + 1}`, zone: zoneNames[0] || "", pose: null, max_seconds: null }]);
  };

  const removeStep = (index: number) => {
    setSteps(steps.filter((_, i) => i !== index));
  };

  const moveStep = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    setSteps(next);
  };

  const updateStep = (index: number, patch: Partial<StepSequenceStep>) => {
    setSteps(steps.map((s, i) => (i === index ? { ...s, ...patch } : s)));
  };

  const onBackdropClick = () => {
    if (dirty) {
      if (window.confirm("Discard unsaved sequence changes?")) onClose();
    } else {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0,0,0,0.7)" }}
      onClick={onBackdropClick}
    >
      <div
        className="bg-[#111111] border border-[#2A2A2A] rounded-lg w-[95vw] max-w-[800px] max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#2A2A2A]">
          <h2 className="text-sm font-medium">Step Sequence — {camera.name}</h2>
          <button onClick={onBackdropClick} className="text-[#A3A3A3] hover:text-[#F5F5F5] text-lg leading-none" aria-label="Close">
            ×
          </button>
        </div>

        <div className="p-4 space-y-3 overflow-auto">
          {zoneNames.length === 0 && (
            <div className="text-xs text-[#666666]">No zones defined yet — draw zones first via "Edit Zones", then steps can reference them.</div>
          )}

          {steps.map((step, i) => (
            <div key={i} className="bg-[#1A1A1A] border border-[#2A2A2A] rounded p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-[#666666] w-5">{i + 1}.</span>
                <input
                  value={step.name}
                  onChange={(e) => updateStep(i, { name: e.target.value })}
                  placeholder="Step name"
                  className="flex-1 px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                />
                <button onClick={() => moveStep(i, -1)} disabled={i === 0} className="text-[#A3A3A3] hover:text-[#F5F5F5] disabled:opacity-30 text-xs px-1">↑</button>
                <button onClick={() => moveStep(i, 1)} disabled={i === steps.length - 1} className="text-[#A3A3A3] hover:text-[#F5F5F5] disabled:opacity-30 text-xs px-1">↓</button>
                <button onClick={() => removeStep(i)} className="text-[#A3A3A3] hover:text-red-400 text-xs px-1">Delete</button>
              </div>
              <div className="flex flex-wrap gap-2">
                <select
                  value={step.zone}
                  onChange={(e) => updateStep(i, { zone: e.target.value })}
                  className="px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                >
                  {zoneNames.length === 0 && <option value="">no zones</option>}
                  {zoneNames.map((z) => (
                    <option key={z} value={z}>{z}</option>
                  ))}
                </select>
                <select
                  value={step.pose ?? ""}
                  onChange={(e) => updateStep(i, { pose: (e.target.value || null) as StepSequenceStep["pose"] })}
                  className="px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                >
                  {POSE_OPTIONS.map((opt) => (
                    <option key={opt.label} value={opt.value ?? ""}>{opt.label}</option>
                  ))}
                </select>
                <input
                  type="number"
                  min={1}
                  value={step.max_seconds ?? ""}
                  onChange={(e) => updateStep(i, { max_seconds: e.target.value ? Number(e.target.value) : null })}
                  placeholder="max seconds (optional)"
                  className="w-40 px-2 py-1 bg-[#1F1F1F] border border-[#2A2A2A] rounded text-xs focus:border-[#1E90FF] outline-none"
                />
              </div>
            </div>
          ))}

          <button
            onClick={addStep}
            className="px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded text-xs hover:text-[#F5F5F5] transition-colors"
          >
            + Add Step
          </button>

          {validationError && <div className="text-xs text-red-400">{validationError}</div>}
          {saveError && <div className="text-xs text-red-400">Save failed: {saveError}</div>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={() => {
                setSaveError(null);
                saveMutation.mutate();
              }}
              disabled={!dirty || !!validationError || saveMutation.isPending}
              className="px-3 py-1.5 bg-[#1E90FF] text-white rounded text-xs hover:bg-[#3BA0FF] transition-colors disabled:opacity-50"
            >
              {saveMutation.isPending ? "Saving..." : "Save Sequence"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Mount `SequenceEditor` in the camera detail page**

In `frontend/src/app/cameras/[id]/page.tsx`:

Add to imports, after `import { ZonesEditor } from "@/components/cameras/ZonesEditor";`:

```tsx
import { SequenceEditor } from "@/components/cameras/SequenceEditor";
import { ListOrdered } from "lucide-react";
```

Add state, after `const [showZones, setShowZones] = useState(false);`:

```tsx
  const [showSequence, setShowSequence] = useState(false);
```

Add a header button, right after the closing `</button>` of the existing "Edit Zones" button (before the "Delete" button):

```tsx
            <button
              onClick={() => setShowSequence(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1A1A1A] text-[#A3A3A3] border border-[#2A2A2A] rounded-md text-xs hover:text-[#F5F5F5] hover:border-[#1E90FF] transition-colors"
            >
              <ListOrdered size={12} /> Edit Sequence
            </button>
```

Add the conditional render, right after the existing block `{showZones && (\n        <ZonesEditor camera={camera} onClose={() => setShowZones(false)} />\n      )}`:

```tsx
      {showSequence && (
        <SequenceEditor camera={camera} onClose={() => setShowSequence(false)} />
      )}
```

- [ ] **Step 4: Verify the frontend builds with no type errors**

Run: `cd frontend && npm run build`
Expected: build succeeds, zero TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/components/cameras/SequenceEditor.tsx "frontend/src/app/cameras/[id]/page.tsx"
git commit -m "Add SequenceEditor UI for configuring per-camera step sequences"
```

---

### Task 9: Self-review

Per user preference, this replaces a formal test suite pass with a direct review of the changes for correctness, simplicity, SOLID boundaries, and end-to-end flow.

- [ ] **Step 1: Re-read the full diff**

Run: `git log --oneline -9` (the 9 commits from Tasks 1–8 above) and `git diff <task-1-base-commit> -- worker/ backend/ frontend/`

Check for:
- **Correctness:** re-trace `sequence_engine.advance()` against the design's four branches (match-and-advance, skip-ahead, timeout, no-op) — confirm `state.completed` is set on every terminal branch (skip/timeout/complete) and never on the silent no-op branch.
- **Correctness:** confirm `camera_worker.py`'s pose/sequence block never calls `continue` — it must fall through to the existing YOLO/Gemini logic below it unconditionally, since sequence tracking is independent of the person/vehicle/intrusion event flow.
- **Simplicity:** confirm `pose_detector.py` and `yolo_detector.py` remain independent siblings (deliberate small duplication of `_letterbox`/`_preprocess`, not a shared base class) — this was a scoping decision, not an oversight; don't "fix" it into a refactor mid-review.
- **SOLID/boundaries:** confirm `person_tracker.py` has zero import of `sequence_engine.py` (the `sequence_state_factory` indirection from Task 4's note) — if this import snuck in, the decoupling design was violated and should be fixed.
- **Flow:** confirm `self.pose_calls` increments once per frame that reaches the pose stage (not per detected person), and that `_zone_for_bbox` correctly reuses `point_in_polygon` from `yolo_detector.py` rather than reimplementing it.
- **Backend:** confirm `_validate_step_sequence` is actually invoked in both `create_camera` and `update_camera` (not just defined), and that `update_camera`'s validation correctly falls back to the camera's *existing* `detection_zones`/`step_sequence` for fields absent from a partial PATCH.

- [ ] **Step 2: Fix anything found inline, re-run the Task 6 Step 7 / Task 7 Step 6 / Task 8 Step 4 verification commands, and commit any fixes**

```bash
git add -A worker/ backend/ frontend/
git commit -m "Self-review fixes for pose-sequence tracking feature"
```
(Skip this commit if nothing needed fixing.)
