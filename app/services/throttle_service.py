"""Limitation de débit et verrouillage progressif, partagés entre workers (ASVS 6.3.1).

Les compteurs vivent dans PostgreSQL (table ``auth_throttle``) et sont écrits dans une
transaction INDÉPENDANTE de celle de la requête : un échec de connexion (qui annule la
transaction de la requête) est quand même compté.

* ``hit(rule, *subjects)`` : fenêtre fixe par sujet (adresse IP, identifiant, compte).
  Au-delà de la limite : ``HTTPException(429)`` avec ``Retry-After``.
* ``check_lock`` / ``record_failure`` / ``record_success`` : verrouillage progressif par
  identifiant de connexion. Le verrou porte sur l'IDENTIFIANT SAISI, que le compte existe
  ou non : un e-mail inconnu se verrouille exactement comme un vrai, la réponse ne révèle
  donc rien (pas d'énumération) et un attaquant ne peut pas savoir quels comptes existent.
  Durée : ``LOCKOUT_BASE_SECONDS`` au seuil, doublée à chaque échec suivant, plafonnée.

Les clés sont des empreintes HMAC (SECRET_KEY) : aucune adresse e-mail ni IP en clair.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import random
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy import text

from app.core import database
from app.core.config import settings
from app.utils.logging import get_logger, security_event

logger = get_logger(__name__)


@dataclass(frozen=True)
class Rule:
    limit: int
    window_seconds: int


# Limites par action et par sujet. Choisies pour ne jamais gêner un humain et rendre une
# attaque automatisée inutile (en plus du verrouillage par identifiant).
RULES: dict[str, Rule] = {
    "login:ip": Rule(30, 300),
    "login:id": Rule(10, 300),
    "register:ip": Rule(10, 3600),
    # Activation par code : le compteur d'essais du code borne déjà les devinettes ; ces règles
    # empêchent d'enchaîner les demandes de codes ou de saturer la boîte d'un tiers.
    "activate:ip": Rule(20, 900),
    "activate:id": Rule(10, 900),
    "resend_activation:ip": Rule(10, 3600),
    "resend_activation:id": Rule(5, 3600),
    "forgot:ip": Rule(10, 3600),
    "forgot:id": Rule(3, 3600),
    "reset:ip": Rule(10, 900),
    "refresh:ip": Rule(120, 300),
    "verify_email:ip": Rule(10, 900),
    "send_verification:user": Rule(5, 3600),
    "verify_phone:user": Rule(5, 900),
    "verify_phone:ip": Rule(20, 900),
    "2fa:user": Rule(5, 300),
    "2fa:ip": Rule(20, 300),
    "password_confirm:user": Rule(5, 900),
}

_HIT_SQL = text(
    """
    INSERT INTO auth_throttle (key, window_start, hits, failures, updated_at)
    VALUES (:key, now(), 1, 0, now())
    ON CONFLICT (key) DO UPDATE SET
        hits = CASE WHEN auth_throttle.window_start <= now() - make_interval(secs => :window)
                    THEN 1 ELSE auth_throttle.hits + 1 END,
        window_start = CASE WHEN auth_throttle.window_start <= now() - make_interval(secs => :window)
                    THEN now() ELSE auth_throttle.window_start END,
        updated_at = now()
    RETURNING hits,
              EXTRACT(EPOCH FROM (window_start + make_interval(secs => :window) - now()))
    """
)

_LOCK_SQL = text(
    "SELECT EXTRACT(EPOCH FROM (locked_until - now())) FROM auth_throttle "
    "WHERE key = :key AND locked_until > now()"
)

_FAIL_SQL = text(
    """
    INSERT INTO auth_throttle (key, window_start, hits, failures, updated_at)
    VALUES (:key, now(), 0, 1, now())
    ON CONFLICT (key) DO UPDATE SET
        -- Les échecs anciens (plus d'un verrou maximal) sont oubliés.
        failures = CASE WHEN auth_throttle.updated_at <= now() - make_interval(secs => :max)
                        THEN 1 ELSE auth_throttle.failures + 1 END,
        updated_at = now()
    RETURNING failures
    """
)


def client_ip(request: Optional[Request]) -> str:
    """Adresse du client telle que vue par uvicorn (``--proxy-headers`` derrière un proxy)."""
    if request is None or request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def _key(rule: str, subject: str) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"{rule}|{subject.strip().lower()}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{rule.split(':')[0]}:{digest[:64]}"


def _too_many(retry_after: float, message: str = "Trop de tentatives, réessayez plus tard") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=message,
        headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
    )


def _run(statement, params) -> Optional[tuple]:
    db = database.get_session_local()()
    try:
        row = db.execute(statement, params).first()
        db.commit()
        if random.random() < 0.01:
            _purge(db)
        return row
    finally:
        db.close()


def _purge(db) -> None:
    try:
        db.execute(
            text(
                "DELETE FROM auth_throttle WHERE updated_at < now() - interval '2 days' "
                "AND (locked_until IS NULL OR locked_until < now())"
            )
        )
        db.execute(text("DELETE FROM auth_one_time_use WHERE expires_at < now()"))
        db.commit()
    except Exception:  # pragma: no cover - ménage opportuniste
        db.rollback()


def hit(rule_name: str, subject: Optional[str]) -> None:
    """Compte une tentative ; 429 + Retry-After au-delà de la limite de la règle."""
    if not settings.RATE_LIMIT_ENABLED or not subject:
        return
    rule = RULES[rule_name]
    row = _run(_HIT_SQL, {"key": _key(rule_name, str(subject)), "window": rule.window_seconds})
    if row is not None and row[0] > rule.limit:
        security_event("rate_limit.exceeded", outcome="blocked", rule=rule_name)
        raise _too_many(float(row[1] or rule.window_seconds))


def hit_all(request: Optional[Request], action: str, identifier: Optional[str] = None, user_id=None) -> None:
    """Applique les règles ``<action>:ip``, ``<action>:id`` et ``<action>:user`` existantes."""
    if f"{action}:ip" in RULES:
        hit(f"{action}:ip", client_ip(request))
    if identifier is not None and f"{action}:id" in RULES:
        hit(f"{action}:id", identifier)
    if user_id is not None and f"{action}:user" in RULES:
        hit(f"{action}:user", str(user_id))


# --------------------------------------------------------------------------- #
# Verrouillage progressif par identifiant
# --------------------------------------------------------------------------- #
def check_lock(identifier: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    row = _run(_LOCK_SQL, {"key": _key("lock", identifier)})
    if row is not None and row[0] is not None and row[0] > 0:
        security_event("login.locked", outcome="blocked")
        raise _too_many(float(row[0]))


def record_failure(identifier: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    key = _key("lock", identifier)
    row = _run(_FAIL_SQL, {"key": key, "max": settings.LOCKOUT_MAX_SECONDS})
    failures = int(row[0]) if row else 0
    if failures >= settings.LOCKOUT_THRESHOLD:
        exponent = min(failures - settings.LOCKOUT_THRESHOLD, 16)
        seconds = min(settings.LOCKOUT_BASE_SECONDS * (2**exponent), settings.LOCKOUT_MAX_SECONDS)
        _run(
            text(
                "UPDATE auth_throttle SET locked_until = now() + make_interval(secs => :s) "
                "WHERE key = :key RETURNING locked_until"
            ),
            {"key": key, "s": seconds},
        )
        security_event("login.lockout", outcome="blocked", failures=failures, lock_seconds=seconds)


def record_success(identifier: str) -> None:
    if not settings.RATE_LIMIT_ENABLED:
        return
    _run(
        text("DELETE FROM auth_throttle WHERE key = :key RETURNING key"),
        {"key": _key("lock", identifier)},
    )


# --------------------------------------------------------------------------- #
# Usage unique (anti-rejeu d'un code TOTP dans sa fenêtre de validité)
# --------------------------------------------------------------------------- #
def mark_used_once(key: str, ttl_seconds: int) -> bool:
    """True si ``key`` n'avait jamais été utilisée (et la marque comme utilisée)."""
    row = _run(
        text(
            "INSERT INTO auth_one_time_use (key, expires_at) "
            "VALUES (:key, now() + make_interval(secs => :ttl)) "
            "ON CONFLICT (key) DO UPDATE SET expires_at = EXCLUDED.expires_at "
            "WHERE auth_one_time_use.expires_at < now() "
            "RETURNING key"
        ),
        {"key": _key("otp", key), "ttl": ttl_seconds},
    )
    return row is not None
