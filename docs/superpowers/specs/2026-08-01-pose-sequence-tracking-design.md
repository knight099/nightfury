# Pose-Based Step-Sequence Tracking — Design

## Problem

Nightwatch can currently detect discrete events (person, vehicle, animal, intrusion) but has no way to reason about *what a person is doing over time* within a scene — e.g. in a retail checkout, "did they pay before leaving?"; in an airport lane, "did they complete the required steps in order?". This requires per-person pose over time, not just a single-frame bounding box.

## Goal

Add a generic, per-camera-configurable **step-sequence tracking** layer:
1. Detect person pose (not just bbox) per frame via a local model.
2. Track each person across frames (multi-person).
3. Classify each tracked person's pose into a coarse label (standing, bending, crouching, sitting, reaching, unknown).
4. Match tracked person's (zone, pose) against a per-camera ordered list of expected steps.
5. Emit an event when a step is skipped, a step stalls past its timeout, or a sequence completes.

This is scenario-agnostic — the same engine configured differently supports retail checkout compliance, airport lane procedures, or any other "expected path through zones + poses" use case.

## Non-goals

- Training a custom action-classification model — pose labels come from geometric heuristics on keypoints, not ML classification.
- Cross-session re-identification — if a track is lost (occluded/left frame > TTL) and the person reappears, they start a new sequence from scratch.
- Live pose preview in the frontend sequence editor.
- Any change to how YOLO detection (person/vehicle/animal/intrusion gate) itself works — this is an additive stage.

## Prerequisite

This depends on the existing, already-designed-but-unimplemented plan `docs/superpowers/plans/2026-07-29-yolo-gemini-cost-reduction.md` (adds `worker/yolo_detector.py`, wires it into `camera_worker.py`). That plan should be implemented first — this design follows the same conventions (ONNX loading pattern, `BoundingBox` model, fail-soft style, config block style) even though the pose model here does its own independent person detection and does not technically call into `yolo_detector.py`.

## Architecture

```
ingest → ring buffer → motion detect → frame sampler → YOLO detect (existing plan) → pose detect → tracker → sequence engine → decision → Gemini (conditional) → package
```

The pose/tracking/sequence stage only runs for cameras that have a non-empty `step_sequence` configured — zero overhead for cameras without one. It runs on frames that already passed the frame sampler, same as YOLO detection (no change to sampling rate).

New worker modules: `worker/pose_detector.py`, `worker/person_tracker.py`, `worker/sequence_engine.py`.

## Pose Model & Keypoint Classification

**Model:** `yolov8n-pose.onnx` (COCO-17 keypoints), same CPU-only `onnxruntime` runtime as the YOLO detection plan — one inference pass yields both person bbox and keypoints, no separate detector needed. Committed as `worker/models/yolov8n-pose.onnx` (~13MB).

```python
@dataclass
class PersonPose:
    bbox: BoundingBox
    keypoints: list[tuple[float, float, float]]  # (x, y, confidence) x 17, COCO order
    label: str  # "standing" | "bending" | "crouching" | "sitting" | "reaching" | "unknown"

class PoseDetector:
    def __init__(self):
        # onnxruntime.InferenceSession over config.pose_model_path
        ...

    def detect(self, frame: np.ndarray) -> list[PersonPose]:
        # letterbox resize to model input size, run inference,
        # standard YOLOv8-pose postprocessing (confidence filter + NMS),
        # rescale bbox + keypoints back to original frame size,
        # classify() each detection's keypoints into a label
        ...
```

**Heuristic classification** (`classify_pose(keypoints) -> str`), geometric rules on joint angles/ratios computed from keypoints whose confidence is >= `pose_keypoint_confidence` (default `0.3`); keypoints below threshold are excluded from angle math, and a rule that lacks enough visible keypoints simply doesn't fire:

- **standing**: hip-knee-ankle angle >160° on both legs (roughly straight).
- **bending**: torso line (shoulder midpoint → hip midpoint) tilted >45° from vertical, legs still roughly straight.
- **crouching**: hip-knee-ankle angle <120°, hips near knee height.
- **sitting**: hip-knee angle ≈90°, hip height roughly constant over recent frames (approximate — no ground-contact signal available).
- **reaching**: a wrist keypoint significantly above shoulder height, or extended beyond hip-width from the torso center.
- **unknown**: insufficient visible keypoints for any rule to fire. Never treated as a hard failure — the sequence engine treats `unknown` as "no pose evidence this frame," not a step match or a violation.

## Multi-Person Tracker

Lightweight, no new dependency (no scipy/Hungarian matching) — greedy IoU matching, in the spirit of a minimal SORT without a motion model:

```python
@dataclass
class Track:
    track_id: int
    last_bbox: BoundingBox
    last_seen_frame: int
    sequence_state: SequenceState

class PersonTracker:
    def update(self, detections: list[PersonPose], frame_idx: int) -> list[TrackedPerson]:
        # 1. Match new detections to existing tracks by max IoU (greedy, threshold track_iou_threshold)
        # 2. Unmatched detections -> new Track (fresh SequenceState, step index 0)
        # 3. Unmatched existing tracks -> increment missed-frame count
        # 4. Tracks with no match for > track_ttl_seconds -> dropped, sequence state discarded
```

Track state lives in memory on the `CameraWorker` instance only — not persisted, not shared across restarts or across cameras.

## Sequence Config Schema & Engine

**Config shape** — new `step_sequence: list[dict]` field on camera config, parallel to the existing `detection_zones`:

```python
step_sequence: list[dict] = [
    {"name": "pick_item",     "zone": "Shelf",   "pose": "reaching", "max_seconds": 30},
    {"name": "go_to_counter", "zone": "Counter", "pose": "standing", "max_seconds": 60},
    {"name": "pay",           "zone": "Counter", "pose": "reaching", "max_seconds": 45},
    {"name": "exit",          "zone": "Exit",    "pose": None,       "max_seconds": None},
]
```

