"""Références de paiement : un espace de noms propre à chaque restaurant.

Tous les restaurants partagent UN compte partenaire chez Easy Transact. La seule
chose que la passerelle conserve de nous est la ``vendor_reference`` : c'est donc elle
qui permet de retrouver « uniquement les transactions d'un restaurant », y compris
dans le tableau de bord ou l'export de la passerelle (recherche par référence).

Format :  ``MRD-7KQ2XA9P-20261007-3F9A1C5E7B20``
           │   │          │        └ 12 caractères aléatoires : unicité globale
           │   │          └ date UTC : lisible, et filtrable par jour
           │   └ PRÉFIXE DU RESTAURANT : unique sur toute la plateforme
           └ marque Marinade

Le préfixe est attribué par le serveur, une seule fois, et ne peut jamais être choisi
par le client : s'il pouvait l'être, un restaurant pourrait prendre le préfixe d'un
autre et brouiller la séparation des transactions.
"""

import base64
import json
import re
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Tuple

# Sans 0/O, 1/I/L, U : un préfixe se lit et se dicte au téléphone sans ambiguïté.
ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
PREFIX_BRAND = "MRD"
PREFIX_RANDOM_LENGTH = 8
PREFIX_PATTERN = re.compile(rf"^{PREFIX_BRAND}-[{ALPHABET}]{{{PREFIX_RANDOM_LENGTH}}}$")


def new_reference_prefix() -> str:
    suffix = "".join(secrets.choice(ALPHABET) for _ in range(PREFIX_RANDOM_LENGTH))
    return f"{PREFIX_BRAND}-{suffix}"


def new_vendor_reference(prefix: str, now: Optional[datetime] = None) -> str:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{prefix}-{moment:%Y%m%d}-{uuid.uuid4().hex[:12].upper()}"[:100]


def belongs_to_prefix(reference: str, prefix: str) -> bool:
    """Une référence appartient au restaurant dont elle porte le préfixe COMPLET.

    Le tiret final évite qu'un préfixe soit pris pour le début d'un autre.
    """
    return reference.startswith(prefix + "-")


def net_amount_fcfa(
    amount_fcfa: int, fees_fcfa: Optional[Decimal], fees_inclusive: Optional[bool]
) -> Optional[Decimal]:
    """Ce que le restaurant reçoit réellement, d'après la sémantique de la passerelle :
    frais « inclus » = déduits du montant ; sinon ils sont payés en plus par le client.
    Inconnu tant que la passerelle n'a pas communiqué ses frais."""
    if fees_fcfa is None or fees_inclusive is None:
        return None
    amount = Decimal(amount_fcfa)
    return amount - fees_fcfa if fees_inclusive else amount


# ----------------------------------------------------------------------- curseur
class InvalidCursor(ValueError):
    pass


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "i": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> Tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidCursor("Invalid pagination cursor") from exc
