# Supervision-Based Tracking & Zone Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pipeline's hand-rolled, mutually-inconsistent
tracking/zone implementations (a greedy-IoU person tracker, a second ad
hoc IoU+proximity tracker inside footfall counting, and a manual
ray-casting polygon test) with source vendored from
[`roboflow/supervision`](https://github.com/roboflow/supervision) — its
`ByteTrack`, `LineZone`, `PolygonZone`, and `DetectionsSmoother` — without
changing the pipeline's architecture, model files, CPU-only ONNX
inference path, or adding `supervision` (and its `opencv-python`/
`matplotlib`/`pandas` transitive footprint) as an installed dependency.

**Architecture:** `supervision` is a data/algorithm library, not an
inference engine — it does not replace `yolo_detector.py`'s ONNX runtime
session or `pose_detector.py`'s pose model. It replaces what happens
*after* inference: the raw NMS'd boxes get wrapped once into a trimmed,
vendored `Detections` type (Task 2), and everything downstream —
tracking, zone membership, line-crossing counts — reads and writes that
one shared type instead of three divergent hand-rolled ones. Two
independent `ByteTrack` instances remain (pose/step-sequence tracking and
footfall tracking consume two different detection sources today — the
pose model's own boxes vs. the general YOLO model's person boxes — and
this refactor does not merge those detection paths, only the tracking
algorithm each uses).

**Why vendor instead of `pip install supervision`:** confirmed against the
real upstream source (not just the docs) that the useful surface for this
pipeline is a small, self-contained fraction of the package. `Detections`
is ~250 relevant lines out of an 87KB/~2500-line file — the rest is
`from_ultralytics`/`from_transformers`/`from_detectron2`/etc. classmethods
for model integrations this pipeline never uses (it runs raw ONNX, not
any of those libraries). `ByteTrack` is fully self-contained on
`numpy`+`scipy` alone — no `cv2`, no `PIL`. `LineZone`'s actual counting
logic needs no `cv2` at all once its companion `LineZoneAnnotator` drawing
class (a separate class in the same file) is left out. The trimmed
vendor's real dependency list is `numpy` + `scipy` + the
`opencv-python-headless` already pinned (needed by `PolygonZone` only) —
nothing else. A plain `pip install supervision` pulls in `opencv-python`
(conflicts with the headless build this ARM edge box needs),
`matplotlib` (used only by unrelated palette-visualization helpers), and
`pyyaml`/`defusedxml`/`pyDeprecate`/`pillow`/`tqdm` (dataset
import/export and progress-bar features this pipeline never touches) for
zero additional benefit.

**Tech Stack:** Python 3.11+, `numpy` + `scipy` (new — everything else
this plan adds already has zero net-new dependencies beyond those two),
existing `onnxruntime` CPU inference, `opencv-python-headless` (already
pinned). No PyTorch, no GPU dependency, confirmed ARM-safe.

**Spec:** No separate spec document. This plan is the spec — it was
scoped directly against the current `agent/pipeline/` source, and against
the real `roboflow/supervision` source at commit-pinned upstream file
paths (recorded per-module in Task 1), during planning.

---

## Findings That Change The Scope

**1. `worker/` is the cloud-VM fallback path — deliberately kept, but not
where the live system's cameras run.** `worker/`/`relay/` remain a real,
supported fallback (direct-connect cameras, or edge boxes that can't run
the pipeline sidecar) — they are not decommissioned. But every camera in
the actual running deployment goes through the self-contained edge agent
(`agent/` supervising `agent/pipeline/` in-process), direct to backend,
with no relay hop. `worker/` has also already drifted from
`agent/pipeline/` in the code — missing `footfall.py`, `capacity.py`, and
`scene_analyzer.py` entirely — consistent with it being the dormant
fallback rather than the actively-developed path. This plan touches
**`agent/pipeline/` only**, since that's what the live system runs;
porting the same refactor to `worker/` is a legitimate follow-up if the
fallback path is ever exercised for real, just not part of this plan.

**2. `pip install supervision` would conflict with the pinned
`opencv-python-headless` and bloat the ARM edge image.** `supervision`
declares `opencv-python` as a hard dependency; both packages install into
the same `cv2` import namespace, and `opencv-python-headless` is pinned
specifically because this runs on a headless Pi/NAS box — pulling in the
GUI-linked build is undesirable even where it "works". It also declares
`matplotlib` (used only by unused palette-visualization helpers) and
several dataset/progress-bar deps this pipeline never touches. This is
the reason this plan vendors trimmed source instead of installing the
package — see the Goal/Architecture sections above for the concrete size
comparison.

**3. Exact upstream signatures were verified against real source before
writing this plan, not guessed.** `ByteTrack`'s constructor
(`track_activation_threshold`, `lost_track_buffer`,
`minimum_matching_threshold`, `frame_rate`, `minimum_consecutive_frames`),
`LineZone.trigger()`'s behavior (confirmed: `in_count`/`out_count` are
monotonic running totals via an internal `Counter`, never reset — so
`footfall.py`'s `drain()` needs its own snapshot-and-subtract, there is no
native delta method), and `LineZone`'s default `triggering_anchors` (all
four box corners, **not** bottom-center — this pipeline's existing
bottom-center "feet cross the line" convention must be passed explicitly)
were all read from the actual file bodies, recorded per-task below with
the exact upstream path and line range vendored from.

**4. `BoxAnnotator`/`LabelAnnotator` were evaluated and dropped.**
`BoxAnnotator` alone is genuinely small (~30 lines), but `LabelAnnotator`
inherits a ~110-line base class plus text-wrapping/smart-positioning
helpers — once trimmed to what this pipeline needs, it is not meaningfully
smaller than the ~20 lines `event_packager.py`'s `_annotate_frame` already
has. There is nothing to gain here; `event_packager.py` is **not
modified** by this plan.

**5. `DetectionsSmoother` is a real, cheap addition this plan adds that
wasn't in the original scope.** Confirmed from source: it's a ~110-line,
pure-`numpy` moving average over each `tracker_id`'s recent boxes, with
zero added inference cost. It directly strengthens Tasks 3–5's payoff —
steadier boxes feeding `LineZone`/`PolygonZone` reduce exactly the
jitter-driven false-crossing class `footfall.py`'s own docstring already
names as its dominant error source. Added as Task 6.

**6. `InferenceSlicer` (tiled inference for small/distant objects) is a
real capability gap but is deliberately NOT part of this plan.** It's a
generic wrapper that re-runs *your own* inference callback once per tile;
on a 1920×1080 frame sliced into overlapping 640×640 tiles that's a 4–6×
multiplier on YOLO cost for every analyzed frame it's used on — directly
at odds with the fleet's existing self-sizing capacity model, which
degrades sampling rate under CPU load. If small/distant-object detection
on wide-angle cameras becomes a real product need, it deserves its own
plan with an explicit per-camera opt-in and a measured CPU cost budget,
not a default-on addition here.

---

## Global Constraints

- **No PyTorch, no GPU dependency, anywhere in this pipeline.** It runs on
  customer-owned edge hardware (Pi / NAS / on-prem box) via CPU-only
  `onnxruntime`. `supervision` itself has no torch dependency; verify
  nothing this plan adds changes that.
- **Never send full video off the box; only ONNX inference and
  `supervision` post-processing run locally.** This plan touches
  post-inference logic only — no new network calls, no new cloud
  dependency.
