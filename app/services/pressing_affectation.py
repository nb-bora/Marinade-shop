"""Affectation intelligente du linge aux machines d'un pressing (service PUR, sans base).

Entrée : l'état des machines du restaurant (``MachineInfo``) et la charge RESTANTE de l'étape
(``Demande`` : poids de la commande moins ce qui est déjà engagé sur des machines). Sortie : au
plus ``MAX_OPTIONS`` options classées, jamais d'écriture.

Règles appliquées (voir ``recommander``) :

1. la capacité d'une machine n'est jamais dépassée (calcul en grammes entiers, sans flottant) ;
2. exclues : machines désactivées, en maintenance ou hors service, de la mauvaise catégorie
   (lavage -> lave_linge, séchage -> seche_linge), sans programme compatible avec les types de
   linge de la commande (programme dont ``types_linge`` contient « tout » ou l'un des types
   demandés ; une commande sans type de linge accepte tout programme) ;
3. machines occupées (réservée, en cycle, cycle terminé, attente de déchargement) : proposées
   comme option « attendre » (``debut_prevu`` = fin estimée du cycle courant, ``attente_min``
   en conséquence), toujours APRÈS les machines libres ;
4. best-fit : la plus petite capacité suffisante est préférée ; une machine plus grande que
   nécessaire reçoit une pénalité proportionnelle à son sous-remplissage
   (``PENALITE_GRANDE_MACHINE`` points au maximum) ;
5. équilibrage : à capacité égale, la machine la moins chargée gagne (1 point par kg de charge
   cumulée des commandes en cours, en plus du temps d'attente) ;
6. semi-automatique : un programme avec ``intervention_humaine`` ajoute
   ``INTERVENTION_MIN`` minutes de présence d'un opérateur et la raison « intervention requise » ;
7. si la charge dépasse la plus grande machine compatible (ou qu'aucune machine compatible
   n'est libre), option ``repartition`` : glouton par capacité décroissante, la dernière
   machine étant la plus petite capable de finir la charge ;
8. dans ces mêmes cas, option ``partielle`` (charges successives) : la plus grande machine
   LIBRE compatible est remplie à sa capacité, le reste sera affecté après ce cycle ;
   score = attente + durée de tous les cycles successifs sur cette machine. Sans machine libre
   (charge au-delà de toute machine), elle porte sur la machine occupée qui finirait le plus
   tôt (option « attendre »). Elle rend la commande faisable dès qu'une machine compatible
   existe ; ``faisable=False`` seulement sans aucune machine compatible ;
9. une machine n'apparaît qu'une fois par option ;
10. la durée vient des programmes de la machine (le plus court des programmes compatibles) ;
11. score = durée totale estimée + attente + pénalités (plus petit = meilleur) ; 3 options max.

Toute heure écrite dans un message est à l'heure du pressing (``pressing_temps``), jamais en UTC.

Constantes de réglage documentées ci-dessous ; elles sont volontairement simples et testées.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from app.services import pressing_temps as temps

# Temps d'intervention d'un opérateur ajouté à la durée d'un programme semi-automatique.
INTERVENTION_MIN = 10
# Pénalité maximale (points) pour une grande machine utilisée pour une petite charge.
PENALITE_GRANDE_MACHINE = 60
# Pénalité (points) par machine supplémentaire dans une répartition (manutention).
PENALITE_PAR_MACHINE = 10
# Attente supposée (minutes) d'une machine occupée dont la fin n'est pas connue.
ATTENTE_PAR_DEFAUT_MIN = 30
MAX_OPTIONS = 3

CATEGORIE_PAR_ETAPE = {"lavage": "lave_linge", "sechage": "seche_linge"}
ETATS_INDISPONIBLES = frozenset({"maintenance", "hors_service"})
ETATS_OCCUPES = frozenset({"reservee", "en_cycle", "cycle_termine", "attente_dechargement"})


@dataclass(frozen=True)
class MachineInfo:
    id: object
    nom: str
    categorie: str
    capacite_g: int
    etat: str = "libre"
    actif: bool = True
    programmes: Tuple[dict, ...] = ()
    fin_estimee: Optional[datetime] = None
    charge_cumulee_kg: float = 0.0
    type_fonctionnement: str = "automatique"


@dataclass(frozen=True)
class Demande:
    charge_g: int
    etape: str
    types_linge: Tuple[str, ...]
    maintenant: datetime


@dataclass(frozen=True)
class Candidat:
    machine: MachineInfo
    programme: str
    duree_min: int
    intervention: bool
    debut: datetime
    libre: bool

    @property
    def fin(self) -> datetime:
        return self.debut + timedelta(minutes=self.duree_min)


@dataclass(frozen=True)
class Exclusion:
    machine_id: object
    nom: str
    raison: str
    code: str  # inactive | indisponible | programme


@dataclass
class MachineAffectee:
    machine_id: object
    nom: str
    charge_g: int
    programme: str
    duree_min: int
    debut_prevu: datetime
    fin_prevue: datetime
    attente_min: int
    intervention_humaine: bool

    @property
    def charge_kg(self) -> float:
        return self.charge_g / 1000

    def to_dict(self) -> dict:
        return {
            "machine_id": self.machine_id,
            "nom": self.nom,
            "charge_kg": self.charge_g / 1000,
            "programme": self.programme,
            "duree_min": self.duree_min,
            "debut_prevu": self.debut_prevu,
            "fin_prevue": self.fin_prevue,
            "attente_min": self.attente_min,
            "intervention_humaine": self.intervention_humaine,
        }


@dataclass
class Option:
    type: str  # machine_unique | repartition | partielle
    score: int
    machines: List[MachineAffectee]
    raisons: List[str] = field(default_factory=list)
    avertissements: List[str] = field(default_factory=list)
    attend: bool = False
    cycles: int = 1  # partielle : nombre de cycles successifs pour toute la charge restante

    @property
    def fin_totale(self) -> datetime:
        """Fin estimée de TOUTE la charge restante (cycles successifs compris)."""
        if self.type == "partielle":
            m = self.machines[0]
            return m.debut_prevu + timedelta(minutes=m.duree_min * self.cycles)
        return max(m.fin_prevue for m in self.machines)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "score": self.score,
            "machines": [m.to_dict() for m in self.machines],
            "raisons": self.raisons,
            "avertissements": self.avertissements,
        }


@dataclass
class Recommandation:
    faisable: bool
    etape: str
    options: List[Option] = field(default_factory=list)
    exclues: List[Exclusion] = field(default_factory=list)
    motif_si_non_faisable: Optional[str] = None
    action_conseillee: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "faisable": self.faisable,
            "etape": self.etape,
            "options": [o.to_dict() for o in self.options],
            "motif_si_non_faisable": self.motif_si_non_faisable,
            "action_conseillee": self.action_conseillee,
            "machines_exclues": [
                {"machine_id": e.machine_id, "nom": e.nom, "raison": e.raison}
                for e in self.exclues
            ],
        }


# ----------------------------------------------------------------------------- utilitaires
def grammes(kg) -> int:
    """Capacité en kg (Decimal, str, float) -> grammes entiers."""
    return int((Decimal(str(kg)) * 1000).to_integral_value())


def _fmt_kg(g: int) -> str:
    texte = f"{g / 1000:.3f}".rstrip("0").rstrip(".")
    return texte.replace(".", ",")


def charge_restante(poids_g: Optional[int], engagee_g: int) -> int:
    """Charge d'une étape encore à affecter : poids - charge engagée, jamais négative."""
    return max(0, (poids_g or 0) - (engagee_g or 0))


