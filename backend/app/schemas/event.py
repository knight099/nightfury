import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CreateEventRequest(BaseModel):
    camera_id: uuid.UUID
    timestamp: datetime
    event_type: str
    confidence: float
    severity: str
    description: str
    bounding_boxes: list[dict] = []
    snapshot_url: str
    clip_url: str | None = None
    ai_model: str = "gemini-2.0-flash"
    ai_response_raw: dict | None = None
    metadata_extra: dict = {}


class EventResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    camera_id: uuid.UUID
    site_id: uuid.UUID
    timestamp: datetime
    event_type: str
    confidence: float
    severity: str
    description: str
    bounding_boxes: list[dict]
    snapshot_url: str
    clip_url: str | None
    ai_model: str

    # Operational state — "did somebody deal with it?"
    status: str = "new"
    acknowledged_by: uuid.UUID | None = None
    acknowledged_at: datetime | None = None
    resolved_by: uuid.UUID | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None

    # Detection quality — "was it right?" (independent of the above)
    feedback: str | None
    feedback_label: str | None
    feedback_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeedbackRequest(BaseModel):
    feedback: str  # approved, rejected, reclassified
    label: str | None = None


class EventStatusRequest(BaseModel):
    status: str  # acknowledged, resolved, dismissed, new
    note: str | None = None


class EventStatsTimeBucket(BaseModel):
    bucket: datetime
    count: int
    by_severity: dict[str, int]


class EventStatsCameraBreakdown(BaseModel):
    camera_id: uuid.UUID | None
    camera_name: str
    count: int


class EventStatsResponse(BaseModel):
    total_events: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    feedback_rate: float
    false_positive_rate: float
    time_series: list[EventStatsTimeBucket] = []
    by_camera: list[EventStatsCameraBreakdown] = []
