import uuid
from datetime import datetime

from pydantic import BaseModel


class CreateAlertRuleRequest(BaseModel):
    name: str
    site_id: uuid.UUID | None = None  # None = all sites
    cameras: list[uuid.UUID] = []
    event_types: list[str] = []
    min_severity: str = "low"
    time_window: dict | None = None  # {start: "22:00", end: "06:00", days: [...]}
    zones: list[str] = []
    notify_channels: list[str]  # whatsapp, email, webhook
    notify_contacts: list[dict]  # [{type, value}]
    webhook_url: str | None = None
    cooldown_seconds: int = 60
    # Ordered rungs: [{after_seconds, channels, contacts}]. Empty = notify
    # once and never chase, which is the existing behaviour.
    escalation: list[dict] = []


class UpdateAlertRuleRequest(BaseModel):
    name: str | None = None
    site_id: uuid.UUID | None = None
    cameras: list[uuid.UUID] | None = None
    event_types: list[str] | None = None
    min_severity: str | None = None
    time_window: dict | None = None
    zones: list[str] | None = None
    notify_channels: list[str] | None = None
    notify_contacts: list[dict] | None = None
    webhook_url: str | None = None
    cooldown_seconds: int | None = None
    enabled: bool | None = None


class AlertRuleResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    site_id: uuid.UUID | None = None
    cameras: list[uuid.UUID]
    event_types: list[str]
    min_severity: str
    time_window: dict | None
    zones: list[str]
    notify_channels: list[str]
    notify_contacts: list[dict]
    webhook_url: str | None
    cooldown_seconds: int
    escalation: list[dict] = []
    enabled: bool
    created_at: datetime
    deleted_at: datetime | None = None

    class Config:
        from_attributes = True


class AlertHistoryResponse(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None
    event_id: uuid.UUID
    channel: str
    recipient: str
    status: str
    sent_at: datetime

    class Config:
        from_attributes = True