def _minutes(delta: timedelta) -> int:
    return max(0, int(round(delta.total_seconds() / 60)))


def normaliser_types(types) -> Tuple[str, ...]:
    propres = []
    for t in types or ():
        t = str(t).strip().lower()
        if t and t not in propres:
            propres.append(t)
    return tuple(propres)


def programme_compatible(programme: dict, types_linge: Sequence[str]) -> bool:
    """Un programme convient si la commande n'a pas de type de linge, ou si le programme
    contient « tout » ou l'un des types demandés."""
    demandes = normaliser_types(types_linge)
    if not demandes:
        return True
    pris_en_charge = normaliser_types(programme.get("types_linge"))
    return "tout" in pris_en_charge or any(t in pris_en_charge for t in demandes)


def meilleur_programme(
    machine: MachineInfo, types_linge: Sequence[str]
) -> Optional[Tuple[str, int, bool]]:
    """(nom, durée avec intervention, intervention) du programme compatible le plus court."""
    meilleur = None
    for programme in machine.programmes:
        if not programme_compatible(programme, types_linge):
            continue
        intervention = bool(programme.get("intervention_humaine"))
        duree = int(programme["duree_min"]) + (INTERVENTION_MIN if intervention else 0)
        if meilleur is None or duree < meilleur[1]:
            meilleur = (programme["nom"], duree, intervention)
    return meilleur


