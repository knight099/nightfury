from dataclasses import dataclass, field

from models import BoundingBox, DetectedEvent


class SequenceState:
    """Per-track progress through a camera's step_sequence. Zero-argument
    constructible so PersonTracker can create one per new track without
    depending on this module (see person_tracker.py's sequence_state_factory)."""

    def __init__(self):
        self.current_step_index = 0
        # Lazily anchored to the first `now` passed into advance(), rather
        # than time.monotonic() at construction time. SequenceState must be
        # zero-arg constructible (Track creates one before any frame with a
        # timestamp is known), so it cannot assume a clock value up front —
        # and the clock advance() is driven by (test harness or caller) may
        # not be wall-clock time.monotonic() at all.
        self.step_entered_at = None
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

    if state.step_entered_at is None:
        state.step_entered_at = now

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

    current_zone = current_step.get("zone")
    later_zones = {
        s.get("zone") for s in step_sequence[state.current_step_index + 1:]
        if s.get("zone") != current_zone
    }
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
