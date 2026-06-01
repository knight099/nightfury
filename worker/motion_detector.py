import cv2
import numpy as np

from config import config


class MotionDetector:
    """Fast frame-difference based motion detection to gate expensive AI calls."""

    def __init__(self):
        self.prev_gray: np.ndarray | None = None
        self.threshold = config.motion_threshold
        self.pixel_threshold = config.motion_pixel_threshold

    def detect(self, frame: np.ndarray) -> tuple[bool, float]:
        """
        Returns (has_motion, motion_ratio).
        motion_ratio is the fraction of pixels that changed significantly.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self.prev_gray is None:
            self.prev_gray = gray
            return False, 0.0

        diff = cv2.absdiff(self.prev_gray, gray)
        _, thresh = cv2.threshold(diff, self.pixel_threshold, 255, cv2.THRESH_BINARY)

        motion_pixels = np.count_nonzero(thresh)
        total_pixels = thresh.shape[0] * thresh.shape[1]
        motion_ratio = motion_pixels / total_pixels

        self.prev_gray = gray
        return motion_ratio > self.threshold, motion_ratio

    def reset(self):
        self.prev_gray = None