def programme_de(
    machine: MachineInfo, nom: str, types_linge: Sequence[str]
) -> Optional[Tuple[str, int, bool]]:
    """Programme précis d'une machine (nom insensible à la casse), s'il est compatible."""
    for programme in machine.programmes:
        if programme["nom"].strip().lower() == nom.strip().lower():
            if not programme_compatible(programme, types_linge):
                return None
            intervention = bool(programme.get("intervention_humaine"))
            duree = int(programme["duree_min"]) + (INTERVENTION_MIN if intervention else 0)
            return (programme["nom"], duree, intervention)
    return None


def debut_possible(machine: MachineInfo, maintenant: datetime) -> Tuple[datetime, bool]:
    """(début possible, libre ?) : une machine occupée n'est disponible qu'à la fin de son cycle."""
    if machine.etat not in ETATS_OCCUPES:
        return maintenant, True
    fin = machine.fin_estimee or (maintenant + timedelta(minutes=ATTENTE_PAR_DEFAUT_MIN))
    return max(maintenant, fin), False


def evaluer_candidats(
    machines: Sequence[MachineInfo], demande: Demande
) -> Tuple[List[Candidat], List[Exclusion]]:
    """Sépare les machines utilisables (avec leur meilleur programme) de celles qui sont exclues."""
    categorie = CATEGORIE_PAR_ETAPE[demande.etape]
    candidats: List[Candidat] = []
    exclues: List[Exclusion] = []
    for machine in machines:
        if machine.categorie != categorie:
            continue  # autre catégorie : sans objet pour cette étape
        if not machine.actif:
            exclues.append(Exclusion(machine.id, machine.nom, "Machine désactivée", "inactive"))
            continue
        if machine.etat in ETATS_INDISPONIBLES:
            libelle = "en maintenance" if machine.etat == "maintenance" else "hors service"
            exclues.append(
                Exclusion(machine.id, machine.nom, f"Machine {libelle}", machine.etat)
            )
            continue
        programme = meilleur_programme(machine, demande.types_linge)
        if programme is None:
            if not machine.programmes:
                raison = "Aucun programme défini sur cette machine"
            else:
                types = ", ".join(demande.types_linge) or "—"
                raison = f"Aucun programme compatible avec le linge demandé ({types})"
            exclues.append(Exclusion(machine.id, machine.nom, raison, "programme"))
            continue
        debut, libre = debut_possible(machine, demande.maintenant)
        nom, duree, intervention = programme
        candidats.append(Candidat(machine, nom, duree, intervention, debut, libre))
    return candidats, exclues


def _affectee(candidat: Candidat, charge_g: int, maintenant: datetime) -> MachineAffectee:
    return MachineAffectee(
        machine_id=candidat.machine.id,
        nom=candidat.machine.nom,
        charge_g=charge_g,
        programme=candidat.programme,
        duree_min=candidat.duree_min,
        debut_prevu=candidat.debut,
        fin_prevue=candidat.fin,
        attente_min=_minutes(candidat.debut - maintenant),
        intervention_humaine=candidat.intervention,
    )


