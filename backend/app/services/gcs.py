"""GCS V4 signed URL generation for event snapshot/clip access.

The worker writes raw `gs://bucket/path/to/object.ext` URIs into the
`events.snapshot_url` / `events.clip_url` columns. The browser cannot fetch
these directly, so the API rewrites them to short-lived V4 signed HTTPS URLs
on read.

This module is fail-soft: if Google credentials are missing (e.g. local dev
without ADC) or any GCS error occurs, the original URI is returned unchanged
so the API keeps working.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Module-level cache for the storage client. Instantiated lazily on first use.
_client = None


def _get_client():
    """Return a cached `storage.Client`, creating it on first call."""
    global _client
    if _client is None:
        # Imported lazily so test environments without google-cloud-storage
        # creds don't fail at import time.
        from google.cloud import storage  # type: ignore

        _client = storage.Client(project=settings.gcs_project)
    return _client


def sign_gcs_upload_url(path: str, content_type: str, expires_in: int | None = None) -> str:
    """Generate a V4 signed URL for PUTting an object to GCS.

    Used by edge boxes to upload event snapshots/clips directly to cloud storage
    without holding a service account key.

    Args:
        path: GCS object path (e.g. "org-id/2026/08/12/camera-id/event-id/snapshot.webp")
        content_type: MIME type of the object being uploaded (e.g. "image/webp")
        expires_in: Seconds until signature expires (default: settings.gcs_signed_url_expiry)

    Returns:
        V4 signed HTTPS URL ready for HTTP PUT.
    """
    client = _get_client()
    bucket = client.bucket(settings.gcs_bucket)
    blob = bucket.blob(path)
    ttl = expires_in or settings.gcs_signed_url_expiry
    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=ttl),
        method="PUT",
        content_type=content_type,
    )
    return url


def sign_gcs_url(uri: Optional[str], expires_in: int | None = None) -> Optional[str]:
    """Convert a `gs://bucket/object` URI to a V4 signed HTTPS URL.

    - Empty/None inputs are returned as-is.
    - URIs not starting with `gs://` are returned as-is (worker may pass through
      already-signed https URLs or relative paths in dev).
    - On any GCS error (missing creds, missing bucket, etc.) the original URI
      is returned and a warning is logged so the API remains usable.
    """
    if not uri:
        return uri
    if not uri.startswith("gs://"):
        return uri

    ttl = expires_in if expires_in is not None else settings.gcs_signed_url_expiry

    try:
        # Strip scheme, split into bucket + object path.
        path = uri[len("gs://"):]
        bucket_name, _, object_name = path.partition("/")
        if not bucket_name or not object_name:
            logger.warning("sign_gcs_url: malformed gs:// URI %r", uri)
            return uri

        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl),
            method="GET",
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft by design
        logger.warning("sign_gcs_url: failed to sign %r (%s); returning raw URI", uri, exc)
        return uri


def fetch_gcs_object(uri: str) -> Optional[tuple[bytes, str]]:
    """Download object bytes + content type for a `gs://` URI.

    Used as a fallback for `/latest-frame` when V4 signing is unavailable
    (e.g. local dev with ADC user credentials, which lack a private key).
    Fail-soft: returns None on any error.
    """
    if not uri or not uri.startswith("gs://"):
        return None

    try:
        path = uri[len("gs://"):]
        bucket_name, _, object_name = path.partition("/")
        if not bucket_name or not object_name:
            return None

        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.get_blob(object_name)
        if blob is None:
            return None
        return blob.download_as_bytes(), blob.content_type or "application/octet-stream"
    except Exception as exc:  # noqa: BLE001 — fail-soft by design
        logger.warning("fetch_gcs_object: failed for %r (%s)", uri, exc)
        return None


def gcs_blob_updated_at(uri: str) -> Optional[datetime]:
    """Return the `updated` timestamp of the blob at the given gs:// URI.

    Returns None if the URI is malformed, the blob does not exist, or any GCS
    error occurs (fail-soft).
    """
    if not uri or not uri.startswith("gs://"):
        return None

    try:
        path = uri[len("gs://"):]
        bucket_name, _, object_name = path.partition("/")
        if not bucket_name or not object_name:
            return None

        client = _get_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.get_blob(object_name)
        if blob is None:
            return None
        return blob.updated
    except Exception as exc:  # noqa: BLE001 — fail-soft by design
        logger.warning("gcs_blob_updated_at: failed for %r (%s)", uri, exc)
        return None


def delete_gcs_object(uri: str) -> bool:
    """Delete the object at a ``gs://`` URI. Returns True if it is gone.

    Used by the retention sweep. Unlike the other helpers here this does NOT
    fail soft into a falsy "nothing happened" — the caller keeps the event row
    when this returns False so the next pass retries, and reporting a failed
    delete as success would orphan the object with nothing left pointing at it.

    An already-missing object counts as success: the desired end state (no
    object) holds, and a delete that has to be idempotent across retries must
    treat "not there" as done.
    """
    if not uri:
        return True
    if not uri.startswith("gs://"):
        # Non-GCS URIs (data: fallbacks used in local dev) have no object to
        # remove — nothing to do, and not an error.
        return True

    try:
        path = uri[len("gs://"):]
        bucket_name, _, object_name = path.partition("/")
        if not bucket_name or not object_name:
            logger.warning("delete_gcs_object: malformed URI %r", uri)
            return False

        client = _get_client()
        blob = client.bucket(bucket_name).blob(object_name)
        blob.delete()
        return True
    except Exception as exc:  # noqa: BLE001
        if "404" in str(exc) or "Not Found" in str(exc):
            return True
        logger.warning("delete_gcs_object: failed for %r (%s)", uri, exc)
        return False
