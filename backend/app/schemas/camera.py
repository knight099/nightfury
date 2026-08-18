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
    step_sequence: list[dict] = []
    counting_lines: list[dict] = []
    sensitivity: str = "medium"
    idle_fps: float = 1.0
    active_fps: float = 5.0


class UpdateCameraRequest(BaseModel):
    name: str | None = None
    ingest_mode: str | None = None
    rtsp_url: str | None = None
    enabled_events: list[str] | None = None
    detection_zones: list[dict] | None = None
    step_sequence: list[dict] | None = None
    counting_lines: list[dict] | None = None
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
    step_sequence: list[dict]
    counting_lines: list[dict] = []
    sensitivity: str
    status: str
    last_frame_at: datetime | None
    worker_id: str | None
    idle_fps: float
    active_fps: float
    created_at: datetime
    deleted_at: datetime | None = None

    class Config:
        from_attributes = True


class CameraCreatedResponse(BaseModel):
    camera: CameraResponse
    ingest_endpoint: str | None = None
    stream_key: str | None = None


class LatestFrameResponse(BaseModel):
    url: str
    updated_at: datetime


class StreamUrlResponse(BaseModel):
    url: str
    expires_at: int


class WebRTCOfferRequest(BaseModel):
    offer: str


class WebRTCAnswerResponse(BaseModel):
    answer: str


class CompileSequenceRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str


class CompileSequenceResponse(BaseModel):
    conversation_id: uuid.UUID
    type: str  # "question" | "draft"
    message: str | None = None
    steps: list[dict] = []
    alert_rule: dict | None = None
    warnings: list[str] = []


class CompileSequenceConversationResponse(BaseModel):
    messages: list[dict]
