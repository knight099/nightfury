import logging

from google.cloud import storage

from config import config

logger = logging.getLogger(__name__)


class GCSUploader:
    """Uploads event snapshots and clips to Google Cloud Storage."""

    def __init__(self):
        self.bucket = None
        try:
            client = storage.Client(project=config.gcs_project)
            self.bucket = client.bucket(config.gcs_bucket)
        except Exception as e:
            logger.warning(f"GCS client init failed, uploads will be skipped: {e}")

    async def upload(self, path: str, data: bytes, content_type: str) -> str:
        """Upload bytes to GCS. Returns the public URL or gs:// path."""
        if self.bucket is None:
            return f"gs://{config.gcs_bucket}/{path}"
        try:
            blob = self.bucket.blob(path)
            blob.upload_from_string(data, content_type=content_type)
            return f"gs://{config.gcs_bucket}/{path}"
        except Exception as e:
            logger.error(f"GCS upload failed for {path}: {e}")
            # Return a placeholder — the event will still be stored
            return f"gs://{config.gcs_bucket}/{path}"
