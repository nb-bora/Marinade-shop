"""Journalisation de l'application.

* Horodatage UTC au format ISO 8601 (ASVS 16.2.2).
* Identifiant de corrélation de la requête (en-tête X-Request-ID) sur chaque ligne.
* ``security_event`` : événements de sécurité structurés (JSON sur une ligne) dans le
  journal ``marinade.security``. Le JSON échappe retours à la ligne et caractères de
  contrôle : une valeur fournie par l'utilisateur ne peut pas forger une fausse ligne
  (injection de journal, ASVS 16.4.1). Les champs dont le nom évoque un secret sont
  masqués : un mot de passe, un jeton ou un code n'est jamais écrit (ASVS 16.2.5).
"""

import json
import logging
import sys
import time
from contextvars import ContextVar
from typing import Any

from app.core.config import settings

# Identifiant de la requête HTTP en cours (posé par le middleware de sécurité).
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
# Adresse du client de la requête en cours (pour les événements de sécurité).
client_ip_var: ContextVar[str] = ContextVar("client_ip", default="-")

_SECRET_MARKERS = (
    "password",
    "token",
    "secret",
    "otp",
    "authorization",
    "cookie",
    "recovery_code",
    "two_factor_code",
    "verification_code",
)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _UtcIsoFormatter(logging.Formatter):
    converter = time.gmtime

    def formatTime(self, record, datefmt=None):  # noqa: N802 (API de logging)
        base = time.strftime("%Y-%m-%dT%H:%M:%S", self.converter(record.created))
        return f"{base}.{int(record.msecs):03d}Z"


def setup_logging():
    """Configure logging for the application"""
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    logger = logging.getLogger("marinade")
    logger.setLevel(log_level)
    logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.addFilter(_RequestIdFilter())
    console_handler.setFormatter(
        _UtcIsoFormatter(
            "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s] %(message)s"
        )
    )
    logger.addHandler(console_handler)
    return logger


def get_logger(name: str = "marinade") -> logging.Logger:
    """Get a logger instance"""
    # Les modules passent souvent __name__ ("app.services.x") : on les range sous
    # "marinade" pour qu'ils héritent du format (UTC, identifiant de requête).
    if name != "marinade" and not name.startswith("marinade."):
        name = f"marinade.{name}"
    return logging.getLogger(name)


def _redact(key: str, value: Any) -> Any:
    if any(marker in key.lower() for marker in _SECRET_MARKERS):
        return "[REDACTED]"
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…"
    return value


def security_event(event: str, *, outcome: str = "success", level: int = logging.INFO, **fields: Any) -> None:
    """Écrit un événement de sécurité structuré (qui, quoi, quand, d'où, résultat).

    ``fields`` ne doit contenir que des identifiants (user_id, session_id, restaurant_id…)
    jamais de secret ; par sécurité, toute clé évoquant un secret est masquée.
    """
    record = {
        "event": event,
        "outcome": outcome,
        "request_id": request_id_var.get(),
        "client_ip": client_ip_var.get(),
        **{k: _redact(k, v) for k, v in fields.items()},
    }
    logging.getLogger("marinade.security").log(
        level, json.dumps(record, default=str, ensure_ascii=True, sort_keys=True)
    )


setup_logging()
