import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.device_provision import DeviceProvision
from app.services.device_token_service import DeviceTokenService

PROVISION_TTL_MINUTES = 10


class DeviceProvisionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Device-side
    # ------------------------------------------------------------------

    async def provision(
        self,
        device_id: uuid.UUID,
        code: str,
        pubkey: str,
        machine_id: str,
        version: Optional[str] = None,
    ) -> DeviceProvision:
        """Upsert a provisioning request for a device.

        If the device already has a live (waiting) request we refresh its
        expiry instead of creating a duplicate.  If the 4-digit code
        collides with another waiting request we pick a new one.
        """
        now = datetime.now(timezone.utc)
        fresh_expiry = now + timedelta(minutes=PROVISION_TTL_MINUTES)

        # Refresh existing live request
        existing = (
            await self.db.execute(
                select(DeviceProvision).where(
                    DeviceProvision.device_id == device_id,
                    DeviceProvision.status == "waiting",
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.expires_at = fresh_expiry
            await self.db.flush()
            return existing

        # Resolve code collisions
        for _ in range(10):
            conflict = (
                await self.db.execute(
                    select(DeviceProvision).where(
                        DeviceProvision.code == code,
                        DeviceProvision.status == "waiting",
                    )
                )
            ).scalar_one_or_none()
            if conflict is None:
                break
            code = f"{random.randint(0, 9999):04d}"

        provision = DeviceProvision(
            device_id=device_id,
            code=code,
            pubkey=pubkey,
            machine_id=machine_id,
            version=version,
            status="waiting",
            expires_at=fresh_expiry,
        )
        self.db.add(provision)
        await self.db.flush()
        return provision

    async def get_status(self, device_id: uuid.UUID) -> Optional[DeviceProvision]:
        return (
            await self.db.execute(
                select(DeviceProvision).where(DeviceProvision.device_id == device_id)
            )
        ).scalar_one_or_none()

    # ------------------------------------------------------------------
    # Customer-side
    # ------------------------------------------------------------------

    async def claim(
        self,
        code: str,
        org_id: uuid.UUID,
        relay_url: str,
    ) -> DeviceProvision:
        """Link a waiting device to an org using the NW-XXXX code."""
        now = datetime.now(timezone.utc)
        provision = (
            await self.db.execute(
                select(DeviceProvision).where(
                    DeviceProvision.code == code,
                    DeviceProvision.status == "waiting",
                    DeviceProvision.expires_at > now,
                )
            )
        ).scalar_one_or_none()

        if provision is None:
            raise ValueError("invalid or expired device code")

        # Reuse existing agent for this machine if one already exists in the org.
        existing_agent = (
            await self.db.execute(
                select(Agent).where(
                    Agent.org_id == org_id,
                    Agent.machine_id == provision.machine_id,
                )
            )
        ).scalar_one_or_none()

        token, token_hash = DeviceTokenService.mint()
        if existing_agent:
            existing_agent.pubkey = provision.pubkey
            existing_agent.device_token_hash = token_hash
            existing_agent.version = provision.version
            existing_agent.status = "online"
            existing_agent.last_seen_at = now
            agent = existing_agent
        else:
            agent = Agent(
                org_id=org_id,
                machine_id=provision.machine_id,
                pubkey=provision.pubkey,
                device_token_hash=token_hash,
                version=provision.version,
                status="online",
                last_seen_at=now,
            )
            self.db.add(agent)
        await self.db.flush()

        provision.status = "claimed"
        provision.org_id = org_id
        provision.agent_id = agent.id
        provision.device_token = token
        provision.relay_url = relay_url
        provision.claimed_at = now
        await self.db.flush()
        return provision
