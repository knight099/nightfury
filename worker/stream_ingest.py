import asyncio
import logging
import subprocess
import numpy as np

from config import config
from models import CameraConfig

logger = logging.getLogger(__name__)


class StreamIngest:
    """Manages FFmpeg subprocess for decoding camera stream into raw frames."""

    def __init__(self, camera_config: CameraConfig):
        self.config = camera_config
        self.process: subprocess.Popen | None = None
        self.reconnect_attempts = 0
        self.max_reconnects = 5
        self.frame_size = config.frame_width * config.frame_height * 3
        self._running = False

    def _get_source_url(self) -> str:
        if self.config.ingest_mode == "rtsp_pull":
            return self.config.rtsp_url or ""
        else:
            return f"rtmp://localhost/live/{self.config.stream_key}"

    def _build_ffmpeg_cmd(self) -> list[str]:
        source = self._get_source_url()
        cmd = [
            config.ffmpeg_path,
            "-hide_banner",
            "-loglevel", "error",
        ]

        if self.config.ingest_mode == "rtsp_pull":
            cmd += ["-rtsp_transport", "tcp", "-timeout", "5000000"]

        cmd += [
            "-i", source,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{config.frame_width}x{config.frame_height}",
            "-r", str(config.max_decode_fps),
            "-an",
            "pipe:1",
        ]
        return cmd

    async def start(self):
        cmd = self._build_ffmpeg_cmd()
        logger.info(f"[{self.config.name}] Starting FFmpeg: {' '.join(cmd[:6])}...")

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=self.frame_size * 2,
        )
        self._running = True
        self.reconnect_attempts = 0

    async def stop(self):
        self._running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def read_frame(self) -> np.ndarray | None:
        """Read one raw frame. Returns None on stream error."""
        if not self.process or not self.process.stdout:
            return None

        raw = self.process.stdout.read(self.frame_size)
        if len(raw) != self.frame_size:
            return None

        return np.frombuffer(raw, dtype=np.uint8).reshape(
            (config.frame_height, config.frame_width, 3)
        )

    async def reconnect(self) -> bool:
        """Attempt to reconnect. Returns True if successful."""
        self.reconnect_attempts += 1
        if self.reconnect_attempts > self.max_reconnects:
            logger.error(f"[{self.config.name}] Max reconnects exceeded")
            return False

        wait = min(5 * self.reconnect_attempts, 30)
        logger.warning(f"[{self.config.name}] Reconnecting in {wait}s (attempt {self.reconnect_attempts})")
        await asyncio.sleep(wait)
        await self.stop()
        try:
            await self.start()
            return True
        except Exception as e:
            logger.error(f"[{self.config.name}] Reconnect failed: {e}")
            return False

    @property
    def is_running(self) -> bool:
        return self._running and self.process is not None and self.process.poll() is None
