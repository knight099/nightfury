import httpx


class GCSUploader:
    """Uploads event snapshots and clips to Google Cloud Storage via
    backend-issued signed upload URLs (no direct GCS credentials on the edge)."""

    def __init__(self, api_client):
        self.api_client = api_client  # reuse existing device-token-authenticated client

    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        """Upload bytes to GCS via a backend-issued signed URL. Returns the gs:// URI.

        Raises on failure (auth error, backend unreachable, GCS PUT failure) instead
        of swallowing the error — callers must not persist a fabricated URI for an
        object that was never actually written. Callers (EventPackager,
        CameraWorker._latest_frame_loop) already handle exceptions from this method
        via their own surrounding try/except, so failures surface as retries/log
        entries rather than corrupt event records.
        """
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
