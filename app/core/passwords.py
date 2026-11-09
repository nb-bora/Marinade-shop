"""Mots de passe : hachage et politique (ASVS V6.2, V11.4).

Hachage : argon2id (paramètres minimaux recommandés par OWASP : 19 Mio, 2 passes,
parallélisme 1). Les anciens hachages bcrypt (coût 12) restent vérifiables et sont
re-hachés en argon2id à la première connexion réussie (``verify_and_update``) :
migration transparente, sans réinitialisation imposée. argon2 n'a pas la limite de
72 octets de bcrypt : les 128 caractères acceptés comptent tous.

Politique : 12 caractères au moins, 128 au plus, aucune règle de composition ; refus
des 10 000 mots de passe les plus courants (liste embarquée) et des mots du contexte
(nom de l'application, adresse e-mail, nom). Vérification HaveIBeenPwned facultative
par k-anonymat (désactivée par défaut, ``PASSWORD_HIBP_CHECK``).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from passlib.context import CryptContext

from app.core.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

MIN_LENGTH = 12
MAX_LENGTH = 128

pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    default="argon2",
    deprecated=["bcrypt"],
    argon2__type="ID",
    argon2__memory_cost=19456,
    argon2__rounds=2,
    argon2__parallelism=1,
    bcrypt__rounds=12,
)

_COMMON_FILE = Path(__file__).with_name("data") / "common_passwords.txt"
_CONTEXT_WORDS = ("marinade",)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return pwd_context.verify(password, hashed)
    except (ValueError, TypeError):
        # Hachage illisible (ancienne donnée) : simple échec, jamais une 500.
        return False


def verify_and_update(password: str, hashed: Optional[str]) -> tuple[bool, Optional[str]]:
    """(valide, nouveau hachage à enregistrer ou None)."""
    if not hashed:
        return False, None
    try:
        return pwd_context.verify_and_update(password, hashed)
    except (ValueError, TypeError):
        return False, None


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return pwd_context.hash("marinade-timing-equalizer-not-a-password")


def burn_verification_time(password: str) -> None:
    """Même coût qu'une vraie vérification : un compte inconnu ne répond pas plus vite."""
    pwd_context.verify(password, _dummy_hash())


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    try:
        lines = _COMMON_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:  # pragma: no cover - fichier livré avec le code
        logger.error("Liste des mots de passe courants introuvable : %s", _COMMON_FILE)
        return frozenset()
    return frozenset(line.strip().lower() for line in lines if line.strip())


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _core(value: str) -> str:
    """Le mot de passe sans les chiffres et symboles ajoutés autour (« Password123! » -> « password »)."""
    return re.sub(r"^[\W\d_]+|[\W\d_]+$", "", value)


def _pwned(password: str) -> bool:
    """HaveIBeenPwned, k-anonymat : seuls 5 caractères du SHA-1 quittent le serveur."""
    import httpx

    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()  # noqa: S324 (protocole HIBP)
    prefix, suffix = digest[:5], digest[5:]
    try:
        response = httpx.get(
            f"https://api.pwnedpasswords.com/range/{prefix}",
            headers={"Add-Padding": "true"},
            timeout=3.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Service indisponible : on ne bloque pas l'inscription (la liste locale s'applique).
        logger.warning("HaveIBeenPwned indisponible : %s", exc.__class__.__name__)
        return False
    for line in response.text.splitlines():
        candidate, _, count = line.partition(":")
        if candidate.strip() == suffix and count.strip() != "0":
            return True
    return False


def password_policy_errors(password: str, context: Iterable[Optional[str]] = ()) -> list[str]:
    """Raisons de refus (liste vide = mot de passe accepté)."""
    errors: list[str] = []
    if len(password) < MIN_LENGTH:
        errors.append(f"Le mot de passe doit contenir au moins {MIN_LENGTH} caractères")
        return errors
    if len(password) > MAX_LENGTH:
        errors.append(f"Le mot de passe ne doit pas dépasser {MAX_LENGTH} caractères")
        return errors
    normalized = _normalize(password)
    common = common_passwords()
    if normalized in common or _core(normalized) in common:
        errors.append("Ce mot de passe est trop courant : choisissez-en un autre")
        return errors
    words = [w for w in (_normalize(c) for c in (*_CONTEXT_WORDS, *context) if c) if len(w) >= 4]
    stripped = _core(normalized)
    if any(stripped == w or normalized == w for w in words):
        errors.append("Le mot de passe ne doit pas reprendre votre nom, votre e-mail ou le nom du service")
        return errors
    if settings.PASSWORD_HIBP_CHECK and _pwned(password):
        errors.append("Ce mot de passe figure dans une fuite de données connue : choisissez-en un autre")
    return errors


def context_words(email: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None) -> list[str]:
    words = [first_name, last_name]
    if email:
        local, _, domain = email.partition("@")
        words += [email, local, domain.split(".")[0] if domain else None]
    return [w for w in words if w]
