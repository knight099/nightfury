"""Look at a camera and propose how it should be configured.

Runs in the pipeline because that is the process holding decoded frames and
the brokered Gemini credential. Frames go pipeline → Gemini directly; they
never reach the backend.
"""

import json
import logging

logger = logging.getLogger(__name__)


class SceneAnalysisError(Exception):
    """The camera could not be analysed. Carries an operator-readable reason."""


SCENE_TYPES = [
    "parking", "corridor", "retail_frontage", "entrance",
    "loading_bay", "atrium", "perimeter", "other",
]

EVENT_TYPES = ["person", "vehicle", "animal", "intrusion", "loitering", "crowd_spike"]

SETUP_PROMPT = f"""You are configuring a CCTV camera for a security platform.

You are shown several frames sampled over a few minutes from ONE fixed camera
called "{{camera_name}}". Frames are {{width}}x{{height}} pixels.

Decide how this camera should be configured. Reply with ONLY a JSON object:

{{{{
  "scene_type": one of {SCENE_TYPES},
  "scene_description": "one sentence describing what this camera watches",
  "confidence": 0.0-1.0,
  "enabled_events": subset of {EVENT_TYPES},
  "sensitivity": "low" | "medium" | "high",
  "zones": [{{{{"name": "...", "polygon": [[x,y],[x,y],[x,y]]}}}}],
  "counting_lines": [{{{{"name": "...", "x1": 0, "y1": 0, "x2": 0, "y2": 0}}}}],
  "suggest_pose": true | false,
  "suggested_alert": null or {{{{"event_types": [...], "min_severity": "low|medium|high|critical"}}}},
  "rationale": "why you chose the above, in plain English for a security manager"
}}}}

Rules:
- Only enable an event type you actually saw evidence for. Enabling vehicle
  detection on an indoor corridor produces false alerts and erodes trust.
- Zone polygons and counting-line coordinates must lie within the frame.
- Only propose a counting line where there is a clear single crossing point
  such as a doorway or gate. If there is no natural crossing, return [].
- suggest_pose only if this scene involves a repeatable procedure worth
  tracking posture for. It is expensive; default to false.
- If you cannot tell what this camera is looking at, set scene_type "other"
  and confidence below 0.5 rather than guessing.
- The rationale is read by a person approving this for many cameras at once.
  Say what you saw and what you deliberately left off.
"""


def _extract_json(text: str) -> dict:
    """Parse the model's reply, tolerating a ```json fence."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise SceneAnalysisError("model did not return JSON")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SceneAnalysisError(f"model returned unparseable JSON: {exc}") from exc


async def analyze_scene(gemini, frames: list[bytes], camera_name: str,
                        width: int = 1280, height: int = 720) -> dict:
    """Ask Gemini to propose a configuration from sampled frames.

    Raises SceneAnalysisError with an operator-readable reason. One corrective
    re-prompt is attempted on unparseable output, matching the sequence
    compiler's behaviour.
    """
    if not frames:
        raise SceneAnalysisError("could not observe this camera long enough")

    prompt = SETUP_PROMPT.format(camera_name=camera_name, width=width, height=height)
    try:
        text = await gemini.generate_text_with_images(prompt, frames)
    except Exception as exc:  # noqa: BLE001
        raise SceneAnalysisError(f"scene analysis unavailable: {exc}") from exc

    try:
        return _extract_json(text)
    except SceneAnalysisError:
        logger.warning("[%s] unparseable setup reply; re-prompting once", camera_name)
        retry_prompt = prompt + "\n\nYour previous reply was not valid JSON. Reply with ONLY the JSON object."
        try:
            text = await gemini.generate_text_with_images(retry_prompt, frames)
        except Exception as exc:  # noqa: BLE001
            raise SceneAnalysisError(f"scene analysis unavailable: {exc}") from exc
        return _extract_json(text)
