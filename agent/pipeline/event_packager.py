import asyncio
import logging
import tempfile
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np

from config import config
from gcs_uploader import GCSUploader
from api_client import ApiClient
from models import CameraConfig, DetectedEvent
from ring_buffer import RingBuffer

logger = logging.getLogger(__name__)


class EventPackager:
    """Packages detected events: annotate snapshot, cut clip, upload, post to API."""

    def __init__(self, gcs: GCSUploader, api: ApiClient):
        self.gcs = gcs
        self.api = api

    async def package_and_send(
        self,
        event: DetectedEvent,
        frame: np.ndarray,
        ring_buffer: RingBuffer,
        camera_config: CameraConfig,
    ) -> str | None:
        """Process event end-to-end. Returns event_id if successful."""
        event_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        date_path = timestamp.strftime("%Y/%m/%d")
        base_path = f"{camera_config.org_id}/{date_path}/{camera_config.camera_id}/{event_id}"

        # 1. Annotate snapshot
        annotated = self._annotate_frame(frame, event)
        _, snapshot_bytes = cv2.imencode(".webp", annotated, [cv2.IMWRITE_WEBP_QUALITY, 85])

        # 2. Cut clip from ring buffer
        clip_bytes = await self._cut_clip(ring_buffer)

        # 3. Upload to GCS
        snapshot_url = await self.gcs.upload(
            f"{base_path}/snapshot.webp", snapshot_bytes.tobytes(), "image/webp"
        )
        clip_url = None
        if clip_bytes:
            clip_url = await self.gcs.upload(
                f"{base_path}/clip.mp4", clip_bytes, "video/mp4"
            )

        # 4. Post to backend API
        success = await self.api.post_event({
            "camera_id": camera_config.camera_id,
            "timestamp": timestamp.isoformat(),
            "event_type": event.event_type,
            "confidence": event.confidence,
            "severity": event.severity,
            "description": event.description,
            "bounding_boxes": [
                {"x1": bb.x1, "y1": bb.y1, "x2": bb.x2, "y2": bb.y2, "label": bb.label}
                for bb in event.bounding_boxes
            ],
            "snapshot_url": snapshot_url,
            "clip_url": clip_url,
            "ai_model": config.gemini_model,
        })

        if success:
            logger.info(
                f"[{camera_config.name}] Event posted: {event.event_type} "
                f"({event.confidence:.0%}) — {event.description}"
            )
            return event_id
        return None

    def _annotate_frame(self, frame: np.ndarray, event: DetectedEvent) -> np.ndarray:
        """Draw bounding boxes and labels on frame."""
        annotated = frame.copy()
        color = (30, 144, 255)  # electric blue BGR

        for bbox in event.bounding_boxes:
            cv2.rectangle(annotated, (bbox.x1, bbox.y1), (bbox.x2, bbox.y2), color, 2)
            label = f"{bbox.label} {event.confidence:.0%}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.rectangle(
                annotated,
                (bbox.x1, bbox.y1 - label_size[1] - 8),
                (bbox.x1 + label_size[0] + 4, bbox.y1),
                color,
                -1,
            )
            cv2.putText(
                annotated, label,
                (bbox.x1 + 2, bbox.y1 - 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
            )

        return annotated

    async def _cut_clip(self, ring_buffer: RingBuffer) -> bytes | None:
        """Extract ~10s clip from ring buffer, encode as H.264 MP4."""
        frames = ring_buffer.get_window(seconds_before=5, seconds_after=5)
        if len(frames) < 20:
            return None

        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
                process = await asyncio.create_subprocess_exec(
                    config.ffmpeg_path,
                    "-y", "-f", "rawvideo",
                    "-pix_fmt", "bgr24",
                    "-s", f"{config.frame_width}x{config.frame_height}",
                    "-r", "10",
                    "-i", "pipe:0",
                    "-c:v", "libx264",
                    "-crf", "28",
                    "-preset", "fast",
                    "-movflags", "+faststart",
                    "-an",
                    tmp.name,
                    stdin=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                frame_data = b"".join(f.tobytes() for f in frames)
                _, stderr = await process.communicate(input=frame_data)

                if process.returncode != 0:
                    logger.warning(f"FFmpeg clip encoding failed: {stderr.decode()[:200]}")
                    return None

                with open(tmp.name, "rb") as f:
                    return f.read()
        except Exception as e:
            logger.warning(f"Clip cutting failed: {e}")
            return None
