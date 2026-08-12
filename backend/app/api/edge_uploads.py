"""Edge box upload URL generation.

Edge boxes (paired agents) call this endpoint to get write-scoped signed URLs
for uploading event snapshots/clips directly to GCS without holding a service
account key.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core.dependencies import get_agent_from_token
from app.models.agent import Agent
from app.services.gcs import sign_gcs_upload_url

router = APIRouter(prefix="/api/edge", tags=["edge"])


class UploadUrlRequest(BaseModel):
    """Request for a signed GCS upload URL.

    path: GCS object path scoped to caller's org (e.g. "{org_id}/2026/08/12/{camera_id}/{event_id}/snapshot.webp")
    content_type: MIME type of the object being uploaded
    """
    path: str
    content_type: str


class UploadUrlResponse(BaseModel):
    """Response with a signed upload URL and GCS URI."""
    upload_url: str
    gs_uri: str


@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    body: UploadUrlRequest,
    agent: Agent = Depends(get_agent_from_token),
) -> UploadUrlResponse:
    """Get a write-scoped signed GCS URL for uploading an object.

    Validates that the requested path is scoped to the caller's org_id,
    preventing one organization from uploading to another's bucket prefix.
    """
    expected_prefix = f"{agent.org_id}/"
    if not body.path.startswith(expected_prefix):
        raise HTTPException(
            status_code=403,
            detail="path must be scoped to caller's org_id",
        )
    url = sign_gcs_upload_url(body.path, body.content_type)
    return UploadUrlResponse(
        upload_url=url,
        gs_uri=f"gs://{settings.gcs_bucket}/{body.path}",
    )
