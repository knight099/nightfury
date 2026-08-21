"""Source vendored from roboflow/supervision — see VENDORED_FROM.md for
exact provenance (upstream commit SHA, file, and line range per module).

Installed as source, not as a `supervision` pip dependency: the useful
surface for this pipeline (Detections, ByteTrack, LineZone, PolygonZone,
DetectionsSmoother) needs only numpy + scipy + the opencv-python-headless
already pinned. A plain `pip install supervision` would pull in
opencv-python (conflicts with the headless build this ARM edge box
needs), matplotlib, and several dataset/progress-bar dependencies this
pipeline never touches. See
docs/superpowers/plans/2026-08-21-supervision-tracking-refactor.md for
the full reasoning.
"""
from sv_vendor.geometry import Point, Position, Rect, Vector
from sv_vendor.detections import Detections
from sv_vendor.byte_tracker.core import ByteTrack
from sv_vendor.line_zone import LineZone

__all__ = ["Point", "Position", "Rect", "Vector", "Detections", "ByteTrack", "LineZone"]
