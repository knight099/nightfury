import hashlib
import hmac
import time

from app.config import settings


def _sign(camera_id: str, expires_at: int) -> str:
    msg = f"{camera_id}:{expires_at}".encode()
    return hmac.new(settings.stream_token_secret.encode(), msg, hashlib.sha256).hexdigest()


def sign_stream_token(camera_id: str, ttl_seconds: int | None = None) -> tuple[str, int]:
    """Generate a short-lived stream token for a camera.

    Returns (token, expires_at_unix).
    """
    expires_at = int(time.time()) + (ttl_seconds or settings.stream_token_ttl_seconds)
    sig = _sign(camera_id, expires_at)
    return f"{expires_at}.{sig}", expires_at


def verify_stream_token(camera_id: str, token: str) -> bool:
    """Verify a stream token for a camera. Fails closed on any malformed input."""
    try:
        expires_str, sig = token.split(".", 1)
        expires_at = int(expires_str)
    except (ValueError, AttributeError):
        return False

    if expires_at < int(time.time()):
        return False

    expected = _sign(camera_id, expires_at)
    return hmac.compare_digest(expected, sig)
