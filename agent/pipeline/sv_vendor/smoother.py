"""Vendored from supervision/detection/tools/smoother.py.

get_smoothed_detections is reimplemented to build a fresh Detections
directly via np.vstack/hstack instead of calling upstream's
Detections.merge() (dropped when detections.py was trimmed in Task 1 —
see sv_vendor/detections.py's module docstring). This only carries
xyxy/confidence/class_id/tracker_id through the merge, not mask/data/
metadata — sufficient for this pipeline's two call sites
(PersonTracker/FootfallCounter), which never set a per-detection `data`
dict on the Detections passed through ByteTrack.
"""
from __future__ import annotations

import warnings
from collections import defaultdict, deque
from copy import deepcopy

import numpy as np

from sv_vendor.detections import Detections


class DetectionsSmoother:
    """
    A utility class for smoothing detections over multiple frames in video
    tracking. It maintains a history of detections for each track and
    provides smoothed predictions based on these histories.

    !!! warning

        - `DetectionsSmoother` requires `tracker_id` on every detection.
        - Not compatible with segmentation models (masks aren't smoothed).
    """

    def __init__(self, length: int = 5) -> None:
        """
        Args:
            length (int): The maximum number of frames to consider for
                smoothing detections. Defaults to 5.
        """
        self.tracks = defaultdict(lambda: deque(maxlen=length))

    def update_with_detections(self, detections: Detections) -> Detections:
        """Updates the smoother with a new set of detections from a frame."""
        if detections.tracker_id is None:
            warnings.warn(
                "Smoothing skipped. DetectionsSmoother requires tracker_id."
            )
            return detections

        for detection_idx in range(len(detections)):
            tracker_id = detections.tracker_id[detection_idx]
            self.tracks[tracker_id].append(detections[detection_idx])

        for track_id in self.tracks.keys():
            if track_id not in detections.tracker_id:
                self.tracks[track_id].append(None)

        for track_id in list(self.tracks.keys()):
            if all(d is None for d in self.tracks[track_id]):
                del self.tracks[track_id]

        return self.get_smoothed_detections()

    def get_track(self, track_id: int) -> Detections | None:
        track = self.tracks.get(track_id, None)
        if track is None:
            return None

        track = [d for d in track if d is not None]
        if len(track) == 0:
            return None

        ret = deepcopy(track[0])
        ret.xyxy = np.mean([d.xyxy for d in track], axis=0)
        ret.confidence = np.mean([d.confidence for d in track], axis=0)
        return ret

    def get_smoothed_detections(self) -> Detections:
        tracked_detections = []
        for track_id in self.tracks:
            track = self.get_track(track_id)
            if track is not None:
                tracked_detections.append(track)

        if not tracked_detections:
            empty = Detections.empty()
            empty.tracker_id = np.array([], dtype=int)
            return empty

        xyxy = np.vstack([d.xyxy for d in tracked_detections])
        confidence = (
            np.hstack([d.confidence for d in tracked_detections])
            if all(d.confidence is not None for d in tracked_detections)
            else None
        )
        class_id = (
            np.hstack([d.class_id for d in tracked_detections])
            if all(d.class_id is not None for d in tracked_detections)
            else None
        )
        tracker_id = (
            np.hstack([d.tracker_id for d in tracked_detections])
            if all(d.tracker_id is not None for d in tracked_detections)
            else None
        )
        return Detections(
            xyxy=xyxy, confidence=confidence, class_id=class_id, tracker_id=tracker_id
        )
