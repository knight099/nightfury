"""Schemas for worker camera assignment payloads."""
import uuid

from pydantic import BaseModel, ConfigDict


class Assignment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    camera_id: uuid.UUID
    org_id: uuid.UUID
    name: str
    ingest_mode: str
    rtsp_url: str | None = None
    stream_key: str | None = None
    enabled_events: list[str]
    detection_zones: list[dict]
    sensitivity: str
    idle_fps: float
    active_fps: float
    timezone: str = "UTC"


class AssignmentsResponse(BaseModel):
    assignments: list[Assignment]
