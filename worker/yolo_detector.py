import logging
from dataclasses import dataclass, field

from models import BoundingBox, CameraConfig, DetectedEvent

logger = logging.getLogger(__name__)

COCO_TO_EVENT_TYPE = {
    "person": "person",
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "motorcycle": "vehicle",
    "dog": "animal",
    "cat": "animal",
    "bird": "animal",
    "horse": "animal",
}

FASTPATH_EVENT_TYPES = {"person", "vehicle", "animal", "intrusion"}


@dataclass
class YoloDetection:
    coco_class: str
    confidence: float
    bbox: BoundingBox


def point_in_polygon(x: float, y: float, points: list) -> bool:
    """Ray-casting point-in-polygon test. points is a list of [x, y] pairs."""
    if len(points) < 3:
        return False
    inside = False
    n = len(points)
    j = n - 1
    for i in range(n):
        xi, yi = points[i][0], points[i][1]
        xj, yj = points[j][0], points[j][1]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _zone_containing(bbox: BoundingBox, zones: list) -> str | None:
    cx = (bbox.x1 + bbox.x2) / 2
    cy = (bbox.y1 + bbox.y2) / 2
    for zone in zones:
        points = zone.get("points", [])
        if point_in_polygon(cx, cy, points):
            return zone.get("name", "unnamed")
    return None


def map_detections(detections: list, camera_config: CameraConfig) -> list:
    """Maps raw YOLO detections to (event_type, detection, zone_name) candidates."""
    results = []
    for d in detections:
        event_type = COCO_TO_EVENT_TYPE.get(d.coco_class)
        if event_type is None:
            continue
        results.append((event_type, d, None))
        if event_type == "person":
            zone = _zone_containing(d.bbox, camera_config.detection_zones)
            if zone is not None:
                results.append(("intrusion", d, zone))
    return results


@dataclass
class Decision:
    action: str  # "drop", "escalate", or "emit"
    events: list = field(default_factory=list)


def decide(
    detections: list,
    camera_config: CameraConfig,
    fastpath_confidence: float,
    escalate_floor: float,
) -> Decision:
    """Three-way decision: drop (no relevant detection), escalate to Gemini,
    or emit events directly from YOLO output."""
    enabled = set(camera_config.enabled_events)
    if not enabled.issubset(FASTPATH_EVENT_TYPES):
        return Decision(action="escalate")

    candidates = [c for c in map_detections(detections, camera_config) if c[0] in enabled]
    if not candidates:
        return Decision(action="drop")

    best_confidence = max(c[1].confidence for c in candidates)
    if best_confidence < escalate_floor:
        return Decision(action="drop")
    if best_confidence < fastpath_confidence:
        return Decision(action="escalate")

    qualifying = [c for c in candidates if c[1].confidence >= fastpath_confidence]
    return Decision(action="emit", events=_build_events(qualifying))


def _build_events(qualifying: list) -> list:
    events = []

    for event_type in ("person", "vehicle", "animal"):
        group = [c for c in qualifying if c[0] == event_type]
        if not group:
            continue
        count = len(group)
        confidence = max(c[1].confidence for c in group)
        bboxes = [
            BoundingBox(x1=c[1].bbox.x1, y1=c[1].bbox.y1, x2=c[1].bbox.x2, y2=c[1].bbox.y2, label=c[1].coco_class)
            for c in group
        ]
        events.append(DetectedEvent(
            event_type=event_type,
            confidence=confidence,
            severity="low",
            description=f"{count} {event_type} detected",
            bounding_boxes=bboxes,
        ))

    intrusions = [c for c in qualifying if c[0] == "intrusion"]
    zones = {}
    for c in intrusions:
        zones.setdefault(c[2], []).append(c)
    for zone_name, group in zones.items():
        count = len(group)
        confidence = max(c[1].confidence for c in group)
        bboxes = [
            BoundingBox(x1=c[1].bbox.x1, y1=c[1].bbox.y1, x2=c[1].bbox.x2, y2=c[1].bbox.y2, label=c[1].coco_class)
            for c in group
        ]
        description = (
            f"Person detected in {zone_name} zone" if count == 1
            else f"{count} people detected in {zone_name} zone"
        )
        events.append(DetectedEvent(
            event_type="intrusion",
            confidence=confidence,
            severity="medium",
            description=description,
            bounding_boxes=bboxes,
            zone=zone_name,
        ))

    return events
