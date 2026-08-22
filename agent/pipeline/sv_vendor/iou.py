"""Trimmed from supervision/detection/utils/iou_and_nms.py — only the
box-IOU path ByteTrack/LineZone/PolygonZone actually use. The rest of that
upstream file (OverlapFilter, mask-IOU, NMS/NMM merge logic) is dropped;
see agent/pipeline/sv_vendor/VENDORED_FROM.md for provenance.
"""
from __future__ import annotations

from enum import Enum

import numpy as np


class OverlapMetric(Enum):
    """
    Attributes:
        IOU: Intersection over Union.
        IOS: Intersection over Smaller.
    """

    IOU = "IOU"
    IOS = "IOS"

    @classmethod
    def list(cls) -> list[str]:
        return list(map(lambda c: c.value, cls))

    @classmethod
    def from_value(cls, value: "OverlapMetric | str") -> "OverlapMetric":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            value = value.upper()
            try:
                return cls(value)
            except ValueError:
                raise ValueError(f"Invalid value: {value}. Must be one of {cls.list()}")
        raise ValueError(
            f"Invalid value type: {type(value)}. Must be an instance of "
            f"{cls.__name__} or str."
        )


def box_iou_batch(
    boxes_true: np.ndarray,
    boxes_detection: np.ndarray,
    overlap_metric: "OverlapMetric | str" = OverlapMetric.IOU,
) -> np.ndarray:
    """
    Compute pairwise overlap scores between batches of bounding boxes.

    Args:
        boxes_true: Array of shape (N, 4) as (x_min, y_min, x_max, y_max).
        boxes_detection: Array of shape (M, 4) as (x_min, y_min, x_max, y_max).
        overlap_metric: IOU or IOS.

    Returns:
        Overlap matrix of shape (N, M).
    """
    overlap_metric = OverlapMetric.from_value(overlap_metric)
    x_min_true, y_min_true, x_max_true, y_max_true = boxes_true.T
    x_min_det, y_min_det, x_max_det, y_max_det = boxes_detection.T
    count_true, count_det = boxes_true.shape[0], boxes_detection.shape[0]

    if count_true == 0 or count_det == 0:
        return np.empty((count_true, count_det), dtype=np.float32)

    x_min_inter = np.empty((count_true, count_det), dtype=np.float32)
    x_max_inter = np.empty_like(x_min_inter)
    y_min_inter = np.empty_like(x_min_inter)
    y_max_inter = np.empty_like(x_min_inter)

    np.maximum(x_min_true[:, None], x_min_det[None, :], out=x_min_inter)
    np.minimum(x_max_true[:, None], x_max_det[None, :], out=x_max_inter)
    np.maximum(y_min_true[:, None], y_min_det[None, :], out=y_min_inter)
    np.minimum(y_max_true[:, None], y_max_det[None, :], out=y_max_inter)

    # we reuse x_max_inter and y_max_inter to store inter_w and inter_h
    np.subtract(x_max_inter, x_min_inter, out=x_max_inter)  # inter_w
    np.subtract(y_max_inter, y_min_inter, out=y_max_inter)  # inter_h
    np.clip(x_max_inter, 0.0, None, out=x_max_inter)
    np.clip(y_max_inter, 0.0, None, out=y_max_inter)

    area_inter = x_max_inter * y_max_inter  # inter_w * inter_h

    area_true = (x_max_true - x_min_true) * (y_max_true - y_min_true)
    area_det = (x_max_det - x_min_det) * (y_max_det - y_min_det)

    if overlap_metric == OverlapMetric.IOU:
        area_norm = area_true[:, None] + area_det[None, :] - area_inter
    elif overlap_metric == OverlapMetric.IOS:
        area_norm = np.minimum(area_true[:, None], area_det[None, :])
    else:
        raise ValueError(
            f"overlap_metric {overlap_metric} is not supported, "
            "only 'IOU' and 'IOS' are supported"
        )

    out = np.zeros_like(area_inter, dtype=np.float32)
    np.divide(area_inter, area_norm, out=out, where=area_norm > 0)
    return out
