"""Signs a browser-usable URL for a camera's latest snapshot frame.

Shared by ``GET /api/cameras/{id}/latest-frame`` and the onboarding status
route — both need the same GCS-signing-with-local-dev-fallback behaviour, and
duplicating it would let the two drift.
"""
import base64
import uuid

from app.config import settings
from app.services.gcs import fetch_gcs_object, gcs_blob_updated_at, sign_gcs_url


async def signed_latest_frame_url(camera_id: uuid.UUID) -> str | None:
    """Best-effort signed URL for a camera's latest frame.

    Returns ``None`` when there is no recent frame at all — callers that need
    to distinguish "no frame yet" from an error (e.g. during onboarding,
    where most cameras won't have one) should treat ``None`` as normal, not
    exceptional.
    """
    uri = f"gs://{settings.gcs_bucket}/latest/{camera_id}.webp"
    updated_at = gcs_blob_updated_at(uri)
    if updated_at is None:
        return None

    signed_url = sign_gcs_url(uri, expires_in=300)
    if signed_url.startswith("gs://"):
        # V4 signing unavailable (e.g. local dev with ADC user credentials,
        # which have no private key to sign with) — inline the bytes instead.
        obj = fetch_gcs_object(uri)
        if obj is None:
            return None
        data, content_type = obj
        signed_url = f"data:{content_type};base64,{base64.b64encode(data).decode()}"

    return signed_url