- **Fail-soft, matching the existing pattern.** `YoloDetector` and
  `PoseDetector` already treat a missing/broken model as "feature
  disabled, never crash the worker" (`self.available = False`). Every
  `supervision`-backed component this plan adds must fail the same way:
  an import or init error disables that stage, logs once, and the camera
  keeps running everything else.
- **No TDD.** Per standing user preference, implement directly, then
  self-review each task for correctness, simplicity, and whether the
  public API of the module being replaced stayed the same shape for its
  caller in `camera_worker.py`. Do not write pytest files unless a task
  explicitly says to.
- **Verification per task:** `cd agent/pipeline && python3 -c "import camera_worker"` must import cleanly (catches wiring breaks without needing a live camera), plus the task's own explicit checks.
- **Commits:** one per task, at the end. Do not commit mid-task.

---

## File Structure

**This plan vendors, not `pip install`s.** `supervision`'s useful surface for
this pipeline — `Detections`, `ByteTrack`, `LineZone`, `PolygonZone`,
`DetectionsSmoother` — is a small, self-contained fraction of the package
(confirmed against the real upstream source: `Detections` is ~250 relevant
lines out of an 87KB/2500-line file, the rest being `from_ultralytics`/
`from_transformers`/etc. classmethods for model integrations this pipeline
never uses; `ByteTrack` is fully self-contained on `numpy`+`scipy` alone;
`LineZone` needs no `cv2` at all once its companion `LineZoneAnnotator`
class is dropped). Vendoring that trimmed set needs only `numpy`, `scipy`,
and the `opencv-python-headless` already pinned — no `matplotlib`, `PIL`,
`pyyaml`, `defusedxml`, or `pyDeprecate`, all of which a plain `pip install
supervision` would otherwise pull in for features this plan never touches.

- `agent/pipeline/sv_vendor/` — CREATE: the trimmed, vendored modules.
  - `sv_vendor/geometry.py` — `Point`, `Vector`, `Position`, `Rect` (stdlib only) (Task 1).
  - `sv_vendor/detections.py` — trimmed `Detections` dataclass (Task 1).
  - `sv_vendor/iou.py` — `box_iou_batch` + `OverlapMetric` (Task 1).
  - `sv_vendor/byte_tracker/` — `kalman_filter.py`, `matching.py`, `single_object_track.py`, `utils.py`, `core.py` (the `ByteTrack` class), vendored near-verbatim (fully self-contained already) (Task 1).
  - `sv_vendor/cross_product.py` — vectorized cross-product helper `LineZone` needs (Task 4).
  - `sv_vendor/line_zone.py` — `LineZone` only, not `LineZoneAnnotator` (Task 4).
  - `sv_vendor/boxes.py` — `clip_boxes` (Task 5).
  - `sv_vendor/converters.py` — `polygon_to_mask` (Task 5).
  - `sv_vendor/polygon_zone.py` — `PolygonZone` only, not `PolygonZoneAnnotator` (Task 5).
  - `sv_vendor/smoother.py` — `DetectionsSmoother` (Task 6).
  - `sv_vendor/__init__.py` — the package's public API, extended incrementally by each task (Task 1, extended in Tasks 4/5/6).
  - `sv_vendor/VENDORED_FROM.md` — CREATE (Task 1, appended to by each later task): records the exact upstream commit SHA and file+line ranges each module was vendored from, so a future security patch or bugfix upstream can be diffed against what's actually in this repo.
- `agent/pipeline/yolo_detector.py` — MODIFY: emit `sv_vendor.Detections` alongside (Task 2), then replace `point_in_polygon`/`_zone_containing` with `sv_vendor.PolygonZone` (Task 5).
- `agent/pipeline/models.py` — MODIFY: no field changes; `BoundingBox` stays the wire/event-schema type, `sv_vendor.Detections` is an internal-only type that never crosses `event_packager.py`'s boundary into `DetectedEvent`.
- `agent/pipeline/person_tracker.py` — MODIFY: internals replaced with `sv_vendor.ByteTrack`; `PersonTracker.update(poses, now) -> list[Track]` signature unchanged.
- `agent/pipeline/footfall.py` — MODIFY: internals replaced with a second `sv_vendor.ByteTrack` + `sv_vendor.LineZone` per line; `FootfallCounter.update(person_boxes, now)` / `.drain()` / `lines_from_config()` signatures unchanged.
- `agent/pipeline/event_packager.py` — NOT MODIFIED. `BoxAnnotator`/`LabelAnnotator` were considered and dropped (see Finding 5) — the existing ~20-line manual `cv2` drawing in `_annotate_frame` is not meaningfully larger or worse than the trimmed library equivalent, so there's nothing to gain by touching this file.
- `agent/pipeline/camera_worker.py` — NOT MODIFIED, except Task 6 adds two `DetectionsSmoother` instances and one call each into the existing pose/footfall branches. Every other task in this plan is scoped so `camera_worker.py`'s calls into these modules (`self.tracker.update(...)`, `self.footfall.update(...)`, `self.yolo.detect(...)`) keep their exact existing signatures. If a task can't preserve a signature, stop and flag it rather than touching `camera_worker.py` to compensate.

---

## Task 1: Vendor `geometry`, `Detections`, and `ByteTrack`

**Files:**
- Create: `agent/pipeline/sv_vendor/__init__.py`, `sv_vendor/geometry.py`,
  `sv_vendor/iou.py`, `sv_vendor/detections.py`,
  `sv_vendor/byte_tracker/{__init__,kalman_filter,matching,single_object_track,utils,core}.py`
- Create: `agent/pipeline/sv_vendor/VENDORED_FROM.md`
- Modify: `agent/pipeline/requirements.txt` (add `scipy`)

**Interfaces:**
- Produces: `sv_vendor.Point`, `sv_vendor.Vector`, `sv_vendor.Position`,
  `sv_vendor.Detections`, `sv_vendor.ByteTrack` — importable as
  `from sv_vendor import Detections, ByteTrack, Point, Position, Vector`
  once `sv_vendor/__init__.py` re-exports them. Tasks 2–6 consume these.

Every file below is vendored from a specific, real upstream location —
recorded in `VENDORED_FROM.md` as you go, in the format
`<local path> <- roboflow/supervision@<commit SHA of main as of today> <upstream path>[:<line range>]`.
Get the pinned commit SHA first:

```bash
curl -s "https://api.github.com/repos/roboflow/supervision/commits/main" | python3 -c "import json,sys; print(json.load(sys.stdin)['sha'])"
```

Use that exact SHA in every `VENDORED_FROM.md` line and in every raw-file
URL below (`https://raw.githubusercontent.com/roboflow/supervision/<SHA>/...`)
instead of `main`, so this vendor is reproducible against a fixed point in
time rather than silently drifting if upstream changes.

- [ ] **Step 1: Vendor geometry.py verbatim**

Fetch and save as `agent/pipeline/sv_vendor/geometry.py`:

```bash
curl -s "https://raw.githubusercontent.com/roboflow/supervision/<SHA>/supervision/geometry/core.py" -o agent/pipeline/sv_vendor/geometry.py
```

This is `Point`, `Vector`, `Position`, `Rect` — ~120 lines, stdlib-only
(`dataclasses`, `enum`, `math.sqrt`), needs no trimming. Confirmed during
planning: no external imports at all.

- [ ] **Step 2: Vendor a trimmed iou.py**

