"""Calculs purs du tableau de bord pressing : alertes et taux d'utilisation (sans base).

Convention du tableau de bord : les champs ``*_mesure*`` viennent d'horodatages réels
(débuts et fins de cycle), les champs ``*_estimee*`` de durées prévues. Aucun calcul ici ne
mélange les deux. Toute heure écrite dans un message est à l'heure du pressing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

from app.services import pressing_temps as temps
from app.services.pressing_affectation import _fmt_kg

# Seuils (minutes) documentés par le contrat. Une alerte se lève quand l'attente DÉPASSE le
# seuil (strictement), et devient critique au-delà du seuil critique.
SEUIL_ATTENTE_DECHARGEMENT_MIN = 15
SEUIL_ATTENTE_DECHARGEMENT_CRITIQUE_MIN = 60
SEUIL_RETARD_CRITIQUE_MIN = 30
SEUIL_DECHARGEMENT_TARDIF_MIN = 120
SEUIL_DECHARGEMENT_TARDIF_CRITIQUE_MIN = 360
SEUIL_RESERVATION_NON_DEMARREE_MIN = 15
SEUIL_RESERVATION_NON_DEMARREE_CRITIQUE_MIN = 45
SEUIL_PRISE_EN_CHARGE_MIN = 30
SEUIL_PRISE_EN_CHARGE_CRITIQUE_MIN = 90
SEUIL_SECHAGE_EN_ATTENTE_MIN = 20
SEUIL_SECHAGE_EN_ATTENTE_CRITIQUE_MIN = 60

ETATS_OCCUPATION = ("en_cycle", "cycle_termine", "attente_dechargement")
ETATS_INACTIFS = ("maintenance", "hors_service")


@dataclass(frozen=True)
class MachineSnapshot:
    machine_id: object
    nom: str
    etat: str
    fin_estimee: Optional[datetime] = None
    commande_id: object = None
    commande_numero: Optional[str] = None
    intervention_humaine: bool = False
    programme: Optional[str] = None
    fin_cycle_reelle: Optional[datetime] = None  # fin du dernier cycle (cycle_termine / attente)
    debut_prevu: Optional[datetime] = None  # machine réservée : début prévu de l'affectation


@dataclass(frozen=True)
class PanneOuverte:
    machine_id: object
    nom: str
    description: str


@dataclass(frozen=True)
class CommandePrete:
    commande_id: object
    numero: str
    pret_le: datetime


@dataclass(frozen=True)
class CommandeRecue:
    """Commande « reçue » qui demande une machine (lavage ou séchage), pas encore affectée."""

    commande_id: object
    numero: str
    cree_le: datetime


@dataclass(frozen=True)
class CommandeAReaffecter:
    """Commande dont une partie de la charge de l'étape reste à affecter, sans machine en cours."""

    commande_id: object
    numero: str
    etape: str
    charge_restante_g: int


@dataclass(frozen=True)
class CommandeAttenteSechage:
    """Linge lavé qui attend le séchage ; ``lavage_fini_le`` = fin réelle du dernier lavage."""

    commande_id: object
    numero: str
    lavage_fini_le: datetime


