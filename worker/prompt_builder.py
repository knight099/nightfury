from datetime import datetime
from zoneinfo import ZoneInfo

from models import CameraConfig


SYSTEM_TEMPLATE = """You are a surveillance AI analyst. Analyze the camera frame for security events.

Camera: {camera_name}
Location: {site_name}
Time: {timestamp} {timezone}
Enabled detections: {enabled_events}
{zones_section}
Sensitivity: {sensitivity}

Respond ONLY with valid JSON matching this schema:
{{
  "events": [
    {{
      "event_type": "<one of: {enabled_events}>",
      "confidence": <float 0.0-1.0>,
      "severity": "<low|medium|high|critical>",
      "description": "<one sentence a security guard would understand>",
      "bounding_boxes": [{{"x1": <int>, "y1": <int>, "x2": <int>, "y2": <int>, "label": "<string>"}}],
      "zone": "<zone name if in a defined zone, else null>"
    }}
  ],
  "person_count": <int>,
  "scene_summary": "<brief scene description>"
}}

Rules:
- Only detect events from the enabled list above
- If nothing notable, return empty events array
- Confidence must reflect true certainty
- Severity guide: low=routine, medium=attention needed, high=immediate response, critical=emergency
- Bounding box coordinates are pixel values for 1280x720 frame
- Do NOT hallucinate events that aren't clearly visible"""


class PromptBuilder:
    """Builds camera-specific prompts for Gemini Vision API."""

    def build(self, camera_config: CameraConfig) -> str:
        zones_section = ""
        if camera_config.detection_zones:
            zone_descs = []
            for z in camera_config.detection_zones:
                zone_descs.append(f"- {z.get('name', 'unnamed')}: region at {z.get('points', [])}")
            zones_section = "Detection zones:\n" + "\n".join(zone_descs)

        now = datetime.now(tz=ZoneInfo(camera_config.timezone))

        return SYSTEM_TEMPLATE.format(
            camera_name=camera_config.name,
            site_name=camera_config.site_name,
            timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
            timezone=camera_config.timezone,
            enabled_events=", ".join(camera_config.enabled_events),
            zones_section=zones_section,
            sensitivity=camera_config.sensitivity,
        )
