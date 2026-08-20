# Foveated (Variable-Resolution) Sampling on the Inference Path — Design

## Source

Gizdov, Ullman & Harari, *"Seeing More with Less: Human-like Representations in
Vision Models"*, CVPR 2025. PDF in repo root.

## Problem

`camera_worker.py` escalates a frame to Gemini by encoding the whole
1280x720 frame at JPEG q80 and shipping it (`camera_worker.py`, the
`cv2.imencode` immediately before `gemini.analyze_frame`). Every escalated
frame costs full-frame image tokens regardless of how much of that frame
carries any information — at 2am a warehouse camera is mostly empty concrete,
and we pay for the concrete at the same fidelity as the person climbing the
fence.

The obvious lever — shrink the frame — is the wrong one. Shrinking uniformly
destroys detail everywhere, and the thing we most need Gemini to see is
usually the smallest object in the frame: a distant person is ~40px tall at
1280x720 and becomes an unreadable smudge at 640x360.

## What the paper claims

Given two images with an **identical pixel count** `N`, one sampled uniformly
and one sampled with density peaking at a fixation point and falling off with
eccentricity, then interpolated back to the original dimensions so the model
is unchanged:

- **+2.7% GQA, +2.1% SEED-Bench, +2.0% VQAv2, +2.2% COCO detection** for
  variable over uniform at 3% sampling density (their Table 1).
- Models reach **~80% of full-resolution accuracy at 3% of the pixels**, and
  near-maximal at 50%. Returns diminish steeply with resolution.
- The variable/uniform gap **widens as density falls** and closes as density
  rises. The paper attributes this to texture and fine detail surviving at the
  fovea and being destroyed everywhere by uniform downsampling.
- Fixation placement is forgiving: variable wins as soon as **>=10-20% of an
  object's area** falls inside the high-resolution region (their Fig 4b), and
  corner fixations still beat uniform (their Table 2).
- The specific falloff function is explicitly stated as **not critical** to the
  result, which frees us to pick one with a clean analytic inverse.

### Limits of the claim, stated plainly

These bound what we can expect and must not be glossed over downstream:

1. **No compute saving is claimed.** They reconstruct to full dimensions and
   keep architectures as-is. Any saving we get comes from *our* choice to send
   a smaller canvas, not from their result.
2. **Their Section 5 findings (globally-acting self-attention, resolution-
   specialized CNN filters) require training from scratch.** They trained
   DETR + ResNet101 on foveated data. We cannot retrain Gemini. Only the
   zero-shot half of the paper (their Table 1, the +1-2.7% band) applies to
   our Gemini path. The larger effects are reachable only for models we own —
   i.e. YOLO (Phase 4).
3. **Their data is daylight web imagery** (COCO/GQA/VQAv2). Ours is night, IR,
   low-contrast, H.264-compressed CCTV. Their gain is attributed to *texture*,
   which is precisely what IR and inter-frame compression destroy first.
   **The gain must be measured on our own footage before anything is built.**

## Why this fits Nightwatch better than it fit the paper

The paper's own biggest weakness is that they had no way to choose a fixation,
so they used the image centre and hoped — and still beat uniform. We already
compute a fixation oracle for free on every frame *before* any Gemini call:

- `motion_detector.detect()` produces a thresholded diff mask — its centroid is
  a fixation candidate, and we currently discard it.
- `yolo_detector.detect()` has already run and produced person/vehicle boxes on
  every frame that escalates.
- `camera_config.detection_zones` are operator-drawn regions of interest.

So we get the technique with a *good* aim rather than a coin-flip one, which
per their Fig 4b is exactly where the advantage is widest.

## Goal

Reduce Gemini image-token cost per escalated frame without losing detection
accuracy, by spending a fixed pixel budget non-uniformly, aimed by signals the
pipeline already computes.

Success is defined in Phase 0 (below) and not before: this design is a
hypothesis with an evaluation attached, not a build order.

## Non-goals

- **Any change to stored evidence.** Snapshots and 10s clips are what an
  operator, an insurer, or a court looks at. They are always the true,
  unwarped frame. Foveation applies to the inference path only.
- **Multiple fixations / scanning.** The paper does not do this either. One
  fixation per frame, or none.
- **Retraining Gemini.** Out of our control.
- **Backend, frontend, relay, or digest changes.** This is pipeline-only, in
  `agent/pipeline/` (and `worker/` only if it proves out and we choose to
  mirror it to the cloud-VM fallback path).
- **Foveating the live-view WebRTC stream.** Live view is for humans, who do
  their own foveating.

## The crop question — why this isn't just "send a crop"

If YOLO already located the person, the obvious move is to crop to that region
and send only that: smaller, sharper, no warping, no coordinate maths. **Crop
is the honest baseline here and it beats foveation on simplicity by a mile.**