def _min(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _niveau(attente: int, critique: int) -> str:
    return "critique" if attente > critique else "avertissement"


def _alertes_machine(m: MachineSnapshot, maintenant: datetime) -> List[dict]:
    """Réservation non démarrée (machine réservée dont le début prévu est dépassé)."""
    if m.etat != "reservee" or m.debut_prevu is None:
        return []
    retard = _min(maintenant - m.debut_prevu)
    if retard <= SEUIL_RESERVATION_NON_DEMARREE_MIN:
        return []
    pour = f" pour {m.commande_numero}" if m.commande_numero else ""
    return [
        {
            "niveau": _niveau(retard, SEUIL_RESERVATION_NON_DEMARREE_CRITIQUE_MIN),
            "type": "reservation_non_demarree",
            "message": f"{m.nom} réservé{pour} depuis {retard} min sans démarrage "
            f"(début prévu à {temps.heure_locale(m.debut_prevu)})",
            "machine_id": m.machine_id,
            "commande_id": m.commande_id,
        }
    ]


def _alertes_commandes(
    recues: Sequence[CommandeRecue],
    a_reaffecter: Sequence[CommandeAReaffecter],
    sechages: Sequence[CommandeAttenteSechage],
    maintenant: datetime,
) -> List[dict]:
    alertes: List[dict] = []
    for c in recues:
        attente = _min(maintenant - c.cree_le)
        if attente > SEUIL_PRISE_EN_CHARGE_MIN:
            alertes.append(
                {
                    "niveau": _niveau(attente, SEUIL_PRISE_EN_CHARGE_CRITIQUE_MIN),
                    "type": "prise_en_charge",
                    "message": f"Commande {c.numero} reçue à {temps.heure_locale(c.cree_le)}, "
                    f"non prise en charge depuis {attente} min",
                    "machine_id": None,
                    "commande_id": c.commande_id,
                }
            )
    for c in a_reaffecter:
        if c.charge_restante_g > 0:
            verbe = "laver" if c.etape == "lavage" else "sécher"
            alertes.append(
                {
                    "niveau": "avertissement",
                    "type": "charge_restante",
                    "message": f"{c.numero} : il reste {_fmt_kg(c.charge_restante_g)} kg "
                    f"à {verbe}",
                    "machine_id": None,
                    "commande_id": c.commande_id,
                }
            )
    for c in sechages:
        attente = _min(maintenant - c.lavage_fini_le)
        if attente > SEUIL_SECHAGE_EN_ATTENTE_MIN:
            alertes.append(
                {
                    "niveau": _niveau(attente, SEUIL_SECHAGE_EN_ATTENTE_CRITIQUE_MIN),
                    "type": "sechage_en_attente",
                    "message": f"{c.numero} : linge lavé en attente de séchage depuis {attente} "
                    f"min (lavage terminé à {temps.heure_locale(c.lavage_fini_le)})",
                    "machine_id": None,
                    "commande_id": c.commande_id,
                }
            )
    return alertes


def calculer_alertes(
    machines: Sequence[MachineSnapshot],
    pannes: Sequence[PanneOuverte],
    commandes_pretes: Sequence[CommandePrete],
    maintenant: datetime,
    *,
    recues: Sequence[CommandeRecue] = (),
    a_reaffecter: Sequence[CommandeAReaffecter] = (),
    sechages: Sequence[CommandeAttenteSechage] = (),
    encaisse_apres_cloture: Optional[int] = None,
) -> List[dict]:
    """Alertes triées : critiques d'abord, puis avertissements, puis infos (ordre stable).

    ``encaisse_apres_cloture`` : montant net des paiements du jour enregistrés après la clôture
    de caisse (``None`` : pas de clôture, ou aucun paiement après elle).
    """
    alertes: List[dict] = []

    for m in machines:
        alertes.extend(_alertes_machine(m, maintenant))
        if m.etat == "en_cycle" and m.fin_estimee is not None and maintenant > m.fin_estimee:
            retard = _min(maintenant - m.fin_estimee)
            alertes.append(
                {
                    "niveau": "critique" if retard >= SEUIL_RETARD_CRITIQUE_MIN else "avertissement",
                    "type": "retard",
                    "message": f"{m.nom} : cycle en retard de {retard} min sur la fin estimée",
                    "machine_id": m.machine_id,
                    "commande_id": m.commande_id,
                }
            )
        if m.etat == "en_cycle" and m.intervention_humaine:
            programme = f" (programme {m.programme})" if m.programme else ""
            alertes.append(
                {
                    "niveau": "info",
                    "type": "intervention",
                    "message": f"{m.nom} : intervention humaine requise{programme}",
                    "machine_id": m.machine_id,
                    "commande_id": m.commande_id,
                }
            )
        if m.etat in ("cycle_termine", "attente_dechargement") and m.fin_cycle_reelle is not None:
            attente = _min(maintenant - m.fin_cycle_reelle)
            if attente > SEUIL_ATTENTE_DECHARGEMENT_MIN:
                alertes.append(
                    {
                        "niveau": "critique"
                        if attente > SEUIL_ATTENTE_DECHARGEMENT_CRITIQUE_MIN
                        else "avertissement",
                        "type": "attente_dechargement",
                        "message": f"{m.nom} : à décharger depuis {attente} min",
                        "machine_id": m.machine_id,
                        "commande_id": m.commande_id,
                    }
                )

    for p in pannes:
        alertes.append(
            {
                "niveau": "critique",
                "type": "panne",
                "message": f"{p.nom} : panne en cours ({p.description})",
                "machine_id": p.machine_id,
                "commande_id": None,
            }
        )

    for c in commandes_pretes:
        attente = _min(maintenant - c.pret_le)
        if attente > SEUIL_DECHARGEMENT_TARDIF_MIN:
            alertes.append(
                {
                    "niveau": "critique"
                    if attente > SEUIL_DECHARGEMENT_TARDIF_CRITIQUE_MIN
                    else "avertissement",
                    "type": "dechargement_tardif",
                    "message": f"Commande {c.numero} prête depuis {attente // 60} h "
                    f"{attente % 60:02d} min, non livrée",
                    "machine_id": None,
                    "commande_id": c.commande_id,
                }
            )

    alertes.extend(_alertes_commandes(recues, a_reaffecter, sechages, maintenant))

    if encaisse_apres_cloture is not None:
        alertes.append(
            {
                "niveau": "avertissement",
                "type": "paiement_apres_cloture",
                "message": "Paiements enregistrés après la clôture du jour : "
                f"{encaisse_apres_cloture} FCFA",
                "machine_id": None,
                "commande_id": None,
            }
        )

    ordre = {"critique": 0, "avertissement": 1, "info": 2}
    alertes.sort(key=lambda a: ordre[a["niveau"]])
    return alertes


def minutes_par_etat(
    evenements: Sequence[Tuple[datetime, str]],
    etat_initial: str,
    debut: datetime,
    fin: datetime,
) -> Dict[str, float]:
    """Minutes passées dans chaque état entre ``debut`` et ``fin`` d'après le journal.

    ``evenements`` : (date, nouvel_etat) ; ceux qui précèdent ``debut`` sont ignorés (leur effet
    est dans ``etat_initial``) ; ceux qui suivent ``fin`` aussi.
    """
    minutes: Dict[str, float] = {}
    if fin <= debut:
        return minutes
    courant, depuis = etat_initial, debut
    for date, nouvel_etat in sorted(evenements, key=lambda e: e[0]):
        if date <= debut:
            continue
        if date >= fin:
            break
        minutes[courant] = minutes.get(courant, 0.0) + (date - depuis).total_seconds() / 60
        courant, depuis = nouvel_etat, date
    minutes[courant] = minutes.get(courant, 0.0) + (fin - depuis).total_seconds() / 60
    return minutes


def utilisation(par_etat: Dict[str, float]) -> Tuple[float, float]:
    """(minutes occupées, minutes disponibles) : disponibles = hors maintenance / hors service ;
    occupées = en cycle, cycle terminé ou en attente de déchargement."""
    total = sum(par_etat.values())
    disponibles = total - sum(par_etat.get(e, 0.0) for e in ETATS_INACTIFS)
    occupees = sum(par_etat.get(e, 0.0) for e in ETATS_OCCUPATION)
    return occupees, disponibles


def taux_pct(occupees: float, disponibles: float) -> float:
    return round(100 * occupees / disponibles, 1) if disponibles > 0 else 0.0
