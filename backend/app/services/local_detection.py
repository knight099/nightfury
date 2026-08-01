"""Local ONNX detection (YOLO + pose) for the Test AI page.

Adapted from worker/yolo_detector.py and worker/pose_detector.py — same
models, same approach, kept as a separate copy since the backend and worker
are separate deployable services with no shared package today. Unlike the
worker's per-camera decide() (which needs CameraConfig zones/enabled_events),
this is a single-shot, camera-agnostic version: run both models on one
frame, and decide fastpath vs escalate purely on max detection confidence.
"""
import logging
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

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

KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
KP = {name: i for i, name in enumerate(KEYPOINT_NAMES)}
NUM_KEYPOINTS = 17
POSE_NMS_SCORE_THRESHOLD = 0.25
POSE_NMS_IOU_THRESHOLD = 0.45

STANDING_LEG_ANGLE_DEG = 160.0
CROUCHING_LEG_ANGLE_DEG = 120.0
SITTING_LEG_ANGLE_MIN_DEG = 70.0
SITTING_LEG_ANGLE_MAX_DEG = 110.0
BENDING_TORSO_TILT_DEG = 45.0
REACHING_WRIST_ABOVE_SHOULDER_RATIO = 0.05


@dataclass
class BBox:
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass
class YoloDetection:
    coco_class: str
    confidence: float
    bbox: BBox


@dataclass
class PersonPose:
    bbox: BBox
    keypoints: list
    label: str = "unknown"


def _letterbox(frame, size: int):
    h, w = frame.shape[:2]
    scale = min(size / h, size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(frame, (nw, nh))
    pad_x = (size - nw) // 2
    pad_y = (size - nh) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
    return canvas, scale, pad_x, pad_y


def _preprocess(letterboxed):
    rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
    normalized = rgb.astype(np.float32) / 255.0
    chw = normalized.transpose(2, 0, 1)
    return np.expand_dims(chw, axis=0)


class YoloDetector:
    """ONNX-based YOLOv8n inference, CPU-only, fail-soft if the model is unavailable."""

    def __init__(self):
        self.available = False
        self.session = None
        self.input_name = None
        try:
            import onnxruntime as ort
            self.session = ort.InferenceSession(
                settings.yolo_model_path, providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            self.available = True
            logger.info(f"YOLO model loaded from {settings.yolo_model_path}")
        except Exception as e:
            logger.error(f"YOLO model failed to load ({e}); local detection disabled")

    def detect(self, frame) -> list | None:
        if not self.available:
            return []
        try:
            size = settings.yolo_input_size
            letterboxed, scale, pad_x, pad_y = _letterbox(frame, size)
            blob = _preprocess(letterboxed)
            outputs = self.session.run(None, {self.input_name: blob})
            return self._postprocess(outputs[0], frame.shape, scale, pad_x, pad_y)
        except Exception as e:
            logger.warning(f"YOLO inference failed: {e}")
            return None

    def _postprocess(self, output, frame_shape, scale, pad_x, pad_y) -> list:
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
                bbox=BBox(x1=int(fx1), y1=int(fy1), x2=int(fx2), y2=int(fy2)),
            ))
        return detections


def _kp(keypoints, name, min_confidence):
    x, y, c = keypoints[KP[name]]
    if c < min_confidence:
        return None
    return (x, y)


def _angle_deg(a, b, c):
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cos_angle = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos_angle))


def _leg_angles(keypoints, min_confidence):
    angles = []
    for side in ("left", "right"):
        hip = _kp(keypoints, f"{side}_hip", min_confidence)
        knee = _kp(keypoints, f"{side}_knee", min_confidence)
        ankle = _kp(keypoints, f"{side}_ankle", min_confidence)
        if hip and knee and ankle:
            angle = _angle_deg(hip, knee, ankle)
            if angle is not None:
                angles.append(angle)
    return angles


def _torso_tilt_deg(keypoints, min_confidence):
    l_sh = _kp(keypoints, "left_shoulder", min_confidence)
    r_sh = _kp(keypoints, "right_shoulder", min_confidence)
    l_hip = _kp(keypoints, "left_hip", min_confidence)
    r_hip = _kp(keypoints, "right_hip", min_confidence)
    shoulders = [p for p in (l_sh, r_sh) if p]
    hips = [p for p in (l_hip, r_hip) if p]
    if not shoulders or not hips:
        return None
    sx = sum(p[0] for p in shoulders) / len(shoulders)
    sy = sum(p[1] for p in shoulders) / len(shoulders)
    hx = sum(p[0] for p in hips) / len(hips)
    hy = sum(p[1] for p in hips) / len(hips)
    dx, dy = hx - sx, hy - sy
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return None
    return math.degrees(math.atan2(abs(dx), abs(dy)))


def _is_reaching(keypoints, min_confidence):
    l_sh = _kp(keypoints, "left_shoulder", min_confidence)
    r_sh = _kp(keypoints, "right_shoulder", min_confidence)
    l_hip = _kp(keypoints, "left_hip", min_confidence)
    r_hip = _kp(keypoints, "right_hip", min_confidence)
    shoulders = [p for p in (l_sh, r_sh) if p]
    hips = [p for p in (l_hip, r_hip) if p]
    if not shoulders or not hips:
        return False
    shoulder_y = sum(p[1] for p in shoulders) / len(shoulders)
    torso_height = abs((sum(p[1] for p in hips) / len(hips)) - shoulder_y) or 1.0
    for side in ("left", "right"):
        wrist = _kp(keypoints, f"{side}_wrist", min_confidence)
        if wrist is None:
            continue
        if (shoulder_y - wrist[1]) > REACHING_WRIST_ABOVE_SHOULDER_RATIO * torso_height * 2:
            return True
    return False


