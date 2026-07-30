"""Local YOLOv8n (ONNX) object detection for the Test AI page's YOLO+Gemini
test agent (POST /api/test-camera/analyze-yolo-gemini).

This is a backend-owned port of worker/yolo_detector.py's gate/fastpath/escalate
logic. It is NOT shared code with the worker — backend and worker are separately
deployed services with independent dependency trees, so the worker's module
can't be imported directly. This copy is deliberately narrower than the
worker's: it only ever considers person/vehicle/animal (no detection zones are
collected on the Test AI page, so "intrusion" is out of scope here — a person
always emits as a plain "person" event, never derived as an intrusion).
"""
import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import settings

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


@dataclass
class BoundingBox:
    x1: int
    y1: int
    x2: int
    y2: int
    label: str


@dataclass
class YoloDetection:
    coco_class: str
    confidence: float
    bbox: BoundingBox


@dataclass
class YoloEvent:
    event_type: str
    confidence: float
    severity: str
    description: str
    bounding_boxes: list = field(default_factory=list)


@dataclass
class Decision:
    action: str  # "drop", "escalate", or "fastpath"
    detections: list = field(default_factory=list)
    events: list = field(default_factory=list)


def decide(detections: list, fastpath_confidence: float, escalate_floor: float) -> Decision:
    """Three-way decision over a fixed person/vehicle/animal event set:
    drop (no relevant detection), escalate to Gemini, or fastpath (emit
    events directly from YOLO output, no Gemini call).

    `detections` must be a real list (possibly empty) of YoloDetection — never
    None. A None result from YoloTestDetector.detect() means inference errored
    and must be handled by the caller (escalate to Gemini) before decide() is
    ever invoked."""
    candidates = [(COCO_TO_EVENT_TYPE[d.coco_class], d) for d in detections if d.coco_class in COCO_TO_EVENT_TYPE]
    if not candidates:
        return Decision(action="drop", detections=detections)

    best_confidence = max(d.confidence for _, d in candidates)
    if best_confidence < escalate_floor:
        return Decision(action="drop", detections=detections)
    if best_confidence < fastpath_confidence:
        return Decision(action="escalate", detections=detections)

    qualifying = [(t, d) for t, d in candidates if d.confidence >= fastpath_confidence]
    return Decision(action="fastpath", detections=detections, events=_build_events(qualifying))


def _build_events(qualifying: list) -> list:
    events = []
    for event_type in ("person", "vehicle", "animal"):
        group = [d for t, d in qualifying if t == event_type]
        if not group:
            continue
        count = len(group)
        confidence = max(d.confidence for d in group)
        bboxes = [
            BoundingBox(x1=d.bbox.x1, y1=d.bbox.y1, x2=d.bbox.x2, y2=d.bbox.y2, label=d.coco_class)
            for d in group
        ]
        events.append(YoloEvent(
            event_type=event_type,
            confidence=confidence,
            severity="low",
            description=f"{count} {event_type} detected",
            bounding_boxes=bboxes,
        ))
    return events


class YoloTestDetector:
    """ONNX-based YOLOv8n inference, CPU-only, fail-soft if the model is unavailable."""

    def __init__(self):
        self.available = False
        self.session = None
        self.input_name = None
        try:
            import onnxruntime as ort
            self.session = ort.InferenceSession(
                settings.yolo_test_model_path, providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            self.available = True
            logger.info(f"YOLO test model loaded from {settings.yolo_test_model_path}")
        except Exception as e:
            logger.error(
                f"YOLO test model failed to load ({e}); every test-agent call "
                "will escalate straight to Gemini"
            )

    def detect(self, frame: np.ndarray) -> list | None:
        """Returns a list of YoloDetection on a clean run (possibly empty if
        nothing was found), or None if inference threw mid-run. Callers must
        NOT treat None the same as an empty list — None means the frame could
        not be evaluated and should escalate to Gemini instead of being
        silently dropped."""
        if not self.available:
            return []
        try:
            size = settings.yolo_test_input_size
            letterboxed, scale, pad_x, pad_y = self._letterbox(frame, size)
            blob = self._preprocess(letterboxed)
            outputs = self.session.run(None, {self.input_name: blob})
            return self._postprocess(outputs[0], frame.shape, scale, pad_x, pad_y)
        except Exception as e:
            logger.warning(f"YOLO test inference failed: {e}")
            return None

    def _letterbox(self, frame: np.ndarray, size: int):
        h, w = frame.shape[:2]
        scale = min(size / h, size / w)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        resized = cv2.resize(frame, (nw, nh))
        pad_x = (size - nw) // 2
        pad_y = (size - nh) // 2
        canvas = np.full((size, size, 3), 114, dtype=np.uint8)
        canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
        return canvas, scale, pad_x, pad_y

    def _preprocess(self, letterboxed: np.ndarray) -> np.ndarray:
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


_detector: YoloTestDetector | None = None


def get_yolo_test_detector() -> YoloTestDetector:
    """Lazily initialize the ONNX session once per process (not per-request)."""
    global _detector
    if _detector is None:
        _detector = YoloTestDetector()
    return _detector
