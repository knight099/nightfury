import uuid
from datetime import time

from sqlalchemy import Boolean, ForeignKey, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DigestPreferences(Base):
    __tablename__ = "digest_preferences"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    morning_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    morning_local_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(7, 0))
    evening_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evening_local_time: Mapped[time] = mapped_column(Time, nullable=False, default=time(19, 0))
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
