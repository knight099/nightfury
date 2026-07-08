"""Device-initiated provisioning API.

Flow:
  1. Device boots → generates NW-XXXX code → POST /api/devices/provision
  2. Device polls GET /api/devices/{device_id}/status every 5s
  3. Customer enters code at nightwatch.ai → POST /api/devices/claim
  4. Device poll returns claimed + device_token → starts streaming
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.device import (
    ClaimRequest,
    ClaimResponse,
    ProvisionRequest,
    ProvisionResponse,
    StatusResponse,
)
from app.services.device_provision_service import DeviceProvisionService

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.post(
    "/provision",
    response_model=ProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def provision_device(
    payload: ProvisionRequest,
    db: AsyncSession = Depends(get_db),
) -> ProvisionResponse:
    """Called by the device at boot to register its pairing code."""
    svc = DeviceProvisionService(db)
    prov = await svc.provision(
        device_id=payload.device_id,
        code=payload.code,
        pubkey=payload.pubkey,
        machine_id=payload.machine_id,
        version=payload.version,
    )
    return ProvisionResponse(
        device_id=prov.device_id,
        code=f"NW-{prov.code}",
        status=prov.status,
        expires_at=prov.expires_at,
    )


@router.get("/{device_id}/status", response_model=StatusResponse)
async def get_device_status(
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> StatusResponse:
    """Device polls this endpoint until status is 'claimed'."""
    svc = DeviceProvisionService(db)
    prov = await svc.get_status(device_id)
    if prov is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="device not found")

    if prov.status == "waiting":
        if prov.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return StatusResponse(status="expired")
        return StatusResponse(status="waiting")

    if prov.status == "claimed":
        return StatusResponse(
            status="claimed",
            device_token=prov.device_token,
            relay_url=prov.relay_url,
            org_id=prov.org_id,
            agent_id=prov.agent_id,
        )

    return StatusResponse(status=prov.status)


@router.post("/claim", response_model=ClaimResponse)
async def claim_device(
    payload: ClaimRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    """Customer enters NW-XXXX code to link a device to their org."""
    if user.role == "super_admin":
        if payload.org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="super_admin must pass org_id",
            )
        org_id = payload.org_id
    elif user.org_id is not None:
        org_id = user.org_id
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user has no org assigned",
        )

    code = payload.code.upper().removeprefix("NW-").strip()

    svc = DeviceProvisionService(db)
    try:
        prov = await svc.claim(code, org_id, settings.relay_public_url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return ClaimResponse(
        agent_id=prov.agent_id,
        org_id=org_id,
        message="Device linked. It will begin streaming within seconds.",
    )
