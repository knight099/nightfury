"""Shared device-token → Agent resolution.

Single implementation used by every device-token auth site (the
``/internal/*`` dependency, the edge-box routes, the relay's verify-token
call, and the agent control WebSocket) so they all get the same indexed
lookup instead of each re-implementing a full-table Argon2 scan.

See ``app.services.device_token_service`` for why the lookup key exists.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.services.device_token_service import DeviceTokenService

logger = logging.getLogger(__name__)


async def resolve_agent_by_token(db: AsyncSession, token: str) -> Agent | None:
    """Resolve a paired Agent from a presented device token.

    Fast path: one indexed lookup on ``agents.device_token_id`` followed by a
    single Argon2 verify — O(1) expensive hashes per request regardless of
    how many agents exist.

    Legacy path: agents paired before the ``device_token_id`` column existed
    have it NULL, so they can't be found by lookup key. Those rows (and only
    those) are scanned and verified the old way; on a successful match the
    row is backfilled with its lookup key, so the legacy set shrinks to zero
    as agents re-authenticate and never grows again. Once it is empty the
    scan degenerates to a cheap indexed "no rows" query.
    """
    if not token:
        return None

    svc = DeviceTokenService()
    token_id = svc.token_id(token)

    result = await db.execute(
        select(Agent).where(
            Agent.device_token_id == token_id,
            Agent.status != "unpaired",
        )
    )
    for agent in result.scalars():
        if agent.device_token_hash and svc.verify(token, agent.device_token_hash):
            return agent

    # Legacy rows only — bounded, shrinking, and empty for new deployments.
    legacy = await db.execute(
        select(Agent).where(
            Agent.device_token_id.is_(None),
            Agent.status != "unpaired",
        )
    )
    for agent in legacy.scalars():
        if agent.device_token_hash and svc.verify(token, agent.device_token_hash):
            agent.device_token_id = token_id
            try:
                await db.flush()
            except Exception:  # pragma: no cover - backfill is best-effort
                logger.warning("device_token_id backfill failed for agent %s", agent.id)
            return agent

    return None
