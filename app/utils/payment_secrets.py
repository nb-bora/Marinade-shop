"""Résolution et validation des références vers les secrets de paiement.

Une configuration de paiement ne stocke pas de secret : elle stocke le NOM de la
variable d'environnement qui le contient. Si un restaurant pouvait choisir ce nom
librement, il pourrait désigner une variable dont il connaît la valeur (par
exemple ``ENVIRONMENT`` ou ``ALLOW_ORIGINS``) et signer lui-même de faux webhooks
« paiement réussi ». Seuls les noms réservés ci-dessous sont donc acceptés : un
opérateur de la plateforme les provisionne, et leur valeur n'est pas devinable.
"""

import os
import re
from typing import Optional

from app.core.config import settings

DEFAULT_CREDENTIAL_ENV_KEY = "EASYTRANSACT_API_TOKEN"
DEFAULT_WEBHOOK_SECRET_ENV_KEY = "EASYTRANSACT_WEBHOOK_SECRET"

# Le nom par défaut, ou le nom par défaut suivi d'un suffixe propre à un
# restaurant : EASYTRANSACT_API_TOKEN_CHEZMAMA, EASYTRANSACT_WEBHOOK_SECRET_CHEZMAMA…
_CREDENTIAL_KEY = re.compile(rf"^{DEFAULT_CREDENTIAL_ENV_KEY}(_[A-Z0-9]+)*$")
_WEBHOOK_SECRET_KEY = re.compile(rf"^{DEFAULT_WEBHOOK_SECRET_ENV_KEY}(_[A-Z0-9]+)*$")


def is_allowed_credential_env_key(name: Optional[str]) -> bool:
    return bool(name) and _CREDENTIAL_KEY.fullmatch(name) is not None


def is_allowed_webhook_secret_env_key(name: Optional[str]) -> bool:
    return bool(name) and _WEBHOOK_SECRET_KEY.fullmatch(name) is not None


def resolve_secret(env_key: str) -> Optional[str]:
    """Read a secret by reference name.

    pydantic-settings loads ``.env`` into ``settings`` but does NOT export it to
    ``os.environ``, so a lookup in ``os.environ`` alone misses the default secrets
    in local development. The two default names therefore fall back to settings.
    """
    value = os.environ.get(env_key)
    if value:
        return value
    if env_key in (DEFAULT_CREDENTIAL_ENV_KEY, DEFAULT_WEBHOOK_SECRET_ENV_KEY):
        return getattr(settings, env_key, None)
    return None
