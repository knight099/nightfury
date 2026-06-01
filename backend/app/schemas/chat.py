import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None  # super_admin may scope to an org


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class ChatMessageDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    camera_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    created_at: datetime


class ConversationSummary(BaseModel):
    conversation_id: uuid.UUID
    last_message_at: datetime
    last_content: str
    camera_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
