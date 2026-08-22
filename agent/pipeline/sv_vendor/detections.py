"""Trimmed from supervision/detection/core.py's `Detections` class.

Upstream is ~2500 lines, of which only the following (verified
self-contained during planning — see
agent/pipeline/sv_vendor/VENDORED_FROM.md) are relevant here: this
pipeline builds Detections from its own ONNX postprocessing output, never
from ultralytics/transformers/detectron2/etc., so every `from_*`
classmethod, `merge()`, `with_nms`/`with_nmm`, and the `area`/`box_area`/
`box_aspect_ratio` properties are dropped. `__post_init__`'s upstream
field-shape validation is also dropped — this pipeline always constructs
Detections from well-formed arrays — but kept as a no-op so a future
contributor has an obvious place to add it back.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from sv_vendor.geometry import Position


@dataclass
class Detections:
    """
    Attributes:
        xyxy (np.ndarray): shape (n, 4), [x1, y1, x2, y2].
        mask (Optional[np.ndarray]): shape (n, H, W), bool.
        confidence (Optional[np.ndarray]): shape (n,).
        class_id (Optional[np.ndarray]): shape (n,).
        tracker_id (Optional[np.ndarray]): shape (n,).
        data (dict): per-detection extra data, arrays/lists of length n.
        metadata (dict): collection-level metadata.
    """

    xyxy: np.ndarray
    mask: np.ndarray | None = None
    confidence: np.ndarray | None = None
    class_id: np.ndarray | None = None
    tracker_id: np.ndarray | None = None
    data: dict[str, np.ndarray | list] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        pass

    def __len__(self):
        return len(self.xyxy)

    def __iter__(
        self,
    ) -> Iterator[
        tuple[
            np.ndarray,
            np.ndarray | None,
            float | None,
            int | None,
            int | None,
            dict[str, np.ndarray | list],
        ]
    ]:
        for i in range(len(self.xyxy)):
            yield (
                self.xyxy[i],
                self.mask[i] if self.mask is not None else None,
                self.confidence[i] if self.confidence is not None else None,
                self.class_id[i] if self.class_id is not None else None,
                self.tracker_id[i] if self.tracker_id is not None else None,
                self._data_item(i),
            )

    def __eq__(self, other: "Detections") -> bool:
        return all(
            [
                np.array_equal(self.xyxy, other.xyxy),
                np.array_equal(self.mask, other.mask),
                np.array_equal(self.class_id, other.class_id),
                np.array_equal(self.confidence, other.confidence),
                np.array_equal(self.tracker_id, other.tracker_id),
                self.data == other.data,
                self.metadata == other.metadata,
            ]
        )

    @classmethod
    def empty(cls) -> "Detections":
        return cls(
            xyxy=np.empty((0, 4), dtype=np.float32),
            confidence=np.array([], dtype=np.float32),
            class_id=np.array([], dtype=int),
        )

    def is_empty(self) -> bool:
        empty_detections = Detections.empty()
        empty_detections.data = self.data
        empty_detections.metadata = self.metadata
        return self == empty_detections

    def get_anchors_coordinates(self, anchor: Position) -> np.ndarray:
        """
        Returns an (n, 2) array of [x, y] anchor coordinates for the given
        Position, computed from xyxy.
        """
        if anchor == Position.CENTER:
            return np.array(
                [
                    (self.xyxy[:, 0] + self.xyxy[:, 2]) / 2,
                    (self.xyxy[:, 1] + self.xyxy[:, 3]) / 2,
                ]
            ).transpose()
        elif anchor == Position.CENTER_OF_MASS:
            raise ValueError(
                "Position.CENTER_OF_MASS requires a detection mask, and this "
                "trimmed Detections does not implement mask centroids "
                "(upstream calculate_masks_centroids was dropped as unused)."
            )
        elif anchor == Position.CENTER_LEFT:
            return np.array(
                [
                    self.xyxy[:, 0],
                    (self.xyxy[:, 1] + self.xyxy[:, 3]) / 2,
                ]
            ).transpose()
        elif anchor == Position.CENTER_RIGHT:
            return np.array(
                [
                    self.xyxy[:, 2],
                    (self.xyxy[:, 1] + self.xyxy[:, 3]) / 2,
                ]
            ).transpose()
        elif anchor == Position.BOTTOM_CENTER:
            return np.array(
                [(self.xyxy[:, 0] + self.xyxy[:, 2]) / 2, self.xyxy[:, 3]]
            ).transpose()
        elif anchor == Position.BOTTOM_LEFT:
            return np.array([self.xyxy[:, 0], self.xyxy[:, 3]]).transpose()
        elif anchor == Position.BOTTOM_RIGHT:
            return np.array([self.xyxy[:, 2], self.xyxy[:, 3]]).transpose()
        elif anchor == Position.TOP_CENTER:
            return np.array(
                [(self.xyxy[:, 0] + self.xyxy[:, 2]) / 2, self.xyxy[:, 1]]
            ).transpose()
        elif anchor == Position.TOP_LEFT:
            return np.array([self.xyxy[:, 0], self.xyxy[:, 1]]).transpose()
        elif anchor == Position.TOP_RIGHT:
            return np.array([self.xyxy[:, 2], self.xyxy[:, 1]]).transpose()

        raise ValueError(f"{anchor} is not supported.")

    def _data_item(self, index: int) -> dict[str, Any]:
        return {k: v[index] for k, v in self.data.items()}

    def __getitem__(
        self, index: "int | slice | list[int] | np.ndarray | str"
    ) -> "Detections | list | np.ndarray | None":
        if isinstance(index, str):
            return self.data.get(index)
        if self.is_empty():
            return self
        if isinstance(index, int):
            index = [index]
        return Detections(
            xyxy=self.xyxy[index],
            mask=self.mask[index] if self.mask is not None else None,
            confidence=self.confidence[index] if self.confidence is not None else None,
            class_id=self.class_id[index] if self.class_id is not None else None,
            tracker_id=self.tracker_id[index] if self.tracker_id is not None else None,
            data={
                k: (v[index] if isinstance(v, np.ndarray) else [v[i] for i in index])
                for k, v in self.data.items()
            },
            metadata=self.metadata,
        )
