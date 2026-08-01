"""Test endpoint — analyze a single frame from device camera via Gemini Vision."""
import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession

import cv2
import numpy as np

from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.redis import get_redis
from app.models.ai_usage import AIUsage
from app.models.user import User
from app.services.local_detection import analyze_frame_locally, pose_detector, yolo_detector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/test-camera", tags=["test-camera"])

# All possible event types across warehouse, manufacturing, office, drones, security
EVENT_CATALOG = {
    "warehouse": [
        "person", "vehicle", "intrusion", "loitering", "forklift_movement",
        "pallet_handling", "package_handling", "spill_detected", "blocked_aisle",
        "unsafe_stacking", "loading_dock_activity", "trailer_arrival",
        "ppe_violation", "unauthorized_zone", "after_hours_activity",
    ],
    "manufacturing": [
        "person", "vehicle", "machine_running", "machine_idle", "machine_fault",
        "ppe_violation", "safety_zone_breach", "fire_smoke", "spill_detected",
        "unsafe_behavior", "tool_left", "object_left", "blocked_emergency_exit",
        "operator_absence", "abnormal_posture", "intrusion",
    ],
    "office": [
        "person", "tailgating", "unauthorized_entry", "loitering",
        "package_delivery", "after_hours_activity", "fire_smoke",
        "object_left", "crowd_spike", "intrusion", "occupancy_count",
    ],
    "drone_aerial": [
        "person", "vehicle", "crowd_gathering", "perimeter_breach",
        "unauthorized_drone", "fire_smoke", "vegetation_change",
        "vehicle_convoy", "unusual_object", "construction_activity",
    ],
    "general_security": [
        "person", "vehicle", "intrusion", "loitering", "fire_smoke",
        "object_left", "ppe_violation", "crowd_spike", "fight_detected",
        "weapon_detected", "fall_detected", "running_detected",
        "tailgating", "perimeter_breach", "vandalism",
    ],
}


def build_prompt(scene_type: str, scene_context: dict | None = None) -> str:
    """Build a context-aware prompt for the camera scene."""
    events = EVENT_CATALOG.get(scene_type, EVENT_CATALOG["general_security"])
    enabled_events_str = ", ".join(events)

    context_section = ""
    if scene_context and any(scene_context.values()):
        parts = []
        for direction in ("center", "left", "right", "top", "bottom", "background"):
            value = scene_context.get(direction)
            if value:
                parts.append(f"  - {direction.capitalize()}: {value}")
        if parts:
            context_section = (
                "\nKnown scene layout (provided by operator — use as ground truth):\n"
                + "\n".join(parts)
                + "\n\nUse this layout to: (1) reduce false positives by ignoring expected objects, "
                "(2) describe locations with operator's labels (e.g., 'near the storage rack on the left'), "
                "(3) detect anomalies relative to the known layout.\n"
            )

    return f"""You are an expert surveillance AI analyst for {scene_type.replace("_", " ")} environments.
Analyze this camera frame for events of interest.

Enabled detections: {enabled_events_str}
{context_section}
Respond ONLY with valid JSON matching this schema:
{{
  "events": [
    {{
      "event_type": "<one of the enabled detections>",
      "confidence": <float 0.0-1.0>,
      "severity": "<low|medium|high|critical>",
      "description": "<one sentence a security guard or supervisor would understand, reference scene layout if helpful>",
      "bounding_boxes": [{{"x1": <int>, "y1": <int>, "x2": <int>, "y2": <int>, "label": "<short label>"}}]
    }}
  ],
  "person_count": <int>,
  "people": [
    {{
      "description": "<gender/age estimate, clothing>",
      "carrying": "<bag, box, package, tool, weapon, none>",
      "carrying_count": <int — number of items being carried>,
      "activity": "<walking, standing, running, sitting, working, etc.>",
      "ppe": {{"helmet": <bool>, "vest": <bool>, "gloves": <bool>, "mask": <bool>}}
    }}
  ],
  "vehicles": [
    {{
      "type": "<car, truck, van, motorcycle, bicycle, forklift, bus, trailer, etc.>",
      "color": "<dominant color>",
      "license_plate": "<plate text if readable, else null>",
      "license_plate_confidence": <float 0.0-1.0>,
      "direction": "<entering, exiting, parked, moving_left, moving_right, stationary>"
    }}
  ],
  "objects": {{
    "boxes": <int — count of cardboard/shipping boxes visible>,
    "bags": <int — count of bags/sacks visible>,
    "pallets": <int — count of pallets visible>,
    "packages": <int — count of packages visible>
  }},
  "scene_summary": "<2-3 sentence description: what's happening, where (use scene layout if provided), any concerns>"
}}

Rules:
- Only emit events that are clearly visible — do NOT hallucinate
- For license plates: only report if you can actually read characters; set confidence accordingly
- Count boxes/bags/pallets/packages even if no event is triggered
- For each person, fill all fields (use null/false where unclear)
- Severity guide: low=routine, medium=attention needed, high=immediate response, critical=emergency
- Bounding box coordinates: pixel values for 1280x720 frame
- If nothing notable, return empty events array but still fill people/vehicles/objects/scene_summary"""


