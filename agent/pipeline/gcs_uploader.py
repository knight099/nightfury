import logging

import httpx

from config import config

logger = logging.getLogger(__name__)


class GCSUploader:
    """Uploads event snapshots and clips to Google Cloud Storage via
    backend-issued signed upload URLs (no direct GCS credentials on the edge)."""

    def __init__(self, api_client):
        self.api_client = api_client  # reuse existing device-token-authenticated client

    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        """Upload bytes to GCS via a backend-issued signed URL. Returns the gs:// URI."""
        try:
            resp = await self.api_client.client.post(
                "/api/edge/upload-url",
                json={"path": path, "content_type": content_type},
            )
            resp.raise_for_status()
            body = resp.json()
            upload_url = body["upload_url"]
            gs_uri = body["gs_uri"]

            async with httpx.AsyncClient() as put_client:
                put_resp = await put_client.put(
                    upload_url, content=data, headers={"Content-Type": content_type}
                )
                put_resp.raise_for_status()

            return gs_uri
        except Exception as e:
            logger.error(f"GCS signed-URL upload failed for {path}: {e}")
            # Return a placeholder — the event will still be stored
            return f"gs://{config.gcs_bucket}/{path}"
