# REMIND Re-Identification Integration — Design

## Problem

The step-sequence tracker's `person_tracker.py` uses a greedy IoU tracker with a short TTL (default 5s) and explicitly no re-identification: when a tracked person is occluded, exits frame briefly, or the tracker simply misses a few frames, they start a *new* track on reappearance and lose all step-sequence progress. This was an accepted, documented tradeoff at design time. [REMIND](https://github.com/knight099/remind-reid-tracker) is an existing project (appearance-based long-term re-identification using DINOv3 features + Hungarian assignment + a per-object memory system) built to solve exactly this class of problem.

## Goal

Let a tracked person's step-sequence progress survive occlusion/re-entry, for cameras that opt into it, by consulting REMIND's identity memory when the local IoU tracker loses a match — without adding GPU/PyTorch requirements to the existing CPU-only worker fleet.

## Research findings (grounding this design)

REMIND's real API (verified against `pipeline/reid_pipeline.py`, not just its README):

```python
class ReIDPipeline:
    def __init__(self, runtime_ctx): ...
    def process_frame(self, frame, frame_id: int, timestamp: float) -> (p_out, a_out, u_out)
```

Two facts drive this design:
1. It's genuinely callable per-frame (not CLI-only, despite the README's framing).
2. **It always runs its own internal YOLO instance-segmentation pass** (via `PerceptionStageFull`) — it does not accept externally-supplied detections. Integrating it means a second, independent YOLO pass plus DINOv3 feature extraction per frame, on top of whatever detection the worker already does. This is real, unavoidable-in-v1 redundant compute, not a minor detail.

Its dependency stack (`torch`, `transformers`, `ultralytics`, DINOv3) directly conflicts with the worker's existing "no PyTorch/ultralytics in the running process, CPU-only ONNX" constraint (set for both the YOLO gate and pose detector). There is no credible CPU-real-time path for a ViT-based feature extractor per detection — this requires GPU compute somewhere.

## Non-goals

- Forking `perception_stage_full.py` to accept our pre-computed detections (eliminating the redundant YOLO pass) — correct long-term architecture, but a real code change to someone else's repo. Explicitly deferred, not scope-crept into v1.
- Cross-camera / site-wide identity linking ("track this person across all cameras at this location") — a bigger, more privacy-sensitive capability than what's being solved here. This design is scoped to within-camera long-term re-identification only, matching the concrete problem (occlusion during one procedure on one camera).
- Running REMIND in-process inside `camera_worker.py` — it lives in a separate service, for the same reason the YOLO gate and pose detector stay CPU-only ONNX: keeping heavy/GPU-dependent inference off the process that has to stay lean across up to `max_cameras` per instance.
- Solving the GPU-hardware question here — this design assumes GPU compute exists *somewhere* reachable from the worker (a dedicated GPU worker tier, or the edge-appliance hardware discussed earlier), but does not decide which. That's an infrastructure/business decision, not an application design one.

## Architecture

```
Worker (CPU, per camera) — only for cameras with step_sequence configured
  pose_detector.detect(frame) → PersonPose(bbox, keypoints, label)
  tracker.update(poses, now) → tracks (existing greedy IoU matcher, unchanged)
  for each detection that DIDN'T match an existing track:
      → identity_resolver.resolve(camera_id, frame, frame_id, now)   [new, optional hook]
          → POST http://reid-service/identify  {camera_id, frame (JPEG bytes), frame_id, timestamp}
          → ReID service: get-or-create per-camera ReIDPipeline instance,
            call process_frame(frame, frame_id, timestamp)
          ← {identities: [{bbox, identity_id, is_new: bool}]}
      → if a returned identity_id matches one this worker has seen before
        (worker-local map: identity_id → SequenceState, separate longer TTL
        than the IoU tracker's 5s): re-attach that SequenceState to the new
        Track instead of creating a fresh one
      → else: create a new Track + fresh SequenceState, exactly as today
```

### ReID service (new)

A standalone Python service (FastAPI, matching this codebase's existing HTTP-service conventions), deployed on GPU-capable hardware — not part of the CPU worker fleet:

- `POST /identify` — body `{camera_id, frame: bytes (JPEG), frame_id: int, timestamp: float}`, auth via a shared key header (same pattern as the worker's existing `X-Worker-Key`, a new distinct key).
- Maintains one `ReIDPipeline` instance per `camera_id` in memory (its identity memory is scene-specific — sharing one instance across cameras would corrupt it), with an idle-eviction reaper on a TTL, the same shape as `person_tracker.py`'s own track eviction.
- Response: `{identities: [{bbox: [x1,y1,x2,y2], identity_id: str, is_new: bool}]}`, derived from REMIND's `p_out`/`a_out`/`u_out`.
- Fail-soft: if the service is unreachable, times out, or errors, the worker's `identity_resolver.resolve()` returns `None` — the tracker falls back to exactly today's behavior (fresh track on no IoU match). This is never a blocking dependency for cameras that don't have it configured or when it's down.

### Worker-side changes

- `person_tracker.py`: `PersonTracker.__init__` gains an optional `identity_resolver` parameter (a callable), following the exact decoupling pattern already used for `sequence_state_factory` — `person_tracker.py` still has zero import of anything ReID-specific. When `update()` has an unmatched detection and a resolver is configured, it calls the resolver before falling back to "always create a new track."
- New worker-local state: `identity_to_sequence_state: dict[str, SequenceState]`, with its own TTL (default proposal: 60s — long enough to cover realistic occlusion durations, short enough to bound memory) — separate from the IoU tracker's 5s track TTL, since the whole point of REMIND is a *longer* re-identification window than frame-to-frame matching provides.
- Only instantiated/called for cameras with a non-empty `step_sequence` **and** a new `reid_enabled` per-camera flag (defaulting to `False`) — this is opt-in on top of opt-in, since it requires GPU infrastructure that won't exist for every deployment.

## Testing

Per standing preference (no TDD ceremony, direct implementation + manual sanity check + self-review), with an explicit caveat: **this feature cannot be fully verified without GPU hardware running the real REMIND pipeline**, unlike everything else built this session on CPU-only ONNX. Testing splits accordingly:
- `person_tracker.py`'s resolver hook: fully testable today with a fake resolver (canned "matched identity X" / "no match" / "resolver unavailable" responses) — verifies the tracker correctly re-attaches a `SequenceState` or falls back, without needing real GPU inference.
- The ReID service itself and its actual accuracy/latency: requires a GPU environment to validate at all — out of reach of this development environment as currently equipped. This should be flagged explicitly as a real spike, not assumed to work from the README/source alone.

## Rollout

- `reid_enabled` defaults to `False` per camera — zero behavior change for every existing deployment until explicitly turned on, and even then only for cameras that also have a `step_sequence` configured.
- Requires new infrastructure (a GPU-capable host for the ReID service) that doesn't exist in this codebase today — this is the actual blocking prerequisite, not the application code.
