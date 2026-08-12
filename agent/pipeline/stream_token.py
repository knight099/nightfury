import hashlib
import hmac
import time

from config import config


def _sign(camera_id: str, expires_at: int) -> str:
    msg = f"{camera_id}:{expires_at}".encode()
    return hmac.new(config.stream_token_secret.encode(), msg, hashlib.sha256).hexdigest()


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
