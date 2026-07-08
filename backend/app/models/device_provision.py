import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DeviceProvision(Base):
    """Tracks a device-initiated provisioning request.

    Flow:
      1. Device boots → generates NW-XXXX code → POST /api/devices/provision
      2. Customer enters code on the dashboard → POST /api/devices/claim
      3. Backend links device to org, issues device_token → Agent record created
      4. Device polls GET /api/devices/{device_id}/status → gets token
    """

    __tablename__ = "device_provisions"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    pubkey: Mapped[str] = mapped_column(String(512), nullable=False)
    machine_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="waiting")
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    device_token: Mapped[str | None] = mapped_column(String(256), nullable=True)
    relay_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
