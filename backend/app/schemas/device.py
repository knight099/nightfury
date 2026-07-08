import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProvisionRequest(BaseModel):
    device_id: uuid.UUID
    code: str
    pubkey: str
    machine_id: str
    version: Optional[str] = None


class ProvisionResponse(BaseModel):
    device_id: uuid.UUID
    code: str
    status: str
    expires_at: datetime


class StatusResponse(BaseModel):
    status: str
    device_token: Optional[str] = None
    relay_url: Optional[str] = None
    org_id: Optional[uuid.UUID] = None
    agent_id: Optional[uuid.UUID] = None


class ClaimRequest(BaseModel):
    code: str
    org_id: Optional[uuid.UUID] = None


class ClaimResponse(BaseModel):
    agent_id: uuid.UUID
    org_id: uuid.UUID
    message: str
