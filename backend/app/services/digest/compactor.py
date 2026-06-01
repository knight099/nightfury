from dataclasses import dataclass
from typing import Iterable, Mapping

DESCRIPTION_MAX = 280


@dataclass
class EventCompact:
    time: str           # ISO 8601
    camera_name: str
    event_type: str
    severity: str
    description: str
    confidence: float


def compact_events(events: Iterable[Mapping]) -> list[EventCompact]:
    """Reduce raw event dicts to the small fields Gemini needs for a text summary."""
    result: list[EventCompact] = []
    for e in events:
        camera_name = e.get("camera_name") or "unknown-camera"
        description = (e.get("description") or "")[:DESCRIPTION_MAX]
        result.append(
            EventCompact(
                time=e["timestamp"].isoformat(),
                camera_name=camera_name,
                event_type=e.get("event_type") or "unknown",
                severity=e.get("severity") or "low",
                description=description,
                confidence=float(e.get("confidence") or 0.0),
            )
        )
    return result
