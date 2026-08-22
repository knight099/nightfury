"""Vendored from supervision/detection/utils/boxes.py — only clip_boxes.
See VENDORED_FROM.md.
"""
from __future__ import annotations

import numpy as np


def clip_boxes(xyxy: np.ndarray, resolution_wh: tuple[int, int]) -> np.ndarray:
    """
    Clips bounding box coordinates to fit within the frame resolution.

    Args:
        xyxy: Array of shape (N, 4) as (x_min, y_min, x_max, y_max).
        resolution_wh: (width, height) of the frame.

    Returns:
        Array of shape (N, 4), clipped.
    """
    result = np.copy(xyxy)
    width, height = resolution_wh
    result[:, [0, 2]] = result[:, [0, 2]].clip(0, width)
    result[:, [1, 3]] = result[:, [1, 3]].clip(0, height)
    return result
