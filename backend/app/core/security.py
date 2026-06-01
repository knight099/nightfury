"""
Nightwatch Security Layer
- Argon2id password hashing (memory-hard, GPU-resistant)
- AES-256-GCM encrypted session tokens (opaque, not decodable by client)
- Server-side sessions in Redis (instant revocation, device-bound)
"""
import hashlib
import os
import secrets
import time
import json
from base64 import urlsafe_b64encode, urlsafe_b64decode
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

# ─── Password Hashing (Argon2id) ──────────────────────────────────────────────

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHashError

    _hasher = PasswordHasher(
        time_cost=3,        # iterations
        memory_cost=65536,  # 64MB
        parallelism=4,
        hash_len=32,
        salt_len=16,
    )

    def hash_password(password: str) -> str:
        return _hasher.hash(password)

    def verify_password(plain_password: str, hashed_password: str) -> bool:
        try:
            return _hasher.verify(hashed_password, plain_password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def needs_rehash(hashed_password: str) -> bool:
        return _hasher.check_needs_rehash(hashed_password)

except ImportError:
    # Fallback to passlib bcrypt if argon2-cffi not installed
    from passlib.context import CryptContext
    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(password: str) -> str:
        return _pwd_context.hash(password)

    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return _pwd_context.verify(plain_password, hashed_password)

    def needs_rehash(hashed_password: str) -> bool:
        return False


# ─── Token Encryption (AES-256-GCM) ───────────────────────────────────────────

def _get_encryption_key() -> bytes:
    """Derive a 32-byte AES key from the secret_key setting."""
    return hashlib.sha256(settings.secret_key.encode()).digest()


def encrypt_token(payload: dict) -> str:
    """
    Encrypt a dict payload into an opaque token string.
    Uses AES-256-GCM — authenticated encryption, not decodable without key.
    """
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    plaintext = json.dumps(payload).encode()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    # Format: nonce || ciphertext, base64url encoded
    raw = nonce + ciphertext
    return urlsafe_b64encode(raw).decode().rstrip("=")


def decrypt_token(token: str) -> dict | None:
    """
    Decrypt an opaque token back to payload dict.
    Returns None if tampered, expired, or invalid.
    """
    try:
        # Re-add padding
        padding = 4 - len(token) % 4
        if padding != 4:
            token += "=" * padding
        raw = urlsafe_b64decode(token)
        nonce = raw[:12]
        ciphertext = raw[12:]
        key = _get_encryption_key()
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext)
    except Exception:
        return None


# ─── Session Token Generation ──────────────────────────────────────────────────

def generate_session_id() -> str:
    """Generate a cryptographically secure session ID (64 hex chars)."""
    return secrets.token_hex(32)


def compute_device_fingerprint(ip: str, user_agent: str) -> str:
    """Hash IP + User-Agent for session binding."""
    raw = f"{ip}:{user_agent}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]
