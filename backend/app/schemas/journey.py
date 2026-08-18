"""Schemas for camera adjacency and event journeys."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CameraConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    camera_a_id: uuid.UUID
    camera_b_id: uuid.UUID
    label: str | None = None
    created_at: datetime


class CreateConnectionRequest(BaseModel):
    camera_a_id: uuid.UUID
    camera_b_id: uuid.UUID
    label: str | None = None


class UpdateConnectionRequest(BaseModel):
    label: str | None = None


class JourneyStepResponse(BaseModel):
    camera_id: uuid.UUID
    camera_name: str
    event_id: uuid.UUID
    timestamp: datetime
    event_type: str
    severity: str
    # Operator's label for the connection walked to reach this step.
    via: str | None = None


class JourneyResponse(BaseModel):
    seed_event_id: uuid.UUID
    # False for most events — nothing happened on a connected camera in the
    # window. A normal outcome, not an error.
    has_journey: bool
    # Templated, never model-generated: the wording carries the "may or may
    # not be the same person" caveat that defines what this feature claims.
    summary: str
    steps: list[JourneyStepResponse] = []
