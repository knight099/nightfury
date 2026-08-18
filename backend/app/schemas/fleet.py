"""Schemas for the site fleet view.

Capacity behaviour nobody can see is indistinguishable from a bug, so these
responses are part of the scaling mechanism rather than a reporting extra.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FleetCamera(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    agent_id: uuid.UUID | None = None
    pinned_agent_id: uuid.UUID | None = None
    last_frame_at: datetime | None = None


class FleetAgent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    machine_id: str
    status: str
    version: str | None = None
    last_seen_at: datetime | None = None

    capacity_cameras: int | None = None
    capacity_source: str = "declared"
    assigned_count: int = 0
    assignment_version: int = 1
    load_state: str = "ok"
    load_reason: str | None = None

    # Derived, so the UI does not have to re-implement the rule that a stale
    # heartbeat means the box is not actually working.
    is_stale: bool = False
    spare_capacity: int = 0
    cameras: list[FleetCamera] = []


class FleetResponse(BaseModel):
    site_id: uuid.UUID
    site_name: str

    agents: list[FleetAgent] = []
    unassigned_cameras: list[FleetCamera] = []

    # The honest coverage number: how many of this site's cameras are actually
    # placed on a live box. This is the figure the pitch promises and the one
    # an operator should be able to read at a glance.
    cameras_total: int = 0
    cameras_covered: int = 0
    capacity_total: int = 0
    # How many more cameras this site can absorb before another appliance is
    # needed. Negative is impossible by construction; zero with unassigned
    # cameras present is the "add an appliance" signal.
    capacity_spare: int = 0


class PinCameraRequest(BaseModel):
    # None clears the pin and returns the camera to automatic placement.
    agent_id: uuid.UUID | None = None
