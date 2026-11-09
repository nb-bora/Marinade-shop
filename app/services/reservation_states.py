"""Machine d'états des réservations.

Une seule source de vérité : chaque route de transition appelle ``verifier_transition``.
Une transition interdite lève ``ConflictError`` (409) avec un message français.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from app.utils.enums import ReservationStatus as S
from app.utils.exceptions import ConflictError

TRANSITIONS: Dict[str, FrozenSet[str]] = {
    S.PENDING.value: frozenset(
        {S.CONFIRMED.value, S.CANCELLED.value, S.NO_SHOW.value, S.CHECKED_IN.value}
    ),
    S.CONFIRMED.value: frozenset(
        {S.CHECKED_IN.value, S.CANCELLED.value, S.NO_SHOW.value}
    ),
    S.CHECKED_IN.value: frozenset({S.COMPLETED.value}),
    S.COMPLETED.value: frozenset(),
    S.CANCELLED.value: frozenset(),
    S.NO_SHOW.value: frozenset(),
}

# Réservations qui occupent (ou vont occuper) une table : elles entrent dans le contrôle
# de chevauchement et dans les indicateurs du jour.
ACTIVES: FrozenSet[str] = frozenset(
    {S.PENDING.value, S.CONFIRMED.value, S.CHECKED_IN.value}
)

TERMINALES: FrozenSet[str] = frozenset(
    {S.COMPLETED.value, S.CANCELLED.value, S.NO_SHOW.value}
)

LIBELLES: Dict[str, str] = {
    S.PENDING.value: "en attente",
    S.CONFIRMED.value: "confirmée",
    S.CHECKED_IN.value: "arrivée",
    S.COMPLETED.value: "terminée",
    S.CANCELLED.value: "annulée",
    S.NO_SHOW.value: "absente",
}


def peut_passer(actuel: str, cible: str) -> bool:
    return cible in TRANSITIONS.get(actuel, frozenset())


def verifier_transition(actuel: str, cible: str) -> None:
    """Lève ``ConflictError`` (409) si la transition n'est pas permise."""
    if not peut_passer(actuel, cible):
        raise ConflictError(
            f"Réservation {LIBELLES.get(actuel, actuel)} : passage à « "
            f"{LIBELLES.get(cible, cible)} » impossible."
        )