# ------------------------------------------------------------------------------- répartition
def repartir(candidats: Sequence[Candidat], charge_g: int) -> Optional[List[Tuple[Candidat, int]]]:
    """Répartit ``charge_g`` sur des machines DISTINCTES, glouton par capacité décroissante.

    La dernière machine est la plus petite capable de porter le reste (best-fit). Retourne
    ``None`` si la capacité cumulée est insuffisante. Jamais de capacité dépassée.
    """
    restants = sorted(
        candidats,
        key=lambda c: (-c.machine.capacite_g, _minutes(c.debut - min(x.debut for x in candidats)),
                       c.machine.charge_cumulee_kg, c.machine.nom),
    )
    plan: List[Tuple[Candidat, int]] = []
    reste = charge_g
    while reste > 0:
        if not restants:
            return None
        pouvant_finir = [c for c in restants if c.machine.capacite_g >= reste]
        if pouvant_finir:
            choisi = min(
                pouvant_finir,
                key=lambda c: (c.machine.capacite_g, c.debut, c.machine.charge_cumulee_kg,
                               c.machine.nom),
            )
            plan.append((choisi, reste))
            return plan
        choisi = restants[0]
        restants = restants[1:]
        plan.append((choisi, choisi.machine.capacite_g))
        reste -= choisi.machine.capacite_g
    return plan


# ------------------------------------------------------------------------------ recommandation
def _option_unique(
    candidat: Candidat, demande: Demande, capacite_min_g: int
) -> Option:
    machine = candidat.machine
    affectee = _affectee(candidat, demande.charge_g, demande.maintenant)
    attente = affectee.attente_min
    penalite = 0
    raisons: List[str] = []
    avertissements: List[str] = []
    if candidat.libre:
        raisons.append("Machine libre immédiatement")
    else:
        avertissements.append(
            f"Machine occupée : attente de {attente} min (libre vers "
            f"{temps.heure_locale(candidat.debut)})"
        )
    if machine.capacite_g == capacite_min_g:
        raisons.append(
            f"Meilleur ajustement : {_fmt_kg(demande.charge_g)} kg pour une capacité de "
            f"{_fmt_kg(machine.capacite_g)} kg"
        )
    else:
        taux = demande.charge_g / machine.capacite_g
        penalite = int(round(PENALITE_GRANDE_MACHINE * (1 - taux)))
        avertissements.append(
            f"Grande machine ({_fmt_kg(machine.capacite_g)} kg) utilisée pour "
            f"{_fmt_kg(demande.charge_g)} kg alors qu'une machine de "
            f"{_fmt_kg(capacite_min_g)} kg suffit (pénalité {penalite})"
        )
    if machine.charge_cumulee_kg:
        raisons.append(f"Charge en cours sur la machine : {machine.charge_cumulee_kg:g} kg")
    else:
        raisons.append("Machine sans commande en attente (équilibrage)")
    if candidat.intervention:
        raisons.append(f"Intervention requise (+{INTERVENTION_MIN} min)")
    score = attente + candidat.duree_min + penalite + int(round(machine.charge_cumulee_kg))
    return Option("machine_unique", score, [affectee], raisons, avertissements, not candidat.libre)


def _option_repartition(
    plan: List[Tuple[Candidat, int]], demande: Demande, motif: str
) -> Option:
    affectees = [_affectee(c, charge, demande.maintenant) for c, charge in plan]
    attente_max = max(a.attente_min for a in affectees)
    duree_totale = max(a.attente_min + a.duree_min for a in affectees)
    cumul = sum(int(round(c.machine.charge_cumulee_kg)) for c, _ in plan)
    score = duree_totale + PENALITE_PAR_MACHINE * (len(plan) - 1) + cumul
    raisons = [
        motif,
        f"Charge répartie sur {len(plan)} machines : "
        + ", ".join(f"{a.nom} {_fmt_kg(a.charge_g)} kg" for a in affectees),
    ]
    avertissements = [
        f"Durée totale estimée : {duree_totale} min (machines utilisées en parallèle)"
    ]
    if attente_max:
        avertissements.append(f"Attente jusqu'à {attente_max} min pour une machine occupée")
    if any(a.intervention_humaine for a in affectees):
        raisons.append(f"Intervention requise (+{INTERVENTION_MIN} min)")
    return Option(
        "repartition", score, affectees, raisons, avertissements, any(not c.libre for c, _ in plan)
    )


