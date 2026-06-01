import uuid
from datetime import datetime, timezone

from app.services.digest.compactor import compact_events, EventCompact


def make_event(ts, severity="medium", description="x", event_type="motion", camera_name="Front"):
    return {
        "id": uuid.uuid4(),
        "timestamp": ts,
        "severity": severity,
        "description": description,
        "event_type": event_type,
        "camera_name": camera_name,
        "confidence": 0.9,
    }


def test_compact_emits_one_record_per_event():
    events = [
        make_event(datetime(2026, 5, 28, 1, 0, tzinfo=timezone.utc)),
        make_event(datetime(2026, 5, 28, 2, 30, tzinfo=timezone.utc), severity="high"),
    ]
    result = compact_events(events)
    assert len(result) == 2
    assert isinstance(result[0], EventCompact)
    assert result[0].time == "2026-05-28T01:00:00+00:00"
    assert result[1].severity == "high"


def test_compact_truncates_long_descriptions():
    long = "x" * 500
    events = [make_event(datetime(2026, 5, 28, tzinfo=timezone.utc), description=long)]
    result = compact_events(events)
    assert len(result[0].description) <= 280


def test_compact_handles_missing_camera_name():
    e = make_event(datetime(2026, 5, 28, tzinfo=timezone.utc))
    e["camera_name"] = None
    result = compact_events([e])
    assert result[0].camera_name == "unknown-camera"
