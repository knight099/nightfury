import asyncio
from unittest.mock import AsyncMock, MagicMock

import numpy as np

from camera_worker import CameraWorker
from config import config


def _run(coro):
    return asyncio.run(coro)


def _make_worker() -> CameraWorker:
    """Build a CameraWorker instance without running its real __init__."""
    worker = CameraWorker.__new__(CameraWorker)
    worker.camera_config = MagicMock()
    worker.camera_config.camera_id = "cam-test-123"
    worker.camera_config.name = "TestCam"
    worker.gcs = MagicMock()
    worker.gcs.upload = AsyncMock(return_value="gs://bucket/latest/cam-test-123.webp")
    worker._running = True
    worker._last_frame = None
    worker._last_uploaded_frame_id = None
    return worker


def test_encode_webp_produces_bytes():
    worker = _make_worker()
    frame = np.full((720, 1280, 3), 128, dtype=np.uint8)

    encoded = worker._encode_webp(frame)

    assert encoded is not None
    assert isinstance(encoded, bytes)
    assert len(encoded) > 0
    # WebP files start with 'RIFF' header
    assert encoded[:4] == b"RIFF"


def test_latest_frame_loop_uploads_frame():
    worker = _make_worker()
    frame = np.full((720, 1280, 3), 200, dtype=np.uint8)
    worker._last_frame = frame

    # Override interval to be very short so the loop runs quickly.
    original_interval = config.latest_frame_interval_seconds
    config.latest_frame_interval_seconds = 0.01

    async def runner():
        task = asyncio.create_task(worker._latest_frame_loop())
        # Give the loop time to do at least one iteration.
        await asyncio.sleep(0.1)
        worker._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        _run(runner())
    finally:
        config.latest_frame_interval_seconds = original_interval

    assert worker.gcs.upload.await_count >= 1
    args, kwargs = worker.gcs.upload.await_args
    path, data, content_type = args
    assert path == "latest/cam-test-123.webp"
    assert content_type == "image/webp"
    assert isinstance(data, bytes)
    assert data[:4] == b"RIFF"


def test_latest_frame_loop_skips_when_no_frame():
    worker = _make_worker()
    worker._last_frame = None

    original_interval = config.latest_frame_interval_seconds
    config.latest_frame_interval_seconds = 0.01

    async def runner():
        task = asyncio.create_task(worker._latest_frame_loop())
        await asyncio.sleep(0.05)
        worker._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        _run(runner())
    finally:
        config.latest_frame_interval_seconds = original_interval

    assert worker.gcs.upload.await_count == 0


def test_latest_frame_loop_skips_unchanged_frame():
    worker = _make_worker()
    frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
    worker._last_frame = frame

    original_interval = config.latest_frame_interval_seconds
    config.latest_frame_interval_seconds = 0.01

    async def runner():
        task = asyncio.create_task(worker._latest_frame_loop())
        # Run long enough for several iterations on the same frame object.
        await asyncio.sleep(0.1)
        worker._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        _run(runner())
    finally:
        config.latest_frame_interval_seconds = original_interval

    # Same frame object — should only be uploaded once even across multiple ticks.
    assert worker.gcs.upload.await_count == 1
