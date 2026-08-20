"""Pydantic schemas for the agent onboarding API."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PairCodeRequest(BaseModel):
    """Body for minting a pair code.

    ``org_id`` is only used for super_admin (who has no org of their own) to
    pick which org the paired agent will belong to. Ignored for normal users
    — they always mint codes for their own org.
    """

    org_id: uuid.UUID | None = None


class PairCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class InstallerRequest(BaseModel):
    """Create a one-click installer for a specific desktop/edge platform."""

    platform: str = Field(
        ...,
        pattern=r"^(linux-amd64|linux-arm64|darwin-amd64|darwin-arm64|windows-amd64)$",
    )
    org_id: uuid.UUID | None = None


class InstallerResponse(BaseModel):
    filename: str
    content: str
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


class DiscoveredDevice(BaseModel):
    """An ONVIF device found by the agent's WS-Discovery probe."""

    uuid: str = Field(..., max_length=256)
    name: str = "unknown"
    xaddr: str = Field(..., max_length=512)


class DiscoverPushRequest(BaseModel):
    """Body of the agent-authenticated push of discovery results."""

    devices: list[DiscoveredDevice] = Field(default_factory=list, max_length=64)


class DiscoverResponse(BaseModel):
    devices: list[DiscoveredDevice]


class RegisterCameraRequest(BaseModel):
    """Register a camera behind an agent.

    Two forms, matching the onboarding wizard:
    - manual entry sends a ready ``rtsp_url``
    - discovered-device flow sends ``onvif_xaddr`` + NVR credentials and the
      backend derives a default RTSP URL from the device host
    ``site_id`` is optional; when omitted the org's first site is used
    (created as "Home" if the org has none).
    """

    name: str
    site_id: uuid.UUID | None = None
    rtsp_url: str | None = None
    onvif_xaddr: str | None = None
    user: str | None = None
    password: str | None = Field(default=None, alias="pass")
    brand: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class RegisterCameraResponse(BaseModel):
    camera_id: uuid.UUID
    status: str


class ResolveJob(BaseModel):
    """An ONVIF GetStreamUri job for the agent to run on the LAN.

    The backend can't reach the camera directly, so it hands the agent the
    device's ONVIF xaddr + NVR credentials and waits for the resolved RTSP
    URL.
    """

    camera_id: uuid.UUID
    xaddr: str
    user: str | None = None
    password: str | None = Field(default=None, alias="pass")

    model_config = ConfigDict(populate_by_name=True)


class ResolveJobsResponse(BaseModel):
    jobs: list[ResolveJob]


class ResolveResultRequest(BaseModel):
    rtsp_url: str | None = None
    error: str | None = None


class OnboardingCameraState(BaseModel):
    camera_id: uuid.UUID
    name: str
    status: str                      # online | offline | error | unassigned
    first_frame_at: datetime | None = None
    snapshot_url: str | None = None
    zones_count: int = 0
    failure_reason: str | None = None


class OnboardingStatusResponse(BaseModel):
    agent_id: uuid.UUID
    state: str                       # see STATES below
    agent_online: bool
    last_seen_at: datetime | None = None
    discovered_count: int = 0
    cameras: list[OnboardingCameraState] = []
    verified_camera_count: int = 0
    failure_reason: str | None = None
