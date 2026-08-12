import numpy as np
import pytest

from motion_detector import MotionDetector


def _make_frame(value: int = 128) -> np.ndarray:
    return np.full((720, 1280, 3), value, dtype=np.uint8)


def test_no_motion_on_identical_frames():
    detector = MotionDetector()
    frame = _make_frame(100)

    has_motion, ratio = detector.detect(frame)  # first frame: no prev
    assert not has_motion

    has_motion, ratio = detector.detect(frame)  # same frame
    assert not has_motion
    assert ratio < 0.01


def test_motion_on_different_frames():
    detector = MotionDetector()

    frame1 = _make_frame(50)
    frame2 = _make_frame(200)

    detector.detect(frame1)
    has_motion, ratio = detector.detect(frame2)

    assert has_motion
    assert ratio > 0.5


def test_motion_on_partial_change():
    detector = MotionDetector()

    frame1 = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame2 = frame1.copy()
    # Change 5% of the frame
    frame2[0:36, :, :] = 255

    detector.detect(frame1)
    has_motion, ratio = detector.detect(frame2)

    assert has_motion
    assert 0.01 < ratio < 0.2


def test_reset():
    detector = MotionDetector()
    frame = _make_frame()
    detector.detect(frame)

    assert detector.prev_gray is not None
    detector.reset()
    assert detector.prev_gray is None
