"""Machine d'états des tickets de production (cuisine, bar, desserts).

Source unique des règles de transition : le service et les routes n'en connaissent
pas le détail. Une transition absente de ces tables est refusée (409) ; un retour
arrière n'est possible que pour la gestion (403 sinon).

    À préparer (QUEUED) -> En préparation (IN_PREPARATION) -> Prêt (READY) -> Servi (SERVED)
    QUEUED / IN_PREPARATION -> Annulé (CANCELLED)
    Retours arrière (gestion) : IN_PREPARATION -> QUEUED, READY -> IN_PREPARATION
    Rappel (toute personne du service, 2 minutes après « Servi ») : SERVED -> READY

Les horodatages suivent l'état courant : chaque entrée pose son instant, chaque sortie
par retour arrière remet à NULL celui de l'état quitté.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, Mapping

from app.utils.exceptions import AuthorizationError, ConflictError
from app.utils.ros_enums import TicketStatus

S = TicketStatus

# Transitions dans le sens normal du service.
FORWARD: Mapping[S, FrozenSet[S]] = {
    S.QUEUED: frozenset({S.IN_PREPARATION, S.CANCELLED}),
    S.IN_PREPARATION: frozenset({S.READY, S.CANCELLED}),
    S.READY: frozenset({S.SERVED}),
    S.SERVED: frozenset(),
    S.CANCELLED: frozenset(),
}

# Retours arrière : réservés à la gestion.
REVERSE: FrozenSet[tuple] = frozenset(
    {(S.IN_PREPARATION, S.QUEUED), (S.READY, S.IN_PREPARATION)}
)

# Fenêtre pendant laquelle un ticket « Servi » peut être rappelé.
RECALL_WINDOW = timedelta(minutes=2)

# Un ticket « Prêt » reste visible sur l'écran pendant ce délai après sa mise à prêt.
READY_DISPLAY_WINDOW = timedelta(minutes=30)

# Ticket actif = encore à faire (compté dans la vue « tout le service »).
ACTIVE_STATUSES = (S.QUEUED.value, S.IN_PREPARATION.value)

_LABELS = {
    S.QUEUED: "À préparer",
    S.IN_PREPARATION: "En préparation",
    S.READY: "Prêt",
    S.SERVED: "Servi",
    S.CANCELLED: "Annulé",
}


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _refusal(current: S, target: S) -> str:
    if current == target:
        return f"Ce ticket est déjà « {_LABELS[current]} »."
    if current == S.SERVED and target == S.READY:
        return "Un ticket servi se rappelle par la fonction de rappel, pas par un changement d'état."
    return (
        f"Passage de « {_LABELS[current]} » à « {_LABELS[target]} » impossible : "
        "le ticket a changé entre-temps, actualisez l'écran."
    )


def transition_updates(
    ticket: Any, target: S, *, can_reverse: bool, now: datetime
) -> Dict[str, Any]:
    """Champs à écrire pour passer ``ticket`` à ``target``.

    Lève ``ConflictError`` (409) si la transition est interdite, ``AuthorizationError``
    (403) si c'est un retour arrière sans le droit de gestion.
    """
    current = S(ticket.status)
    target = S(target)
    if target in FORWARD.get(current, frozenset()):
        pass
    elif (current, target) in REVERSE:
        if not can_reverse:
            raise AuthorizationError(
                "Seul le management peut revenir à l'étape précédente."
            )
    else:
        raise ConflictError(_refusal(current, target))

    updates: Dict[str, Any] = {"status": target.value}
    if target == S.IN_PREPARATION:
        if ticket.started_at is None:
            updates["started_at"] = now
    elif target == S.QUEUED:
        updates["started_at"] = None  # retour arrière : la préparation n'a pas commencé
    if target == S.READY:
        updates["ready_at"] = now
    elif current == S.READY:
        updates["ready_at"] = None  # retour arrière : plus prêt
    if target == S.SERVED:
        updates["served_at"] = now
    if target == S.CANCELLED:
        updates["cancelled_at"] = now
    return updates


def recall_updates(ticket: Any, *, now: datetime) -> Dict[str, Any]:
    """Rappel d'un ticket servi : il redevient « Prêt », seulement dans la fenêtre."""
    if S(ticket.status) != S.SERVED:
        raise ConflictError("Seul un ticket servi peut être rappelé.")
    served_at = ticket.served_at
    if served_at is None or now - _aware(served_at) >= RECALL_WINDOW:
        raise ConflictError(
            "Le rappel n'est possible que pendant les 2 minutes qui suivent « Servi »."
        )
    return {"status": S.READY.value, "served_at": None, "ready_at": now}
