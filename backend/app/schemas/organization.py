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
    deleted_at: datetime | None = None

    class Config:
        from_attributes = True


class CreateOrgRequest(BaseModel):
    name: str
    plan: str = "free"
    settings: dict | None = None


class UpdateOrgRequest(BaseModel):
    name: str | None = None
    plan: str | None = None
    # `settings` is deliberately NOT updatable here.
    #
    # It used to be, and it REPLACED the whole JSONB blob — so one PATCH could
    # clobber unrelated keys, and could write an unvalidated `retention_days`
    # that bypasses the range checks on PUT /api/settings/org/retention and
    # causes irreversible deletion on the next nightly purge.
    #
    # Settings that matter get their own validated endpoint. No caller ever
    # sent this field (the frontend's updateMyOrg is typed {name?, plan?}),
    # so removing it breaks nothing.
