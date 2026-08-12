import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from config import config
from offline_queue import OfflineQueue

logger = logging.getLogger(__name__)


class ApiClient:
    """HTTP client for communicating with the Nightwatch backend API."""

    def __init__(self):
        self.base_url = config.backend_url
        self.headers = {
            "X-Worker-Key": config.worker_api_key,
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=15.0,
        )
        # Lazy-init offline queue; tolerate failures (e.g., unwritable path)
        try:
            self.queue = OfflineQueue(
                config.offline_queue_path,
                config.offline_queue_max_rows,
            )
        except Exception as e:
            logger.error(f"Failed to initialize offline queue: {e}")
            self.queue = None

        self._drain_lock: asyncio.Lock = asyncio.Lock()
        self._last_drain_at: float = 0.0
        self._drain_min_interval: float = 30.0  # seconds
        self._drain_tasks: set[asyncio.Task] = set()

    async def post_event(self, event_data: dict) -> bool:
        """Post a detected event to the backend. Returns True on success.

        On connection error / 5xx: queues the event for later replay.
        On 4xx: drops (will never succeed) — logs warning.
        On 201: opportunistically drains queued events.
        """
        try:
            resp = await self.client.post("/internal/events", json=event_data)
            if resp.status_code == 201:
                # Fire-and-forget drain; do not let it block or crash the caller
                if self.queue is not None:
                    self._spawn_drain()
                return True
            if 400 <= resp.status_code < 500:
                logger.warning(
                    f"Event post rejected ({resp.status_code}), not queueing: "
                    f"{resp.text[:200]}"
                )
                return False
            # 5xx or other -> queue
            logger.warning(
                f"Event post failed ({resp.status_code}): {resp.text[:200]}"
            )
            await self._queue_event(event_data)
            return False
        except Exception as e:
            logger.error(f"Event post error: {e}")
            await self._queue_event(event_data)
            return False

    async def _queue_event(self, event_data: dict) -> None:
        if self.queue is None:
            return
        try:
            await self.queue.enqueue(event_data)
            logger.info("Event queued to offline buffer for later replay")
        except Exception as e:
            logger.error(f"Failed to enqueue event to offline buffer: {e}")

    async def send_heartbeat(self, camera_id: str, status: str, metrics: dict) -> bool:
        """Send health heartbeat for a camera."""
        payload = {
            "worker_id": config.worker_id,
            "camera_id": camera_id,
            "status": status,
            **metrics,
        }
        try:
            resp = await self.client.post("/internal/heartbeat", json=payload)
            ok = resp.status_code == 200
        except Exception as e:
            logger.debug(f"Heartbeat failed: {e}")
            return False

        # Throttled drain on heartbeat success
        if ok and self.queue is not None:
            now = time.monotonic()
            if now - self._last_drain_at >= self._drain_min_interval:
                self._last_drain_at = now
                try:
                    qsize = await self.queue.size()
                except Exception as e:
                    logger.debug(f"Queue size check failed: {e}")
                    qsize = 0
                if qsize > 0:
                    self._spawn_drain()
        return ok

    async def get_assignments(self) -> list[dict] | None:
        """Get camera assignments for this worker from the backend.

        Returns the list of assignment dicts on success, or None if the
        backend was unreachable / returned a non-200 response. Callers should
        treat None as a transient failure (do not reconcile this tick).
        """
        try:
            resp = await self.client.get("/internal/assignments")
            if resp.status_code != 200:
                logger.warning(f"assignments fetch failed: {resp.status_code}")
                return None
            return resp.json().get("assignments", [])
        except Exception as e:
            logger.warning(f"assignments fetch error: {e}")
            return None

    def _spawn_drain(self) -> None:
        task = asyncio.create_task(self._safe_drain())
        self._drain_tasks.add(task)
        task.add_done_callback(self._drain_tasks.discard)

    async def _safe_drain(self) -> None:
        try:
            await self._drain_queue()
        except Exception as e:
            logger.error(f"Offline queue drain failed: {e}")

    async def _drain_queue(self) -> None:
        if self.queue is None:
            return
        if self._drain_lock.locked():
            return
        async with self._drain_lock:
            batch = await self.queue.peek_batch(50)
            if not batch:
                return

            to_delete: list[int] = []
            stop_early = False
            stop_index = len(batch)

            for idx, (row_id, payload) in enumerate(batch):
                try:
                    resp = await self.client.post(
                        "/internal/events", json=payload
                    )
                except Exception as e:
                    logger.warning(
                        f"Drain: connection error on queued event {row_id}: {e}"
                    )
                    stop_early = True
                    stop_index = idx
                    break

                if resp.status_code == 201:
                    to_delete.append(row_id)
                elif 400 <= resp.status_code < 500:
                    cam = payload.get("camera_id", "?")
                    et = payload.get("event_type", "?")
                    logger.warning(
                        f"Drain: dropping queued event {row_id} "
                        f"(camera={cam} type={et}) "
                        f"rejected with {resp.status_code}"
                    )
                    to_delete.append(row_id)
                else:
                    # 5xx -> stop drain, keep for later
                    logger.warning(
                        f"Drain: backend {resp.status_code}, halting drain"
                    )
                    stop_early = True
                    stop_index = idx
                    break

            if to_delete:
                await self.queue.delete(to_delete)
                logger.info(
                    f"Drained {len(to_delete)} queued event(s) to backend"
                )
            if stop_early:
                remaining_ids = [
                    row_id for row_id, _ in batch[stop_index:]
                ]
                if remaining_ids:
                    await self.queue.increment_attempts(remaining_ids)

    async def close(self):
        # Cancel any in-flight drain tasks before closing the httpx client
        # to avoid RuntimeError from posting through an aclosed client.
        if self._drain_tasks:
            for task in list(self._drain_tasks):
                task.cancel()
            await asyncio.gather(*self._drain_tasks, return_exceptions=True)
        await self.client.aclose()
        if self.queue is not None:
            try:
                await self.queue.close()
            except Exception as e:
                logger.debug(f"Queue close error: {e}")
