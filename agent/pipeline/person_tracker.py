import logging
from dataclasses import dataclass

import numpy as np
from sv_vendor import ByteTrack, Detections
from sv_vendor.smoother import DetectionsSmoother

from pose_detector import PersonPose

logger = logging.getLogger(__name__)


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
        # compatibility, mapped onto ByteTrack's real kwargs (confirmed
        # from supervision/tracker/byte_tracker/core.py):
        # minimum_matching_threshold plays the iou_threshold role,
        # lost_track_buffer plays the ttl_seconds role but is frame-COUNTS,
        # not seconds (upstream: max_time_lost = int(frame_rate / 30.0 *
        # lost_track_buffer)) — so convert via frame_rate.
        self._bytetrack = ByteTrack(
            minimum_matching_threshold=iou_threshold,
            lost_track_buffer=round(ttl_seconds * frame_rate),
            frame_rate=frame_rate,
        )
        # 3 frames, not upstream's default 5: this pipeline samples at
        # 1-5fps, so 5 frames of smoothing lag can be up to 5 seconds
        # behind real motion at idle rate. 3 keeps lag under 3 seconds
        # while still damping single-frame jitter.
        self._smoother = DetectionsSmoother(length=3)
        self.sequence_state_factory = sequence_state_factory
        # ByteTrack keeps a track alive internally (in its own lost_tracks
        # pool, reassigning the same tracker_id on reappearance) for
        # lost_track_buffer frames — but update_with_detections only
        # RETURNS tracks matched in the current call, so "not in this
        # frame's result" does NOT mean "ByteTrack forgot it". Pruning on
        # that basis would delete sequence_state on every single missed
        # frame (occlusion, a dropped detection) even though ByteTrack
        # reuses the id moments later. Prune on ttl_seconds instead,
        # mirroring ByteTrack's own lost_track_buffer window, tracked via
        # last-seen-at per sequence_state rather than per-frame presence.
        self._ttl_seconds = ttl_seconds
        self._sequence_states: dict[int, object] = {}
        self._sequence_states_last_seen: dict[int, float] = {}

    def update(self, poses: list[PersonPose], now: float) -> list[Track]:
        if not poses:
            self._bytetrack.update_with_detections(Detections.empty())
            self._prune_sequence_states(now)
            return []

        xyxy = np.array(
            [[p.bbox.x1, p.bbox.y1, p.bbox.x2, p.bbox.y2] for p in poses], dtype=np.float32
        )
        # Pose model has no per-box confidence surfaced here; ByteTrack
        # requires a confidence array (used directly in
        # update_with_detections), so use a constant.
        confidence = np.array([1.0] * len(poses), dtype=np.float32)
        detections = Detections(xyxy=xyxy, confidence=confidence, class_id=np.zeros(len(poses), dtype=int))
        tracked = self._bytetrack.update_with_detections(detections)
        tracked = self._smoother.update_with_detections(tracked)

        tracks: list[Track] = []
        for i in range(len(tracked)):
            track_id = int(tracked.tracker_id[i])
            if track_id not in self._sequence_states:
                self._sequence_states[track_id] = self.sequence_state_factory()
            self._sequence_states_last_seen[track_id] = now
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

        self._prune_sequence_states(now)
        return tracks

    def _prune_sequence_states(self, now: float) -> None:
        for track_id, last_seen in list(self._sequence_states_last_seen.items()):
            if now - last_seen > self._ttl_seconds:
                del self._sequence_states[track_id]
                del self._sequence_states_last_seen[track_id]
