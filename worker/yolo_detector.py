import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from config import config
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


COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]

YOLO_NMS_SCORE_THRESHOLD = 0.25
YOLO_NMS_IOU_THRESHOLD = 0.45


class YoloDetector:
    """ONNX-based YOLOv8n inference, CPU-only, fail-soft if the model is unavailable."""

    def __init__(self):
        self.available = False
        self.session = None
        self.input_name = None
        try:
            import onnxruntime as ort
            self.session = ort.InferenceSession(
                config.yolo_model_path, providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            self.available = True
            logger.info(f"YOLO model loaded from {config.yolo_model_path}")
        except Exception as e:
            logger.error(
                f"YOLO model failed to load ({e}); YOLO gating disabled, "
                "all frames will escalate to Gemini as before"
            )

    def detect(self, frame) -> list:
        if not self.available:
            return []
        size = config.yolo_input_size
        letterboxed, scale, pad_x, pad_y = self._letterbox(frame, size)
        blob = self._preprocess(letterboxed)

        try:
            outputs = self.session.run(None, {self.input_name: blob})
        except Exception as e:
            logger.warning(f"YOLO inference failed: {e}")
            return []

        return self._postprocess(outputs[0], frame.shape, scale, pad_x, pad_y)

    def _letterbox(self, frame, size: int):
        h, w = frame.shape[:2]
        scale = min(size / h, size / w)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        resized = cv2.resize(frame, (nw, nh))
        pad_x = (size - nw) // 2
        pad_y = (size - nh) // 2
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        return canvas, scale, pad_x, pad_y

    def _preprocess(self, letterboxed):
        rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
        normalized = rgb.astype(np.float32) / 255.0
        chw = normalized.transpose(2, 0, 1)
        return np.expand_dims(chw, axis=0)

    def _postprocess(self, output, frame_shape, scale, pad_x, pad_y) -> list:
        # output shape: (1, 84, N) -> (N, 84): 4 bbox coords (cx,cy,w,h) + 80 class scores
        preds = output[0].transpose(1, 0)
        boxes_cxcywh = preds[:, :4]
        class_scores = preds[:, 4:]
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(len(class_scores)), class_ids]

        keep = confidences >= YOLO_NMS_SCORE_THRESHOLD
        boxes_cxcywh = boxes_cxcywh[keep]
        class_ids = class_ids[keep]
        confidences = confidences[keep]

        if len(boxes_cxcywh) == 0:
            return []

        x1 = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
        y1 = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
        nms_boxes = np.stack([x1, y1, boxes_cxcywh[:, 2], boxes_cxcywh[:, 3]], axis=1)

        indices = cv2.dnn.NMSBoxes(
            nms_boxes.tolist(), confidences.tolist(),
            YOLO_NMS_SCORE_THRESHOLD, YOLO_NMS_IOU_THRESHOLD,
        )
        if len(indices) == 0:
            return []
        indices = np.array(indices).flatten()

        frame_h, frame_w = frame_shape[0], frame_shape[1]
        detections = []
        for i in indices:
            bx1, by1, bw, bh = nms_boxes[i]
            bx2, by2 = bx1 + bw, by1 + bh
            fx1 = max(0, min(frame_w, (bx1 - pad_x) / scale))
            fy1 = max(0, min(frame_h, (by1 - pad_y) / scale))
            fx2 = max(0, min(frame_w, (bx2 - pad_x) / scale))
            fy2 = max(0, min(frame_h, (by2 - pad_y) / scale))

            class_id = int(class_ids[i])
            coco_class = COCO_CLASSES[class_id] if class_id < len(COCO_CLASSES) else "unknown"
            detections.append(YoloDetection(
                coco_class=coco_class,
                confidence=float(confidences[i]),
                bbox=BoundingBox(x1=int(fx1), y1=int(fy1), x2=int(fx2), y2=int(fy2), label=coco_class),
            ))
        return detections