def _cycles(charge_g: int, capacite_g: int) -> int:
    return -(-charge_g // capacite_g)  # division entière arrondie au supérieur


def _option_partielle(candidat: Candidat, demande: Demande, motif: str) -> Option:
    """Charges successives : la machine est remplie à sa capacité, le reste viendra après."""
    machine = candidat.machine
    charge = min(machine.capacite_g, demande.charge_g)
    cycles = _cycles(demande.charge_g, machine.capacite_g)
    affectee = _affectee(candidat, charge, demande.maintenant)
    raisons = [
        motif,
        f"Charges successives : {_fmt_kg(charge)} kg dans « {machine.nom} » "
        f"(capacité {_fmt_kg(machine.capacite_g)} kg)",
    ]
    avertissements = [
        f"Il restera {_fmt_kg(demande.charge_g - charge)} kg à traiter après ce cycle "
        f"(environ {cycles} cycles au total)"
    ]
    if candidat.libre:
        raisons.append("Machine libre immédiatement")
    else:
        avertissements.append(
            f"Machine occupée : attente de {affectee.attente_min} min (libre vers "
            f"{temps.heure_locale(candidat.debut)})"
        )
    if candidat.intervention:
        raisons.append(f"Intervention requise (+{INTERVENTION_MIN} min par cycle)")
    score = affectee.attente_min + cycles * candidat.duree_min
    return Option(
        "partielle", score, [affectee], raisons, avertissements, not candidat.libre, cycles
    )


def _partielle(
    candidats: Sequence[Candidat], demande: Demande, machines: Sequence[MachineInfo]
) -> Optional[Option]:
    """Option « partielle » quand aucune machine libre ne peut prendre toute la charge.

    Machine libre : la plus grande (moins de cycles), puis le programme le plus court, puis la
    moins chargée. Sans machine libre, seulement si la charge dépasse toute machine compatible
    (sinon une option « attendre » sur une machine capable existe déjà) : la machine occupée
    qui finirait toute la charge le plus tôt.
    """
    charge = demande.charge_g
    capacite_max = max((c.machine.capacite_g for c in candidats), default=0)
    libres = [c for c in candidats if c.libre]
    if not candidats or any(c.machine.capacite_g >= charge for c in libres):
        return None
    if libres:
        choisi = min(
            libres,
            key=lambda c: (-c.machine.capacite_g, c.duree_min, c.machine.charge_cumulee_kg,
                           c.machine.nom),
        )
    elif charge > capacite_max:
        choisi = min(
            candidats,
            key=lambda c: (
                _minutes(c.debut - demande.maintenant)
                + _cycles(charge, c.machine.capacite_g) * c.duree_min,
                -c.machine.capacite_g,
                c.machine.nom,
            ),
        )
    else:
        return None
    if charge > capacite_max:
        motif = (
            f"La charge restante ({_fmt_kg(charge)} kg) dépasse la plus grande machine "
            f"compatible ({_fmt_kg(capacite_max)} kg)"
        )
    else:
        motif = "Aucune machine assez grande n'est libre : traitement en plusieurs cycles"
    option = _option_partielle(choisi, demande, motif)
    categorie = CATEGORIE_PAR_ETAPE[demande.etape]
    for m in machines:
        if m.actif and m.etat == "maintenance" and m.categorie == categorie and m.capacite_g >= charge:
            option.avertissements.append(
                f"« {m.nom} » ({_fmt_kg(m.capacite_g)} kg), en maintenance, pourrait traiter "
                "toute la charge à son retour"
            )
            break
    return option


def recommander(machines: Sequence[MachineInfo], demande: Demande) -> Recommandation:
    """Calcule les options d'affectation (au plus ``MAX_OPTIONS``). Aucune écriture."""
    if demande.etape not in CATEGORIE_PAR_ETAPE:
        raise ValueError(f"Étape inconnue : {demande.etape}")
    candidats, exclues = evaluer_candidats(machines, demande)
    resultat = Recommandation(faisable=False, etape=demande.etape, exclues=exclues)
    charge = demande.charge_g

    capables = [c for c in candidats if c.machine.capacite_g >= charge]
    options: List[Option] = []
    if capables:
        capacite_min = min(c.machine.capacite_g for c in capables)
        options.extend(_option_unique(c, demande, capacite_min) for c in capables)

    capacite_max = max((c.machine.capacite_g for c in candidats), default=0)
    libres = [c for c in candidats if c.libre]
    if candidats and (charge > capacite_max or not any(c.libre for c in capables)):
        # Plan 1 : machines libres seulement (rapide) ; plan 2 : toutes (avec attente).
        vus = set()
        for ensemble in (libres, candidats):
            if not ensemble:
                continue
            plan = repartir(ensemble, charge)
            if plan is None or len(plan) < 2:
                continue
            cle = frozenset(c.machine.id for c, _ in plan)
            if cle in vus:
                continue
            vus.add(cle)
            if charge > capacite_max:
                motif = (
                    f"La charge ({_fmt_kg(charge)} kg) dépasse la plus grande machine "
                    f"compatible ({_fmt_kg(capacite_max)} kg)"
                )
            else:
                motif = "Aucune machine assez grande n'est libre : répartition sur les machines libres"
            options.append(_option_repartition(plan, demande, motif))

    partielle = _partielle(candidats, demande, machines)
    if partielle is not None:
        options.append(partielle)

    if options:
        # Libres d'abord (règle 3), puis par score ; départage stable par nom de première machine.
        options.sort(key=lambda o: (o.attend, o.score, o.machines[0].nom))
        resultat.options = options[:MAX_OPTIONS]
        resultat.faisable = True
        return resultat

    # Aucune option : expliquer et conseiller.
    capacite_totale = sum(c.machine.capacite_g for c in candidats)
    en_maintenance = [e for e in exclues if e.code == "maintenance"]
    cap_maintenance = sum(
        m.capacite_g
        for m in machines
        if m.actif and m.etat == "maintenance" and m.categorie == CATEGORIE_PAR_ETAPE[demande.etape]
    )
    if not candidats:
        resultat.motif_si_non_faisable = (
            "Aucune machine de " + ("lavage" if demande.etape == "lavage" else "séchage")
            + " utilisable (désactivées, hors service, en maintenance ou sans programme compatible)"
        )
    else:
        resultat.motif_si_non_faisable = (
            f"La charge ({_fmt_kg(charge)} kg) dépasse la capacité cumulée des machines "
            f"compatibles ({_fmt_kg(capacite_totale)} kg)"
        )
    if en_maintenance and capacite_totale + cap_maintenance >= charge:
        resultat.action_conseillee = "attendre"
        resultat.motif_si_non_faisable += " : une machine en maintenance pourrait revenir"
    else:
        resultat.action_conseillee = "decision_responsable"
    return resultat


def verifier_capacites(
    plan: Sequence[Tuple[Candidat, int]],
    charge_g: int,
    charge_restante_g: Optional[int] = None,
) -> None:
    """Garde-fou (utilisé à l'affectation) : capacité jamais dépassée, charge DEMANDÉE
    (``charge_g``, inférieure à la restante pour une option partielle) entièrement couverte,
    jamais plus que la charge restante de l'étape."""
    ids = [c.machine.id for c, _ in plan]
    if len(set(ids)) != len(ids):
        raise ValueError("Une machine ne peut apparaître qu'une fois")
    for c, charge in plan:
        if charge <= 0:
            raise ValueError(f"Charge nulle ou négative sur {c.machine.nom}")
        if charge > c.machine.capacite_g:
            raise ValueError(f"Capacité dépassée sur {c.machine.nom}")
    if sum(charge for _, charge in plan) != charge_g:
        raise ValueError("La charge n'est pas entièrement affectée")
    if charge_restante_g is not None and charge_g > charge_restante_g:
        raise ValueError("La charge affectée dépasse la charge restante de l'étape")
