"""Device token service for paired agents.

Mints opaque long-lived tokens (returned once to the agent) and stores only
the Argon2id hash in the database, mirroring how user passwords are handled.

Lookup keys
-----------
Argon2id is deliberately expensive, so verifying a presented token by
scanning every agent row and Argon2-verifying against each hash is
O(N_agents) expensive hashes per request — and worst-case (an invalid token)
on *every* miss. That is a DoS vector on the hot ingestion path
(``/internal/events``, ``/internal/heartbeat``) and on the edge-box routes.

To make verification O(1), every token also has a non-secret *lookup key*
(``token_id``): a truncated SHA-256 digest of the token, stored on the agent
row alongside the hash. SHA-256 is a fast hash, so it costs nothing to
compute per request, and because the token is 48 bytes of CSPRNG output the
digest reveals nothing useful about it. The lookup key selects exactly one
candidate row; a single Argon2 verify then confirms it.

The lookup key is NOT a substitute for the Argon2 verify — it only narrows
the candidate set. Authentication still rests entirely on the Argon2 hash.
"""
import hashlib
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

#: Length (hex chars) of the stored token lookup key. 32 hex chars = 128
#: bits of the SHA-256 digest — far beyond any realistic collision risk.
TOKEN_ID_LEN = 32


class DeviceTokenService:
    @staticmethod
    def token_id(token: str) -> str:
        """Return the non-secret lookup key for ``token``.

        Deterministic and cheap: a truncated SHA-256 of the token. Safe to
        index and to store in plaintext — it is not a credential and cannot
        be used to authenticate.
        """
        return hashlib.sha256(token.encode()).hexdigest()[:TOKEN_ID_LEN]

    @staticmethod
    def mint() -> tuple[str, str, str]:
        """Return ``(token, hash, token_id)``. Persist the hash + token_id."""
        token = secrets.token_urlsafe(48)
        hashed = _hasher.hash(token)
        return token, hashed, DeviceTokenService.token_id(token)

    @staticmethod
    def verify(token: str, hashed: str) -> bool:
        try:
            return _hasher.verify(hashed, token)
        except (VerifyMismatchError, InvalidHashError):
            return False
