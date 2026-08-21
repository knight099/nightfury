import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, model_validator


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
    claim_url: str          # https://app.../connect?claim=<opaque>


class StatusResponse(BaseModel):
    status: str
    device_token: Optional[str] = None
    relay_url: Optional[str] = None
    org_id: Optional[uuid.UUID] = None
    agent_id: Optional[uuid.UUID] = None


class ClaimRequest(BaseModel):
    # Exactly one of code / claim_token must be supplied — code is the
    # customer-typed NW-XXXXXX digits, claim_token is the opaque one-time
    # lookup handle encoded in the QR. Both resolve to the same device;
    # neither is ever the device_token itself.
    code: Optional[str] = None
    claim_token: Optional[str] = None
    org_id: Optional[uuid.UUID] = None

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "ClaimRequest":
        if bool(self.code) == bool(self.claim_token):
            raise ValueError("exactly one of code or claim_token is required")
        return self


class ClaimResponse(BaseModel):
    agent_id: uuid.UUID
    org_id: uuid.UUID
    message: str
