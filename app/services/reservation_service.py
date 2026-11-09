"""Réservations et liste d'attente : règles métier, verrous et effets sur les tables.

Règles principales (voir aussi ``reservation_states`` et ``availability_service``) :

- transitions d'état gardées (409) ;
- anti-chevauchement sur une table, vérifié sous verrou de la ligne ``tables`` ;
- garde de capacité, de date passée et d'horaires d'ouverture, levée seulement par la
  gestion (``forcer=True``) ;
- occupation des tables : confirmation -> ``reservee``, arrivée -> ``occupee`` + session de
  salle, annulation ou absence -> ``libre`` si rien d'autre ne suit dans les 4 heures ;
- liste d'attente : position attribuée sous verrou du restaurant, renumérotation à chaque
  sortie dans la même transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.reservation import Reservation, ReservationGuest, WaitlistEntry
from app.models.restaurant import Restaurant, Table
from app.models.ros import RosCustomer, RosOrder
from app.schemas.reservation import (
    ReservationCreate,
    ReservationGuestCreate,
    WaitlistCreate,
)
from app.schemas.ros import SessionCreate
from app.services import availability_service as av
from app.services import email_templates, restaurant_emails
from app.services.reservation_states import TERMINALES, verifier_transition
from app.services.ros_service import RosService
from app.utils.enums import ReservationStatus as S
from app.utils.enums import TableStatut
from app.utils.exceptions import (
    ConflictError,
    MarinadeException,
    NotFoundError,
    ValidationError,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

TOLERANCE_RETARD_MIN = 5
FENETRE_LIBERATION_H = 4
ATTENTE_STATUTS = ("WAITING", "SEATED", "REMOVED", "EXPIRED", "CANCELLED")
DECALAGE_RENUMEROTATION = 1_000_000


class RegleReservation(MarinadeException):
    """Refus d'une règle de réservation (date, horaires, données) : HTTP 422."""

    default_code = "reservation.regle"
    http_status = 422


def _conflit_details(res: Reservation, zone) -> Dict[str, Any]:
    return {
        "reservation_id": str(res.id),
        "customer_name": res.customer_name,
        "heure": av.libelle_heure(res.reservation_date, zone),
        "party_size": res.party_size,
    }


def _description_conflit(res: Reservation, zone) -> str:
    return (
        f"{res.customer_name}, {res.party_size} couvert(s), à "
        f"{av.libelle_heure(res.reservation_date, zone)}"
    )


def _contexte_session(table: Optional[Table], couverts: int) -> str:
    base = f"{couverts} couvert" + ("s" if couverts > 1 else "")
    return f"{base} · {table.emplacement}" if table is not None and table.emplacement else base


def _restaurant(db: Session, restaurant_id: uuid.UUID) -> Restaurant:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise NotFoundError("Restaurant introuvable")
    return restaurant


def ensure_refs_du_restaurant(
    db: Session,
    restaurant_id: uuid.UUID,
    *,
    table_ids: Tuple[Optional[uuid.UUID], ...] = (),
    customer_id: Optional[uuid.UUID] = None,
) -> None:
    """Un identifiant venu du corps de requête doit appartenir au restaurant (400 sinon)."""
    for table_id in table_ids:
        if table_id is None:
            continue
        table = db.get(Table, table_id)
        if table is None or table.restaurant_id != restaurant_id or table.deleted_at is not None:
            raise ValidationError("Table invalide pour ce restaurant")
    if customer_id is not None:
        customer = db.get(RosCustomer, customer_id)
        if customer is None or customer.restaurant_id != restaurant_id:
            raise ValidationError("Client invalide pour ce restaurant")


