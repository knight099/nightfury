import asyncio
import os
import tempfile

import pytest

from offline_queue import OfflineQueue


def _run(coro):
    return asyncio.run(coro)


def _fresh_queue(max_rows: int = 10000) -> tuple[OfflineQueue, str]:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    # Remove the empty file so sqlite creates a clean DB
    os.unlink(path)
    return OfflineQueue(path, max_rows=max_rows), path


def _cleanup(queue: OfflineQueue, path: str) -> None:
    _run(queue.close())
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass


def test_enqueue_size_peek_delete_roundtrip():
    queue, path = _fresh_queue()
    try:
        async def scenario():
            assert await queue.size() == 0

            await queue.enqueue({"camera_id": "cam-1", "event_type": "person"})
            await queue.enqueue({"camera_id": "cam-2", "event_type": "vehicle"})
            await queue.enqueue({"camera_id": "cam-3", "event_type": "package"})

            assert await queue.size() == 3

            batch = await queue.peek_batch(10)
            assert len(batch) == 3
            ids = [row_id for row_id, _ in batch]
            payloads = [p for _, p in batch]

            # FIFO ordering
            assert payloads[0]["camera_id"] == "cam-1"
            assert payloads[1]["camera_id"] == "cam-2"
            assert payloads[2]["camera_id"] == "cam-3"

            # Delete first two
            await queue.delete(ids[:2])
            assert await queue.size() == 1

            remaining = await queue.peek_batch(10)
            assert len(remaining) == 1
            assert remaining[0][1]["camera_id"] == "cam-3"

        _run(scenario())
    finally:
        _cleanup(queue, path)


def test_overflow_drops_oldest():
    cap = 5
    queue, path = _fresh_queue(max_rows=cap)
    try:
        async def scenario():
            # Insert cap + 5 rows
            for i in range(cap + 5):
                await queue.enqueue({"i": i})

            size = await queue.size()
            assert size == cap

            batch = await queue.peek_batch(100)
            seen = [p["i"] for _, p in batch]
            # The 5 oldest (i=0..4) should be dropped, leaving i=5..9
            assert seen == [5, 6, 7, 8, 9]

        _run(scenario())
    finally:
        _cleanup(queue, path)


def test_json_payload_roundtrips_nested_structures():
    queue, path = _fresh_queue()
    try:
        async def scenario():
            payload = {
                "camera_id": "cam-1",
                "timestamp": "2026-05-29T12:34:56+00:00",
                "event_type": "person_detected",
                "confidence": 0.91,
                "severity": "medium",
                "description": "A person walked across the driveway",
                "bounding_boxes": [
                    {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4, "label": "person"},
                    {"x": 0.5, "y": 0.6, "w": 0.1, "h": 0.1, "label": "bag"},
                ],
                "snapshot_url": "gs://bucket/snap.webp",
                "clip_url": "gs://bucket/clip.mp4",
                "ai_model": "gemini-2.0-flash",
                "metadata": {"nested": {"deep": [1, 2, {"k": "v"}]}, "n": None},
            }
            await queue.enqueue(payload)

            batch = await queue.peek_batch(1)
            assert len(batch) == 1
            _, restored = batch[0]
            assert restored == payload

        _run(scenario())
    finally:
        _cleanup(queue, path)


def test_increment_attempts():
    queue, path = _fresh_queue()
    try:
        async def scenario():
            await queue.enqueue({"a": 1})
            await queue.enqueue({"a": 2})
            batch = await queue.peek_batch(10)
            ids = [row_id for row_id, _ in batch]

            await queue.increment_attempts(ids)
            await queue.increment_attempts(ids[:1])

            # No public getter; verify via internal connection
            with queue._lock:
                cur = queue._conn.execute(
                    "SELECT id, attempts FROM events ORDER BY id ASC"
                )
                rows = cur.fetchall()
            assert rows[0][1] == 2
            assert rows[1][1] == 1

        _run(scenario())
    finally:
        _cleanup(queue, path)


def test_delete_empty_list_is_noop():
    queue, path = _fresh_queue()
    try:
        async def scenario():
            await queue.enqueue({"a": 1})
            await queue.delete([])
            assert await queue.size() == 1

        _run(scenario())
    finally:
        _cleanup(queue, path)
