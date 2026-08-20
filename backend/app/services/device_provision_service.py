import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.agent import Agent
from app.models.device_provision import DeviceProvision
from app.services.device_token_service import DeviceTokenService

PROVISION_TTL_MINUTES = 10

# 4-digit codes are legacy: boxes flashed before the crypto/rand change.
# Accept them until the pilot fleet is confirmed upgraded, then delete this.
LEGACY_CODE_LENGTH = 4
CODE_LENGTH = 6

# Redis key prefix for the opaque one-time claim token minted alongside each
# code. The token is a lookup handle, not a credential — it resolves to a
# device_id exactly the way typing the six digits does, and is deleted the
# instant it is consumed so it cannot be replayed.
CLAIM_TOKEN_PREFIX = "device:claim_token:"


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
    ) -> tuple[DeviceProvision, str]:
        """Upsert a provisioning request for a device.

        If the device already has a live (waiting) request we refresh its
        expiry instead of creating a duplicate.  If the code collides with
        another waiting request we pick a new one of the same length.

        Returns the provision row and a fresh opaque claim_token. The claim
        token is a Redis-only lookup handle (device:claim_token:{token} ->
        device_id), never persisted to Postgres and never the device_token
        itself — it is minted (and re-minted) on every call so a stale QR
        from an earlier boot cannot outlive the code it was printed with.
        """
        if len(code) not in (LEGACY_CODE_LENGTH, CODE_LENGTH) or not code.isdigit():
            raise ValueError(
                f"code must be {LEGACY_CODE_LENGTH} or {CODE_LENGTH} digits"
            )

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
            # A device_id alone must not be enough to pull a fresh claim
            # handle for someone else's waiting provisioning row — verify
            # this call is coming from the same box (pubkey + machine_id)
            # that created it before refreshing anything.
            if existing.pubkey != pubkey or existing.machine_id != machine_id:
                raise ValueError(
                    "device_id already has a pending provisioning request "
                    "from a different device"
                )
            existing.expires_at = fresh_expiry
            await self.db.flush()
            claim_token = await self._mint_claim_token(existing.device_id)
            return existing, claim_token

        # Resolve code collisions, keeping the same digit length.
        code_len = len(code)
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
            code = f"{secrets.randbelow(10**code_len):0{code_len}d}"

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
        claim_token = await self._mint_claim_token(provision.device_id)
        return provision, claim_token

    async def _mint_claim_token(self, device_id: uuid.UUID) -> str:
        """Mint an opaque one-time claim token for device_id in Redis.

        Same TTL as the pairing code. A lookup handle, not a credential:
        possessing it lets an *already-authenticated* customer claim the
        box, exactly as typing the six digits does.
        """
        claim_token = secrets.token_urlsafe(32)
        redis = await get_redis()
        await redis.set(
            f"{CLAIM_TOKEN_PREFIX}{claim_token}",
            str(device_id),
            ex=PROVISION_TTL_MINUTES * 60,
        )
        return claim_token

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
        """Link a waiting device to an org using the NW-XXXXXX (or legacy
        NW-XXXX) code."""
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

        return await self._finish_claim(provision, org_id, relay_url)

    async def claim_by_token(
        self,
        claim_token: str,
        org_id: uuid.UUID,
        relay_url: str,
    ) -> DeviceProvision:
        """Link a waiting device to an org using the opaque QR claim token.

        The token is a Redis-only lookup handle to a device_id — resolving
        it never exposes or requires the device_token. It is deleted
        immediately once resolved so it is genuinely single-use even if the
        claim itself later fails validation.
        """
        redis = await get_redis()
        key = f"{CLAIM_TOKEN_PREFIX}{claim_token}"
        device_id = await redis.get(key)
        await redis.delete(key)

        if device_id is None:
            raise ValueError("invalid or expired claim token")

        now = datetime.now(timezone.utc)
        provision = (
            await self.db.execute(
                select(DeviceProvision).where(
                    DeviceProvision.device_id == uuid.UUID(device_id),
                    DeviceProvision.status == "waiting",
                    DeviceProvision.expires_at > now,
                )
            )
        ).scalar_one_or_none()

        if provision is None:
            raise ValueError("invalid or expired device code")

        return await self._finish_claim(provision, org_id, relay_url)

    async def _finish_claim(
        self,
        provision: DeviceProvision,
        org_id: uuid.UUID,
        relay_url: str,
    ) -> DeviceProvision:
        now = datetime.now(timezone.utc)
        # Reuse existing agent for this machine if one already exists in the org.
        existing_agent = (
            await self.db.execute(
                select(Agent).where(
                    Agent.org_id == org_id,
                    Agent.machine_id == provision.machine_id,
                )
            )
        ).scalar_one_or_none()

        token, token_hash, token_id = DeviceTokenService.mint()
        if existing_agent:
            existing_agent.pubkey = provision.pubkey
            existing_agent.device_token_hash = token_hash
            existing_agent.device_token_id = token_id
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
                device_token_id=token_id,
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
