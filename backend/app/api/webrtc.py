from fastapi import APIRouter, Depends

from app.config import settings
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.webrtc import IceServer, IceServersResponse
from app.services.turn_credentials import mint_turn_credentials

router = APIRouter(prefix="/api/webrtc", tags=["webrtc"])


@router.get("/ice-servers", response_model=IceServersResponse)
async def get_ice_servers(user: User = Depends(get_current_user)) -> IceServersResponse:
    """Short-lived ICE server list for the browser's RTCPeerConnection.

    Always includes public STUN. Includes a freshly minted TURN credential
    only when TURN is configured on this deployment (see
    app.services.turn_credentials) — otherwise the browser falls back to
    direct P2P via STUN alone.
    """
    servers = [IceServer(urls="stun:stun.l.google.com:19302")]

    minted = mint_turn_credentials()
    if minted:
        username, credential, _expires_at = minted
        servers.append(
            IceServer(
                urls=f"turn:{settings.turn_url}",
                username=username,
                credential=credential,
            )
        )

    return IceServersResponse(iceServers=servers)
