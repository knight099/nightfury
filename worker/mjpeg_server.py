import asyncio
import logging

import cv2

from config import config
from stream_token import verify_stream_token

logger = logging.getLogger(__name__)

BOUNDARY = b"frame"


class MJPEGServer:
    """Minimal server streaming live camera frames as MJPEG
    (multipart/x-mixed-replace) over plain HTTP.

    Serves `GET /stream/{camera_id}?token=...` by repeatedly JPEG-encoding the
    camera worker's most recent decoded frame. If `stream_token_secret` is
    configured, requests must include a valid signed token (issued by the
    backend's `/api/cameras/{id}/stream-url` endpoint) or the connection is
    rejected with 403. Falls back to `/latest-frame` snapshot polling on the
    frontend if the stream is unavailable.
    """

    def __init__(self, get_worker):
        # get_worker: camera_id (str) -> CameraWorker | None
        self._get_worker = get_worker
        self._server: asyncio.base_events.Server | None = None

    async def start(self):
        if not config.mjpeg_server_enabled:
            return
        self._server = await asyncio.start_server(
            self._handle_client, config.mjpeg_server_host, config.mjpeg_server_port
        )
        logger.info(
            f"MJPEG dev stream server listening on "
            f"{config.mjpeg_server_host}:{config.mjpeg_server_port}"
        )

    async def stop(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5)
            # Drain remaining request headers.
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line in (b"\r\n", b"\n", b""):
                    break

            parts = request_line.decode("latin-1").split()
            path = parts[1] if len(parts) >= 2 else "/"

            if not path.startswith("/stream/"):
                await self._write_response(writer, 404, b"not found")
                return

            raw_path = path[len("/stream/"):]
            camera_id, _, query = raw_path.partition("?")
            camera_id = camera_id.strip("/")

            if config.stream_token_secret:
                token = ""
                for param in query.split("&"):
                    key, _, value = param.partition("=")
                    if key == "token":
                        token = value
                        break
                if not verify_stream_token(camera_id, token):
                    await self._write_response(writer, 403, b"forbidden")
                    return

            worker = self._get_worker(camera_id)
            if worker is None:
                await self._write_response(writer, 404, b"camera not streaming")
                return

            await self._stream_frames(writer, worker)
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            pass
        except Exception as e:
            logger.debug(f"MJPEG client error: {e}")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _write_response(self, writer: asyncio.StreamWriter, status: int, body: bytes):
        reason = {200: "OK", 403: "Forbidden", 404: "Not Found"}.get(status, "Error")
        headers = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Connection: close\r\n\r\n"
        ).encode()
        writer.write(headers + body)
        await writer.drain()

    async def _stream_frames(self, writer: asyncio.StreamWriter, worker):
        headers = (
            "HTTP/1.1 200 OK\r\n"
            f"Content-Type: multipart/x-mixed-replace; boundary={BOUNDARY.decode()}\r\n"
            "Cache-Control: no-cache, no-store, must-revalidate\r\n"
            "Pragma: no-cache\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        writer.write(headers)
        await writer.drain()

        interval = 1.0 / config.mjpeg_fps
        last_frame_id = None

        while True:
            frame = worker.last_frame
            if frame is None:
                await asyncio.sleep(interval)
                continue

            # Avoid re-encoding/sending the exact same buffer twice.
            if id(frame) != last_frame_id:
                ok, jpeg = await asyncio.to_thread(
                    cv2.imencode, ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, config.mjpeg_quality]
                )
                if ok:
                    last_frame_id = id(frame)
                    chunk = (
                        b"--" + BOUNDARY + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                        + jpeg.tobytes() + b"\r\n"
                    )
                    writer.write(chunk)
                    await writer.drain()

            await asyncio.sleep(interval)
