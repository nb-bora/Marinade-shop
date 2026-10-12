"""Machine à états d'une machine de pressing (pur, sans base de données).

Source de vérité des transitions : le service et les tests s'y réfèrent, le lot « commandes »
l'utilisera pour réserver, lancer et décharger.
"""

from typing import Dict, FrozenSet, Optional

from app.services.pressing_calcul import PressingRegleError
from app.utils.exceptions import ConflictError

ETATS = (
    "libre",
    "reservee",
    "en_cycle",
    "cycle_termine",
    "attente_dechargement",
    "maintenance",
    "hors_service",
)

TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "libre": frozenset({"reservee", "en_cycle", "maintenance", "hors_service"}),
    "reservee": frozenset({"libre", "en_cycle"}),
    "en_cycle": frozenset({"cycle_termine"}),
    "cycle_termine": frozenset({"attente_dechargement", "libre"}),
    "attente_dechargement": frozenset({"libre"}),
    "maintenance": frozenset({"libre", "hors_service"}),
    "hors_service": frozenset({"libre", "maintenance"}),
}

# Ces états immobilisent la machine : motif obligatoire pour y entrer.
ETATS_MOTIF_OBLIGATOIRE = frozenset({"maintenance", "hors_service"})
# Une machine dans l'un de ces états ne peut pas être désactivée.
ETATS_OCCUPES = frozenset({"en_cycle", "reservee"})

LIBELLES = {
    "libre": "libre",
    "reservee": "réservée",
    "en_cycle": "en cycle",
    "cycle_termine": "cycle terminé",
    "attente_dechargement": "en attente de déchargement",
    "maintenance": "en maintenance",
    "hors_service": "hors service",
}


class TransitionInterdite(ConflictError):
    """Transition d'état refusée (HTTP 409)."""


def transitions_depuis(etat: str) -> FrozenSet[str]:
    return TRANSITIONS.get(etat, frozenset())


def verifier_transition(actuel: str, cible: str, motif: Optional[str] = None) -> None:
    """Lève ``TransitionInterdite`` (409) ou ``PressingRegleError`` (422, motif manquant)."""
    if cible not in TRANSITIONS or actuel not in TRANSITIONS:
        raise PressingRegleError(f"État inconnu : « {cible} »")
    if cible not in TRANSITIONS[actuel]:
        raise TransitionInterdite(
            f"Transition interdite : une machine {LIBELLES[actuel]} ne peut pas "
            f"passer à l'état « {LIBELLES[cible]} »"
        )
    if cible in ETATS_MOTIF_OBLIGATOIRE and not (motif and motif.strip()):
        raise PressingRegleError(
            f"Un motif est obligatoire pour passer la machine à l'état « {LIBELLES[cible]} »"
        )
