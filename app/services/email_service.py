"""Envoi d'emails : transport SMTP réel, gabarit HTML de marque, envoi en arrière-plan.

Choix du transport (``EMAIL_BACKEND``) :

- ``auto`` (défaut) : SMTP si ``SMTP_USERNAME`` et ``SMTP_PASSWORD`` sont renseignés, sinon
  ``console`` (le message est seulement journalisé : aucun email ne part) ;
- ``smtp`` : SMTP obligatoire, une configuration incomplète lève une erreur ;
- ``console`` : journalise l'envoi sans l'effectuer ;
- ``memory`` : garde les messages dans ``OUTBOX`` (tests) ;
- ``disabled`` : n'envoie rien.

Sécurité : le mot de passe SMTP n'apparaît jamais dans les journaux ; les en-têtes sont posés
par ``email.message.EmailMessage``, qui refuse les retours à la ligne (pas d'injection
d'en-tête) ; tout texte inséré dans le HTML est échappé.
"""

from __future__ import annotations

import smtplib
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

SECURITES = ("starttls", "ssl", "none")
# Erreurs SMTP qui ne valent pas la peine d'être retentées : identifiants refusés,
# expéditeur ou destinataire rejeté. Le reste (réseau, serveur occupé) est retenté.
_NON_RETENTABLES = (
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPNotSupportedError,
)


@dataclass
class SentEmail:
    to: str
    subject: str
    text: str
    html: Optional[str]
    message_id: str
    extra: Dict[str, Any] = field(default_factory=dict)


# Boîte d'envoi du transport ``memory`` (tests).
OUTBOX: List[SentEmail] = []
_pool: Optional[ThreadPoolExecutor] = None
_pool_lock = threading.Lock()


class EmailError(Exception):
    """Envoi impossible (configuration, réseau ou refus du serveur)."""


# --------------------------------------------------------------------------- configuration


def _password() -> str:
    secret = settings.SMTP_PASSWORD
    value = secret.get_secret_value() if secret is not None else ""
    # Google affiche les mots de passe d'application par groupes de 4 séparés par des espaces.
    return "".join(value.split())


def smtp_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USERNAME and _password())


def active_backend() -> str:
    backend = (settings.EMAIL_BACKEND or "auto").strip().lower()
    if backend == "auto":
        return "smtp" if smtp_configured() else "console"
    return backend


def _from_header() -> str:
    return formataddr((settings.EMAIL_FROM_NAME, settings.EMAIL_FROM))


# --------------------------------------------------------------------------- construction


def build_message(
    to: str, subject: str, text: str, html_body: Optional[str] = None
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = _from_header()
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=settings.EMAIL_FROM.rsplit("@", 1)[-1] or None)
    if settings.EMAIL_REPLY_TO:
        msg["Reply-To"] = settings.EMAIL_REPLY_TO
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    return msg


# --------------------------------------------------------------------------- transport


def _smtp_send(msg: EmailMessage) -> None:
    if not smtp_configured():
        raise EmailError(
            "SMTP non configuré : renseigner SMTP_HOST, SMTP_USERNAME et SMTP_PASSWORD"
        )
    security = (settings.SMTP_SECURITY or "starttls").lower()
    timeout = settings.SMTP_TIMEOUT_SECONDS
    context = ssl.create_default_context()
    if security == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout, context=context
        )
    else:
        client = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=timeout)
    with client:
        client.ehlo()
        if security == "starttls":
            client.starttls(context=context)
            client.ehlo()
        client.login(settings.SMTP_USERNAME, _password())
        client.send_message(msg)


def _send_with_retries(msg: EmailMessage) -> None:
    attempts = max(1, settings.SMTP_MAX_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        try:
            _smtp_send(msg)
            return
        except _NON_RETENTABLES as exc:
            raise EmailError(f"SMTP refusé : {type(exc).__name__}") from exc
        except EmailError:
            raise
        except (smtplib.SMTPException, OSError) as exc:
            if attempt == attempts:
                raise EmailError(f"SMTP indisponible : {type(exc).__name__}") from exc
            logger.warning(
                f"SMTP tentative {attempt}/{attempts} échouée ({type(exc).__name__}), nouvel essai"
            )
            time.sleep(min(2 ** (attempt - 1), 8))


def send_email(
    to: str, subject: str, text: str, html_body: Optional[str] = None
) -> Dict[str, Any]:
    """Envoie un email de façon synchrone. Ne lève pas : retourne ``{"success": …}``."""
    backend = active_backend()
    try:
        msg = build_message(to, subject, text, html_body)
    except (ValueError, TypeError) as exc:  # adresse ou en-tête invalide
        return {"success": False, "error": f"Message invalide : {exc}", "backend": backend}
    message_id = str(msg["Message-ID"])
    try:
        if backend == "smtp":
            _send_with_retries(msg)
        elif backend == "memory":
            OUTBOX.append(SentEmail(to, subject, text, html_body, message_id))
        elif backend == "console":
            logger.info(f"[email:console] à={to} sujet={subject!r} (aucun envoi réel)")
        elif backend == "disabled":
            return {"success": False, "error": "Envoi d'emails désactivé", "backend": backend}
        else:
            return {"success": False, "error": f"Transport inconnu : {backend}", "backend": backend}
    except EmailError as exc:
        logger.error(f"Email non envoyé à {to} ({backend}) : {exc}")
        return {"success": False, "error": str(exc), "backend": backend}
    logger.info(f"Email envoyé à {to} ({backend}) : {subject!r}")
    return {"success": True, "backend": backend, "message_id": message_id, "timestamp": time.time()}


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="email")
        return _pool


def send_email_async(
    to: str, subject: str, text: str, html_body: Optional[str] = None
) -> None:
    """Envoie en arrière-plan : la requête HTTP ne dépend pas de la latence SMTP (et le temps
    de réponse ne révèle pas si un compte existe). Les transports hors SMTP sont synchrones."""
    if active_backend() != "smtp":
        send_email(to, subject, text, html_body)
        return
    _get_pool().submit(send_email, to, subject, text, html_body)


# La mise en page vit dans email_layout ; ré-exportée ici pour les appelants existants.
from app.services.email_layout import Details, Hero, Stat, Status, render_email  # noqa: E402,F401


def frontend_url(path: str, **query: str) -> str:
    from urllib.parse import quote, urlencode

    base = settings.FRONTEND_URL.rstrip("/")
    qs = f"?{urlencode(query, quote_via=quote)}" if query else ""
    return f"{base}{path}{qs}"
