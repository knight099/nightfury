import uuid
from datetime import datetime

from pydantic import BaseModel


class AssistantMessageRequest(BaseModel):
    message: str
    conversation_id: uuid.UUID | None = None
    current_route: str | None = None


class ProposalResponse(BaseModel):
    id: uuid.UUID
    kind: str
    summary: str
    payload: dict
    status: str
    expires_at: datetime

    class Config:
        from_attributes = True


class AssistantMessageResponse(BaseModel):
    conversation_id: uuid.UUID
    text: str
    proposals: list[ProposalResponse] = []
    navigate: str | None = None
    stopped_early: bool = False


class ApplyProposalResponse(BaseModel):
    status: str
    created_id: uuid.UUID | None = None
