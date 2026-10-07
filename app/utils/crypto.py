"""Chiffrement réversible des secrets applicatifs stockés en base (secret TOTP).

Un secret TOTP doit être relu en clair pour valider un code : on ne peut donc pas
le hacher comme un mot de passe. On le chiffre avec Fernet (AES-128-CBC + HMAC).
"""

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_PREFIX = "enc:"


def _fernet() -> Fernet:
    material = settings.TWO_FACTOR_ENCRYPTION_KEY or settings.SECRET_KEY
    digest = hashlib.sha256(f"marinade-2fa:{material}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    return _PREFIX + _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(stored: Optional[str]) -> Optional[str]:
    """Return the clear secret, or None if it cannot be recovered.

    Values without the ``enc:`` prefix are legacy plaintext rows and are returned
    unchanged, so enabling encryption never locks an existing user out.
    """
    if not stored:
        return None
    if not stored.startswith(_PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored[len(_PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None
