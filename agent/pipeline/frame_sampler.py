import time

import cv2
import numpy as np

from config import config


class FrameSampler:
    """
    Adaptive frame sampling: sends frames to AI at controlled rate.
    IDLE state: 1 frame/sec. ACTIVE state (motion): 5 frames/sec.
    Also deduplicates very similar frames to avoid wasting API calls.
    """

    STATE_IDLE = "idle"
    STATE_ACTIVE = "active"

    def __init__(self, idle_fps: float | None = None, active_fps: float | None = None):
        self.idle_fps = idle_fps or config.idle_fps
        self.active_fps = active_fps or config.active_fps
        # Runtime sampling multiplier, 0 < factor <= 1, set by the supervisor
        # when the box is over capacity. Scaling here rather than editing
        # idle_fps/active_fps keeps the stream signature unchanged, so
        # degrading load does not restart every stream on the box.
        self.load_factor: float = 1.0
        self.state = self.STATE_IDLE
        self.last_sample_time: float = 0
        self.last_motion_time: float = 0
        self.last_sampled_gray: np.ndarray | None = None

    def should_sample(self, frame: np.ndarray, has_motion: bool) -> bool:
        """Decide whether this frame should be sent to AI."""
        now = time.time()

        if has_motion:
            self.last_motion_time = now
            self.state = self.STATE_ACTIVE
        elif now - self.last_motion_time > config.no_motion_timeout:
            self.state = self.STATE_IDLE

        base_fps = self.active_fps if self.state == self.STATE_ACTIVE else self.idle_fps
        effective_fps = max(0.05, base_fps * self.load_factor)
        target_interval = 1.0 / effective_fps

        if now - self.last_sample_time < target_interval:
            return False

        if self._is_duplicate(frame):
            return False

        self.last_sample_time = now
        return True

    def _is_duplicate(self, frame: np.ndarray) -> bool:
        """Skip if frame is nearly identical to last sampled frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray_small = cv2.resize(gray, (160, 90))

        if self.last_sampled_gray is None:
            self.last_sampled_gray = gray_small
            return False

        # Simple normalized correlation
        score = cv2.matchTemplate(
            gray_small, self.last_sampled_gray, cv2.TM_CCOEFF_NORMED
        )[0][0]

        if score > 0.98:
            return True

        self.last_sampled_gray = gray_small
        return False
