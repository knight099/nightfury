"""SQLite-backed offline queue for events when the backend is unreachable.

Stores JSON-encoded event payloads on disk and replays them once the backend
becomes reachable again. Uses stdlib sqlite3 with WAL journaling and offloads
blocking calls via asyncio.to_thread.
"""
import asyncio
import json
import logging
import sqlite3
import threading
from typing import Optional

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL,
    queued_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempts INTEGER NOT NULL DEFAULT 0
);
"""

_INDEX = "CREATE INDEX IF NOT EXISTS idx_events_id ON events(id);"


class OfflineQueue:
    """Persistent FIFO queue of pending event payloads."""

    def __init__(self, db_path: str, max_rows: int = 10000):
        self.db_path = db_path
        self.max_rows = max_rows
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = sqlite3.connect(
            db_path,
            check_same_thread=False,
            isolation_level=None,  # autocommit
        )
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError as e:
            logger.warning(f"Could not enable WAL on offline queue: {e}")
        self._conn.execute(_SCHEMA)
        self._conn.execute(_INDEX)

    # ---- internal sync helpers (called inside to_thread) ----

    def _enqueue_sync(self, payload_json: str) -> None:
        with self._lock:
            assert self._conn is not None
            self._conn.execute(
                "INSERT INTO events (payload) VALUES (?)", (payload_json,)
            )
            cur = self._conn.execute("SELECT COUNT(*) FROM events")
            count = cur.fetchone()[0]
            if count > self.max_rows:
                excess = count - self.max_rows
                self._conn.execute(
                    "DELETE FROM events WHERE id IN ("
                    "SELECT id FROM events ORDER BY id ASC LIMIT ?)",
                    (excess,),
                )
                logger.warning(
                    f"Offline queue overflow: dropped {excess} oldest event(s) "
                    f"(cap={self.max_rows})"
                )

    def _peek_batch_sync(self, limit: int) -> list[tuple[int, dict]]:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute(
                "SELECT id, payload FROM events ORDER BY id ASC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        out: list[tuple[int, dict]] = []
        for row_id, payload_json in rows:
            try:
                out.append((row_id, json.loads(payload_json)))
            except json.JSONDecodeError as e:
                logger.error(
                    f"Corrupt offline queue row id={row_id}: {e}; deleting"
                )
                # Best-effort delete of corrupt row
                with self._lock:
                    if self._conn is not None:
                        self._conn.execute(
                            "DELETE FROM events WHERE id = ?", (row_id,)
                        )
        return out

    def _delete_sync(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            assert self._conn is not None
            self._conn.executemany(
                "DELETE FROM events WHERE id = ?", [(i,) for i in ids]
            )

    def _increment_attempts_sync(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            assert self._conn is not None
            self._conn.executemany(
                "UPDATE events SET attempts = attempts + 1 WHERE id = ?",
                [(i,) for i in ids],
            )

    def _size_sync(self) -> int:
        with self._lock:
            assert self._conn is not None
            cur = self._conn.execute("SELECT COUNT(*) FROM events")
            return int(cur.fetchone()[0])

    def _close_sync(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    # ---- async API ----

    async def enqueue(self, payload: dict) -> None:
        payload_json = json.dumps(payload, default=str)
        await asyncio.to_thread(self._enqueue_sync, payload_json)

    async def peek_batch(self, limit: int = 50) -> list[tuple[int, dict]]:
        return await asyncio.to_thread(self._peek_batch_sync, limit)

    async def delete(self, ids: list[int]) -> None:
        await asyncio.to_thread(self._delete_sync, ids)

    async def increment_attempts(self, ids: list[int]) -> None:
        await asyncio.to_thread(self._increment_attempts_sync, ids)

    async def size(self) -> int:
        return await asyncio.to_thread(self._size_sync)

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)
