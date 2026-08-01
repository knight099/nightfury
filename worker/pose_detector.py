import logging
import math
from dataclasses import dataclass, field

from models import BoundingBox

logger = logging.getLogger(__name__)

# COCO-17 keypoint order, as emitted by YOLOv8-pose.
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
]
KP = {name: i for i, name in enumerate(KEYPOINT_NAMES)}

POSE_LABELS = {"standing", "bending", "crouching", "sitting", "reaching", "unknown"}

STANDING_LEG_ANGLE_DEG = 160.0
CROUCHING_LEG_ANGLE_DEG = 120.0
SITTING_LEG_ANGLE_MIN_DEG = 70.0
SITTING_LEG_ANGLE_MAX_DEG = 110.0
BENDING_TORSO_TILT_DEG = 45.0
REACHING_WRIST_ABOVE_SHOULDER_RATIO = 0.05  # fraction of frame-independent bbox height


@dataclass
class PersonPose:
    bbox: BoundingBox
    keypoints: list  # list[tuple[float, float, float]], (x, y, confidence) x 17, COCO order
    label: str = "unknown"


def _kp(keypoints, name, min_confidence):
    x, y, c = keypoints[KP[name]]
    if c < min_confidence:
        return None
    return (x, y)


def _angle_deg(a, b, c) -> float | None:
    """Angle ABC at vertex b, in degrees. a, b, c are (x, y) tuples."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cos_angle = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    cos_angle = max(-1.0, min(1.0, cos_angle))
    return math.degrees(math.acos(cos_angle))


def _leg_angles(keypoints, min_confidence) -> list:
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


def _torso_tilt_deg(keypoints, min_confidence) -> float | None:
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


def _is_reaching(keypoints, min_confidence) -> bool:
    l_sh = _kp(keypoints, "left_shoulder", min_confidence)
    r_sh = _kp(keypoints, "right_shoulder", min_confidence)
    l_hip = _kp(keypoints, "left_hip", min_confidence)
    r_hip = _kp(keypoints, "right_hip", min_confidence)
    shoulders = [p for p in (l_sh, r_sh) if p]
    hips = [p for p in (l_hip, r_hip) if p]
    if not shoulders or not hips:
        return False
    shoulder_y = sum(p[1] for p in shoulders) / len(shoulders)
    torso_height = abs(
        (sum(p[1] for p in hips) / len(hips)) - shoulder_y
    ) or 1.0

    for side in ("left", "right"):
        wrist = _kp(keypoints, f"{side}_wrist", min_confidence)
        if wrist is None:
            continue
        # A wrist meaningfully above shoulder height (smaller y = higher in image).
        if (shoulder_y - wrist[1]) > REACHING_WRIST_ABOVE_SHOULDER_RATIO * torso_height * 2:
            return True
    return False


def classify_pose(keypoints, min_confidence: float = 0.3) -> str:
    """Classify a person's pose from 17 COCO keypoints using geometric heuristics.

    keypoints: list of 17 (x, y, confidence) tuples, COCO order (see KEYPOINT_NAMES).
    Priority order avoids ambiguous double-fires: reaching > bending > crouching > sitting > standing.
    Returns "unknown" if no rule has enough visible keypoints to fire.
    """
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
