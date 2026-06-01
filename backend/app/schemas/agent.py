"""Pydantic schemas for the agent onboarding API."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PairCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class PairRequest(BaseModel):
    code: str = Field(..., pattern=r"^\d{6}$")
    machine_id: str = Field(..., min_length=8, max_length=128)
    pubkey: str = Field(..., min_length=16, max_length=512)
    version: str | None = None


class PairResponse(BaseModel):
    device_token: str
    relay_url: str
    org_id: uuid.UUID
    agent_id: uuid.UUID


class AgentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    machine_id: str
    version: str | None = None
    transport: str | None = None
    status: str
    last_seen_at: datetime | None = None
    created_at: datetime


class AgentListResponse(BaseModel):
    agents: list[AgentSummary]


class AgentDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    machine_id: str
    version: str | None = None
    transport: str | None = None
    status: str
    last_seen_at: datetime | None = None
    created_at: datetime
    cameras_streaming: int = 0


class DiscoveredCamera(BaseModel):
    name: str | None = None
    rtsp_url: str
    brand: str | None = None
    model: str | None = None


class DiscoverResponse(BaseModel):
    cameras: list[DiscoveredCamera]


class RegisterCameraRequest(BaseModel):
    name: str
    site_id: uuid.UUID
    rtsp_url: str
    brand: str | None = None


class RegisterCameraResponse(BaseModel):
    camera_id: uuid.UUID
