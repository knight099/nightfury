"""Derives onboarding state from facts already in the database.

The wizard renders whatever this returns. It deliberately keeps no state of
its own: a customer who refreshes, or resumes on their phone after starting
on a laptop, must land on the same step. Anything stored in React would be
lost on refresh and would drift from reality the moment a box went offline.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.agent import Agent
from app.models.camera import Camera

# Ordered. Each state is "the furthest point reached", never a step counter.
STATES = [
    "waiting_claim",
    "paired",
    "scanning",
    "cameras_selected",
    "stream_verified",
    "zones_saved",
    "alert_verified",
    "protected",
]

# An agent is considered offline once it misses this much heartbeat. Matches
# the fleet sweep's staleness window so the two surfaces never disagree.
AGENT_STALE_AFTER = timedelta(seconds=90)


def _discovery_key(agent_id: uuid.UUID) -> str:
    return f"agent:discovered:{agent_id}"


def _walk_test_key(agent_id: uuid.UUID) -> str:
    return f"agent:walktest_passed:{agent_id}"


class OnboardingStatusService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def status(self, agent: Agent) -> dict:
        now = datetime.now(timezone.utc)
        last_seen = agent.last_seen_at
        if last_seen is not None and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        agent_online = last_seen is not None and (now - last_seen) < AGENT_STALE_AFTER

        rows = await self.db.execute(
            select(Camera).where(
                Camera.agent_id == agent.id,
                Camera.deleted_at.is_(None),
            )
        )
        cameras = list(rows.scalars().all())

        redis = await get_redis()
        raw_discovered = await redis.get(_discovery_key(agent.id))
        discovered_count = 0
        if raw_discovered:
            try:
                discovered_count = len(json.loads(raw_discovered).get("devices", []))
            except (ValueError, AttributeError):
                discovered_count = 0

        walk_passed = bool(await redis.get(_walk_test_key(agent.id)))

        camera_states = [
            {
                "camera_id": c.id,
                "name": c.name,
                "status": c.status,
                "first_frame_at": c.last_frame_at,
                "snapshot_url": None,  # filled by the route, needs signing
                "zones_count": len(c.detection_zones or []),
                "failure_reason": self._camera_failure(c),
            }
            for c in cameras
        ]

        verified = [c for c in cameras if c.last_frame_at is not None]
        zoned = [c for c in verified if (c.detection_zones or [])]

        state = self._derive(
            agent_online=agent_online,
            camera_count=len(cameras),
            verified_count=len(verified),
            zoned_count=len(zoned),
            walk_passed=walk_passed,
            discovered_count=discovered_count,
        )

        return {
            "agent_id": agent.id,
            "state": state,
            "agent_online": agent_online,
            "last_seen_at": last_seen,
            "discovered_count": discovered_count,
            "cameras": camera_states,
            "verified_camera_count": len(verified),
            "failure_reason": None if agent_online else "Box is not reporting in.",
        }

    def _derive(
        self,
        *,
        agent_online: bool,
        camera_count: int,
        verified_count: int,
        zoned_count: int,
        walk_passed: bool,
        discovered_count: int,
    ) -> str:
        # Walked backwards on purpose: report the furthest point actually
        # reached, so a customer who adds a second camera later is not
        # dragged back to "scanning".
        if walk_passed and zoned_count > 0:
            return "protected"
        if walk_passed:
            return "alert_verified"
        if zoned_count > 0:
            return "zones_saved"
        if verified_count > 0:
            return "stream_verified"
        if camera_count > 0:
            return "cameras_selected"
        if discovered_count > 0:
            return "scanning"
        if agent_online:
            return "paired"
        return "waiting_claim"

    def _camera_failure(self, c: Camera) -> str | None:
        if c.status == "unassigned":
            return "No appliance is analysing this camera."
        if c.status == "error":
            return "The box could not open this camera's stream."
        if c.rtsp_url is None:
            return "Still resolving this camera's stream address."
        return None
