"""Helpers for encrypting secrets before they are stored in the database."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    secret = (settings.AI_KEY_ENCRYPTION_SECRET or settings.SECRET_KEY).strip()
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith(_PREFIX):
        return text
    token = _fernet().encrypt(text.encode("utf-8")).decode("utf-8")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str:
    text = value or ""
    if not text.startswith(_PREFIX):
        return text
    token = text[len(_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def is_encrypted_secret(value: str | None) -> bool:
    return bool(value and value.startswith(_PREFIX))
