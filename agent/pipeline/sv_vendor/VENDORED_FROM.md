# Vendored from roboflow/supervision

Source vendored, not `pip install`ed — see
`docs/superpowers/plans/2026-08-21-supervision-tracking-refactor.md` for why.

Upstream commit: `fd3de344dc9ba2dacd1e996ee6416b60d5e4d0d2` (roboflow/supervision `main` as of 2026-08-21).

| Local path | Upstream path | Notes |
|---|---|---|
| `geometry.py` | `supervision/geometry/core.py` | Verbatim. |
| `iou.py` | `supervision/detection/utils/iou_and_nms.py` | Trimmed to `OverlapMetric` + `box_iou_batch` only. |
| `detections.py` | `supervision/detection/core.py` | Heavily trimmed `Detections` dataclass — see module docstring for exactly what was dropped (all `from_*` classmethods, `merge()`, `with_nms`/`with_nmm`, area properties, upstream field validation). |
| `byte_tracker/kalman_filter.py` | `supervision/tracker/byte_tracker/kalman_filter.py` | Verbatim, imports fixed to `sv_vendor.*`. |
| `byte_tracker/matching.py` | `supervision/tracker/byte_tracker/matching.py` | Verbatim, imports fixed. |
| `byte_tracker/single_object_track.py` | `supervision/tracker/byte_tracker/single_object_track.py` | Verbatim, imports fixed. |
| `byte_tracker/utils.py` | `supervision/tracker/byte_tracker/utils.py` | Verbatim. |
| `byte_tracker/core.py` | `supervision/tracker/byte_tracker/core.py` | Verbatim (the `ByteTrack` class), imports fixed. |
| `cross_product.py` | `supervision/detection/utils/internal.py` | Just the `cross_product` function. |
| `line_zone.py` | `supervision/detection/line_zone.py` | Only the `LineZone` class (upstream lines 26–319 as of the pinned SHA) — `LineZoneAnnotator`/`LineZoneAnnotatorMulticlass` dropped. |
| `boxes.py` | `supervision/detection/utils/boxes.py` | Just `clip_boxes`. |
| `converters.py` | `supervision/detection/utils/converters.py` | Just `polygon_to_mask`. |
| `polygon_zone.py` | `supervision/detection/tools/polygon_zone.py` | Only the `PolygonZone` class — `PolygonZoneAnnotator` dropped. |
| `smoother.py` | `supervision/detection/tools/smoother.py` | Verbatim, imports fixed. |

To check for upstream bugfixes/security patches: diff the local file
against `https://raw.githubusercontent.com/roboflow/supervision/<upstream path>`
at a newer commit, re-apply the same trims, and update this table's SHA.
