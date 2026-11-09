"""Fuseau, horaires d'ouverture et disponibilité des tables pour les réservations.

Horaires : ``Restaurant.horaires_ouverture`` est un objet indexé par jour de la semaine en
français (``lundi`` … ``dimanche``), chaque jour portant ``actif`` et ``plages`` (liste de
``{ouverture, fermeture}`` au format ``HH:MM``). Une fermeture antérieure à l'ouverture
signifie « après minuit ».
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.reservation import Reservation
from app.models.restaurant import Restaurant, Table
from app.services.reservation_states import ACTIVES
from app.utils.enums import TableStatut

FUSEAU_DEFAUT = "Africa/Douala"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
# Repli pour la disponibilité quand les horaires ne sont pas renseignés.
OUVERTURE_DEFAUT = time(12, 0)
FERMETURE_DEFAUT = time(23, 0)
PAS_CRENEAU_MIN = 30
DUREE_DEFAUT_MIN = 90
# Durée maximale d'une réservation : au-delà, le contrôle de chevauchement n'est plus fiable.
DUREE_MAX_MIN = 1440


def fuseau_de(restaurant: Restaurant) -> tzinfo:
    nom = getattr(restaurant, "timezone", None) or FUSEAU_DEFAUT
    try:
        return ZoneInfo(nom)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(FUSEAU_DEFAUT)


def nom_fuseau(restaurant: Restaurant) -> str:
    return getattr(restaurant, "timezone", None) or FUSEAU_DEFAUT


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _heure(valeur: object) -> Optional[time]:
    if not isinstance(valeur, str) or len(valeur) != 5 or valeur[2] != ":":
        return None
    try:
        return time(int(valeur[:2]), int(valeur[3:]))
    except ValueError:
        return None


def plages_du_jour(restaurant: Restaurant, jour: date) -> List[Tuple[datetime, datetime]]:
    """Plages d'ouverture d'un jour civil, en instants aware (fuseau du restaurant).

    Liste vide si le jour est fermé. ``None`` si aucun horaire n'est configuré (voir
    ``horaires_configures``).
    """
    zone = fuseau_de(restaurant)
    horaires = restaurant.horaires_ouverture
    if not isinstance(horaires, dict):
        return []
    jour_cle = JOURS[jour.weekday()]
    entree = horaires.get(jour_cle)
    if not isinstance(entree, dict) or entree.get("actif") is False:
        return []
    brutes = entree.get("plages")
    if not isinstance(brutes, list) or not brutes:
        brutes = [{"ouverture": entree.get("ouverture"), "fermeture": entree.get("fermeture")}]
    plages: List[Tuple[datetime, datetime]] = []
    for plage in brutes:
        if not isinstance(plage, dict):
            continue
        ouverture = _heure(plage.get("ouverture"))
        fermeture = _heure(plage.get("fermeture"))
        if ouverture is None or fermeture is None or ouverture == fermeture:
            continue
        debut = datetime.combine(jour, ouverture, tzinfo=zone)
        fin = datetime.combine(jour, fermeture, tzinfo=zone)
        if fin <= debut:
            fin = fin + timedelta(days=1)
        plages.append((debut, fin))
    return plages


def horaires_configures(restaurant: Restaurant) -> bool:
    horaires = restaurant.horaires_ouverture
    return isinstance(horaires, dict) and any(
        isinstance(horaires.get(j), dict) for j in JOURS
    )


def dans_horaires(restaurant: Restaurant, instant: datetime) -> bool:
    """Vrai si l'instant tombe dans une plage d'ouverture (ou si rien n'est configuré)."""
    if not horaires_configures(restaurant):
        return True
    local = instant.astimezone(fuseau_de(restaurant))
    for jour in (local.date() - timedelta(days=1), local.date()):
        for debut, fin in plages_du_jour(restaurant, jour):
            if debut <= instant < fin:
                return True
    return False


def chevauche(debut_a: datetime, duree_a: int, debut_b: datetime, duree_b: int) -> bool:
    return debut_a < debut_b + timedelta(minutes=duree_b) and debut_b < debut_a + timedelta(
        minutes=duree_a
    )


def lock_table(db: Session, table_id: uuid.UUID) -> Optional[Table]:
    """Verrou de ligne sur la table : sérialise les réservations concurrentes sur elle."""
    return (
        db.query(Table)
        .filter(Table.id == table_id, Table.deleted_at.is_(None))
        .with_for_update()
        .one_or_none()
    )


def reservations_actives_sur_table(
    db: Session,
    table_id: uuid.UUID,
    debut: datetime,
    duree: int,
    *,
    exclue: Optional[uuid.UUID] = None,
) -> List[Reservation]:
    """Réservations actives de la table qui chevauchent [debut, debut + duree)."""
    candidates = (
        db.query(Reservation)
        .filter(
            Reservation.table_id == table_id,
            Reservation.deleted_at.is_(None),
            Reservation.status.in_(ACTIVES),
            Reservation.reservation_date > debut - timedelta(minutes=DUREE_MAX_MIN),
            Reservation.reservation_date < debut + timedelta(minutes=duree),
        )
        .order_by(Reservation.reservation_date)
        .all()
    )
    return [
        r
        for r in candidates
        if (exclue is None or r.id != exclue)
        and chevauche(debut, duree, r.reservation_date, r.duration_minutes)
    ]


@dataclass
class Creneau:
    debut: datetime
    tables_libres: int
    passe: bool

    @property
    def disponible(self) -> bool:
        return self.tables_libres > 0 and not self.passe


def creneaux_du_jour(
    db: Session,
    restaurant: Restaurant,
    jour: date,
    party_size: int,
    duree: int,
    now: Optional[datetime] = None,
) -> List[Creneau]:
    """Créneaux de 30 minutes du jour, avec le nombre de tables assez grandes et libres
    sur toute la durée. Les horaires viennent du restaurant ; à défaut, 12:00-23:00."""
    zone = fuseau_de(restaurant)
    now = now or maintenant()
    plages = plages_du_jour(restaurant, jour)
    if not horaires_configures(restaurant):
        plages = [(
            datetime.combine(jour, OUVERTURE_DEFAUT, tzinfo=zone),
            datetime.combine(jour, FERMETURE_DEFAUT, tzinfo=zone),
        )]

    tables = (
        db.query(Table)
        .filter(
            Table.restaurant_id == restaurant.id,
            Table.deleted_at.is_(None),
            Table.capacite >= party_size,
            Table.statut != TableStatut.MAINTENANCE.value,
        )
        .all()
    )
    if not plages:
        return []

    debut_jour = datetime.combine(jour, time(0, 0), tzinfo=zone) - timedelta(minutes=DUREE_MAX_MIN)
    fin_jour = datetime.combine(jour, time(0, 0), tzinfo=zone) + timedelta(days=2)
    reservations = (
        db.query(Reservation)
        .filter(
            Reservation.restaurant_id == restaurant.id,
            Reservation.deleted_at.is_(None),
            Reservation.status.in_(ACTIVES),
            Reservation.table_id.isnot(None),
            Reservation.reservation_date >= debut_jour,
            Reservation.reservation_date < fin_jour,
        )
        .all()
        if tables
        else []
    )
    par_table: Dict[uuid.UUID, List[Reservation]] = {}
    for r in reservations:
        par_table.setdefault(r.table_id, []).append(r)

    creneaux: List[Creneau] = []
    pas = timedelta(minutes=PAS_CRENEAU_MIN)
    duree_td = timedelta(minutes=duree)
    for debut_plage, fin_plage in plages:
        courant = debut_plage
        while courant < fin_plage:
            libres = 0
            for table in tables:
                occupee = any(
                    chevauche(courant, duree, r.reservation_date, r.duration_minutes)
                    for r in par_table.get(table.id, [])
                )
                if not occupee:
                    libres += 1
            creneaux.append(Creneau(debut=courant, tables_libres=libres, passe=courant < now))
            courant += pas
    # Un créneau qui se termine après la fermeture n'est pas proposé (le service doit tenir).
    return [c for c in creneaux if c.debut + duree_td <= max(f for _, f in plages)]


def libelle_heure(instant: datetime, zone: tzinfo) -> str:
    return instant.astimezone(zone).strftime("%H:%M")
