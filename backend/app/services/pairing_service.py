"""Pairing service for agent device onboarding.

Manages 6-digit one-time codes that an authenticated user generates for an
agent process to redeem for a long-lived device token.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_pair_code import AgentPairCode

PAIR_CODE_TTL_SECONDS = 600


class PairingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def mint_code(self, org_id: uuid.UUID, user_id: uuid.UUID) -> str:
        """Generate a unique zero-padded 6-digit code and persist it."""
        for _ in range(10):
            code = f"{secrets.randbelow(1_000_000):06d}"
            existing = await self.db.execute(
                select(AgentPairCode).where(AgentPairCode.code == code)
            )
            if existing.scalar_one_or_none() is None:
                break
        else:
            raise RuntimeError("could not allocate unique pair code")

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=PAIR_CODE_TTL_SECONDS)
        row = AgentPairCode(
            code=code,
            org_id=org_id,
            created_by=user_id,
            expires_at=expires_at,
        )
        self.db.add(row)
        await self.db.flush()
        return code

    async def get_code(self, code: str) -> AgentPairCode | None:
        result = await self.db.execute(
            select(AgentPairCode).where(AgentPairCode.code == code)
        )
        return result.scalar_one_or_none()

    async def redeem_code(self, code: str) -> uuid.UUID:
        """Atomically consume a pair code and return its org_id.

        Raises ValueError("not found"|"consumed"|"expired") on failure.
        """
        row = await self.get_code(code)
        if row is None:
            raise ValueError("not found")
        if row.consumed_at is not None:
            raise ValueError("consumed")
        # Compare in UTC; DB column is timezone-aware
        now = datetime.now(timezone.utc)
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise ValueError("expired")
        row.consumed_at = now
        await self.db.flush()
        return row.org_id
