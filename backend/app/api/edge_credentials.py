"""Edge box Gemini/Vertex AI short-lived token broker.

Edge boxes (paired agents) call this endpoint to obtain a short-lived Vertex
AI access token minted server-side, so they never hold a long-lived static
Gemini/Vertex credential on hardware that could be physically stolen.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import settings
from app.core.dependencies import get_agent_from_token
from app.models.agent import Agent
from app.services.gemini_broker import mint_vertex_token

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
    """
    token, expires_at = mint_vertex_token(ttl_seconds=1800)
    return GeminiTokenResponse(
        access_token=token,
        expires_at=expires_at.isoformat(),
        vertex_project=settings.gemini_vertex_project,
        vertex_location=settings.gemini_vertex_location,
    )
