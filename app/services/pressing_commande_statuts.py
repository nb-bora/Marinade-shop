"""Machine à états d'une commande de pressing (pur, sans base de données).

Parcours nominal : recue -> en_attente_machine -> en_lavage -> attente_sechage -> en_sechage
-> pret -> livre. Variantes :

* lavage seul : ``en_lavage -> pret`` ;
* séchage seul (le client apporte du linge déjà lavé) : ``en_attente_machine -> en_sechage`` ;
* articles seuls (repassage, nettoyage à sec... sans machine) : ``recue -> pret`` (la route
  ``/pret`` vérifie qu'aucun lavage ni séchage n'est demandé) ;
* séchage après lavage : la commande repasse par ``en_attente_machine`` quand les sèche-linge
  sont réservés (``attente_sechage -> en_attente_machine``) ;
* libération des machines réservées (aucune ligne active ne reste sur l'étape) : retour à
  ``recue`` (étape lavage, ou séchage seul) ou à ``attente_sechage`` (séchage après lavage) ;
* charges successives : tant qu'une partie de la charge reste à affecter, la commande garde son
  statut (``en_attente_machine``, ``en_lavage``, ``en_sechage``) et reste affectable ;
* ``annulee`` : possible depuis ``recue``, ``en_attente_machine`` et ``attente_sechage``
  uniquement (jamais pendant un cycle).
"""

from typing import Dict, FrozenSet

from app.services.pressing_calcul import PressingRegleError
from app.utils.exceptions import ConflictError

STATUTS = (
    "recue",
    "en_attente_machine",
    "en_lavage",
    "attente_sechage",
    "en_sechage",
    "pret",
    "livre",
    "annulee",
)

TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "recue": frozenset({"en_attente_machine", "pret", "annulee"}),
    "en_attente_machine": frozenset(
        {"en_lavage", "en_sechage", "annulee", "recue", "attente_sechage"}
    ),
    "en_lavage": frozenset({"attente_sechage", "pret"}),
    "attente_sechage": frozenset({"en_attente_machine", "en_sechage", "annulee"}),
    "en_sechage": frozenset({"pret"}),
    "pret": frozenset({"livre"}),
    "livre": frozenset(),
    "annulee": frozenset(),
}

STATUTS_ANNULABLES = frozenset(
    statut for statut, cibles in TRANSITIONS.items() if "annulee" in cibles
)
STATUTS_EN_COURS = frozenset({"en_attente_machine", "en_lavage", "attente_sechage", "en_sechage"})
STATUTS_CYCLE = frozenset({"en_lavage", "en_sechage"})
STATUTS_FINAUX = frozenset({"livre", "annulee"})
# Statuts depuis lesquels on peut chercher des machines pour l'étape courante.
STATUTS_AFFECTABLES = frozenset({"recue", "attente_sechage"})
# Statuts où l'étape est déjà engagée : affectables seulement s'il reste de la charge
# (charges successives, cycle interrompu, affectation libérée en partie).
STATUTS_REAFFECTABLES = frozenset({"en_attente_machine", "en_lavage", "en_sechage"})

LIBELLES = {
    "recue": "reçue",
    "en_attente_machine": "en attente de machine",
    "en_lavage": "en lavage",
    "attente_sechage": "en attente de séchage",
    "en_sechage": "en séchage",
    "pret": "prête",
    "livre": "livrée",
    "annulee": "annulée",
}


class TransitionCommandeInterdite(ConflictError):
    """Transition de statut refusée (HTTP 409)."""


def transitions_depuis(statut: str) -> FrozenSet[str]:
    return TRANSITIONS.get(statut, frozenset())


def verifier_transition(actuel: str, cible: str) -> None:
    """Lève ``TransitionCommandeInterdite`` (409) ou ``PressingRegleError`` (statut inconnu)."""
    if actuel not in TRANSITIONS or cible not in TRANSITIONS:
        raise PressingRegleError(f"Statut inconnu : « {cible} »")
    if cible in TRANSITIONS[actuel]:
        return
    if cible == "annulee" and actuel in STATUTS_CYCLE:
        raise TransitionCommandeInterdite(
            f"Une commande {LIBELLES[actuel]} ne peut pas être annulée : "
            "terminez d'abord le cycle et déchargez la machine"
        )
    raise TransitionCommandeInterdite(
        f"Transition interdite : une commande {LIBELLES[actuel]} ne peut pas "
        f"passer au statut « {LIBELLES[cible]} »"
    )


def etape_initiale(lavage: bool, sechage: bool):
    """Première étape machine d'une commande (``None`` : aucune machine, articles seuls)."""
    if lavage:
        return "lavage"
    if sechage:
        return "sechage"
    return None
