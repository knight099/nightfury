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
        # Drop tracks that have aged out first (before attempting to match).
        for track_id in list(self._tracks.keys()):
            if now - self._tracks[track_id].last_seen_at > self.ttl_seconds:
                del self._tracks[track_id]

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

        return matched_tracks