Foveation only earns its place because of what Gemini is being asked. We are
not asking *"is there a person"* — YOLO answered that. We escalate for *what is
happening*, which usually needs the rest of the scene:

- Cropped: "a man standing." Foveated: "a man at the perimeter fence beside the
  loading bay."
- Zones live in the full frame. Crop the frame and there is no reference for
  whether he is inside the restricted area or beside it.
- Two people at opposite corners: crop picks a winner and discards the other.
  Foveation keeps the second one, softly.
- Loitering, tailgating, an abandoned bag are all *relationships between
  things*. A crop cuts the relationship out.

Crop discards context permanently; foveation demotes it. For a "what is going
on here" question that difference is the entire point — **but it is a claim,
not a measurement**, and the paper never tested it because they could not
locate the object first. We can. Phase 0 therefore runs **four arms, not
three**, and if crop wins we take crop and skip every bit of the warping
complexity below.

## Architecture

### New component: `agent/pipeline/foveate.py`

Pure OpenCV/numpy. No model, no network, no new runtime dependency beyond what
the pipeline already imports.

```python
@dataclass(frozen=True)
class WarpMap:
    """Forward warp plus its exact inverse for one (fixation, canvas, k)."""
    fixation: tuple[float, float]     # in SOURCE frame coords
    source_size: tuple[int, int]      # (w, h) of the true frame
    canvas_size: tuple[int, int]      # (w, h) of what we send
    k: float                          # foveation strength; k -> 0 == uniform

    def to_source(self, x: float, y: float) -> tuple[float, float]: ...
    def bbox_to_source(self, b: BoundingBox) -> BoundingBox: ...

def build_warp(...) -> WarpMap: ...
def apply(frame: np.ndarray, wm: WarpMap) -> np.ndarray:  # cv2.remap
```

### The falloff function

Radially symmetric about the fixation. For an output pixel at radius `r_out`
from the fixation in canvas space, sample the source at radius:

```
r_in(r_out) = R_in * (exp(k * r_out / R_out) - 1) / (exp(k) - 1)
```

with the exact inverse

```
r_out(r_in) = (R_out / k) * ln(1 + (r_in / R_in) * (exp(k) - 1))
```

`k` controls foveation strength; as `k -> 0` this degenerates to the linear
(uniform) map, which is what makes the uniform arm of the experiment a
special case of the same code path rather than a second implementation.

Chosen for the closed-form inverse. The paper uses a Wilson-Bergen falloff, and
explicitly states the choice of function is not critical to the result — so we
take the one that makes the coordinate contract provable rather than
approximate.

Implementation is a precomputed `cv2.remap` pair `(map_x, map_y)`, cached per
`(fixation, canvas, k)`. Fixations are **quantized to a grid** (e.g. 32px) so
the cache actually hits instead of rebuilding a full-resolution map every
frame.

### The fixation ladder

This is the part the paper does not have, and it needs care because of *when*
escalation actually fires. Per `config.py`, `yolo_fastpath_confidence: 0.75`
and `yolo_escalate_floor: 0.35`: if YOLO is confident we emit directly and
never call Gemini. **Gemini is called precisely when YOLO is unsure** — a
0.4-confidence maybe-person, or an inference error where there are no boxes at
all. The aiming signal is weakest exactly where we need it. Hence a ladder:

1. **Low-confidence YOLO detections**, if any — still a good aim at 0.4.
   Fixation = area-weighted centroid of relevant-class boxes.
2. **Motion centroid** from the `motion_detector` mask. Requires exposing the
   centroid, which is computed-and-discarded today.
3. **Zone centroid** — the operator already said where to watch.
4. **No foveation.** Send uniform at the same budget.

### The dispersion guard

Single-fixation foveation has one honest failure mode the paper never faced:
two intruders at opposite corners. Before foveating, compute the spread of
candidate ROI centroids (normalized to frame diagonal) and the fraction of
total ROI area that would land outside the high-acuity disc. If either exceeds
threshold, **fall back to uniform** rather than picking a winner and blurring
away a second intruder. Missing an intruder to save tokens is not a trade we
make.

## The coordinate contract — the single largest risk

Foveation is a nonlinear warp, and everything downstream thinks in 1280x720
pixel space:

- `prompt_builder.py` hardcodes *"Bounding box coordinates are pixel values for
  1280x720 frame"*
- `gemini_client._parse_response` builds `BoundingBox` from that space
- `point_in_polygon`, `_zone_for_bbox`, `footfall.py` counting lines, and
  camera-adjacency journeys all consume it

**Invariant: nothing downstream of `gemini_client` ever sees canvas
coordinates.** `_parse_response` inverse-maps every bbox back to source space
before returning. Zone logic, footfall, and journeys are then untouched — which
is what keeps this change small.

Two specifics that are easy to get wrong:

- **A rectangle in canvas space is not a rectangle in source space.** The
  radial warp bends straight lines. Inverse-map the 4 corners *and the 4 edge
  midpoints*, then take the axis-aligned bounding box of those 8 points. Corners
  alone under-cover a box that straddles the fovea boundary.
