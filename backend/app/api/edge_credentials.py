"""Edge box Gemini/Vertex AI short-lived token broker.

Edge boxes (paired agents) call this endpoint to obtain a short-lived Vertex
AI access token minted server-side, so they never hold a long-lived static
Gemini/Vertex credential on hardware that could be physically stolen.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core.dependencies import get_agent_from_token
from app.models.agent import Agent
from app.services.gemini_broker import GeminiBrokerUnavailable, mint_vertex_token

router = APIRouter(prefix="/api/edge", tags=["edge"])


class GeminiTokenResponse(BaseModel):
    """Short-lived Vertex AI access token + the project/location to target."""
    access_token: str
    expires_at: str
    vertex_project: str
    vertex_location: str


@router.post("/gemini-token", response_model=GeminiTokenResponse)
async def get_gemini_token(
    agent: Agent = Depends(get_agent_from_token),
) -> GeminiTokenResponse:
    """Mint a fresh ~30-minute Vertex AI access token for a paired edge box.

    A new token is minted on every call — never cached/reused across agents.

    Returns 503 when the broker can't mint a token in this environment (no
    ADC configured, ambient identity isn't a service account, or the
    self-impersonation IAM binding is missing) rather than surfacing an
    unhandled 500.
    """
    try:
        token, expires_at = mint_vertex_token(ttl_seconds=1800)
    except GeminiBrokerUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Gemini token broker unavailable"
        ) from exc
    return GeminiTokenResponse(
        access_token=token,
        expires_at=expires_at.isoformat(),
        vertex_project=settings.gemini_vertex_project,
        vertex_location=settings.gemini_vertex_location,
    )
