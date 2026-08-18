import asyncio
import json
import logging
import time
from datetime import datetime

import cv2
from google import genai
from google.genai.types import GenerateContentConfig, Part
from google.oauth2.credentials import Credentials

from config import config
from models import BoundingBox, CameraConfig, DetectedEvent
from prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLDS = {
    "low": 0.85,
    "medium": 0.70,
    "high": 0.50,
}


class GeminiClient:
    """Gemini Vision API client with retry, circuit breaker, and rate limiting."""

    def __init__(self, api_client: "ApiClient"):
        self.api_client = api_client
        self._token: str | None = None
        self._token_expires_at: float = 0
        self._vertex_project = config.gemini_vertex_project
        self._vertex_location = config.gemini_vertex_location

        # No broker token exists yet at construction time, so on an edge box
        # there is nothing to build a Vertex client from. Defer: the client
        # is (re)built by _ensure_token() before the first analyze_frame()
        # call. Failing hard here would crash-loop the whole pipeline
        # sidecar on every edge box.
        try:
            self.client = self._build_client()
        except Exception as e:
            logger.info("Gemini client deferred until first broker token: %s", e)
            self.client = None
        self.model = config.gemini_model
        self.prompt_builder = PromptBuilder()
        self.semaphore = asyncio.Semaphore(config.gemini_max_concurrent)

        # Circuit breaker state
        self.failure_count = 0
        self.circuit_open_until: float = 0
        self.total_calls = 0
        self.total_errors = 0

    def _build_client(self):
        """Build the Gemini client.

        Vertex AI with a broker-issued, short-lived token is the only
        supported path on an edge box. The static-`GEMINI_API_KEY` fallback
        exists solely for the legacy Worker-VM deployment mode and is
        DISABLED when running as an edge box: a transient broker outage must
        not silently revert the box to holding a long-lived static Gemini
        credential on physically-accessible hardware, which is precisely
        what the broker was built to eliminate.

        "Am I an edge box?" uses the same signal as the rest of the pipeline
        — a device token (NIGHTWATCH_DEVICE_TOKEN) is present.
        """
        is_edge_box = bool(config.device_token)
        try:
            if not self._token:
                # No broker token fetched yet (e.g. at construction time, before the
                # first analyze_frame() call has run _ensure_token()).
                raise RuntimeError("no broker token available yet")
            credentials = Credentials(token=self._token)
            client = genai.Client(
                vertexai=True,
                project=self._vertex_project,
                location=self._vertex_location,
                credentials=credentials,
            )
            logger.info("Gemini client initialized via Vertex AI (broker token)")
            return client
        except Exception as e:
            if is_edge_box:
                logger.error(
                    "Vertex AI auth failed (%s); running as an edge box "
                    "(device token present), so the static GEMINI_API_KEY "
                    "fallback is disabled by policy%s",
                    e,
                    " (a GEMINI_API_KEY is set in this environment and is being"
                    " deliberately ignored)" if config.gemini_api_key else "",
                )
                raise
            if not config.gemini_api_key:
                logger.error(f"Vertex AI auth failed and no GEMINI_API_KEY set: {e}")
                raise
            logger.warning(
                f"Vertex AI auth failed ({e}); no device token present "
                "(Worker-VM mode), falling back to static Gemini API key"
            )
            return genai.Client(api_key=config.gemini_api_key)

    async def _ensure_token(self):
        """Fetch/refresh the broker-issued Vertex AI access token, ~60s ahead of expiry."""
        if self._token and time.time() < self._token_expires_at - 60:
            return
        resp = await self.api_client.client.post("/api/edge/gemini-token")
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        expires_at = datetime.fromisoformat(body["expires_at"])
        self._token_expires_at = expires_at.timestamp()
        self._vertex_project = body.get("vertex_project", self._vertex_project)
        self._vertex_location = body.get("vertex_location", self._vertex_location)
        self.client = self._build_client()  # rebuild so the Vertex client uses the fresh token

    async def analyze_frame(
        self, frame_jpeg: bytes, camera_config: CameraConfig
    ) -> list[DetectedEvent]:
        """Send frame to Gemini, parse structured response, filter by config."""

        if time.time() < self.circuit_open_until:
            return []

        try:
            await self._ensure_token()
        except Exception as e:
            logger.error(f"[{camera_config.name}] could not obtain Vertex token: {e}")
            self._record_failure()
            return []

        if self.client is None:
            logger.error(f"[{camera_config.name}] no usable Gemini client")
            self._record_failure()
            return []

        prompt = self.prompt_builder.build(camera_config)

        async with self.semaphore:
            try:
                self.total_calls += 1
                response = await asyncio.wait_for(
                    self._call_gemini(prompt, frame_jpeg),
                    timeout=config.gemini_timeout_seconds,
                )
                self.failure_count = 0
                return self._parse_response(response, camera_config)

            except asyncio.TimeoutError:
                logger.warning(f"[{camera_config.name}] Gemini timeout")
                self._record_failure()
                return []

            except Exception as e:
                if self._is_auth_error(e) and self._try_api_key_fallback():
                    logger.warning(
                        f"[{camera_config.name}] Vertex auth failed mid-flight; switched to Gemini API key. Retrying."
                    )
                    try:
                        response = await asyncio.wait_for(
                            self._call_gemini(prompt, frame_jpeg),
                            timeout=config.gemini_timeout_seconds,
                        )
                        self.failure_count = 0
                        return self._parse_response(response, camera_config)
                    except Exception as e2:
                        logger.error(f"[{camera_config.name}] Gemini error after fallback: {e2}")
                        self._record_failure()
                        return []
                logger.error(f"[{camera_config.name}] Gemini error: {e}")
                self._record_failure()
                return []

    async def generate_text_with_images(self, prompt: str, images: list[bytes]) -> str:
        """One text reply grounded in several JPEG frames.

        Used by scene analysis at setup time, not on the detection hot path.
        It deliberately bypasses the circuit breaker guarding analyze_frame
        (no check of circuit_open_until, no _record_failure() on error) —
        a setup run failing must never open the breaker that detection
        depends on. Errors are raised to the caller instead.
        """
        await self._ensure_token()
        if self.client is None:
            raise RuntimeError("no usable Gemini client")

        parts = [Part.from_text(text=prompt)]
        parts.extend(Part.from_bytes(data=img, mime_type="image/jpeg") for img in images)

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=parts,
        )
        return response.text or ""

    def _is_auth_error(self, e: Exception) -> bool:
        msg = str(e).lower()
        return any(s in msg for s in ("credential", "unauthenticated", "unauthorized", "401", "403", "permission"))

    def _try_api_key_fallback(self) -> bool:
        """Swap to a static-API-key client after a mid-flight auth failure.

        Same policy as `_build_client`: never allowed on an edge box, where a
        long-lived static Gemini key must not become the effective credential
        just because the broker had a bad minute.
        """
        if config.device_token:
            logger.error(
                "Vertex auth failed mid-flight; static GEMINI_API_KEY fallback "
                "is disabled on edge boxes (device token present)%s",
                " — a key is set and is being ignored" if config.gemini_api_key else "",
            )
            return False
        if not config.gemini_api_key:
            return False
        try:
            self.client = genai.Client(api_key=config.gemini_api_key)
            return True
        except Exception as e:
            logger.error(f"Failed to init Gemini API key fallback client: {e}")
            return False

    async def _call_gemini(self, prompt: str, frame_jpeg: bytes) -> str:
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=[
                Part.from_text(text=prompt),
                Part.from_bytes(data=frame_jpeg, mime_type="image/jpeg"),
            ],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        return response.text

    def _parse_response(self, text: str, camera_config: CameraConfig) -> list[DetectedEvent]:
        """Parse JSON response, filter by camera's enabled events and sensitivity."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"[{camera_config.name}] Malformed Gemini JSON response")
            return []

        threshold = CONFIDENCE_THRESHOLDS.get(camera_config.sensitivity, 0.70)
        events = []

        for event_data in data.get("events", []):
            event_type = event_data.get("event_type", "")
            confidence = event_data.get("confidence", 0)

            if event_type not in camera_config.enabled_events:
                continue
            if confidence < threshold:
                continue

            bboxes = []
            for bb in event_data.get("bounding_boxes", []):
                bboxes.append(BoundingBox(
                    x1=bb.get("x1", 0),
                    y1=bb.get("y1", 0),
                    x2=bb.get("x2", 0),
                    y2=bb.get("y2", 0),
                    label=bb.get("label", ""),
                ))

            events.append(DetectedEvent(
                event_type=event_type,
                confidence=confidence,
                severity=event_data.get("severity", "low"),
                description=event_data.get("description", ""),
                bounding_boxes=bboxes,
                zone=event_data.get("zone"),
            ))

        return events

    def _record_failure(self):
        self.failure_count += 1
        self.total_errors += 1
        if self.failure_count > 10:
            self.circuit_open_until = time.time() + 30
            self.failure_count = 0
            logger.warning("Circuit breaker OPEN — pausing Gemini calls for 30s")

    @property
    def stats(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "circuit_open": time.time() < self.circuit_open_until,
        }