class ReservationService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ lecture
    def charger(self, reservation_id: uuid.UUID) -> Reservation:
        reservation = (
            self.db.query(Reservation)
            .filter(Reservation.id == reservation_id, Reservation.deleted_at.is_(None))
            .one_or_none()
        )
        if reservation is None:
            raise NotFoundError("Réservation introuvable")
        return reservation

    # ------------------------------------------------------------------ garde
    def _verifier_creneau(
        self,
        restaurant: Restaurant,
        debut: datetime,
        duree: int,
        couverts: int,
        table: Optional[Table],
        *,
        forcer: bool,
        exclue: Optional[uuid.UUID],
        controle_date: bool,
        controle_capacite: bool,
    ) -> None:
        zone = av.fuseau_de(restaurant)
        if controle_date and not forcer:
            if debut < av.maintenant() - timedelta(minutes=TOLERANCE_RETARD_MIN):
                raise RegleReservation(
                    "La date est passée. Seule la gestion peut enregistrer une réservation dans le passé."
                )
            if not av.dans_horaires(restaurant, debut):
                raise RegleReservation(
                    "Ce créneau est hors des horaires d'ouverture. "
                    "Seule la gestion peut le forcer."
                )
        if table is None:
            return
        if controle_capacite and table.capacite < couverts and not forcer:
            raise ConflictError(
                f"La table {table.numero} accueille {table.capacite} personne(s) : "
                f"{couverts} couverts dépassent la capacité. Seule la gestion peut forcer."
            )
        conflits = av.reservations_actives_sur_table(
            self.db, table.id, debut, duree, exclue=exclue
        )
        if conflits:
            premier = conflits[0]
            raise ConflictError(
                f"La table {table.numero} est déjà réservée : {_description_conflit(premier, zone)}.",
                details=_conflit_details(premier, zone),
            )

    # ------------------------------------------------------------------ tables
    def _reserver_table(self, table_id: Optional[uuid.UUID]) -> None:
        table = av.lock_table(self.db, table_id) if table_id else None
        if table is not None and table.statut == TableStatut.LIBRE.value:
            table.statut = TableStatut.RESERVEE.value

    def _liberer_table_si_libre(self, table_id: Optional[uuid.UUID], res: Reservation) -> None:
        """Remet la table en « libre » seulement si elle était réservée pour ``res`` et que
        rien d'autre active ne la prend dans les 4 heures qui viennent."""
        if table_id is None:
            return
        table = av.lock_table(self.db, table_id)
        if table is None or table.statut != TableStatut.RESERVEE.value:
            return
        suivantes = av.reservations_actives_sur_table(
            self.db,
            table.id,
            av.maintenant(),
            FENETRE_LIBERATION_H * 60,
            exclue=res.id,
        )
        if not suivantes:
            table.statut = TableStatut.LIBRE.value

    # ------------------------------------------------------------------ création
    def create(
        self,
        restaurant_id: uuid.UUID,
        data: ReservationCreate,
        *,
        user_id: uuid.UUID,
        forcer: bool,
    ) -> Reservation:
        restaurant = _restaurant(self.db, restaurant_id)
        ensure_refs_du_restaurant(
            self.db,
            restaurant_id,
            table_ids=(data.table_id,),
            customer_id=data.customer_id,
        )
        table = av.lock_table(self.db, data.table_id) if data.table_id else None
        self._verifier_creneau(
            restaurant,
            data.reservation_date,
            data.duration_minutes,
            data.party_size,
            table,
            forcer=forcer,
            exclue=None,
            controle_date=True,
            controle_capacite=True,
        )
        reservation = Reservation(
            restaurant_id=restaurant_id,
            table_id=data.table_id,
            customer_id=data.customer_id,
            created_by=user_id,
            customer_name=data.customer_name,
            customer_phone=data.customer_phone,
            customer_email=data.customer_email,
            status=S.PENDING.value,
            party_size=data.party_size,
            reservation_date=data.reservation_date,
            duration_minutes=data.duration_minutes,
            notes=data.notes,
            source=data.source,
            reminder_sent=data.reminder_sent,
            arrival_notes=data.arrival_notes,
            preferences_jsonb=data.preferences_jsonb,
        )
        self.db.add(reservation)
        self.db.flush()
        self._creer_invites(reservation.id, data.invites)
        self.db.flush()
        self.db.refresh(reservation)
        restaurant_emails.notify_reservation(self.db, reservation, "pending")
        return reservation

    def _creer_invites(self, reservation_id: uuid.UUID, invites: List[ReservationGuestCreate]) -> None:
        for invite in invites:
            self.db.add(
                ReservationGuest(
                    reservation_id=reservation_id,
                    name=invite.name,
                    age_category=invite.age_category,
                    is_vegetarian=invite.is_vegetarian,
                    allergenes=invite.allergenes,
                    notes=invite.notes,
                )
            )

    # ------------------------------------------------------------------ modification
    def update(
        self, reservation: Reservation, changes: Dict[str, Any], *, forcer: bool
    ) -> Reservation:
        if reservation.status in TERMINALES:
            raise ConflictError(
                "Une réservation terminée, annulée ou absente ne se modifie plus."
            )
        restaurant = _restaurant(self.db, reservation.restaurant_id)
        ensure_refs_du_restaurant(
            self.db,
            reservation.restaurant_id,
            table_ids=(changes.get("table_id"),),
            customer_id=changes.get("customer_id"),
        )
        date_change = "reservation_date" in changes
        duree_change = "duration_minutes" in changes
        table_change = "table_id" in changes
        party_change = "party_size" in changes
        if reservation.status == S.CHECKED_IN.value and (date_change or duree_change or table_change):
            raise ConflictError(
                "Une réservation arrivée ne peut plus changer de date, de durée ni de table."
            )

        nouvelle_table_id = changes["table_id"] if table_change else reservation.table_id
        ancienne_table_id = reservation.table_id
        debut = changes.get("reservation_date", reservation.reservation_date)
        duree = changes.get("duration_minutes", reservation.duration_minutes)
        couverts = changes.get("party_size", reservation.party_size)

        if date_change or duree_change or table_change or party_change:
            table = av.lock_table(self.db, nouvelle_table_id) if nouvelle_table_id else None
            self._verifier_creneau(
                restaurant,
                debut,
                duree,
                couverts,
                table,
                forcer=forcer,
                exclue=reservation.id,
                controle_date=date_change,
                controle_capacite=party_change or table_change,
            )

        for champ, valeur in changes.items():
            setattr(reservation, champ, valeur)
        self.db.flush()

        if table_change and reservation.status == S.CONFIRMED.value and ancienne_table_id != nouvelle_table_id:
            self._liberer_table_si_libre(ancienne_table_id, reservation)
            self._reserver_table(nouvelle_table_id)
        self.db.flush()
        self.db.refresh(reservation)
        return reservation

    # ------------------------------------------------------------------ transitions
    def confirmer(self, reservation: Reservation, notes: Optional[str]) -> Reservation:
        if reservation.status == S.CONFIRMED.value:
            # Confirmer deux fois : rien à faire, pas de second e-mail.
            return reservation
        verifier_transition(reservation.status, S.CONFIRMED.value)
        reservation.status = S.CONFIRMED.value
        reservation.confirmed_at = av.maintenant()
        if notes:
            reservation.notes = f"{reservation.notes}\n{notes}" if reservation.notes else notes
        self._reserver_table(reservation.table_id)
        self.db.flush()
        self.db.refresh(reservation)
        restaurant_emails.notify_reservation(self.db, reservation, "confirmed")
        return reservation

    def arriver(self, reservation: Reservation) -> Reservation:
        verifier_transition(reservation.status, S.CHECKED_IN.value)
        table = av.lock_table(self.db, reservation.table_id) if reservation.table_id else None
        if table is not None and table.statut in (TableStatut.OCCUPEE.value, TableStatut.MAINTENANCE.value):
            raise ConflictError(
                f"La table {table.numero} est {'occupée' if table.statut == TableStatut.OCCUPEE.value else 'hors service'} : "
                "libérez-la avant d'installer ce groupe."
            )
        session = RosService(self.db).open_session(
            reservation.restaurant_id,
            SessionCreate(
                customer_id=reservation.customer_id,
                table_id=reservation.table_id,
                table_context=_contexte_session(table, reservation.party_size),
            ),
        )
        if table is not None:
            table.statut = TableStatut.OCCUPEE.value
        reservation.session_id = session.id
        reservation.status = S.CHECKED_IN.value
        reservation.checked_in_at = av.maintenant()
        self.db.flush()
        self.db.refresh(reservation)
        logger.info("Reservation %s arrivee, session %s", reservation.id, session.id)
        return reservation

    def absent(self, reservation: Reservation) -> Reservation:
        verifier_transition(reservation.status, S.NO_SHOW.value)
        etait_confirmee = reservation.status == S.CONFIRMED.value
        reservation.status = S.NO_SHOW.value
        reservation.no_show_at = av.maintenant()
        self.db.flush()
        if etait_confirmee:
            self._liberer_table_si_libre(reservation.table_id, reservation)
        self.db.flush()
        self.db.refresh(reservation)
        return reservation

    def terminer(self, reservation: Reservation) -> Reservation:
        verifier_transition(reservation.status, S.COMPLETED.value)
        # La session de salle appartient au plan : la table n'est pas libérée ici.
        reservation.status = S.COMPLETED.value
        reservation.completed_at = av.maintenant()
        self.db.flush()
        self.db.refresh(reservation)
        return reservation

    def annuler(self, reservation: Reservation, user_id: uuid.UUID, motif: str) -> Reservation:
        verifier_transition(reservation.status, S.CANCELLED.value)
        etait_confirmee = reservation.status == S.CONFIRMED.value
        reservation.status = S.CANCELLED.value
        reservation.cancelled_at = av.maintenant()
        reservation.cancelled_by = user_id
        reservation.cancel_reason = motif
        self.db.flush()
        if etait_confirmee:
            self._liberer_table_si_libre(reservation.table_id, reservation)
        restaurant_emails.notify_reservation(self.db, reservation, "cancelled")
        self.db.flush()
        self.db.refresh(reservation)
        return reservation

    def supprimer(self, reservation: Reservation, motif: Optional[str]) -> None:
        if reservation.status == S.CHECKED_IN.value:
            raise ConflictError("Une réservation arrivée ne se supprime pas : terminez-la.")
        etait_confirmee = reservation.status == S.CONFIRMED.value
        reservation.deleted_at = av.maintenant()
        if motif:
            reservation.cancel_reason = motif
        self.db.flush()
        if etait_confirmee:
            self._liberer_table_si_libre(reservation.table_id, reservation)

    # ------------------------------------------------------------------ disponibilité
    def disponibilite(
        self, restaurant_id: uuid.UUID, jour, couverts: int, duree: int
    ) -> Dict[str, Any]:
        restaurant = _restaurant(self.db, restaurant_id)
        creneaux = av.creneaux_du_jour(self.db, restaurant, jour, couverts, duree)
        zone = av.fuseau_de(restaurant)
        return {
            "date": jour.isoformat(),
            "fuseau": av.nom_fuseau(restaurant),
            "duree_minutes": duree,
            "party_size": couverts,
            "horaires_configures": av.horaires_configures(restaurant),
            "creneaux": [
                {
                    "debut": c.debut,
                    "heure": c.debut.astimezone(zone).strftime("%H:%M"),
                    "tables_libres": c.tables_libres,
                    "disponible": c.disponible,
                    "passe": c.passe,
                }
                for c in creneaux
            ],
        }

    # ------------------------------------------------------------------ clients
    def rechercher_clients(self, restaurant_id: uuid.UUID, requete: str, limite: int = 10) -> List[RosCustomer]:
        motif = f"%{requete.strip()}%"
        return (
            self.db.query(RosCustomer)
            .filter(
                RosCustomer.restaurant_id == restaurant_id,
                or_(RosCustomer.name.ilike(motif), RosCustomer.phone.ilike(motif)),
            )
            .order_by(RosCustomer.name)
            .limit(limite)
            .all()
        )

    def resume_client(self, restaurant_id: uuid.UUID, customer_id: uuid.UUID) -> Dict[str, Any]:
        client = self.db.get(RosCustomer, customer_id)
        if client is None or client.restaurant_id != restaurant_id:
            raise NotFoundError("Client introuvable")
        visites, derniere = self.db.query(
            func.count(RosOrder.id), func.max(RosOrder.created_at)
        ).filter(
            RosOrder.restaurant_id == restaurant_id,
            RosOrder.customer_id == customer_id,
            RosOrder.status.notin_(["DRAFT", "CANCELLED"]),
        ).one()
        base = self.db.query(func.count(Reservation.id)).filter(
            Reservation.restaurant_id == restaurant_id,
            Reservation.customer_id == customer_id,
            Reservation.deleted_at.is_(None),
        )
        reservations = int(base.scalar() or 0)
        absences = int(
            base.filter(Reservation.status == S.NO_SHOW.value).scalar() or 0
        )
        return {
            "id": client.id,
            "name": client.name,
            "phone": client.phone,
            "email": client.email,
            "visites": int(visites or 0),
            "absences": absences,
            "reservations": reservations,
            "derniere_visite": derniere,
        }


