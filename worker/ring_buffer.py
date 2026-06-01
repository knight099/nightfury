import time
from collections import deque

import numpy as np

from config import config
from models import TimestampedFrame


class RingBuffer:
    """Circular buffer holding last N seconds of frames for clip extraction."""

    def __init__(self, max_seconds: int | None = None, fps: int | None = None):
        max_sec = max_seconds or config.ring_buffer_seconds
        target_fps = fps or config.max_decode_fps
        self.max_frames = max_sec * target_fps
        self.buffer: deque[TimestampedFrame] = deque(maxlen=self.max_frames)

    def add(self, frame: np.ndarray):
        self.buffer.append(TimestampedFrame(frame=frame, timestamp=time.time()))

    def get_window(self, seconds_before: float = 5.0, seconds_after: float = 5.0) -> list[np.ndarray]:
        """Get frames from N seconds before now."""
        now = time.time()
        start = now - seconds_before
        return [tf.frame for tf in self.buffer if tf.timestamp >= start]

    def get_recent(self, seconds: float = 1.0) -> list[np.ndarray]:
        """Get frames from the last N seconds."""
        cutoff = time.time() - seconds
        return [tf.frame for tf in self.buffer if tf.timestamp >= cutoff]

    @property
    def duration_seconds(self) -> float:
        if len(self.buffer) < 2:
            return 0.0
        return self.buffer[-1].timestamp - self.buffer[0].timestamp

    def __len__(self) -> int:
        return len(self.buffer)
