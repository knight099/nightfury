"""Vendored from supervision/detection/utils/internal.py's cross_product
function — see VENDORED_FROM.md.
"""
from __future__ import annotations

import numpy as np

from sv_vendor.geometry import Vector


def cross_product(anchors: np.ndarray, vector: Vector) -> np.ndarray:
    """
    Get array of cross products of each anchor with a vector.

    Args:
        anchors: Array of anchors of shape (number of anchors, detections, 2).
        vector: Vector to calculate cross product with.

    Returns:
        Array of cross products of shape (number of anchors, detections).
    """
    vector_at_zero = np.array(
        [
            vector.end.x - vector.start.x,
            vector.end.y - vector.start.y,
        ]
    )
    vector_start = np.array([vector.start.x, vector.start.y])
    return np.cross(vector_at_zero, anchors - vector_start)