class WaitlistService:
    def __init__(self, db: Session):
        self.db = db

    def charger(self, entry_id: uuid.UUID) -> WaitlistEntry:
        entry = self.db.get(WaitlistEntry, entry_id)
        if entry is None:
            raise NotFoundError("Entrée de liste d'attente introuvable")
        return entry

    def _verrouiller_restaurant(self, restaurant_id: uuid.UUID) -> None:
        # Verrou de ligne : deux ajouts simultanés attendent l'un l'autre, donc obtiennent
        # deux positions différentes.
        self.db.query(Restaurant.id).filter(Restaurant.id == restaurant_id).with_for_update().one_or_none()

    def creer(self, restaurant_id: uuid.UUID, data: WaitlistCreate) -> WaitlistEntry:
        _restaurant(self.db, restaurant_id)
        ensure_refs_du_restaurant(
            self.db,
            restaurant_id,
            table_ids=(data.requested_table_id,),
            customer_id=data.customer_id,
        )
        self._verrouiller_restaurant(restaurant_id)
        position = (
            self.db.query(func.coalesce(func.max(WaitlistEntry.position), 0))
            .filter(WaitlistEntry.restaurant_id == restaurant_id, WaitlistEntry.status == "WAITING")
            .scalar()
            or 0
        ) + 1
        entry = WaitlistEntry(
            restaurant_id=restaurant_id,
            customer_name=data.customer_name,
            customer_phone=data.customer_phone,
            customer_email=data.customer_email,
            customer_id=data.customer_id,
            party_size=data.party_size,
            requested_table_id=data.requested_table_id,
            position=position,
            estimated_wait_minutes=data.estimated_wait_minutes,
            status="WAITING",
            source=data.source,
            notes=data.notes,
            preferences_jsonb=data.preferences_jsonb,
            joined_at=av.maintenant(),
        )
        self.db.add(entry)
        self.db.flush()
        self.db.refresh(entry)
        return entry

    def _renumeroter(self, restaurant_id: uuid.UUID) -> None:
        """Positions 1..n des entrées en attente, dans l'ordre, sans violer l'index unique.

        Deux temps : décalage de toutes les positions au-delà de la plage, puis affectation
        des positions définitives. Aucune valeur cible ne peut encore être occupée.
        """
        en_attente = (
            self.db.query(WaitlistEntry)
            .filter(WaitlistEntry.restaurant_id == restaurant_id, WaitlistEntry.status == "WAITING")
            .order_by(WaitlistEntry.position, WaitlistEntry.joined_at, WaitlistEntry.id)
            .all()
        )
        if not en_attente:
            return
        self.db.query(WaitlistEntry).filter(
            WaitlistEntry.id.in_([e.id for e in en_attente])
        ).update(
            {WaitlistEntry.position: WaitlistEntry.position + DECALAGE_RENUMEROTATION},
            synchronize_session=False,
        )
        for rang, entry in enumerate(en_attente, start=1):
            entry.position = rang
        self.db.flush()

    def installer(
        self,
        entry: WaitlistEntry,
        table_id: Optional[uuid.UUID],
        *,
        forcer: bool,
    ) -> WaitlistEntry:
        if entry.status != "WAITING":
            raise ConflictError("Cette entrée n'est plus en attente : elle ne peut pas être installée.")
        if table_id is None:
            raise RegleReservation("Choisissez la table où installer ce groupe.")
        restaurant = _restaurant(self.db, entry.restaurant_id)
        ensure_refs_du_restaurant(self.db, entry.restaurant_id, table_ids=(table_id,))
        table = av.lock_table(self.db, table_id)
        if table is None:
            raise ValidationError("Table invalide pour ce restaurant")
        if table.statut != TableStatut.LIBRE.value:
            raise ConflictError(f"La table {table.numero} n'est pas libre.")
        if table.capacite < entry.party_size and not forcer:
            raise ConflictError(
                f"La table {table.numero} accueille {table.capacite} personne(s) : "
                f"{entry.party_size} couverts dépassent la capacité. Seule la gestion peut forcer."
            )
        maintenant = av.maintenant()
        zone = av.fuseau_de(restaurant)
        prochaines = av.reservations_actives_sur_table(
            self.db, table.id, maintenant, av.DUREE_DEFAUT_MIN
        )
        if prochaines:
            premier = prochaines[0]
            raise ConflictError(
                f"La table {table.numero} est réservée dans la prochaine heure et demie : "
                f"{_description_conflit(premier, zone)}.",
                details=_conflit_details(premier, zone),
            )
        session = RosService(self.db).open_session(
            entry.restaurant_id,
            SessionCreate(
                customer_id=entry.customer_id,
                table_id=table.id,
                table_context=_contexte_session(table, entry.party_size),
            ),
        )
        table.statut = TableStatut.OCCUPEE.value
        entry.status = "SEATED"
        entry.seated_at = maintenant
        entry.assigned_table_id = table.id
        self.db.flush()
        self._renumeroter(entry.restaurant_id)
        logger.info("Liste d'attente %s installee (session %s)", entry.id, session.id)
        self.db.refresh(entry)
        return entry

    def retirer(self, entry: WaitlistEntry, motif: Optional[str]) -> WaitlistEntry:
        if entry.status != "WAITING":
            raise ConflictError("Cette entrée n'est plus en attente : elle ne peut pas être retirée.")
        entry.status = "REMOVED"
        entry.removed_at = av.maintenant()
        if motif:
            entry.notes = f"{entry.notes}\n{motif}" if entry.notes else motif
        self.db.flush()
        self._renumeroter(entry.restaurant_id)
        self.db.refresh(entry)
        return entry

    def prevenir(self, entry: WaitlistEntry) -> str:
        """Envoie « votre table est prête » après le commit. Renvoie l'adresse prévue."""
        if entry.status != "WAITING":
            raise ConflictError("Seule une entrée en attente peut être prévenue.")
        adresse = (entry.customer_email or "").strip()
        if not adresse:
            raise RegleReservation("Cette entrée n'a pas d'adresse e-mail : prévenez le client sur place.")
        restaurant = _restaurant(self.db, entry.restaurant_id)
        zone = av.fuseau_de(restaurant)
        maintenant = av.maintenant().astimezone(zone)
        data = {
            "customer_name": entry.customer_name,
            "restaurant": restaurant.name,
            "date": maintenant.strftime("%d/%m/%Y"),
            "time": maintenant.strftime("%H:%M"),
            "party_size": entry.party_size,
            "table": None,
            "reference": str(entry.id)[:8].upper(),
            "kind": "table_ready",
        }
        email_templates.send_after_commit(self.db, "reservation", adresse, data, "fr")
        return adresse