- `prompt_builder` must take the canvas dimensions as a parameter instead of
  hardcoding them, or Gemini reports coordinates in a space that does not exist.

Getting this wrong does not throw — it silently mis-fires intrusion alerts near
the frame edges. It therefore gets round-trip property tests (warp a known
box, inverse it, assert containment within tolerance) before any A/B runs.

## Config additions (`agent/pipeline/config.py`)

```python
# Foveated sampling on the Gemini escalation path (see 2026-08-20 spec).
# Default OFF. Do not enable before the Phase 0 evaluation clears it.
foveation_enabled: bool = False
foveation_canvas_scale: float = 0.5     # linear; 0.5 => ~25% pixel budget
foveation_strength: float = 2.5         # k; 0 == uniform
foveation_max_roi_spread: float = 0.35  # dispersion guard, frac of diagonal
foveation_fixation_grid: int = 32       # quantization for remap cache

# Shadow mode: send a sampled fraction of escalations BOTH ways and log the
# disagreement. Doubles Gemini spend on sampled frames — metered, capped.
foveation_shadow_fraction: float = 0.0
foveation_shadow_daily_cap: int = 200   # per camera
```

Per-camera override travels in the existing camera-config payload; no backend
schema change (config is free-form JSON), no migration.

## Evaluation

### Phase 0 — offline, four arms, before any pipeline change

Replay recorded clips from real cameras through each arm at a **matched pixel
budget**, at 3% / 10% / 30% density:

| Arm | What |
|---|---|
| `full` | true 1280x720 frame (ceiling) |
| `uniform` | evenly downscaled (today's cheap option; the paper's baseline) |
| `crop` | cropped to YOLO/motion ROI at the same pixel count |
| `variable` | foveated, fixated by the ladder |

Measured per arm: event agreement against `full`, false-negative rate on
labeled intrusions, description quality, and **actual image tokens** from
`response.usage_metadata`.

Split results by **day vs night/IR**, because that is the axis on which we
expect the paper's texture-driven gain to evaporate.

**Ground truth:** `events.feedback` already collects operator true/false-positive
judgements, which is a usable labeled source we are already accumulating.
Supplement with hand-labeled night clips.

**Decision gate.** Proceed to Phase 1 only if `variable` beats *both* `uniform`
and `crop` on night footage at matched budget. If `crop` wins, implement crop
and delete this design. If `uniform` wins, stop — the paper does not transfer
to CCTV, which is a publishable-internally result in itself and cost us days,
not weeks.

### Phase 1-4, gated on Phase 0

| Phase | Work | Decides |
|---|---|---|
| 1 | `foveate.py` + inverse map + round-trip property tests | Correctness foundation |
| 2 | Shadow-mode A/B on one pilot camera | Real accuracy + token delta in production |
| 3 | Foveated YOLO letterbox, inference-only | `yolo_detector._letterbox` already resizes 1280x720 -> 640, i.e. uniform at ~25% density — literally the paper's baseline condition. A foveated letterbox may improve small-object recall at identical inference cost. |
| 4 | Retrain YOLOv8n on foveated data | The only path to the paper's Section 5 effects (resolution-specialized filters), since it is the one model we own |

## Observability

Add to the per-camera heartbeat payload (free-form metrics dict, no backend
change):

- `foveated_frames` / `uniform_frames` — how often the dispersion guard fired
- `fixation_source` counts — which ladder rung aimed each frame
- `gemini_image_tokens` — from `usage_metadata`, so the saving is *measured*,
  never projected

Token instrumentation lands in Phase 1 regardless of outcome; we currently
cannot state what a Gemini call costs us, which is a gap independent of this
work.

## Fail-soft

If `build_warp` or `cv2.remap` throws for any reason, log once at WARNING and
send the uniform full frame — today's exact behaviour. Foveation is an
optimization and must never be able to drop a frame or an event. Same posture
as the existing GCS-upload and YOLO-inference fail-soft paths.

## Rollout

- `foveation_enabled` defaults `False`. Off is today's behaviour, byte for byte.
- Enable per-camera on one pilot site first, in shadow mode, before any camera
  runs foveation-only.
- No backend, frontend, or DB change at any phase. No API contract change.

## Open questions

- Do we mirror this into `worker/` for the cloud-VM fallback path, or leave
  that path uniform forever? Leaning: leave it — the fallback path is not where
  cost pressure lives, and divergence there is cheaper than double maintenance.
- Should setup-run scene analysis (`scene_analyzer.py`, 10 frames per camera)
  also foveate? It is a *scene* question, not an object question, so the
  fixation ladder has nothing to aim at. Leaning: no.
- Does foveation interact with the per-site AI budget metering in a way that
  makes shadow mode unaffordable at pilot scale? Needs a number before Phase 2.
