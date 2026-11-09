"""Jetons d'accès JWT (ASVS V9).

* Algorithme FIXÉ côté serveur (HS256/384/512 selon ``ALGORITHM``, validé au démarrage) :
  l'en-tête ``alg`` du jeton n'est jamais pris en compte, ``none`` est impossible.
* Émetteur (``iss``) et audience (``aud``) vérifiés ; ``exp``, ``iat``, ``sub``, ``sid``,
  ``jti`` et ``type`` obligatoires.
* ``sid`` = session (famille de jetons de rafraîchissement) : la révocation d'une session
  rend ses jetons d'accès inutilisables immédiatement (vérifié à chaque requête).

PyJWT remplace python-jose (vulnérabilités sans correctif, dépendance ecdsa vulnérable).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"
_REQUIRED_CLAIMS = ["exp", "iat", "sub", "sid", "jti", "type", "iss", "aud"]


class InvalidToken(Exception):
    pass


def create_access_token(user_id: uuid.UUID | str, session_id: uuid.UUID | str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "sid": str(session_id),
        "jti": uuid.uuid4().hex,
        "type": ACCESS_TOKEN_TYPE,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Claims d'un jeton d'accès valide, sinon ``InvalidToken``."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            options={"require": _REQUIRED_CLAIMS},
            leeway=5,
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidToken("wrong token type")
    try:
        uuid.UUID(str(payload["sub"]))
        uuid.UUID(str(payload["sid"]))
    except ValueError as exc:
        raise InvalidToken("malformed subject") from exc
    return payload
