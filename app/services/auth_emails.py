"""Emails du parcours d'authentification : bienvenue, vérification, réinitialisation, mot de
passe modifié. Gabarits dans ``email_templates`` ; envoi en arrière-plan : le temps de réponse
de l'API ne dépend pas du serveur SMTP et ne révèle pas si un compte existe. Langue de
l'utilisateur (champ ``locale`` quand il existe), français par défaut.
"""

from __future__ import annotations

from typing import Any

from app.services import email_templates


def _lang(user: Any) -> str:
    return "en" if str(getattr(user, "locale", "") or "").lower().startswith("en") else "fr"


def _send(name: str, user: Any, **extra: Any) -> None:
    email_templates.send(
        name, user.email, {"first_name": user.first_name, **extra}, _lang(user)
    )


def send_welcome(user: Any) -> None:
    _send("welcome", user)


def send_activation_code(db: Any, user: Any, code: str) -> None:
    """Code d'activation du compte. Envoyé APRÈS le commit : si l'inscription est annulée, aucun
    email ne part ; le code n'est jamais envoyé pour un compte qui n'existe pas."""
    email_templates.send_after_commit(
        db,
        "activation_code",
        user.email,
        {"first_name": user.first_name, "code": code, "email": user.email},
        _lang(user),
    )


def send_verification(user: Any, token: str) -> None:
    _send("verify_email", user, token=token)


def send_password_reset(user: Any, token: str) -> None:
    _send("password_reset", user, token=token)


def send_password_changed(user: Any) -> None:
    _send("password_changed", user)