Create `agent/pipeline/sv_vendor/iou.py` containing only the `OverlapMetric`
enum and `box_iou_batch` function, vendored from
`supervision/detection/utils/iou_and_nms.py` — specifically the
`OverlapMetric` class definition and the `box_iou_batch` function body
(confirmed self-contained: pure `numpy`, no `cv2`/mask dependency for the
box-only path). Do not vendor the rest of that file (`OverlapFilter`,
`_jaccard`, mask-IOU variants, NMS/NMM merge logic) — none of it is used
by `ByteTrack`, `LineZone`, or `PolygonZone`.

- [ ] **Step 3: Vendor the ByteTrack package**

```bash
mkdir -p agent/pipeline/sv_vendor/byte_tracker
for f in kalman_filter matching single_object_track utils core; do
  curl -s "https://raw.githubusercontent.com/roboflow/supervision/<SHA>/supervision/tracker/byte_tracker/${f}.py" \
    -o "agent/pipeline/sv_vendor/byte_tracker/${f}.py"
done
touch agent/pipeline/sv_vendor/byte_tracker/__init__.py
```

Then fix imports in the copied files (they're self-contained already —
confirmed during planning that `matching.py` needs only
`scipy.optimize.linear_sum_assignment` + `box_iou_batch`, `kalman_filter.py`
needs only `scipy.linalg`, `single_object_track.py` needs only
`kalman_filter.KalmanFilter` + `utils.IdCounter`, `core.py` (the
`ByteTrack` class) needs `Detections`, `box_iou_batch`, `matching`,
`KalmanFilter`, `STrack`/`TrackState`, `IdCounter`):

- In `matching.py`: change
  `from supervision.detection.utils.iou_and_nms import box_iou_batch` to
  `from sv_vendor.iou import box_iou_batch`.
- In `core.py`: change `from supervision.detection.core import Detections`
  to `from sv_vendor.detections import Detections`; change
  `from supervision.detection.utils.iou_and_nms import box_iou_batch` to
  `from sv_vendor.iou import box_iou_batch`; change
  `from supervision.tracker.byte_tracker import matching` to
  `from sv_vendor.byte_tracker import matching`; change
  `from supervision.tracker.byte_tracker.kalman_filter import KalmanFilter`
  to `from sv_vendor.byte_tracker.kalman_filter import KalmanFilter`;
  change `from supervision.tracker.byte_tracker.single_object_track import
  STrack, TrackState` to
  `from sv_vendor.byte_tracker.single_object_track import STrack, TrackState`;
  change `from supervision.tracker.byte_tracker.utils import IdCounter` to
  `from sv_vendor.byte_tracker.utils import IdCounter`.
- In `single_object_track.py`: change
  `from supervision.tracker.byte_tracker.kalman_filter import KalmanFilter`
  to `from sv_vendor.byte_tracker.kalman_filter import KalmanFilter`;
  change `from supervision.tracker.byte_tracker.utils import IdCounter` to
  `from sv_vendor.byte_tracker.utils import IdCounter`.

Confirmed real `ByteTrack.__init__` signature (from `core.py`, read during
planning): `track_activation_threshold: float = 0.25`,
`lost_track_buffer: int = 30`, `minimum_matching_threshold: float = 0.8`,
`frame_rate: int = 30`, `minimum_consecutive_frames: int = 1`. Note
`update_with_detections` builds `np.hstack((detections.xyxy,
detections.confidence[:, np.newaxis]))` directly — `confidence` is
**required**, never `None`, on every `Detections` passed to `ByteTrack`.

- [ ] **Step 4: Vendor a trimmed Detections**

Create `agent/pipeline/sv_vendor/detections.py`. This is the one file
that needs real trimming rather than a verbatim copy — the upstream
`supervision/detection/core.py` is ~2500 lines, of which only the
following (all confirmed present and self-contained during planning) are
needed:

- The `@dataclass class Detections` field block: `xyxy: np.ndarray`,
  `mask: np.ndarray | None = None`, `confidence: np.ndarray | None = None`,
  `class_id: np.ndarray | None = None`, `tracker_id: np.ndarray | None = None`,
  `data: dict = field(default_factory=dict)`,
  `metadata: dict = field(default_factory=dict)`.
- `__len__`, `__iter__`, `__eq__` (drop the `is_data_equal`/
  `is_metadata_equal` upstream helper calls inside `__eq__` — replace with
  plain `self.data == other.data` and `self.metadata == other.metadata`;
  this pipeline never stores non-comparable objects in either dict, so the
  upstream helpers' extra numpy-array-aware comparison logic isn't needed).
- `empty()` and `is_empty()`.
- `get_anchors_coordinates(self, anchor: Position) -> np.ndarray` — copy
  verbatim (it's pure `xyxy` array arithmetic per `Position` value, no
  external calls).
- `__getitem__` — copy verbatim, but replace the upstream
  `get_data_item(self.data, index)` call with an inline equivalent:
  `{k: (v[index] if isinstance(v, np.ndarray) else [v[i] for i in (index if isinstance(index, list) else [index])]) for k, v in self.data.items()}`
  (upstream's `get_data_item` handles a few more exotic cases this
  pipeline's `data` dict never populates — this pipeline only ever stores
  the `coco_class` numpy string array from Task 2, so the simpler inline
  version is sufficient; if a later task adds a list-typed `data` entry,
  revisit this).
- Drop entirely: every `from_*` classmethod (11 of them —
  `from_yolov5`/`from_ultralytics`/`from_yolo_nas`/`from_tensorflow`/
  `from_deepsparse`/`from_mmdetection`/`from_transformers`/
  `from_detectron2`/`from_inference`/`from_sam`/
  `from_azure_analyze_image`/`from_paddledet`/`from_lmm`/`from_vlm`/
  `from_easyocr`/`from_ncnn`), `merge()`, `__setitem__`, `area`/
  `box_area`/`box_aspect_ratio` properties, `with_nms`/`with_nmm`.

