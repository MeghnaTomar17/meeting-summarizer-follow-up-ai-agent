"""Password hashing helpers for gateway authentication use cases."""

from __future__ import annotations

from passlib.exc import UnknownHashError
from passlib.context import CryptContext

_PASSWORD_CONTEXT = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a PBKDF2-SHA256 hash for plaintext at the service boundary."""
    return _PASSWORD_CONTEXT.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify plaintext input against a persisted password hash."""
    try:
        return _PASSWORD_CONTEXT.verify(password, password_hash)
    except (UnknownHashError, ValueError):
        return False
