"""Vendored from supervision/detection/tools/polygon_zone.py — only the
`PolygonZone` class. `PolygonZoneAnnotator` is dropped — this pipeline
never draws the zone outline onto video, so its cv2 drawing / draw-utils
dependencies are never pulled in. See VENDORED_FROM.md.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

import numpy as np
import numpy.typing as npt

from sv_vendor.boxes import clip_boxes
from sv_vendor.converters import polygon_to_mask
from sv_vendor.detections import Detections
from sv_vendor.geometry import Position


class PolygonZone:
    """
    A class for defining a polygon-shaped zone within a frame for detecting objects.

    !!! warning

        PolygonZone uses the `tracker_id`. Plug tracking into your inference
        pipeline before using this class if you need per-track state.

    Attributes:
        polygon (np.ndarray): A polygon represented by a numpy array of shape
            `(N, 2)`, containing the `x`, `y` coordinates of the points.
        triggering_anchors (Iterable[Position]): A list of positions specifying
            which anchors of the detections bounding box to consider when deciding
            on whether the detection fits within the PolygonZone
            (default: (Position.BOTTOM_CENTER,)).
        current_count (int): The current count of detected objects within the zone.
        mask (np.ndarray): The 2D bool mask for the polygon zone.
    """

    def __init__(
        self,
        polygon: npt.NDArray[np.int64],
        triggering_anchors: Iterable[Position] = (Position.BOTTOM_CENTER,),
    ):
        self.polygon = polygon.astype(int)
        self.triggering_anchors = triggering_anchors
        if not list(self.triggering_anchors):
            raise ValueError("Triggering anchors cannot be empty.")

        self.current_count = 0

        x_max, y_max = np.max(polygon, axis=0)
        self.frame_resolution_wh = (x_max + 1, y_max + 1)
        self.mask = polygon_to_mask(
            polygon=polygon, resolution_wh=(x_max + 2, y_max + 2)
        )

    def trigger(self, detections: Detections) -> npt.NDArray[np.bool_]:
        """
        Determines if the detections are within the polygon zone.

        Args:
            detections (Detections): The detections to check against the zone.

        Returns:
            np.ndarray: A boolean array indicating if each detection is within
                the polygon zone.
        """
        clipped_xyxy = clip_boxes(
            xyxy=detections.xyxy, resolution_wh=self.frame_resolution_wh
        )
        clipped_detections = replace(detections, xyxy=clipped_xyxy)
        all_clipped_anchors = np.array(
            [
                np.ceil(clipped_detections.get_anchors_coordinates(anchor)).astype(int)
                for anchor in self.triggering_anchors
            ]
        )

        is_in_zone: npt.NDArray[np.bool_] = (
            self.mask[all_clipped_anchors[:, :, 1], all_clipped_anchors[:, :, 0]]
            .transpose()
            .astype(bool)
        )

        is_in_zone: npt.NDArray[np.bool_] = np.all(is_in_zone, axis=1)
        self.current_count = int(np.sum(is_in_zone))
        return is_in_zone.astype(bool)