def classify_pose(keypoints, min_confidence: float = 0.3) -> str:
    if _is_reaching(keypoints, min_confidence):
        return "reaching"
    tilt = _torso_tilt_deg(keypoints, min_confidence)
    if tilt is not None and tilt > BENDING_TORSO_TILT_DEG:
        return "bending"
    leg_angles = _leg_angles(keypoints, min_confidence)
    if leg_angles:
        best = max(leg_angles)
        if best < CROUCHING_LEG_ANGLE_DEG:
            return "crouching"
        if SITTING_LEG_ANGLE_MIN_DEG <= best <= SITTING_LEG_ANGLE_MAX_DEG:
            return "sitting"
        if best > STANDING_LEG_ANGLE_DEG:
            return "standing"
    return "unknown"


class PoseDetector:
    """ONNX-based YOLOv8-pose inference, CPU-only, fail-soft if unavailable."""

    def __init__(self):
        self.available = False
        self.session = None
        self.input_name = None
        try:
            import onnxruntime as ort
            self.session = ort.InferenceSession(
                settings.pose_model_path, providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            self.available = True
            logger.info(f"Pose model loaded from {settings.pose_model_path}")
        except Exception as e:
            logger.error(f"Pose model failed to load ({e}); pose overlay disabled")

    def detect(self, frame):
        if not self.available:
            return []
        size = settings.pose_input_size
        letterboxed, scale, pad_x, pad_y = _letterbox(frame, size)
        blob = _preprocess(letterboxed)
        try:
            outputs = self.session.run(None, {self.input_name: blob})
        except Exception as e:
            logger.warning(f"Pose inference failed: {e}")
            return None
        return self._postprocess(outputs[0], frame.shape, scale, pad_x, pad_y)

    def _postprocess(self, output, frame_shape, scale, pad_x, pad_y):
        preds = output[0].transpose(1, 0)
        boxes_cxcywh = preds[:, :4]
        confidences = preds[:, 4]
        kpts_raw = preds[:, 5:].reshape(-1, NUM_KEYPOINTS, 3)

        keep = confidences >= POSE_NMS_SCORE_THRESHOLD
        boxes_cxcywh = boxes_cxcywh[keep]
        confidences = confidences[keep]
        kpts_raw = kpts_raw[keep]
        if len(boxes_cxcywh) == 0:
            return []

        x1 = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
        y1 = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
        nms_boxes = np.stack([x1, y1, boxes_cxcywh[:, 2], boxes_cxcywh[:, 3]], axis=1)

        indices = cv2.dnn.NMSBoxes(
            nms_boxes.tolist(), confidences.tolist(),
            POSE_NMS_SCORE_THRESHOLD, POSE_NMS_IOU_THRESHOLD,
        )
        if len(indices) == 0:
            return []
        indices = np.array(indices).flatten()

        frame_h, frame_w = frame_shape[0], frame_shape[1]

        def rescale_point(x, y):
            fx = max(0, min(frame_w, (x - pad_x) / scale))
            fy = max(0, min(frame_h, (y - pad_y) / scale))
            return fx, fy

        poses = []
        for i in indices:
            bx1, by1, bw, bh = nms_boxes[i]
            bx2, by2 = bx1 + bw, by1 + bh
            fx1, fy1 = rescale_point(bx1, by1)
            fx2, fy2 = rescale_point(bx2, by2)
            keypoints = []
            for kx, ky, kc in kpts_raw[i]:
                rx, ry = rescale_point(kx, ky)
                keypoints.append((float(rx), float(ry), float(kc)))
            bbox = BBox(x1=int(fx1), y1=int(fy1), x2=int(fx2), y2=int(fy2))
            label = classify_pose(keypoints, settings.pose_keypoint_confidence)
            poses.append(PersonPose(bbox=bbox, keypoints=keypoints, label=label))
        return poses


# Module-level singletons — model load happens once per backend process,
# same fail-soft pattern as the worker (available=False if the file/package
# is missing, never crashes the app).
yolo_detector = YoloDetector()
pose_detector = PoseDetector()


@dataclass
class LocalAnalysis:
    detections: list  # list[YoloDetection]
    poses: list  # list[PersonPose]
    decision: str  # "fastpath" | "escalate"
    max_confidence: float
    inference_error: bool = False


def analyze_frame_locally(frame) -> LocalAnalysis:
    """Run YOLO + pose on one frame and decide fastpath vs escalate.

    Mirrors the worker's confidence-gated approach, simplified for a single
    ad-hoc frame with no camera/zone context: max detection confidence >=
    local_detection_fastpath_confidence -> fastpath (skip Gemini), else
    escalate. A YOLO inference error always escalates (fail toward Gemini,
    same as the worker), never silently drops.
    """
    detections = yolo_detector.detect(frame) if settings.local_detection_enabled else []
    poses = pose_detector.detect(frame) if settings.local_detection_enabled else []

    if detections is None:
        return LocalAnalysis(detections=[], poses=poses or [], decision="escalate", max_confidence=0.0, inference_error=True)

    max_confidence = max((d.confidence for d in detections), default=0.0)
    decision = "fastpath" if max_confidence >= settings.local_detection_fastpath_confidence else "escalate"
    return LocalAnalysis(detections=detections, poses=poses or [], decision=decision, max_confidence=max_confidence)
