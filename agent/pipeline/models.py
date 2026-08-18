from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class CameraConfig:
    camera_id: str
    org_id: str
    name: str
    ingest_mode: str  # rtsp_pull, rtmp_push, srt_push
    site_id: str = ""
    site_name: str = ""
    rtsp_url: str | None = None
    stream_key: str | None = None
    enabled_events: list[str] = field(default_factory=lambda: ["person", "vehicle", "intrusion"])
    detection_zones: list[dict] = field(default_factory=list)
    step_sequence: list[dict] = field(default_factory=list)
    # Operator-drawn line segments for footfall counting.
    counting_lines: list[dict] = field(default_factory=list)
    sensitivity: str = "medium"
    timezone: str = "Asia/Kolkata"
    idle_fps: float = 1.0
    active_fps: float = 5.0

    @classmethod
    def from_assignment(cls, a: dict) -> "CameraConfig":
        return cls(
            camera_id=a["camera_id"],
            org_id=a["org_id"],
            name=a.get("name", ""),
            ingest_mode=a["ingest_mode"],
            site_id=a.get("site_id", ""),
            site_name=a.get("site_name", ""),
            rtsp_url=a.get("rtsp_url"),
            stream_key=a.get("stream_key"),
            enabled_events=a.get("enabled_events", ["person", "vehicle", "intrusion"]),
            detection_zones=a.get("detection_zones", []),
            step_sequence=a.get("step_sequence", []),
            counting_lines=a.get("counting_lines", []),
            sensitivity=a.get("sensitivity", "medium"),
            timezone=a.get("timezone", "UTC"),
            idle_fps=float(a.get("idle_fps", 1.0)),
            active_fps=float(a.get("active_fps", 5.0)),
        )


@dataclass
class BoundingBox:
    x1: int
    y1: int
    x2: int
    y2: int
    label: str


@dataclass
class DetectedEvent:
    event_type: str
    confidence: float
    severity: str
    description: str
    bounding_boxes: list[BoundingBox] = field(default_factory=list)
    zone: str | None = None


@dataclass
class TimestampedFrame:
    frame: "numpy.ndarray"
    timestamp: float
