"""Vendored from supervision/detection/line_zone.py — only the `LineZone`
class (upstream lines 26-319 as of the pinned commit; see
VENDORED_FROM.md). `LineZoneAnnotator`/`LineZoneAnnotatorMulticlass` are
dropped — this pipeline never draws the line itself onto video, so their
cv2/draw/image dependencies are never pulled in.
"""
from __future__ import annotations

import warnings
from collections import Counter, defaultdict, deque
from collections.abc import Iterable

import numpy as np
import numpy.typing as npt

from sv_vendor.cross_product import cross_product
from sv_vendor.detections import Detections
from sv_vendor.geometry import Point, Position, Vector


class LineZone:
    """
    This class is responsible for counting the number of objects that cross a
    predefined line.

    !!! warning

        LineZone uses the `tracker_id`. Plug tracking into your inference
        pipeline before using this class.

    Attributes:
        in_count (int): The number of objects that have crossed the line from outside
            to inside.
        out_count (int): The number of objects that have crossed the line from inside
            to outside.
        in_count_per_class (Dict[int, int]): Number of objects of each class that have
            crossed the line from outside to inside.
        out_count_per_class (Dict[int, int]): Number of objects of each class that have
            crossed the line from inside to outside.
    """

    def __init__(
        self,
        start: Point,
        end: Point,
        triggering_anchors: Iterable[Position] = (
            Position.TOP_LEFT,
            Position.TOP_RIGHT,
            Position.BOTTOM_LEFT,
            Position.BOTTOM_RIGHT,
        ),
        minimum_crossing_threshold: int = 1,
    ):
        """
        Args:
            start (Point): The starting point of the line.
            end (Point): The ending point of the line.
            triggering_anchors (List[Position]): A list of positions
                specifying which anchors of the detections bounding box
                to consider when deciding on whether the detection
                has passed the line counter or not. By default, this
                contains the four corners of the detection's bounding box
            minimum_crossing_threshold (int): Detection needs to be seen
                on the other side of the line for this many frames to be
                considered as having crossed the line. This is useful when
                dealing with unstable bounding boxes or when detections
                may linger on the line.
        """
        self.vector = Vector(start=start, end=end)
        self.limits = self._calculate_region_of_interest_limits(vector=self.vector)
        self.crossing_history_length = max(2, minimum_crossing_threshold + 1)
        self.crossing_state_history: dict[int, deque[bool]] = defaultdict(
            lambda: deque(maxlen=self.crossing_history_length)
        )
        self._in_count_per_class: Counter = Counter()
        self._out_count_per_class: Counter = Counter()
        self.triggering_anchors = triggering_anchors
        if not list(self.triggering_anchors):
            raise ValueError("Triggering anchors cannot be empty.")
        self.class_id_to_name: dict[int, str] = {}

    @property
    def in_count(self) -> int:
        return sum(self._in_count_per_class.values())

    @property
    def out_count(self) -> int:
        return sum(self._out_count_per_class.values())

    @property
    def in_count_per_class(self) -> dict[int, int]:
        return dict(self._in_count_per_class)

    @property
    def out_count_per_class(self) -> dict[int, int]:
        return dict(self._out_count_per_class)

    def trigger(self, detections: Detections) -> tuple[np.ndarray, np.ndarray]:
        """
        Update the `in_count` and `out_count` based on the objects that cross the line.

        Args:
            detections (Detections): A list of detections for which to update the
                counts.

        Returns:
            A tuple of two boolean NumPy arrays. The first array indicates which
                detections have crossed the line from outside to inside. The second
                array indicates which detections have crossed the line from inside to
                outside.
        """
        crossed_in = np.full(len(detections), False)
        crossed_out = np.full(len(detections), False)

        if len(detections) == 0:
            return crossed_in, crossed_out

        if detections.tracker_id is None:
            warnings.warn(
                "Line zone counting skipped. LineZone requires tracker_id. Plug "
                "tracking into your inference pipeline before using this class."
            )
            return crossed_in, crossed_out

        self._update_class_id_to_name(detections)

        in_limits, has_any_left_trigger, has_any_right_trigger = (
            self._compute_anchor_sides(detections)
        )

        class_ids: list[int | None] = (
            list(detections.class_id)
            if detections.class_id is not None
            else [None] * len(detections)
        )

        for i, (class_id, tracker_id) in enumerate(
            zip(class_ids, detections.tracker_id)
        ):
            if not in_limits[i]:
                continue

            if has_any_left_trigger[i] and has_any_right_trigger[i]:
                continue

            tracker_state: bool = has_any_left_trigger[i]
            crossing_history = self.crossing_state_history[tracker_id]
            crossing_history.append(tracker_state)

            if len(crossing_history) < self.crossing_history_length:
                continue

            oldest_state = crossing_history[0]
            if crossing_history.count(oldest_state) > 1:
                continue

            if tracker_state:
                self._in_count_per_class[class_id] += 1
                crossed_in[i] = True
            else:
                self._out_count_per_class[class_id] += 1
                crossed_out[i] = True

        return crossed_in, crossed_out

    @staticmethod
    def _calculate_region_of_interest_limits(vector: Vector) -> tuple[Vector, Vector]:
        magnitude = vector.magnitude

        if magnitude == 0:
            raise ValueError("The magnitude of the vector cannot be zero.")

        delta_x = vector.end.x - vector.start.x
        delta_y = vector.end.y - vector.start.y

        unit_vector_x = delta_x / magnitude
        unit_vector_y = delta_y / magnitude

        perpendicular_vector_x = -unit_vector_y
        perpendicular_vector_y = unit_vector_x

        start_region_limit = Vector(
            start=vector.start,
            end=Point(
                x=vector.start.x + perpendicular_vector_x,
                y=vector.start.y + perpendicular_vector_y,
            ),
        )
        end_region_limit = Vector(
            start=vector.end,
            end=Point(
                x=vector.end.x - perpendicular_vector_x,
                y=vector.end.y - perpendicular_vector_y,
            ),
        )
        return start_region_limit, end_region_limit

    def _compute_anchor_sides(
        self, detections: Detections
    ) -> tuple[npt.NDArray[np.bool_], npt.NDArray[np.bool_], npt.NDArray[np.bool_]]:
        """
        Find if detections' anchors are within the limit of the line
        zone and which anchors are on its left and right side.

        Limits:
        ```
                |    IN    ↑
                |          |
          OUT   o---LINE---o   OUT
                |          |
                ↓    IN    |
        ```
        """
        assert len(detections) > 0
        assert detections.tracker_id is not None

        all_anchors = np.array(
            [
                detections.get_anchors_coordinates(anchor)
                for anchor in self.triggering_anchors
            ]
        )

        cross_products_1 = cross_product(all_anchors, self.limits[0])
        cross_products_2 = cross_product(all_anchors, self.limits[1])

        # Works because limit vectors are pointing in opposite directions
        in_limits = (cross_products_1 > 0) == (cross_products_2 > 0)
        in_limits = np.all(in_limits, axis=0)

        triggers = cross_product(all_anchors, self.vector) < 0
        has_any_left_trigger = np.any(triggers, axis=0)
        has_any_right_trigger = np.any(~triggers, axis=0)

        return in_limits, has_any_left_trigger, has_any_right_trigger

    def _update_class_id_to_name(self, detections: Detections) -> None:
        """
        Update the attribute keeping track of which class
        IDs correspond to which class names.

        Assumes that class_names are only provided when class_ids are.
        """
        class_names = detections.data.get("class_name")
        assert class_names is None or detections.class_id is not None

        if detections.class_id is None:
            return

        if class_names is None:
            new_names = {class_id: str(class_id) for class_id in detections.class_id}
        else:
            new_names = {
                class_id: class_name
                for class_id, class_name in zip(detections.class_id, class_names)
            }
        self.class_id_to_name.update(new_names)