- `zone` must match an existing `detection_zones[].name`. A step's condition is met when the tracked person's bbox center is inside that zone **and** (if `pose` is set, non-null) their current pose label matches.
- `max_seconds`: how long a track may remain at/before this step before it's considered stalled; `null` means no timeout (e.g. a final step with no further progression to wait for).
- Steps are ordered and must be completed in order per track. Reaching a *later* step's zone before completing all earlier required steps is itself the violation signal ("skipped ahead").

**Engine** (`worker/sequence_engine.py`):

```python
@dataclass
class SequenceState:
    current_step_index: int = 0
    step_entered_at: float = field(default_factory=time.monotonic)
    completed: bool = False

def advance(state, step_sequence, tracked_person, now) -> SequenceEvent | None:
    # if tracked_person's zone+pose matches step_sequence[current_step_index]:
    #     advance index, reset step_entered_at
    #     if now at last step index -> mark completed, return "sequence_completed"
    # elif tracked_person's zone matches a LATER step's zone (skip-ahead detected):
    #     return "step_skipped" (names the step that was skipped)
    # elif now - state.step_entered_at > step_sequence[current_step_index].max_seconds:
    #     return "step_timeout"
    # else:
    #     return None (no event yet)
```

Each `SequenceState` fires `step_skipped` / `step_timeout` / `sequence_completed` at most once per occurrence (state transitions to a terminal/reset condition after firing, to avoid repeat alerts every frame while a track lingers).

## Event Emission

New `event_type` values flow through the existing `DetectedEvent` → alert pipeline exactly like YOLO fast-path events today — no Gemini call, no downstream schema change. `bounding_boxes` populated from the track's last known bbox.

| event_type | severity | description template |
|---|---|---|
| `step_skipped` | `medium` | `"Skipped step '{step_name}' — reached '{zone}' early"` |
| `step_timeout` | `medium` | `"Stalled at step '{step_name}' for over {max_seconds}s"` |
| `sequence_completed` | `low` | `"Completed sequence: {step_names joined by ' → '}"` |

## Config Additions (`worker/config.py`)

```python
# Pose detection + step-sequence tracking
pose_enabled: bool = True
pose_model_path: str = "models/yolov8n-pose.onnx"
pose_keypoint_confidence: float = 0.3
track_iou_threshold: float = 0.3
track_ttl_seconds: float = 5.0
```

`step_sequence` itself is per-camera config (like `detection_zones`), not global.

## Fail-Soft Behavior

Same pattern as the YOLO detection plan:
- If `yolov8n-pose.onnx` fails to load at `PoseDetector.__init__` (missing file, bad weights, onnxruntime import error): log one ERROR, set `self.available = False`. `CameraWorker` checks this once at startup — if unavailable, cameras with a `step_sequence` configured simply skip this stage entirely (existing YOLO gate + Gemini path for those frames is unaffected; no crash, no partial state).
- If inference throws mid-run on a specific frame: log a WARNING (not spamming), skip pose for that frame only. The tracker treats it as a missed-frame for all active tracks (counts toward TTL), not a hard reset of sequence state.

## Backend / DB

- New `step_sequence: JSONB` column on the `cameras` table (Alembic migration, default `[]`).
- Extend the existing camera-update Pydantic schema and endpoint to accept/return `step_sequence` — same pattern as `detection_zones`, no new route.
- Validation on write: every `step_sequence[].zone` must match an existing `detection_zones[].name` on that camera; `pose` must be one of the 6 fixed labels or `null`.

## Frontend

New `SequenceEditor.tsx` component, sibling to `ZonesEditor.tsx`, added to `/cameras/[id]` (new section — zones must already exist, since steps reference zone names):

- List view of steps in order: name (text input), zone (dropdown sourced from `camera.detection_zones`), pose (dropdown: the 6 fixed labels + "any"), max_seconds (number input, optional).
- Add / remove / reorder steps (reuse existing list-editing UI patterns from `ZonesEditor.tsx` / alert-rules UI rather than adding a new drag-and-drop library).
- Save → same camera-update API call pattern as zones, sending `step_sequence`.
- Client-side validation before save mirrors backend validation (zone exists, pose is a valid label, at least 1 step).
- No live pose preview in this UI (would require streaming worker-side inference to the frontend — out of scope).

## Testing

Per standing preference: implement directly, self-review for correctness/simplicity/SOLID/flow rather than TDD ceremony. Targeted unit tests against pure logic, no real model inference:

- `test_pose_detector.py`: `classify_pose()` against synthetic keypoint arrays for each label (straight-leg → standing, bent-torso → bending, low-hip-height → crouching, etc.) and the `unknown` fallback on sparse/low-confidence keypoints.
- `test_person_tracker.py`: IoU matching preserves track ID across frames; new-track creation on unmatched detections; TTL-based drop of stale tracks.
- `test_sequence_engine.py`: `advance()` branch coverage — in-order progression, skip-ahead violation, timeout violation, full completion, and "fires once" behavior (no repeat alerts while a track lingers in a terminal state).
- Backend: extend existing camera-update tests to cover `step_sequence` validation (zone cross-check, pose label validation).

## Rollout

- `pose_enabled` defaults to `True` but is a single config flag, independently toggleable per-deployment from `yolo_enabled`.
- Zero impact on cameras without a `step_sequence` configured — the entire stage is skipped for them.
- Depends on the YOLO detection plan (`2026-07-29-yolo-gemini-cost-reduction`) being implemented first; implementation order: (1) that plan, (2) this plan.
