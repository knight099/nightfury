"""Tests for FrameSampler — adaptive rate control and deduplication."""
import time

import numpy as np
import pytest

from frame_sampler import FrameSampler


def _solid_frame(color=(128, 128, 128), size=(720, 1280, 3)):
    return np.full(size, color, dtype=np.uint8)


def _noise_frame(size=(720, 1280, 3)):
    rng = np.random.default_rng(int(time.time() * 1000) % 2**32)
    return rng.integers(0, 255, size, dtype=np.uint8)


class TestFrameSamplerStateTransitions:
    def test_initial_state_is_idle(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        assert fs.state == FrameSampler.STATE_IDLE

    def test_motion_transitions_to_active(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        frame = _noise_frame()
        fs.should_sample(frame, has_motion=True)
        assert fs.state == FrameSampler.STATE_ACTIVE

    def test_no_motion_keeps_idle(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        frame = _noise_frame()
        fs.should_sample(frame, has_motion=False)
        assert fs.state == FrameSampler.STATE_IDLE

    def test_active_returns_to_idle_after_timeout(self, monkeypatch):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)

        # Trigger ACTIVE
        motion_frame = _noise_frame()
        fs.should_sample(motion_frame, has_motion=True)
        assert fs.state == FrameSampler.STATE_ACTIVE

        # Simulate time passing beyond no_motion_timeout (default 10s)
        fs.last_motion_time = time.time() - 20
        fs.last_sample_time = time.time() - 5  # make sure interval passes

        another_frame = _noise_frame()
        fs.should_sample(another_frame, has_motion=False)
        assert fs.state == FrameSampler.STATE_IDLE


class TestFrameSamplerRateControl:
    def test_first_frame_always_sampled(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        frame = _noise_frame()
        assert fs.should_sample(frame, has_motion=False) is True

    def test_second_frame_rejected_within_interval(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        frame1 = _noise_frame()
        frame2 = _noise_frame()
        # First sample accepted
        fs.should_sample(frame1, has_motion=False)
        # Immediately after — should be rejected (< 1s)
        result = fs.should_sample(frame2, has_motion=False)
        assert result is False

    def test_active_mode_has_higher_rate(self, monkeypatch):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        # First frame accepted
        frame = _noise_frame()
        fs.should_sample(frame, has_motion=True)

        # 0.15s later (within 1s idle, but within 0.2s active)
        fs.last_sample_time = time.time() - 0.25
        frame2 = _noise_frame()
        # In ACTIVE mode (0.25s > 1/5.0=0.2s), should accept
        result = fs.should_sample(frame2, has_motion=True)
        assert result is True

    def test_idle_mode_rejects_frame_too_soon(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        # First frame accepted
        frame = _noise_frame()
        fs.should_sample(frame, has_motion=False)

        # 0.5s later — still within 1s idle interval
        fs.last_sample_time = time.time() - 0.5
        frame2 = _noise_frame()
        result = fs.should_sample(frame2, has_motion=False)
        assert result is False


class TestFrameSamplerDeduplication:
    def test_identical_frame_deduplicated(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        frame = _solid_frame((100, 100, 100))

        # First sample taken
        fs.should_sample(frame, has_motion=False)
        fs.last_sample_time = time.time() - 2  # force interval past

        # Same frame again — should be deduplicated
        result = fs.should_sample(frame.copy(), has_motion=False)
        assert result is False

    def test_different_frame_not_deduplicated(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        # Use noise frames so correlation is genuinely low
        frame1 = _noise_frame()
        fs.should_sample(frame1, has_motion=False)
        fs.last_sample_time = time.time() - 2  # force interval past

        frame2 = _noise_frame()  # different noise — correlation will be low
        result = fs.should_sample(frame2, has_motion=False)
        assert result is True

    def test_no_last_frame_not_deduplicated(self):
        fs = FrameSampler(idle_fps=1.0, active_fps=5.0)
        assert fs.last_sampled_gray is None
        frame = _solid_frame()
        result = fs.should_sample(frame, has_motion=False)
        assert result is True
