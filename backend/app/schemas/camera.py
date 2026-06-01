import uuid
from datetime import datetime

from pydantic import BaseModel


class CreateCameraRequest(BaseModel):
    name: str
    site_id: uuid.UUID
    ingest_mode: str  # rtsp_pull, rtmp_push, srt_push
    rtsp_url: str | None = None
    enabled_events: list[str] = ["person", "vehicle", "intrusion"]
    detection_zones: list[dict] = []
    sensitivity: str = "medium"
    idle_fps: float = 1.0
    active_fps: float = 5.0


class UpdateCameraRequest(BaseModel):
    name: str | None = None
    ingest_mode: str | None = None
    rtsp_url: str | None = None
    enabled_events: list[str] | None = None
    detection_zones: list[dict] | None = None
    sensitivity: str | None = None
    idle_fps: float | None = None
    active_fps: float | None = None


class CameraResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    site_id: uuid.UUID
    name: str
    ingest_mode: str
    stream_key: str | None
    enabled_events: list[str]
    detection_zones: list[dict]
    sensitivity: str
    status: str
    last_frame_at: datetime | None
    worker_id: str | None
    idle_fps: float
    active_fps: float
    created_at: datetime

    class Config:
        from_attributes = True


class CameraCreatedResponse(BaseModel):
    camera: CameraResponse
    ingest_endpoint: str | None = None
    stream_key: str | None = None


class LatestFrameResponse(BaseModel):
    url: str
    updated_at: datetime
