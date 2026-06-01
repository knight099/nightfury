import uuid
from datetime import datetime

from pydantic import BaseModel


class CreateSiteRequest(BaseModel):
    name: str
    address: str | None = None
    timezone: str = "Asia/Kolkata"


class UpdateSiteRequest(BaseModel):
    name: str | None = None
    address: str | None = None
    timezone: str | None = None


class SiteResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    address: str | None
    timezone: str
    created_at: datetime

    class Config:
        from_attributes = True
