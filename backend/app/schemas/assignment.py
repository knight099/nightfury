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
    step_sequence: list[dict] = []
    counting_lines: list[dict] = []
    sensitivity: str
    idle_fps: float
    active_fps: float
    timezone: str = "UTC"


class AssignmentsResponse(BaseModel):
    assignments: list[Assignment]
    # Bumped by the placement reconciler whenever this agent's camera set
    # changes. The agent echoes it back as ``If-None-Match``; an unchanged
    # version answers 304 instead of re-sending the whole payload, which is
    # what keeps a 25-agent fleet polling every 10s from being expensive.
    # None for the cloud-VM worker path, which has no per-agent version.
    assignment_version: int | None = None
