"""Device token service for paired agents.

Mints opaque long-lived tokens (returned once to the agent) and stores only
the Argon2id hash in the database, mirroring how user passwords are handled.
"""
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


class DeviceTokenService:
    @staticmethod
    def mint() -> tuple[str, str]:
        """Return ``(token, hash)``. Persist only the hash."""
        token = secrets.token_urlsafe(48)
        hashed = _hasher.hash(token)
        return token, hashed

    @staticmethod
    def verify(token: str, hashed: str) -> bool:
        try:
            return _hasher.verify(hashed, token)
        except (VerifyMismatchError, InvalidHashError):
            return False
