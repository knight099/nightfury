"""Wire shapes for agentic camera setup."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SetupJob(BaseModel):
    """One camera for the pipeline to observe and propose a config for."""

    camera_id: uuid.UUID
    camera_name: str
    rtsp_url: str | None = None
    # Observation parameters travel with the job so they can be tuned
    # server-side without shipping a new agent build.
    frame_count: int = 10
    observe_seconds: int = 180


class SetupJobsResponse(BaseModel):
    jobs: list[SetupJob] = []


class SetupResultRequest(BaseModel):
    """The pipeline's answer for one camera: a proposal, or why not."""

    proposal: dict | None = None
    error: str | None = None
    frame_width: int = 1280
    frame_height: int = 720


class ProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    camera_id: uuid.UUID
    status: str
    scene_type: str | None = None
    scene_description: str | None = None
    confidence: float | None = None
    proposal: dict = {}
    rationale: str | None = None
    error: str | None = None
    approved_at: datetime | None = None


class ReviewGroupResponse(BaseModel):
    scene_type: str
    label: str
    bulk_approvable: bool
    shared_config: dict = {}
    proposals: list[ProposalResponse] = []
    differing: list[ProposalResponse] = []


class SetupRunResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    status: str
    camera_count: int
    pending: int = 0
    groups: list[ReviewGroupResponse] = []


class StartRunRequest(BaseModel):
    # Explicit camera list, never "the whole site" — the operator chooses the
    # batch so they can learn from the first one.
    camera_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=50)


class ApproveGroupRequest(BaseModel):
    scene_type: str