The `__post_init__` validation call
(`validate_detections_fields(...)`) is also dropped — this pipeline
always constructs `Detections` from its own well-formed arrays (Task 2's
`to_sv_detections`, Task 3/4's pose/footfall box conversions), so
upstream's defensive cross-field shape validation is redundant here; keep
`__post_init__` as a no-op `pass` rather than deleting the method, so a
future contributor who wants to add validation has an obvious place to do
it.

- [ ] **Step 5: Wire sv_vendor's public API**

Create `agent/pipeline/sv_vendor/__init__.py`:

```python
from sv_vendor.geometry import Point, Position, Rect, Vector
from sv_vendor.detections import Detections
from sv_vendor.byte_tracker.core import ByteTrack

__all__ = ["Point", "Position", "Rect", "Vector", "Detections", "ByteTrack"]
```

- [ ] **Step 6: Pin scipy and verify**

Add to `agent/pipeline/requirements.txt`:

```
scipy>=1.10.0
```

(This is the *only* new dependency this entire plan adds — `ByteTrack`'s
Kalman filter and Hungarian-algorithm matching genuinely need it; there is
no way to vendor around it without reimplementing `scipy.linalg` and
`scipy.optimize.linear_sum_assignment`, which is not worth doing.)

```bash
cd agent/pipeline
.venv/bin/pip install "scipy>=1.10.0"
.venv/bin/python3 -c "
import numpy as np
from sv_vendor import Detections, ByteTrack, Point, Position, Vector

d = Detections(
    xyxy=np.array([[10, 10, 50, 90]], dtype=np.float32),
    confidence=np.array([0.9], dtype=np.float32),
    class_id=np.array([0], dtype=int),
)
tracker = ByteTrack()
tracked = tracker.update_with_detections(d)
assert len(tracked) == 1
assert tracked.tracker_id is not None
print('ok:', tracked.tracker_id)
"
```
Expected: `ok: [1]` (or similar — a single assigned tracker id).

Self-review: does `VENDORED_FROM.md` record every file with a real commit
SHA and upstream path (not `main`, which drifts)? Does `sv_vendor/`
import cleanly with `matplotlib`, `PIL`, and `opencv-python` absent from
the venv (confirm by checking `pip list` doesn't have them, or by running
the verify script in a venv that never had `supervision` installed at
all)? Run `cd agent/pipeline && .venv/bin/python3 -c "import camera_worker; print('ok')"` — expect `ok`, confirming nothing existing broke.

- [ ] **Step 7: Commit**

```bash
git add agent/pipeline/sv_vendor/ agent/pipeline/requirements.txt
git commit -m "feat(pipeline): vendor Detections/ByteTrack from roboflow/supervision"
```

---

## Task 2: `Detections` adapter in the YOLO gate

**Files:**
- Modify: `agent/pipeline/yolo_detector.py`

**Interfaces:**
- Consumes: `sv_vendor.Detections` (Task 1).
- Produces: `YoloDetector.detect(frame) -> list[YoloDetection] | None`
  **unchanged** (every existing caller keeps working) **plus** a new
  `YoloDetector.detect_sv(frame) -> Detections | None`, built from the
  same postprocessed arrays, that Tasks 3–5 consume instead of re-deriving
  `Detections` from `YoloDetection` objects three separate times.

- [ ] **Step 1: Add the Detections adapter**

In `agent/pipeline/yolo_detector.py`, after `_postprocess`:

```python
from sv_vendor import Detections


def to_sv_detections(detections: list["YoloDetection"]) -> "Detections":
    """Adapt this module's postprocessed YOLO output into Detections.

    Purely a data reshape — no re-inference, no re-NMS (NMS already ran in
    _postprocess via cv2.dnn.NMSBoxes). class_id is looked up positionally
    against COCO_CLASSES so it round-trips through Detections.data
    without needing a second class-name map downstream.
    """
    if not detections:
        return Detections.empty()
    xyxy = np.array(
        [[d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2] for d in detections],
        dtype=np.float32,
    )
    confidence = np.array([d.confidence for d in detections], dtype=np.float32)
    class_id = np.array(
        [COCO_CLASSES.index(d.coco_class) if d.coco_class in COCO_CLASSES else -1 for d in detections],
        dtype=int,
    )
    return Detections(
        xyxy=xyxy,
        confidence=confidence,
        class_id=class_id,
        data={"coco_class": np.array([d.coco_class for d in detections])},
    )
```

Add `detect_sv` to `YoloDetector`:

```python
    def detect_sv(self, frame) -> "Detections | None":
        """Detections view of detect(frame) — same fail-soft contract:
        None means inference errored (escalate), not "nothing found"."""
        detections = self.detect(frame)
        if detections is None:
            return None
        return to_sv_detections(detections)
```

- [ ] **Step 2: Verify**

```bash
cd agent/pipeline
.venv/bin/python3 -c "
from yolo_detector import YoloDetector, to_sv_detections, YoloDetection
from models import BoundingBox
d = YoloDetection(coco_class='person', confidence=0.9, bbox=BoundingBox(x1=1,y1=2,x2=3,y2=4,label='person'))
sv_dets = to_sv_detections([d])
assert len(sv_dets) == 1
assert sv_dets.data['coco_class'][0] == 'person'
print('ok')
"
```
Expected: `ok`

Self-review: does `detect_sv` preserve the exact None-means-error contract
`camera_worker.py` already depends on for `detect()`? Is `COCO_CLASSES`
still the single source of truth for class names (no second copy
introduced)?

- [ ] **Step 3: Commit**

```bash
git add agent/pipeline/yolo_detector.py
git commit -m "feat(pipeline): add Detections adapter to the YOLO gate"
```

---

## Task 3: Replace the pose/step-sequence tracker with `ByteTrack`

**Files:**
- Modify: `agent/pipeline/person_tracker.py`

**Interfaces:**
- Consumes: `sv_vendor.ByteTrack`, `sv_vendor.Detections` (Task 1);
  `PersonPose` from `pose_detector.py` (unchanged).
- Produces: `PersonTracker.update(poses: list[PersonPose], now: float) ->
  list[Track]` — **exact same signature and return shape** `camera_worker.py`
  already calls (`Track.track_id`, `.pose`, `.sequence_state`,
  `.last_seen_at`). Internals only change.

- [ ] **Step 1: Rewrite PersonTracker on top of ByteTrack**

Replace the greedy-IoU matching body of `person_tracker.py`, keeping the
`Track` dataclass and the public `update()` signature identical:

```python
import numpy as np
from sv_vendor import ByteTrack, Detections

from pose_detector import PersonPose


@dataclass
class Track:
    track_id: int
    pose: PersonPose
    sequence_state: object
    last_seen_at: float
    missed_frames: int = 0


class PersonTracker:
    """Wraps ByteTrack for pose/step-sequence tracking.

    ByteTrack tracks detections, not arbitrary payloads — it has no
    concept of "this track's sequence_state". This class keeps that
    mapping itself: sequence_state lives in self._sequence_states, keyed
    by the tracker_id ByteTrack assigns, created on first sight of a new
    id and dropped once ByteTrack stops reporting that id (which happens
    automatically once it exceeds ByteTrack's own lost-track buffer — no
    separate TTL bookkeeping needed here anymore).
    """

    def __init__(self, iou_threshold: float, ttl_seconds: float, sequence_state_factory, frame_rate: int = 5):
        # iou_threshold/ttl_seconds kept as constructor args for call-site
        # compatibility, mapped onto ByteTrack's real kwargs (confirmed from
        # supervision/tracker/byte_tracker/core.py during planning):
        # minimum_matching_threshold plays the iou_threshold role (default
        # 0.8 upstream; this pipeline's old greedy tracker used a looser
        # 0.3 — start at that and tune), lost_track_buffer plays the
        # ttl_seconds role but is frame-COUNTS, not seconds (upstream:
        # max_time_lost = int(frame_rate / 30.0 * lost_track_buffer)) — so
        # convert: lost_track_buffer = round(ttl_seconds * frame_rate).
        self._bytetrack = ByteTrack(
            minimum_matching_threshold=iou_threshold,
            lost_track_buffer=round(ttl_seconds * frame_rate),
            frame_rate=frame_rate,
        )
        self.sequence_state_factory = sequence_state_factory
        self._sequence_states: dict[int, object] = {}

    def update(self, poses: list[PersonPose], now: float) -> list[Track]:
        if not poses:
            tracked = self._bytetrack.update_with_detections(Detections.empty())
            self._prune_sequence_states(active_ids=set())
            return []

        xyxy = np.array(
            [[p.bbox.x1, p.bbox.y1, p.bbox.x2, p.bbox.y2] for p in poses], dtype=np.float32
        )
        confidence = np.array([1.0] * len(poses), dtype=np.float32)  # pose model has no per-box confidence surfaced here
        detections = Detections(xyxy=xyxy, confidence=confidence, class_id=np.zeros(len(poses), dtype=int))
        tracked = self._bytetrack.update_with_detections(detections)

        active_ids = set()
        tracks: list[Track] = []
        for i in range(len(tracked)):
            track_id = int(tracked.tracker_id[i])
            active_ids.add(track_id)
            if track_id not in self._sequence_states:
                self._sequence_states[track_id] = self.sequence_state_factory()
            # Match this tracked box back to its source PersonPose by
            # nearest xyxy — ByteTrack reorders/filters, so index i on
            # `tracked` does not line up with index i on `poses`.
            tx1, ty1, tx2, ty2 = tracked.xyxy[i]
            pose = min(
                poses,
                key=lambda p: abs(p.bbox.x1 - tx1) + abs(p.bbox.y1 - ty1) + abs(p.bbox.x2 - tx2) + abs(p.bbox.y2 - ty2),
            )
            tracks.append(Track(
                track_id=track_id,
                pose=pose,
                sequence_state=self._sequence_states[track_id],
                last_seen_at=now,
            ))

        self._prune_sequence_states(active_ids)
        return tracks

    def _prune_sequence_states(self, active_ids: set[int]) -> None:
        for track_id in list(self._sequence_states.keys()):
            if track_id not in active_ids:
                del self._sequence_states[track_id]
```

Delete the old `_iou` helper — `ByteTrack` no longer needs it.

- [ ] **Step 2: Verify**

```bash
cd agent/pipeline
.venv/bin/python3 -c "
from person_tracker import PersonTracker
from pose_detector import PersonPose
from models import BoundingBox
import time

pt = PersonTracker(iou_threshold=0.3, ttl_seconds=2.0, sequence_state_factory=lambda: {'step': 0})
pose = PersonPose(bbox=BoundingBox(x1=10, y1=10, x2=50, y2=90, label='person'), keypoints=[(0,0,0)]*17, label='standing')
tracks = pt.update([pose], time.time())
assert len(tracks) == 1
tid = tracks[0].track_id
tracks2 = pt.update([pose], time.time() + 0.1)
assert tracks2[0].track_id == tid, 'same person should keep the same track id across consecutive frames'
print('ok')
"
```
Expected: `ok`

Self-review: does `_prune_sequence_states` ever drop a state that's still
active (data loss mid-sequence)? Does the nearest-box matching in Step 1
break down when two people overlap closely — and if so, is that a
regression from the old greedy IoU tracker, or the same class of error it
already had? (It's the same class: neither tracker does re-identification,
so ambiguous overlap was always a known limitation — confirm this stays
true, don't silently accept a new failure mode.)

- [ ] **Step 3: Commit**

```bash
git add agent/pipeline/person_tracker.py
git commit -m "refactor(pipeline): replace greedy-IoU person tracker with ByteTrack"
```

---

## Task 4: Vendor `LineZone`; replace footfall's tracker + crossing logic

**Files:**
- Create: `agent/pipeline/sv_vendor/line_zone.py`, `sv_vendor/cross_product.py`
- Modify: `agent/pipeline/footfall.py`, `agent/pipeline/sv_vendor/__init__.py`

**Interfaces:**
- Consumes: `sv_vendor.ByteTrack`, `sv_vendor.Detections`,
  `sv_vendor.Point`/`Position`/`Vector` (Task 1).
- Produces: `sv_vendor.LineZone`, consumed by this task's rewrite of
  `footfall.py`. `FootfallCounter.update(person_boxes, now)`,
  `FootfallCounter.drain() -> dict[str, dict[str, int]]`,
  `FootfallCounter.active_tracks`, and `lines_from_config(raw) ->
  list[CountingLine]` — **all four signatures unchanged**, since
  `camera_worker.py` calls all four today.

- [ ] **Step 1: Vendor cross_product**

Create `agent/pipeline/sv_vendor/cross_product.py`, vendored from
`supervision/detection/utils/internal.py`'s `cross_product` function (~15
lines, confirmed self-contained — pure `numpy`, takes an array of anchor
points and a `Vector`, returns the vectorized 2D cross product used to
decide which side of the line each anchor point falls on).

- [ ] **Step 2: Vendor a trimmed LineZone**

Create `agent/pipeline/sv_vendor/line_zone.py`, vendored from
`supervision/detection/line_zone.py` — **only the `LineZone` class**
(confirmed at upstream lines 26–319 as of the commit SHA recorded in
`VENDORED_FROM.md`), not `LineZoneAnnotator`/`LineZoneAnnotatorMulticlass`
(the rest of that file — drawing helpers this pipeline doesn't use, since
it never renders the line itself onto video). Because the annotator
classes are dropped, the file-level imports trim down to just:

```python
from __future__ import annotations
import warnings
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from typing import Any

import numpy as np
import numpy.typing as npt

from sv_vendor.detections import Detections
from sv_vendor.cross_product import cross_product
from sv_vendor.geometry import Point, Position, Vector
```

(dropping upstream's `cv2`, `functools.lru_cache`, `typing.Literal`,
`supervision.config.CLASS_NAME_DATA_FIELD`, `supervision.draw.color.Color`,
`supervision.draw.utils.draw_rectangle/draw_text`,
`supervision.utils.image.overlay_image`, and
`supervision.utils.internal.SupervisionWarnings` — none of those are used
by `LineZone` itself, only by the annotator classes; replace the one
`warnings.warn(..., category=SupervisionWarnings)` call inside
`trigger()` with a plain `warnings.warn(...)`, dropping the custom
category). Copy the class body verbatim otherwise — confirmed during
planning that `LineZone.__init__`, `trigger()`,
`_calculate_region_of_interest_limits`, `_compute_anchor_sides`, and
`_update_class_id_to_name` have no other external dependencies.

Confirmed real behavior from reading `trigger()`'s source during
planning, load-bearing for Task 4's `FootfallCounter` rewrite below:
- `in_count`/`out_count` are **properties that sum a `Counter`**
  (`_in_count_per_class`/`_out_count_per_class`), never reset by anything
  in the class — a monotonic running total, not a delta. `drain()` must
  snapshot-and-subtract itself.
- Default `triggering_anchors` is `(Position.TOP_LEFT, Position.TOP_RIGHT,
  Position.BOTTOM_LEFT, Position.BOTTOM_RIGHT)` — all four box corners,
  **not** bottom-center. This pipeline's old `footfall.py` used
  bottom-center specifically (a person's feet crossing the line, not
  their head) — must be passed explicitly as
  `triggering_anchors=(Position.BOTTOM_CENTER,)` in Task 4's
  `LineZone(...)` construction, or tall people will be counted as
  crossing earlier than they should.
- `trigger(detections)` requires `detections.tracker_id` to be set (warns
  and no-ops otherwise) — `ByteTrack` must run first, every frame.
- There's also a `minimum_crossing_threshold: int = 1` constructor kwarg
  upstream (default requires a track be seen on the new side for 2
  consecutive triggered frames before counting) — this overlaps with this
  pipeline's old `MIN_TRACK_HITS = 2` debounce constant. Use
  `minimum_crossing_threshold=1` (upstream default, equivalent to the old
  `MIN_TRACK_HITS`) rather than reimplementing that debounce separately.

Add to `agent/pipeline/sv_vendor/__init__.py`:

```python
from sv_vendor.line_zone import LineZone
```

and add `"LineZone"` to `__all__`.

- [ ] **Step 3: Rewrite FootfallCounter on ByteTrack + LineZone**

Keep `CountingLine` as the config dataclass (still built by
`lines_from_config`, still named/x1/y1/x2/y2 for the frontend's zone
editor to keep drawing against), but use it only to construct one
`LineZone` per line internally:

```python
import numpy as np
from sv_vendor import ByteTrack, Detections, LineZone, Point, Position


@dataclass
class CountingLine:
    name: str
    x1: int
    y1: int
    x2: int
    y2: int


class FootfallCounter:
    """Counts directional line crossings for one camera, backed by
    ByteTrack (tracking) + LineZone (crossing detection) instead of
    this module's previous hand-rolled IoU+proximity tracker and manual
    side-of-line math.

    Still not re-identification — see the module docstring's estimate
    caveats, which remain true: ByteTrack also has no cross-occlusion
    identity recovery beyond its own lost-track buffer.
    """

    def __init__(self, lines: list[CountingLine]):
        self.lines = lines
        self._bytetrack = ByteTrack()
        self._zones = {
            line.name: LineZone(
                start=Point(line.x1, line.y1),
                end=Point(line.x2, line.y2),
                # Bottom-center, matching this pipeline's old convention
                # (a person's feet cross the line, not their head) — the
                # LineZone default is all four box corners, confirmed
                # during Task 4 Step 2's read of the real source.
                triggering_anchors=(Position.BOTTOM_CENTER,),
                minimum_crossing_threshold=1,
            )
            for line in lines
        }
        # LineZone.in_count/out_count are running totals, confirmed by
        # reading the real source in Task 4 Step 2 — no reset/delta method
        # exists — so drain() needs its own snapshot-and-subtract.
        self._last_totals = {name: {"in": 0, "out": 0} for name in self._zones}

    def update(self, person_boxes: list, now: float) -> None:
        if not self.lines:
            return
        if not person_boxes:
            self._bytetrack.update_with_detections(Detections.empty())
            return

        xyxy = np.array([[b.x1, b.y1, b.x2, b.y2] for b in person_boxes], dtype=np.float32)
        confidence = np.array([1.0] * len(person_boxes), dtype=np.float32)
        detections = Detections(xyxy=xyxy, confidence=confidence, class_id=np.zeros(len(person_boxes), dtype=int))
        tracked = self._bytetrack.update_with_detections(detections)

        for zone in self._zones.values():
            zone.trigger(tracked)

    def drain(self) -> dict[str, dict[str, int]]:
        out = {}
        for name, zone in self._zones.items():
            current = {"in": int(zone.in_count), "out": int(zone.out_count)}
            previous = self._last_totals[name]
            out[name] = {
                "in": current["in"] - previous["in"],
                "out": current["out"] - previous["out"],
            }
            self._last_totals[name] = current
        return out

    @property
    def active_tracks(self) -> int:
        return len(self._bytetrack.tracker_id) if hasattr(self._bytetrack, "tracker_id") else 0


def lines_from_config(raw: list) -> list[CountingLine]:
    lines: list[CountingLine] = []
    for item in raw or []:
        try:
            lines.append(CountingLine(
                name=str(item["name"]),
                x1=int(item["x1"]), y1=int(item["y1"]),
                x2=int(item["x2"]), y2=int(item["y2"]),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("skipping malformed counting line %r: %s", item, exc)
    return lines
```

- [ ] **Step 4: Verify**

```bash
cd agent/pipeline
.venv/bin/python3 -c "
from footfall import FootfallCounter, CountingLine
from models import BoundingBox
import time

lines = [CountingLine(name='door', x1=0, y1=50, x2=200, y2=50)]
fc = FootfallCounter(lines)
now = time.time()
# Walk a person from above the line to below it across a few frames.
for y in (10, 30, 45, 55, 70, 90):
    fc.update([BoundingBox(x1=90, y1=y, x2=110, y2=y+40, label='person')], now)
    now += 0.2
counts = fc.drain()
assert 'door' in counts
print('counts:', counts)
"
```
Expected: prints a `counts` dict for `door` — confirm by eye that one
crossing registered in the direction the walk implies (this is the one
behavior worth actually eyeballing, not just asserting a shape, because
getting `in`/`out` backwards silently produces confidently wrong
dashboard numbers).

Self-review: does `drain()`'s snapshot-and-subtract correctly handle the
case where `LineZone`'s internal `Counter` is untouched between two
`drain()` calls (delta of zero, not a crash)? Does the vendored
`line_zone.py` still import cleanly with no `cv2`/`PIL` reference left
over from the trim in Step 2?

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline/footfall.py agent/pipeline/sv_vendor/line_zone.py agent/pipeline/sv_vendor/cross_product.py agent/pipeline/sv_vendor/__init__.py
git commit -m "feat(pipeline): vendor LineZone; replace footfall's custom tracker+crossing math with ByteTrack + LineZone"
```

---

## Task 5: Vendor `PolygonZone`; replace the ray-casting zone test

**Files:**
- Create: `agent/pipeline/sv_vendor/polygon_zone.py`, `sv_vendor/boxes.py`, `sv_vendor/converters.py`
- Modify: `agent/pipeline/yolo_detector.py`, `agent/pipeline/sv_vendor/__init__.py`

**Interfaces:**
- Consumes: `YoloDetector.detect_sv()` (Task 2); `sv_vendor.Detections` (Task 1).
- Produces: `sv_vendor.PolygonZone`. `_zone_containing(bbox, zones) -> str
  | None` **signature unchanged** (still called from `map_detections`),
  internals swapped.

- [ ] **Step 1: Vendor the two small utilities PolygonZone needs**

Create `agent/pipeline/sv_vendor/boxes.py` with just `clip_boxes`,
vendored from `supervision/detection/utils/boxes.py` (~20 lines, pure
`numpy` — clips an `(N, 4)` xyxy array to a `(width, height)` resolution).

Create `agent/pipeline/sv_vendor/converters.py` with just
`polygon_to_mask`, vendored from
`supervision/detection/utils/converters.py` (~15 lines — this is the one
place `PolygonZone` genuinely needs `cv2`: `cv2.fillPoly(mask,
[polygon.astype(np.int32)], color=1)` — already have `cv2` via the pinned
`opencv-python-headless`, so this is not a new dependency).

- [ ] **Step 2: Vendor a trimmed PolygonZone**

Create `agent/pipeline/sv_vendor/polygon_zone.py`, vendored from
`supervision/detection/tools/polygon_zone.py` — **only the `PolygonZone`
class**, not `PolygonZoneAnnotator` (the rest of that file — drawing
helpers this pipeline doesn't use, same pattern as Task 4's
`LineZoneAnnotator` drop). Confirmed real signature and behavior from
reading the source during planning:

```python
def __init__(
    self,
    polygon: npt.NDArray[np.int64],
    triggering_anchors: Iterable[Position] = (Position.BOTTOM_CENTER,),
): ...

def trigger(self, detections: Detections) -> npt.NDArray[np.bool_]: ...
```

`triggering_anchors` **defaults to `(Position.BOTTOM_CENTER,)`** already —
unlike `LineZone` (Task 4), no override is needed to match this
pipeline's "a person's feet are in the zone" convention; the upstream
default already agrees with it. `trigger()` returns one bool per
detection, `True` where that detection's anchor falls inside the polygon
— confirming the plan's original `pz.trigger(single)[0]` usage below is
correct. `PolygonZone` also exposes `self.current_count` (updated on every
`trigger()` call) — not consumed by this task, but available if a later
task wants live zone-occupancy counts rather than only this task's
per-bbox membership test.

Trim the file's imports to:

```python
from __future__ import annotations
from collections.abc import Iterable
from dataclasses import replace

import numpy as np
import numpy.typing as npt

from sv_vendor.detections import Detections
from sv_vendor.boxes import clip_boxes
from sv_vendor.converters import polygon_to_mask
from sv_vendor.geometry import Position
```

(dropping upstream's `cv2`, `supervision.draw.color.Color`,
`supervision.draw.utils.draw_filled_polygon/draw_polygon/draw_text`, and
`supervision.geometry.utils.get_polygon_center` — all used only by
`PolygonZoneAnnotator`). Copy `__init__` and `trigger()` verbatim
otherwise; both depend only on `clip_boxes`, `polygon_to_mask`,
`dataclasses.replace`, and `Detections.get_anchors_coordinates` (already
in the Task 1 vendor).

Add to `agent/pipeline/sv_vendor/__init__.py`:

```python
from sv_vendor.polygon_zone import PolygonZone
```

and add `"PolygonZone"` to `__all__`.

- [ ] **Step 3: Cache one PolygonZone per configured zone, keyed by shape**

`_zone_containing` is called once per detection per frame, and camera
zones don't change frame-to-frame, so build `PolygonZone` instances
once per distinct zone-points list rather than reconstructing them on
every call:

```python
import numpy as np
from sv_vendor import Detections, PolygonZone

_polygon_zone_cache: dict[tuple, "PolygonZone"] = {}


def _get_polygon_zone(zone: dict) -> "PolygonZone | None":
    points = zone.get("points", [])
    if len(points) < 3:
        return None
    key = tuple(tuple(p) for p in points)
    if key not in _polygon_zone_cache:
        polygon = np.array(points, dtype=np.float32)
        _polygon_zone_cache[key] = PolygonZone(polygon=polygon)
    return _polygon_zone_cache[key]


def _zone_containing(bbox: BoundingBox, zones: list) -> str | None:
    single = Detections(
        xyxy=np.array([[bbox.x1, bbox.y1, bbox.x2, bbox.y2]], dtype=np.float32),
        confidence=np.array([1.0], dtype=np.float32),
        class_id=np.zeros(1, dtype=int),
    )
    for zone in zones:
        pz = _get_polygon_zone(zone)
        if pz is None:
            continue
        if pz.trigger(single)[0]:
            return zone.get("name", "unnamed")
    return None
```

Delete `point_in_polygon` — nothing else in the codebase calls it (confirm
with the grep in Step 4 before deleting).

- [ ] **Step 4: Confirm point_in_polygon has no other callers before deleting it**

```bash
cd /Users/vaibhaw/Developer/vision
grep -rn "point_in_polygon" agent/ backend/ frontend/ | grep -v "\.pyc"
```
Expected: only the definition and the one now-removed call site in
`yolo_detector.py`'s own `_zone_containing` (already replaced above) —
i.e., the grep should come back empty after the edit. If anything else
still imports `point_in_polygon`, keep the function and only swap the
*internal* call site, don't delete it out from under another caller.

- [ ] **Step 5: Verify zone membership matches the old ray-casting result**

```bash
cd agent/pipeline
.venv/bin/python3 -c "
from yolo_detector import _zone_containing
from models import BoundingBox

zones = [{'name': 'entrance', 'points': [[0,0],[100,0],[100,100],[0,100]]}]
inside = BoundingBox(x1=10, y1=10, x2=30, y2=30, label='person')
outside = BoundingBox(x1=200, y1=200, x2=230, y2=230, label='person')
assert _zone_containing(inside, zones) == 'entrance'
assert _zone_containing(outside, zones) is None
print('ok')
"
```
Expected: `ok`

Self-review: does the polygon-zone cache ever grow unbounded (a camera
whose zones get redrawn repeatedly across its lifetime without a process
restart)? Since zone edits go through the backend and land back on the
agent via a config refresh — confirm whether the process restarts on a
config change (if it does, the in-memory cache dying with it is fine and
this is a non-issue; if config hot-reloads without a restart, cap the
cache or key it off `(camera_id, zone_name)` and evict stale entries).

- [ ] **Step 6: Commit**

```bash
git add agent/pipeline/yolo_detector.py agent/pipeline/sv_vendor/polygon_zone.py agent/pipeline/sv_vendor/boxes.py agent/pipeline/sv_vendor/converters.py agent/pipeline/sv_vendor/__init__.py
git commit -m "feat(pipeline): vendor PolygonZone; replace ray-casting polygon test"
```

---

## Task 6: Vendor `DetectionsSmoother` for track stability

Finding 5: not in the original scope, added because it's a real, cheap
win — a ~110-line pure-`numpy` moving average over each `tracker_id`'s
recent boxes, zero added inference cost, that directly reduces the
jitter-driven false-crossing class `footfall.py`'s own docstring already
names as its dominant error source. `BoxAnnotator`/`LabelAnnotator`
(Finding 4) are explicitly NOT part of this plan — see the Findings
section; `event_packager.py` is not touched anywhere in this plan.

**Files:**
- Create: `agent/pipeline/sv_vendor/smoother.py`
- Modify: `agent/pipeline/person_tracker.py`, `agent/pipeline/footfall.py`, `agent/pipeline/sv_vendor/__init__.py`
- `agent/pipeline/camera_worker.py` — NOT MODIFIED: both smoothers are wired inside `PersonTracker`/`FootfallCounter`'s own `__init__`/`update`, so `camera_worker.py`'s existing calls into them need no change.

**Interfaces:**
- Consumes: `sv_vendor.Detections` (Task 1).
- Produces: `sv_vendor.DetectionsSmoother`, with one instance wired into
  `PersonTracker` (Task 3) and one into `FootfallCounter` (Task 4) —
  smoothing happens *before* each tracker's own boxes are handed
  downstream, not as a third independent stage `camera_worker.py` has to
  call.

- [ ] **Step 1: Vendor DetectionsSmoother**

Fetch and save as `agent/pipeline/sv_vendor/smoother.py`, vendored from
`supervision/detection/tools/smoother.py` (confirmed ~110 lines, fully
self-contained on `numpy` + stdlib `collections`/`copy` — the one thing it
needs from `Detections` is `Detections.merge()`, which Task 1 Step 4
explicitly dropped when trimming `detections.py`). Two options, pick the
simpler one once you're looking at the real vendored body: either (a) add
back a minimal `merge()` to `sv_vendor/detections.py` — just the
`xyxy`/`confidence`/`class_id`/`tracker_id` stacking Task 1's
`stack_or_none` helper did, dropping the `data`/`metadata` merge machinery
this pipeline's `data` dict never needs merged — or (b) reimplement
`DetectionsSmoother.get_smoothed_detections` to build a fresh `Detections`
directly with `np.vstack`/`np.hstack` instead of calling `.merge()` at
all, avoiding touching Task 1's file again. Prefer (b) — it keeps
`detections.py` exactly as trimmed in Task 1 and keeps the smoother
self-contained in its own file.

Import fix: change `from supervision.detection.core import Detections` to
`from sv_vendor.detections import Detections`.

Add to `agent/pipeline/sv_vendor/__init__.py`:

```python
from sv_vendor.smoother import DetectionsSmoother
```

and add `"DetectionsSmoother"` to `__all__`.

- [ ] **Step 2: Wire a smoother into PersonTracker**

In `agent/pipeline/person_tracker.py`, add
`self._smoother = DetectionsSmoother(length=3)` to `PersonTracker.__init__`
(3 frames, not upstream's default 5 — this pipeline samples at 1–5fps, so
5 frames of smoothing lag is up to 5 seconds behind real motion at idle
rate; 3 keeps lag under 3 seconds while still damping single-frame
jitter). In `update()`, smooth `tracked` before the per-detection loop
that builds `Track` objects:

```python
        tracked = self._bytetrack.update_with_detections(detections)
        tracked = self._smoother.update_with_detections(tracked)
```

Note `DetectionsSmoother.update_with_detections` requires
`detections.tracker_id` — confirmed from its source, it warns and returns
the input unchanged otherwise — so this call must stay *after*
`update_with_detections` on the tracker, never before.

- [ ] **Step 3: Wire a smoother into FootfallCounter**

In `agent/pipeline/footfall.py`, same pattern: add
`self._smoother = DetectionsSmoother(length=3)` to
`FootfallCounter.__init__`, and in `update()`:

```python
        tracked = self._bytetrack.update_with_detections(detections)
        tracked = self._smoother.update_with_detections(tracked)
        for zone in self._zones.values():
            zone.trigger(tracked)
```

Smoothing here directly firms up `LineZone`'s crossing decisions — a
smoothed box crosses the line's `triggering_anchors` on a steadier
trajectory than a raw jittery one, which is the concrete mechanism behind
Finding 5's "reduces the jitter-driven false-crossing class" claim.

- [ ] **Step 4: Verify**

```bash
cd agent/pipeline
.venv/bin/python3 -c "
from person_tracker import PersonTracker
from pose_detector import PersonPose
from models import BoundingBox
import time

pt = PersonTracker(iou_threshold=0.3, ttl_seconds=2.0, sequence_state_factory=lambda: {'step': 0})
pose = PersonPose(bbox=BoundingBox(x1=10, y1=10, x2=50, y2=90, label='person'), keypoints=[(0,0,0)]*17, label='standing')
for _ in range(4):
    tracks = pt.update([pose], time.time())
assert len(tracks) == 1
print('ok')
"
cd agent/pipeline && .venv/bin/python3 -c "import camera_worker; print('ok')"
```
Expected: `ok` both times — confirms smoothing doesn't break the existing
track-id-stability contract Task 3's verify already established, and that
`camera_worker.py`'s imports still resolve untouched.

Self-review: is `length=3` actually applied to both smoothers, not left
at upstream's default 5 by accident? Does either smoother ever get handed
an already-smoothed `Detections` from the *other* tracker by mistake (it
shouldn't — `PersonTracker` and `FootfallCounter` each own a private
`_smoother` instance, never shared)?

- [ ] **Step 5: Commit**

```bash
git add agent/pipeline/sv_vendor/smoother.py agent/pipeline/sv_vendor/__init__.py agent/pipeline/person_tracker.py agent/pipeline/footfall.py
git commit -m "feat(pipeline): vendor DetectionsSmoother, wire into pose and footfall tracking"
```

---

## Task 7: End-to-end verification on a real stream

**Files:** none (verification only).

- [ ] **Step 1: Run against a live or looped test RTSP source**

```bash
cd agent/pipeline
.venv/bin/python3 test_webcam.py   # or point CAMERAS_CONFIG at a real/looped RTSP source
```

Watch logs for the pipeline's normal per-camera stats line (frames
processed, events detected, footfall counts) over at least 2 minutes with
a person walking in frame across a configured counting line and a
configured zone.

- [ ] **Step 2: Confirm no regression in event volume**

Compare event counts/types against a pre-refactor run of the same test
clip if one is available (`git stash` back to before Task 1, run the same
clip, `git stash pop`, re-run) — flag any material drop or spike in
`intrusion` or footfall counts specifically, since those are the two
paths this plan touched most.

- [ ] **Step 3: Update docs**

In `agent/pipeline/CLAUDE.md`, under "Pose-Based Step-Sequence Tracking"
and add a new subsection "Footfall & Zone Tracking" noting that both now
run on `ByteTrack` (two independent instances — pose tracking and
footfall tracking do not share track ids, since they track different
detection sources) plus `LineZone` / `PolygonZone`, replacing the
hand-rolled trackers this doc previously described. Note both instances
also feed a `DetectionsSmoother` (Task 6) before their boxes reach
`sequence_engine.py`/`LineZone` respectively. Also add a one-line note
that this vendored code lives in `agent/pipeline/sv_vendor/`, sourced
from `roboflow/supervision` — see `sv_vendor/VENDORED_FROM.md` for exact
provenance — not installed as a pip dependency. Remove references to
`person_tracker.py`'s greedy-IoU matching being "no re-identification" as
a *limitation of this codebase specifically* — it's now inherited from
`ByteTrack`, which has the same property (still true, just worth
attributing correctly since a future reader might otherwise think it's
fixable by tuning this repo's own code).

---

## Self-Review Notes

**Scope discipline.** `camera_worker.py` is explicitly untouched — every
task was written so the module it modifies keeps its existing public
signature. This was checked task-by-task above, not assumed.

**What this plan deliberately does NOT do:**
- Does not touch `worker/` (Finding 1) — it's the dormant cloud-VM
  fallback path, not where the live system's cameras run; every camera
  in the actual deployment goes through `agent/pipeline/` on the edge
  agent, direct to backend.
- Does not replace the ONNX inference itself, or move to `supervision`'s
  `from_ultralytics()` connector — this pipeline doesn't use the
  `ultralytics` package at all (raw ONNX runtime only), and adopting it
  would be a much larger, unrelated change (adds a PyTorch-adjacent
  dependency surface this plan's Global Constraints explicitly rule out).
- Does not touch pose classification (`classify_pose`'s angle heuristics)
  — `supervision` has no pose-classification concept; only the *tracking*
  of already-classified poses was in scope.
- Does not merge the two independent `ByteTrack` instances (pose
  tracking vs. footfall tracking) into one, even though both track
  "people" — they consume detections from two different models today, and
  unifying that is a real architecture change (would cut a redundant
  inference pass) that deserves its own plan, not a side effect of a
  library swap.
- Does not vendor `BoxAnnotator`/`LabelAnnotator` (Finding 4) —
  `event_packager.py` is untouched, evaluated and found not worth it.
- Does not add `InferenceSlicer` for small/distant-object detection
  (Finding 6) — a real capability `supervision` offers that this pipeline
  doesn't have, deliberately left out because it multiplies YOLO cost
  4–6× per tile and needs its own costed, opt-in plan rather than a
  default-on addition here.

**Net effect on code size:** replaces roughly 250 lines of hand-rolled
IoU/proximity/ray-casting logic across three files (`person_tracker.py`,
`footfall.py`, `yolo_detector.py`'s zone test) with thin adapters over
vendored, tested algorithms, adds one new capability this pipeline didn't
have before (`DetectionsSmoother`, Task 6), and keeps every call site in
`camera_worker.py` byte-for-byte unchanged except Task 6's two internal
smoother wirings inside `PersonTracker`/`FootfallCounter` themselves.
