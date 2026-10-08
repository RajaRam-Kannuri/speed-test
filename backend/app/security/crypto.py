"""Encryption of secrets at rest (Fernet / AES-128-CBC + HMAC-SHA256)."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from ..config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode())
    if settings.env == "production":
        raise RuntimeError("LLX_ENCRYPTION_KEY must be set in production")
    # Development fallback: derive a key from the secret key.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("secret could not be decrypted with the configured key") from exc
