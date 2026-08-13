import base64
import hashlib
import hmac
import time

from app.config import settings


def mint_turn_credentials(ttl_seconds: int | None = None) -> tuple[str, str, int] | None:
    """Mint a short-lived coturn REST-API credential pair.

    Returns (username, credential, expires_at_unix), or None if TURN isn't
    configured (turn_url/turn_shared_secret unset) — callers should fall
    back to STUN-only rather than fail.

    Follows coturn's time-limited credential mechanism: username is the
    expiry timestamp, credential is base64(HMAC-SHA1(shared_secret, username)).
    """
    if not settings.turn_url or not settings.turn_shared_secret:
        return None

    expires_at = int(time.time()) + (ttl_seconds or settings.turn_credential_ttl_seconds)
    username = str(expires_at)
    digest = hmac.new(
        settings.turn_shared_secret.encode(), username.encode(), hashlib.sha1
    ).digest()
    credential = base64.b64encode(digest).decode()
    return username, credential, expires_at
