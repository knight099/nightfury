import asyncio
import logging
import time

import cv2
import numpy as np

from config import config
from models import CameraConfig
from stream_ingest import StreamIngest
from ring_buffer import RingBuffer
from motion_detector import MotionDetector
from frame_sampler import FrameSampler
from gemini_client import GeminiClient
from event_packager import EventPackager
from gcs_uploader import GCSUploader
from api_client import ApiClient
from yolo_detector import YoloDetector, decide

logger = logging.getLogger(__name__)


class CameraWorker:
    """
    Main processing pipeline for a single camera.
    Runs in its own asyncio task: ingest → buffer → motion → sample → AI → package.
    """

    def __init__(self, camera_config: CameraConfig, gemini: GeminiClient):
        self.camera_config = camera_config
        self.stream = StreamIngest(camera_config)
        self.ring_buffer = RingBuffer()
        self.motion_detector = MotionDetector()
        self.frame_sampler = FrameSampler(
            idle_fps=camera_config.idle_fps,
            active_fps=camera_config.active_fps,
        )
        self.gemini = gemini
        self.yolo = YoloDetector()
        self.gcs = GCSUploader()
        self.api = ApiClient()
        self.packager = EventPackager(self.gcs, self.api)

        self._running = False
        self._task: asyncio.Task | None = None
        self._latest_frame_task: asyncio.Task | None = None
        self._last_frame: np.ndarray | None = None
        self._last_uploaded_frame_id: int | None = None

        # Stats
        self.frames_processed = 0
        self.events_detected = 0
        self.gemini_calls = 0
        self.yolo_calls = 0
        self.yolo_gated_frames = 0
        self.yolo_fastpath_events = 0
        self.last_frame_time: float = 0
        self.errors: list[str] = []

    async def start(self):
        """Start the camera processing pipeline."""
        self._running = True
        await self.stream.start()
        self._task = asyncio.create_task(self._run_loop())
        self._latest_frame_task = asyncio.create_task(self._latest_frame_loop())
        logger.info(f"[{self.camera_config.name}] Worker started")

    async def stop(self):
        """Stop the camera processing pipeline."""
        self._running = False
        tasks = [t for t in (self._task, self._latest_frame_task) if t is not None]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.stream.stop()
        await self.api.close()
        logger.info(f"[{self.camera_config.name}] Worker stopped")

    async def _run_loop(self):
        """Main frame processing loop."""
        while self._running:
            try:
                frame = await asyncio.to_thread(self.stream.read_frame)

                if frame is None:
                    if not await self.stream.reconnect():
                        self._running = False
                        self.errors.append("stream_lost")
                        break
                    continue

                self.frames_processed += 1
                self.last_frame_time = time.time()
                self._last_frame = frame

                # Add to ring buffer (for clip extraction later)
                self.ring_buffer.add(frame)

                # Motion detection
                has_motion, motion_ratio = self.motion_detector.detect(frame)

                # Frame sampling decision
                if not self.frame_sampler.should_sample(frame, has_motion):
                    continue

                if config.yolo_enabled and self.yolo.available:
                    self.yolo_calls += 1
                    yolo_detections = await asyncio.to_thread(self.yolo.detect, frame)

                    if yolo_detections is None:
                        # Inference errored mid-run; fail toward the safe path
                        # (escalate to Gemini) rather than silently dropping
                        # the frame. Do NOT call decide() with None.
                        logger.warning(
                            f"[{self.camera_config.name}] YOLO inference error on this "
                            "frame; escalating to Gemini instead of dropping"
                        )
                    else:
                        decision = decide(
                            yolo_detections, self.camera_config,
                            config.yolo_fastpath_confidence, config.yolo_escalate_floor,
                        )

                        if decision.action == "drop":
                            self.yolo_gated_frames += 1
                            continue

                        if decision.action == "emit":
                            self.yolo_fastpath_events += len(decision.events)
                            for event in decision.events:
                                self.events_detected += 1
                                await self.packager.package_and_send(
                                    event, frame, self.ring_buffer, self.camera_config
                                )
                            continue

                        # decision.action == "escalate" -> fall through to Gemini below

                # Encode frame as JPEG for Gemini
                _, jpeg_buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                frame_jpeg = jpeg_buffer.tobytes()

                # Send to Gemini Vision
                self.gemini_calls += 1
                events = await self.gemini.analyze_frame(frame_jpeg, self.camera_config)

                # Package and send each detected event
                for event in events:
                    self.events_detected += 1
                    await self.packager.package_and_send(
                        event, frame, self.ring_buffer, self.camera_config
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.camera_config.name}] Pipeline error: {e}")
                self.errors.append(str(e)[:100])
                await asyncio.sleep(1)

    async def _latest_frame_loop(self):
        """Periodically encode and upload the most recent frame to GCS for live snapshot polling."""
        while self._running:
            try:
                await asyncio.sleep(config.latest_frame_interval_seconds)
                frame = self._last_frame
                if frame is None:
                    continue
                # Skip if frame hasn't changed since last upload (same buffer object).
                frame_id = id(frame)
                if frame_id == self._last_uploaded_frame_id:
                    continue

                webp_bytes = await asyncio.to_thread(self._encode_webp, frame)
                if webp_bytes is None:
                    continue

                path = f"latest/{self.camera_config.camera_id}.webp"
                try:
                    await self.gcs.upload(path, webp_bytes, "image/webp")
                    self._last_uploaded_frame_id = frame_id
                except Exception as e:
                    logger.warning(
                        f"[{self.camera_config.name}] latest-frame upload failed: {e}"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    f"[{self.camera_config.name}] latest-frame loop error: {e}"
                )

    def _encode_webp(self, frame: np.ndarray) -> bytes | None:
        ok, buf = cv2.imencode(
            ".webp", frame, [cv2.IMWRITE_WEBP_QUALITY, config.latest_frame_quality]
        )
        if not ok:
            return None
        return buf.tobytes()

    async def send_heartbeat(self):
        """Send health metrics to the backend."""
        metrics = {
            "frames_processed": self.frames_processed,
            "events_detected": self.events_detected,
            "gemini_calls": self.gemini_calls,
            "yolo_calls": self.yolo_calls,
            "yolo_gated_frames": self.yolo_gated_frames,
            "yolo_fastpath_events": self.yolo_fastpath_events,
            "buffer_duration": self.ring_buffer.duration_seconds,
            "sampler_state": self.frame_sampler.state,
            "errors": self.errors[-5:],
        }
        status = "online" if self._running and self.stream.is_running else "error"
        await self.api.send_heartbeat(self.camera_config.camera_id, status, metrics)

    @property
    def last_frame(self) -> np.ndarray | None:
        return self._last_frame

    @property
    def is_alive(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def stream_config_signature(self) -> tuple:
        c = self.camera_config
        return (c.ingest_mode, c.rtsp_url, c.stream_key, c.idle_fps, c.active_fps)

    def update_config(self, new_config: CameraConfig) -> None:
        """Update non-stream-affecting config fields in place.

        Stream-affecting fields (ingest_mode, rtsp_url, stream_key, idle_fps,
        active_fps) are NOT applied here; the supervisor must restart the
        worker if those changed.
        """
        self.camera_config = new_config
        try:
            self.motion_detector  # placeholder; sensitivity is read from config at gemini time
        except Exception:
            pass
        logger.info(
            f"[{new_config.name}] config updated "
            f"(sensitivity={new_config.sensitivity}, "
            f"events={new_config.enabled_events}, "
            f"zones={len(new_config.detection_zones)})"
        )
