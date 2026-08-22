"""Vendored from supervision/detection/utils/converters.py — only
polygon_to_mask. See VENDORED_FROM.md.
"""
from __future__ import annotations

import cv2
import numpy as np


def polygon_to_mask(polygon: np.ndarray, resolution_wh: tuple[int, int]) -> np.ndarray:
    """Generate a mask from a polygon.

    Args:
        polygon: The polygon vertices.
        resolution_wh: (width, height) of the desired mask resolution.

    Returns:
        A 2D mask, where the polygon is marked with 1's and the rest is 0's.
    """
    width, height = map(int, resolution_wh)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [polygon.astype(np.int32)], color=1)
    return mask
