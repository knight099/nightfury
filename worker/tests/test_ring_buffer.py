import time

import numpy as np
import pytest

from ring_buffer import RingBuffer


def _frame() -> np.ndarray:
    return np.zeros((720, 1280, 3), dtype=np.uint8)


def test_add_and_length():
    buf = RingBuffer(max_seconds=5, fps=10)
    assert len(buf) == 0

    for _ in range(10):
        buf.add(_frame())
    assert len(buf) == 10


def test_max_capacity():
    buf = RingBuffer(max_seconds=1, fps=5)  # max 5 frames
    for _ in range(20):
        buf.add(_frame())
    assert len(buf) == 5


def test_get_window():
    buf = RingBuffer(max_seconds=10, fps=10)

    # Add frames
    for _ in range(30):
        buf.add(_frame())
        time.sleep(0.01)

    frames = buf.get_window(seconds_before=0.5)
    assert len(frames) > 0
    assert len(frames) <= 30


def test_get_recent():
    buf = RingBuffer(max_seconds=10, fps=10)
    for _ in range(10):
        buf.add(_frame())

    recent = buf.get_recent(seconds=1.0)
    assert len(recent) == 10  # all frames are within last second
