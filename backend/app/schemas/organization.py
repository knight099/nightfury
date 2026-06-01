import uuid
from datetime import datetime

from pydantic import BaseModel


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    settings: dict
    created_at: datetime

    class Config:
        from_attributes = True


class CreateOrgRequest(BaseModel):
    name: str
    plan: str = "free"
    settings: dict | None = None


class UpdateOrgRequest(BaseModel):
    name: str | None = None
    plan: str | None = None
    settings: dict | None = None