class SceneContext(BaseModel):
    center: str | None = None
    left: str | None = None
    right: str | None = None
    top: str | None = None
    bottom: str | None = None
    background: str | None = None


class AnalyzeFrameRequest(BaseModel):
    image_base64: str
    scene_type: str = "general_security"
    scene_context: SceneContext | None = None


class AnalyzeCombinedRequest(BaseModel):
    image_base64: str
    audio_base64: str
    audio_mime_type: str = "audio/webm"
    scene_type: str = "general_security"
    scene_context: SceneContext | None = None
    audio_duration_s: float | None = None


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    question: str
    recent_events: list[dict] = []  # last N analysis results (lightweight)
    history: list[ChatMessage] = []  # prior chat turns
    image_base64: str | None = None  # optional current frame for visual questions
    scene_type: str = "general_security"
    scene_context: SceneContext | None = None


@router.get("/event-catalog")
async def get_event_catalog(user: User = Depends(get_current_user)):
    """Return the catalog of supported events grouped by scene type."""
    return {"catalog": EVENT_CATALOG}


class AnalyzeLocalRequest(BaseModel):
    image_base64: str


@router.get("/local-detection-status")
async def local_detection_status(user: User = Depends(get_current_user)):
    """Whether the local YOLO/pose models loaded, and the fastpath threshold in use."""
    return {
        "yolo_available": yolo_detector.available,
        "pose_available": pose_detector.available,
        "fastpath_confidence": settings.local_detection_fastpath_confidence,
        "local_detection_enabled": settings.local_detection_enabled,
    }


