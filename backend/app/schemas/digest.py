from datetime import datetime, time
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


DigestKind = Literal["scheduled_morning", "scheduled_evening", "on_demand"]


class DigestHighlight(BaseModel):
    time: datetime
    camera_name: str
    why_notable: str
    event_id: uuid.UUID | None = None


class DigestPayload(BaseModel):
    headline: str
    period: str
    total_events: int
    by_severity: dict[str, int]
    narrative: str
    highlights: list[DigestHighlight]
    quiet_periods: list[str] = Field(default_factory=list)
    degraded: bool = False


class DigestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # None = organisation-wide; set = this digest covers one site only.
    site_id: uuid.UUID | None = None
    kind: DigestKind
    range_start: datetime
    range_end: datetime
    event_count: int
    payload: DigestPayload
    delivered_channels: list[str]
    created_at: datetime


class DigestListResponse(BaseModel):
    items: list[DigestResponse]
    total: int


class DigestRequest(BaseModel):
    start: datetime
    end: datetime
    camera_ids: list[uuid.UUID] | None = None
    site_id: uuid.UUID | None = None

    @field_validator("end")
    @classmethod
    def end_after_start(cls, v, info):
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError("end must be after start")
        return v


class DigestPreferencesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    morning_enabled: bool
    morning_local_time: time
    evening_enabled: bool
    evening_local_time: time
    whatsapp_enabled: bool
    email_enabled: bool


class DigestPreferencesUpdate(BaseModel):
    morning_enabled: bool | None = None
    morning_local_time: time | None = None
    evening_enabled: bool | None = None
    evening_local_time: time | None = None
    whatsapp_enabled: bool | None = None
    email_enabled: bool | None = None