@router.post("/analyze-local")
async def analyze_local(
    body: AnalyzeLocalRequest,
    user: User = Depends(get_current_user),
):
    """Run local YOLO + pose ONNX inference on a frame, mirroring the worker's
    confidence-gated pipeline: max detection confidence >= threshold means
    this frame would be handled locally (fastpath, no Gemini call needed);
    otherwise it would escalate. This endpoint never calls Gemini itself —
    the frontend decides whether to follow up with /analyze based on the
    returned decision."""
    require_role(user, "operator")

    try:
        image_data = base64.b64decode(body.image_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image data")

    arr = np.frombuffer(image_data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not decode image")

    started = time.monotonic()
    result = await asyncio.to_thread(analyze_frame_locally, frame)
    latency_ms = int((time.monotonic() - started) * 1000)

    return {
        "decision": result.decision,
        "max_confidence": result.max_confidence,
        "fastpath_threshold": settings.local_detection_fastpath_confidence,
        "inference_error": result.inference_error,
        "latency_ms": latency_ms,
        "detections": [
            {
                "coco_class": d.coco_class,
                "confidence": d.confidence,
                "bbox": {"x1": d.bbox.x1, "y1": d.bbox.y1, "x2": d.bbox.x2, "y2": d.bbox.y2},
            }
            for d in result.detections
        ],
        "poses": [
            {
                "bbox": {"x1": p.bbox.x1, "y1": p.bbox.y1, "x2": p.bbox.x2, "y2": p.bbox.y2},
                "keypoints": [
                    {"x": x, "y": y, "confidence": confidence}
                    for x, y, confidence in p.keypoints
                ],
                "label": p.label,
            }
            for p in result.poses
        ],
    }


# Pricing for gemini-2.5-flash (per 1M tokens, USD) — adjust if pricing changes
PRICE_INPUT_TEXT_PER_1M = 0.30
PRICE_INPUT_IMAGE_PER_1M = 0.30
PRICE_OUTPUT_PER_1M = 2.50


def _estimate_cost(prompt_tokens: int, output_tokens: int) -> float:
    return (prompt_tokens * PRICE_INPUT_TEXT_PER_1M + output_tokens * PRICE_OUTPUT_PER_1M) / 1_000_000


async def _record_usage(
    user: User,
    usage: dict,
    latency_ms: int,
    operation: str,
    model: str,
    db: AsyncSession,
):
    """Store per-call usage in Redis (per-user) AND Postgres (org-wide audit)."""
    prompt_tokens = usage.get("prompt_token_count", 0) or 0
    output_tokens = usage.get("candidates_token_count", 0) or 0
    total_tokens = usage.get("total_token_count", 0) or 0
    thoughts_tokens = usage.get("thoughts_token_count", 0) or 0
    cost = _estimate_cost(prompt_tokens, output_tokens)
    user_id = str(user.id)

    # ── Redis (fast path, per-user, 30-day TTL) ──────────────────────────
    try:
        redis = await get_redis()
        ts = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": ts,
            "operation": operation,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "thoughts_tokens": thoughts_tokens,
            "latency_ms": latency_ms,
            "cost_usd": cost,
        }
        list_key = f"test_camera:history:{user_id}"
        await redis.lpush(list_key, json.dumps(entry))
        await redis.ltrim(list_key, 0, 99)
        await redis.expire(list_key, 30 * 24 * 3600)

        agg_key = f"test_camera:agg:{user_id}"
        await redis.hincrby(agg_key, "calls", 1)
        await redis.hincrby(agg_key, "prompt_tokens", prompt_tokens)
        await redis.hincrby(agg_key, "output_tokens", output_tokens)
        await redis.hincrby(agg_key, "total_tokens", total_tokens)
        await redis.hincrbyfloat(agg_key, "cost_usd", cost)
        await redis.hincrby(agg_key, "total_latency_ms", latency_ms)
        await redis.expire(agg_key, 30 * 24 * 3600)
    except Exception as e:
        logger.warning(f"Failed to record usage in Redis: {e}")

    # ── Postgres (durable, org-wide for owner reporting) ─────────────────
    try:
        usage_row = AIUsage(
            org_id=user.org_id,
            user_id=user.id,
            model=model,
            operation=operation,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            thoughts_tokens=thoughts_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
        )
        db.add(usage_row)
        await db.flush()
    except Exception as e:
        logger.warning(f"Failed to record usage in DB: {e}")


@router.get("/usage")
async def get_usage(user: User = Depends(get_current_user)):
    """Return aggregate + recent test camera usage for current user."""
    try:
        redis = await get_redis()
        agg = await redis.hgetall(f"test_camera:agg:{user.id}")
        history_raw = await redis.lrange(f"test_camera:history:{user.id}", 0, 99)

        history = []
        for item in history_raw:
            try:
                history.append(json.loads(item))
            except json.JSONDecodeError:
                pass

        calls = int(agg.get("calls", 0)) if agg else 0
        return {
            "aggregate": {
                "calls": calls,
                "prompt_tokens": int(agg.get("prompt_tokens", 0)) if agg else 0,
                "output_tokens": int(agg.get("output_tokens", 0)) if agg else 0,
                "total_tokens": int(agg.get("total_tokens", 0)) if agg else 0,
                "cost_usd": float(agg.get("cost_usd", 0)) if agg else 0.0,
                "total_latency_ms": int(agg.get("total_latency_ms", 0)) if agg else 0,
                "avg_latency_ms": int(int(agg.get("total_latency_ms", 0)) / calls) if calls else 0,
            },
            "history": history,
        }
    except Exception as e:
        logger.error(f"Failed to fetch usage: {e}")
        return {"aggregate": {}, "history": []}


@router.delete("/usage")
async def reset_usage(user: User = Depends(get_current_user)):
    """Reset test camera usage stats for current user."""
    try:
        redis = await get_redis()
        await redis.delete(f"test_camera:agg:{user.id}")
        await redis.delete(f"test_camera:history:{user.id}")
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Failed to reset usage: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset usage")


AUDIO_EVENT_CATALOG = [
    "glass_break", "gunshot", "scream", "alarm", "explosion", "siren",
    "crowd_noise", "argument", "dog_barking", "vehicle_engine", "footsteps",
    "machinery_running", "machinery_fault", "door_forced", "door_slam",
    "fire_crackling", "water_leak", "smoke_alarm", "power_failure",
    "intruder_movement", "running", "fighting", "weapon_handling",
]

AUDIO_PROMPT = """You are an expert audio surveillance analyst. Analyze this audio clip for security-relevant sounds.

Detectable event types: {events}

Respond ONLY with valid JSON matching this schema:
{{
  "events": [
    {{
      "event_type": "<one of the detectable types>",
      "confidence": <float 0.0-1.0>,
      "severity": "<low|medium|high|critical>",
      "description": "<one sentence a security guard would understand>",
      "timestamp_offset_s": <float — seconds from start of clip where event occurs>
    }}
  ],
  "speech_detected": <bool>,
  "speech_summary": "<brief summary of any speech content, or null if none>",
  "ambient_level": "<silent|quiet|normal|loud|very_loud>",
  "dominant_sound": "<main sound in the clip in 3-5 words>",
  "scene_summary": "<2-3 sentence description of the audio scene: what sounds are present, any concerns>"
}}

Rules:
- Only report events clearly audible — do NOT hallucinate
- Severity guide: low=routine, medium=attention needed, high=immediate response, critical=emergency
- If speech is detected, summarize the gist only — do not transcribe verbatim
- If nothing notable, return empty events array but still fill all other fields"""


class AnalyzeAudioRequest(BaseModel):
    audio_base64: str
    mime_type: str = "audio/webm"
    scene_type: str = "general_security"
    duration_s: float | None = None


COMBINED_PROMPT = """You are an expert multimodal surveillance AI. You are given BOTH a camera frame AND an audio clip captured at the same moment.

Your job is to produce a SINGLE unified event list that correlates what is SEEN and what is HEARD. Do not list visual and audio events separately — merge them into one coherent picture.

Scene type: {scene_type}
Enabled visual event types: {visual_events}
Enabled audio event types: {audio_events}
{context_section}
For each event:
- If a sound corroborates something visible (e.g., a gunshot sound + a person running), combine them into one high-confidence event.
- If a sound has no visual match, report it as an audio-sourced event (source: "audio").
- If a visual event has no audio match, report it as a visual-sourced event (source: "visual").
- If both senses confirm the same event, mark it source: "combined" and raise confidence accordingly.

Respond ONLY with valid JSON matching this schema:
{{
  "events": [
    {{
      "event_type": "<event type>",
      "confidence": <float 0.0-1.0>,
      "severity": "<low|medium|high|critical>",
      "source": "<visual|audio|combined>",
      "description": "<one sentence integrating both what was seen and heard>",
      "bounding_boxes": [{{"x1": <int>, "y1": <int>, "x2": <int>, "y2": <int>, "label": "<short label>"}}]
    }}
  ],
  "person_count": <int>,
  "people": [
    {{
      "description": "<gender/age estimate, clothing>",
      "carrying": "<bag, box, package, tool, weapon, none>",
      "carrying_count": <int>,
      "activity": "<walking, running, shouting, working, etc.>",
      "ppe": {{"helmet": <bool>, "vest": <bool>, "gloves": <bool>, "mask": <bool>}}
    }}
  ],
  "vehicles": [
    {{
      "type": "<car, truck, forklift, etc.>",
      "color": "<color>",
      "license_plate": "<plate or null>",
      "license_plate_confidence": <float>,
      "direction": "<entering|exiting|parked|stationary|moving>"
    }}
  ],
  "objects": {{
    "boxes": <int>, "bags": <int>, "pallets": <int>, "packages": <int>
  }},
  "audio": {{
    "ambient_level": "<silent|quiet|normal|loud|very_loud>",
    "dominant_sound": "<3-5 words>",
    "speech_detected": <bool>,
    "speech_summary": "<gist of speech or null>"
  }},
  "scene_summary": "<2-3 sentences integrating both visual and audio observations — what is happening, any cross-modal correlations, any concerns>"
}}

Rules:
- Only report events that are actually present in the image or audio — do NOT hallucinate
- Bounding boxes: pixel coordinates for 1280x720 frame; omit array if event is audio-only
- Severity guide: low=routine, medium=attention needed, high=immediate response, critical=emergency
- Merged events have higher confidence than single-modality ones"""


@router.post("/analyze-combined")
async def analyze_combined(
    body: AnalyzeCombinedRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Analyze a frame + audio clip together in a single Gemini call, producing unified events."""
    require_role(user, "operator")

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Part
    except ImportError:
        raise HTTPException(status_code=500, detail="google-genai not installed on backend")

    if not settings.gemini_api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    try:
        image_data = base64.b64decode(body.image_base64)
        audio_data = base64.b64decode(body.audio_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 data")

    visual_events = EVENT_CATALOG.get(body.scene_type, EVENT_CATALOG["general_security"])
    context_section = ""
    if body.scene_context and any(v for v in body.scene_context.model_dump().values() if v):
        ctx = body.scene_context.model_dump()
        lines = "\n".join(f"  - {k}: {v}" for k, v in ctx.items() if v)
        context_section = f"\nKnown scene layout:\n{lines}\n"

    prompt = COMBINED_PROMPT.format(
        scene_type=body.scene_type.replace("_", " "),
        visual_events=", ".join(visual_events),
        audio_events=", ".join(AUDIO_EVENT_CATALOG),
        context_section=context_section,
    )

    mime = body.audio_mime_type.split(";")[0].strip()
    started = time.monotonic()

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                Part.from_bytes(data=image_data, mime_type="image/jpeg"),
                Part.from_bytes(data=audio_data, mime_type=mime),
                Part.from_text(text=prompt),
            ],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        latency_ms = int((time.monotonic() - started) * 1000)

        usage_dict = {}
        if response.usage_metadata:
            usage_dict = {
                "prompt_token_count": response.usage_metadata.prompt_token_count or 0,
                "candidates_token_count": response.usage_metadata.candidates_token_count or 0,
                "total_token_count": response.usage_metadata.total_token_count or 0,
                "thoughts_token_count": response.usage_metadata.thoughts_token_count or 0,
            }

        await _record_usage(user, usage_dict, latency_ms, "analyze_combined", "gemini-2.5-flash", db)

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.warning("Malformed JSON from Gemini combined analysis")
            data = {
                "events": [], "person_count": 0, "people": [], "vehicles": [],
                "objects": {"boxes": 0, "bags": 0, "pallets": 0, "packages": 0},
                "audio": {"ambient_level": "unknown", "dominant_sound": "unknown", "speech_detected": False, "speech_summary": None},
                "scene_summary": "Failed to parse AI response",
            }

        data["_meta"] = {
            "latency_ms": latency_ms,
            "prompt_tokens": usage_dict.get("prompt_token_count", 0),
            "output_tokens": usage_dict.get("candidates_token_count", 0),
            "total_tokens": usage_dict.get("total_token_count", 0),
            "cost_usd": _estimate_cost(
                usage_dict.get("prompt_token_count", 0),
                usage_dict.get("candidates_token_count", 0),
            ),
            "audio_duration_s": body.audio_duration_s,
        }
        return data

    except Exception as e:
        logger.error(f"Gemini combined analysis failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {str(e)}")


@router.post("/analyze-audio")
async def analyze_audio(
    body: AnalyzeAudioRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Analyze a base64-encoded audio clip from the microphone via Gemini."""
    require_role(user, "operator")

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Part
    except ImportError:
        raise HTTPException(status_code=500, detail="google-genai not installed on backend")

    if not settings.gemini_api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    try:
        audio_data = base64.b64decode(body.audio_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 audio data")

    prompt = AUDIO_PROMPT.format(events=", ".join(AUDIO_EVENT_CATALOG))
    started = time.monotonic()

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        mime = body.mime_type.split(";")[0].strip()  # strip codec params
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                Part.from_bytes(data=audio_data, mime_type=mime),
                Part.from_text(text=prompt),
            ],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        latency_ms = int((time.monotonic() - started) * 1000)

        usage_dict = {}
        if response.usage_metadata:
            usage_dict = {
                "prompt_token_count": response.usage_metadata.prompt_token_count or 0,
                "candidates_token_count": response.usage_metadata.candidates_token_count or 0,
                "total_token_count": response.usage_metadata.total_token_count or 0,
                "thoughts_token_count": response.usage_metadata.thoughts_token_count or 0,
            }

        await _record_usage(user, usage_dict, latency_ms, "analyze_audio", "gemini-2.5-flash", db)

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.warning("Malformed JSON from Gemini audio analysis")
            data = {
                "events": [],
                "speech_detected": False,
                "speech_summary": None,
                "ambient_level": "unknown",
                "dominant_sound": "unknown",
                "scene_summary": "Failed to parse AI response",
            }

        data["_meta"] = {
            "latency_ms": latency_ms,
            "prompt_tokens": usage_dict.get("prompt_token_count", 0),
            "output_tokens": usage_dict.get("candidates_token_count", 0),
            "total_tokens": usage_dict.get("total_token_count", 0),
            "cost_usd": _estimate_cost(
                usage_dict.get("prompt_token_count", 0),
                usage_dict.get("candidates_token_count", 0),
            ),
            "duration_s": body.duration_s,
        }
        return data

    except Exception as e:
        logger.error(f"Gemini audio analysis failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {str(e)}")


@router.post("/analyze")
async def analyze_frame(
    body: AnalyzeFrameRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Analyze a single base64-encoded frame via Gemini Vision."""
    require_role(user, "operator")

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Part
    except ImportError:
        raise HTTPException(status_code=500, detail="google-genai not installed on backend")

    image_data = base64.b64decode(body.image_base64)

    scene_context_dict = body.scene_context.model_dump() if body.scene_context else None
    prompt = build_prompt(body.scene_type, scene_context_dict)

    started = time.monotonic()

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                Part.from_text(text=prompt),
                Part.from_bytes(data=image_data, mime_type="image/jpeg"),
            ],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        latency_ms = int((time.monotonic() - started) * 1000)

        usage_dict = {}
        if response.usage_metadata:
            usage_dict = {
                "prompt_token_count": response.usage_metadata.prompt_token_count or 0,
                "candidates_token_count": response.usage_metadata.candidates_token_count or 0,
                "total_token_count": response.usage_metadata.total_token_count or 0,
                "thoughts_token_count": response.usage_metadata.thoughts_token_count or 0,
            }

        await _record_usage(user, usage_dict, latency_ms, "analyze", "gemini-2.5-flash", db)

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            logger.warning("Malformed JSON from Gemini")
            data = {
                "events": [], "person_count": 0, "people": [], "vehicles": [],
                "objects": {"boxes": 0, "bags": 0, "pallets": 0, "packages": 0},
                "scene_summary": "Failed to parse AI response",
            }

        data["_meta"] = {
            "latency_ms": latency_ms,
            "prompt_tokens": usage_dict.get("prompt_token_count", 0),
            "output_tokens": usage_dict.get("candidates_token_count", 0),
            "total_tokens": usage_dict.get("total_token_count", 0),
            "cost_usd": _estimate_cost(
                usage_dict.get("prompt_token_count", 0),
                usage_dict.get("candidates_token_count", 0),
            ),
        }
        return data

    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {str(e)}")


CHAT_SYSTEM = """You are a surveillance assistant chatting with a security operator who is watching a live camera feed.

You have access to:
- Recent AI analyses of camera frames (last few captures with detected events, people, vehicles, objects)
- Optionally the current frame image
- The scene type ({scene_type}) and operator-provided scene layout

Behavior:
- Answer questions about what's happening, what was detected, and trends across recent frames
- Be concise and factual — security guards need quick, direct answers
- When asked "what's happening now" → describe the most recent capture
- When asked about counts, trends, or comparisons → reason across the recent_events list
- If the question is unrelated to surveillance, politely redirect
- Never invent events that weren't in recent_events or visible in the image
- Use plain text. No markdown headings. Short paragraphs or bullet lists are fine."""


@router.post("/chat")
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Chat about recent events and the current scene."""
    require_role(user, "operator")

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Part
    except ImportError:
        raise HTTPException(status_code=500, detail="google-genai not installed on backend")

    started = time.monotonic()

    context_parts = []
    if body.scene_context:
        ctx = body.scene_context.model_dump()
        if any(ctx.values()):
            layout = "\n".join(f"  - {k}: {v}" for k, v in ctx.items() if v)
            context_parts.append(f"Scene layout (operator-provided):\n{layout}")

    if body.recent_events:
        recent_text = "Recent camera analyses (oldest to newest, last item is current):\n"
        for i, evt in enumerate(body.recent_events[:10]):
            ts = evt.get("captured_at", "")
            events = evt.get("events", [])
            people = evt.get("person_count", 0)
            vehicles = len(evt.get("vehicles", []) or [])
            objects = evt.get("objects", {}) or {}
            scene = evt.get("scene_summary", "")
            event_lines = [
                f"    - [{e.get('severity', '?').upper()}] {e.get('event_type', '?')}: {e.get('description', '')}"
                for e in events
            ]
            event_block = "\n".join(event_lines) if event_lines else "    (no events)"
            recent_text += (
                f"\n[{i+1}] {ts}\n"
                f"  People: {people}, Vehicles: {vehicles}, "
                f"Boxes: {objects.get('boxes', 0)}, Bags: {objects.get('bags', 0)}\n"
                f"  Scene: {scene}\n"
                f"  Events:\n{event_block}\n"
            )
        context_parts.append(recent_text)

    history_text = ""
    if body.history:
        for msg in body.history[-6:]:
            history_text += f"\n{msg.role.upper()}: {msg.content}"

    prompt = CHAT_SYSTEM.format(scene_type=body.scene_type)
    if context_parts:
        prompt += "\n\n" + "\n\n".join(context_parts)
    if history_text:
        prompt += f"\n\nConversation so far:{history_text}"
    prompt += f"\n\nUSER: {body.question}\nASSISTANT:"

    contents: list = [Part.from_text(text=prompt)]
    if body.image_base64:
        try:
            img_bytes = base64.b64decode(body.image_base64)
            contents.append(Part.from_bytes(data=img_bytes, mime_type="image/jpeg"))
        except Exception:
            logger.warning("Bad chat image_base64, ignoring")

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=GenerateContentConfig(temperature=0.3),
        )

        latency_ms = int((time.monotonic() - started) * 1000)

        usage_dict = {}
        if response.usage_metadata:
            usage_dict = {
                "prompt_token_count": response.usage_metadata.prompt_token_count or 0,
                "candidates_token_count": response.usage_metadata.candidates_token_count or 0,
                "total_token_count": response.usage_metadata.total_token_count or 0,
                "thoughts_token_count": response.usage_metadata.thoughts_token_count or 0,
            }

        await _record_usage(user, usage_dict, latency_ms, "chat", "gemini-2.5-flash", db)

        return {
            "answer": response.text or "(no response)",
            "_meta": {
                "latency_ms": latency_ms,
                "prompt_tokens": usage_dict.get("prompt_token_count", 0),
                "output_tokens": usage_dict.get("candidates_token_count", 0),
                "total_tokens": usage_dict.get("total_token_count", 0),
                "cost_usd": _estimate_cost(
                    usage_dict.get("prompt_token_count", 0),
                    usage_dict.get("candidates_token_count", 0),
                ),
            },
        }
    except Exception as e:
        logger.error(f"Chat call failed: {e}")
        raise HTTPException(status_code=502, detail=f"Chat failed: {str(e)}")
