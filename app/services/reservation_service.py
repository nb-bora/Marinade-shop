from typing import Optional, List
from datetime import datetime, timedelta, timezone, date, time
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from app.models.reservation import (
    Reservation,
    ReservationGuest,
    WaitlistEntry,
)
from app.models.restaurant import Table
from app.models.ros import RosCustomer, ServiceSession
from app.repositories.base import BaseRepository
from app.repositories.restaurant_repository import (
    RestaurantRepository,
    TableRepository,
)
from app.repositories.ros_repository import (
    RosCustomerRepository,
    ServiceSessionRepository,
)
from app.schemas.reservation import (
    ReservationCreate,
    ReservationListFilters,
    WaitlistCreate,
)
from app.utils.enums import ReservationStatus, TableStatut
from app.utils.exceptions import (
    BusinessLogicError,
    NotFoundError,
    ValidationError,
)
from app.utils.logging import get_logger
import uuid

logger = get_logger(__name__)


def _combine_date_heure(d: date, heure: str) -> datetime:
    try:
        parts = heure.split(":")
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
    except Exception as exc:
        raise ValidationError(f"Invalid heure_reservation '{heure}': {exc}")
    t = time(hh, mm)
    naive = datetime.combine(d, t)
    if naive.tzinfo is None:
        naive = naive.replace(tzinfo=timezone.utc)
    return naive


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    return s or None


class ReservationRepository(BaseRepository[Reservation]):
    def __init__(self, db: Session):
        super().__init__(Reservation, db)

    def create_with_guests(
        self,
        reservation_data: dict,
        guests: Optional[List[dict]] = None,
    ) -> Reservation:
        reservation = Reservation(**reservation_data)
        self.db.add(reservation)
        self.db.flush()
        self.db.refresh(reservation)
        if guests:
            for guest in guests:
                g = ReservationGuest(
                    reservation_id=reservation.id,
                    name=guest.get("name") or guest.get("nom"),
                    age_category=guest.get("age_category")
                    or (str(guest["age"]) if guest.get("age") is not None else None),
                    is_vegetarian=bool(guest.get("is_vegetarian", False)),
                    allergenes=guest.get("allergenes") or guest.get("preferences"),
                    notes=guest.get("notes"),
                )
                self.db.add(g)
            self.db.flush()
            self.db.refresh(reservation)
        return reservation

    def list_active_for_table_range(
        self,
        table_id: uuid.UUID,
        start: datetime,
        end: datetime,
        exclude_reservation_id: Optional[uuid.UUID] = None,
    ) -> List[Reservation]:
        q = self.db.query(Reservation).filter(
            Reservation.table_id == table_id,
            Reservation.status.notin_(
                [ReservationStatus.CANCELLED.value, ReservationStatus.NO_SHOW.value]
            ),
            Reservation.reservation_date < end,
            func.timezone("UTC", Reservation.reservation_date)
            + (Reservation.duration_minutes * func.cast("1 minute", func.interval))
            > start,
        )
        if exclude_reservation_id is not None:
            q = q.filter(Reservation.id != exclude_reservation_id)
        return q.all()

    def list_for_restaurant(
        self,
        restaurant_id: uuid.UUID,
        filters: Optional[ReservationListFilters] = None,
    ) -> List[Reservation]:
        q = self.db.query(Reservation).filter(
            Reservation.restaurant_id == restaurant_id
        )
        if filters:
            if filters.date_debut is not None:
                start_of_day = datetime.combine(
                    filters.date_debut, time.min, tzinfo=timezone.utc
                )
                q = q.filter(Reservation.reservation_date >= start_of_day)
            if filters.date_fin is not None:
                end_of_day = datetime.combine(
                    filters.date_fin, time.max, tzinfo=timezone.utc
                )
                q = q.filter(Reservation.reservation_date <= end_of_day)
            if filters.statut:
                q = q.filter(Reservation.status == filters.statut)
            if filters.table_id:
                q = q.filter(Reservation.table_id == filters.table_id)
            if filters.nom_client:
                pattern = f"%{filters.nom_client.strip().lower()}%"
                q = q.filter(func.lower(Reservation.customer_name).like(pattern))
            if filters.phone_client:
                pattern = f"%{filters.phone_client.strip()}%"
                q = q.filter(Reservation.customer_phone.like(pattern))
        return q.order_by(Reservation.reservation_date.desc()).all()


class ReservationGuestRepository(BaseRepository[ReservationGuest]):
    def __init__(self, db: Session):
        super().__init__(ReservationGuest, db)

    def list_by_reservation(self, reservation_id: uuid.UUID) -> List[ReservationGuest]:
        return (
            self.db.query(ReservationGuest)
            .filter(ReservationGuest.reservation_id == reservation_id)
            .all()
        )


class WaitlistEntryRepository(BaseRepository[WaitlistEntry]):
    def __init__(self, db: Session):
        super().__init__(WaitlistEntry, db)

    def max_position(self, restaurant_id: uuid.UUID) -> int:
        result = (
            self.db.query(func.max(WaitlistEntry.position))
            .filter(
                WaitlistEntry.restaurant_id == restaurant_id,
                WaitlistEntry.status == "WAITING",
            )
            .scalar()
        )
        return int(result or 0)

    def list_waiting(self, restaurant_id: uuid.UUID) -> List[WaitlistEntry]:
        return (
            self.db.query(WaitlistEntry)
            .filter(
                WaitlistEntry.restaurant_id == restaurant_id,
                WaitlistEntry.status == "WAITING",
            )
            .order_by(WaitlistEntry.position.asc(), WaitlistEntry.joined_at.asc())
            .all()
        )

    def decrement_positions_after(
        self, restaurant_id: uuid.UUID, from_position: int
    ) -> None:
        entries = (
            self.db.query(WaitlistEntry)
            .filter(
                WaitlistEntry.restaurant_id == restaurant_id,
                WaitlistEntry.status == "WAITING",
                WaitlistEntry.position > from_position,
            )
            .order_by(WaitlistEntry.position.asc())
            .all()
        )
        for entry in entries:
            entry.position = entry.position - 1
        self.db.flush()

    def find_next_waiting(
        self, restaurant_id: uuid.UUID, expire_minutes: int = 60
    ) -> Optional[WaitlistEntry]:
        threshold = _utc_now() - timedelta(minutes=expire_minutes)
        return (
            self.db.query(WaitlistEntry)
            .filter(
                WaitlistEntry.restaurant_id == restaurant_id,
                WaitlistEntry.status == "WAITING",
                WaitlistEntry.joined_at >= threshold,
            )
            .order_by(WaitlistEntry.position.asc(), WaitlistEntry.joined_at.asc())
            .first()
        )


class ReservationService:
    def __init__(self, db: Session):
        self.db = db
        self.reservation_repo = ReservationRepository(db)
        self.guest_repo = ReservationGuestRepository(db)
        self.restaurant_repo = RestaurantRepository(db)
        self.table_repo = TableRepository(db)
        self.customer_repo = RosCustomerRepository(db)
        self.session_repo = ServiceSessionRepository(db)

    def check_table_availability(
        self,
        table_id: uuid.UUID,
        reservation_date: datetime,
        duration_minutes: int,
        exclude_reservation_id: Optional[uuid.UUID] = None,
    ) -> bool:
        if duration_minutes <= 0:
            raise ValidationError("duration_minutes must be positive")
        if reservation_date.tzinfo is None:
            reservation_date = reservation_date.replace(tzinfo=timezone.utc)
        start = reservation_date
        end = reservation_date + timedelta(minutes=duration_minutes)
        conflicts = self.reservation_repo.list_active_for_table_range(
            table_id, start, end, exclude_reservation_id=exclude_reservation_id
        )
        return len(conflicts) == 0

    def create_reservation(
        self,
        restaurant_id: uuid.UUID,
        data: ReservationCreate,
        created_by: Optional[uuid.UUID] = None,
    ) -> Reservation:
        if not self.restaurant_repo.get(str(restaurant_id)):
            raise NotFoundError("Restaurant not found")
        if data.nombre_personnes <= 0:
            raise ValidationError("Party size must be positive")
        reservation_date = _combine_date_heure(
            data.date_reservation, data.heure_reservation
        )
        duration = 90
        duration_minutes = getattr(data, "duration_minutes", None)
        if isinstance(duration_minutes, int) and duration_minutes > 0:
            duration = duration_minutes

        table = None
        if data.table_id is not None:
            table = self.table_repo.get(str(data.table_id))
            if not table or table.restaurant_id != restaurant_id:
                raise ValidationError("Invalid table for this restaurant")
            if table.statut == TableStatut.MAINTENANCE.value:
                raise BusinessLogicError("Table is under maintenance")
            if not self.check_table_availability(
                data.table_id, reservation_date, duration
            ):
                raise BusinessLogicError("Table not available at this time")

        reservation_data = {
            "restaurant_id": restaurant_id,
            "table_id": data.table_id,
            "customer_name": data.nom_client.strip(),
            "customer_phone": _normalize(data.phone_client),
            "customer_email": _normalize(data.email_client),
            "status": ReservationStatus.PENDING.value,
            "party_size": data.nombre_personnes,
            "reservation_date": reservation_date,
            "duration_minutes": duration,
            "notes": _normalize(data.notes),
            "source": _normalize(data.source) or "POS",
            "preferences_jsonb": data.preferences or data.metadata_jsonb,
            "created_by": created_by,
        }
        depot = getattr(data, "depot_garantie", None)
        if depot is not None and reservation_data["preferences_jsonb"] is None:
            reservation_data["preferences_jsonb"] = {}
        if depot is not None:
            reservation_data["preferences_jsonb"] = (
                reservation_data["preferences_jsonb"] or {}
            )
            reservation_data["preferences_jsonb"]["depot_garantie"] = str(depot)

        guest_data = []
        invites = getattr(data, "invites", None) or []
        for inv in invites:
            if hasattr(inv, "model_dump"):
                guest_data.append(inv.model_dump())
            elif isinstance(inv, dict):
                guest_data.append(inv)

        reservation = self.reservation_repo.create_with_guests(
            reservation_data, guests=guest_data
        )

        if (
            data.table_id is not None
            and reservation.status == ReservationStatus.CONFIRMED.value
        ):
            if table and table.statut == TableStatut.LIBRE.value:
                self.table_repo.update(table, {"statut": TableStatut.RESERVEE.value})

        logger.info(
            f"Reservation created: {reservation.id} for restaurant {restaurant_id} "
            f"table={data.table_id} party_size={data.nombre_personnes}"
        )
        return reservation

    def confirm_reservation(
        self,
        reservation_id: uuid.UUID,
        confirmed_by: Optional[uuid.UUID] = None,
    ) -> Reservation:
        reservation = self.reservation_repo.get(str(reservation_id))
        if not reservation:
            raise NotFoundError("Reservation not found")
        if reservation.status in {
            ReservationStatus.CANCELLED.value,
            ReservationStatus.NO_SHOW.value,
        }:
            raise BusinessLogicError(
                f"Cannot confirm reservation with status '{reservation.status}'"
            )
        reservation.status = ReservationStatus.CONFIRMED.value
        reservation.confirmed_at = _utc_now()
        if confirmed_by is not None:
            if reservation.preferences_jsonb is None:
                reservation.preferences_jsonb = {}
            reservation.preferences_jsonb = {
                **reservation.preferences_jsonb,
                "confirmed_by": str(confirmed_by),
            }
        if reservation.table_id is not None:
            table = self.table_repo.get(str(reservation.table_id))
            if table and table.statut == TableStatut.LIBRE.value:
                self.table_repo.update(table, {"statut": TableStatut.RESERVEE.value})
        self.db.flush()
        self.db.refresh(reservation)
        logger.info(f"Reservation confirmed: {reservation_id} by {confirmed_by}")
        return reservation

    def check_in_reservation(
        self,
        reservation_id: uuid.UUID,
    ) -> Reservation:
        reservation = self.reservation_repo.get(str(reservation_id))
        if not reservation:
            raise NotFoundError("Reservation not found")
        if reservation.status in {
            ReservationStatus.CANCELLED.value,
            ReservationStatus.NO_SHOW.value,
            ReservationStatus.COMPLETED.value,
        }:
            raise BusinessLogicError(
                f"Cannot check-in reservation with status '{reservation.status}'"
            )

        reservation.status = ReservationStatus.CHECKED_IN.value
        reservation.checked_in_at = _utc_now()

        customer = None
        if reservation.customer_id is not None:
            customer = self.customer_repo.get(str(reservation.customer_id))
        if customer is None:
            customer_data = {
                "restaurant_id": reservation.restaurant_id,
                "name": reservation.customer_name,
                "phone": reservation.customer_phone,
                "email": reservation.customer_email,
                "preferences_jsonb": reservation.preferences_jsonb,
            }
            customer = self.customer_repo.create(customer_data)
            reservation.customer_id = customer.id

        session = None
        if reservation.session_id is not None:
            session = self.session_repo.get(str(reservation.session_id))
        if session is None and reservation.table_id is not None:
            existing = self.session_repo.get_session_by_table(
                reservation.restaurant_id, reservation.table_id
            )
            if existing:
                session = existing
            else:
                session_data = {
                    "restaurant_id": reservation.restaurant_id,
                    "customer_id": customer.id,
                    "table_id": reservation.table_id,
                }
                session = self.session_repo.create(session_data)
            reservation.session_id = session.id

        if reservation.table_id is not None:
            table = self.table_repo.get(str(reservation.table_id))
            if table and table.statut in {
                TableStatut.LIBRE.value,
                TableStatut.RESERVEE.value,
            }:
                self.table_repo.update(table, {"statut": TableStatut.OCCUPEE.value})

        self.db.flush()
        self.db.refresh(reservation)
        logger.info(
            f"Reservation checked-in: {reservation_id}, customer={customer.id}, session={session.id if session else None}"
        )
        return reservation

    def cancel_reservation(
        self,
        reservation_id: uuid.UUID,
        reason: Optional[str] = None,
        cancelled_by: Optional[uuid.UUID] = None,
    ) -> Reservation:
        reservation = self.reservation_repo.get(str(reservation_id))
        if not reservation:
            raise NotFoundError("Reservation not found")
        if reservation.status in {
            ReservationStatus.CANCELLED.value,
            ReservationStatus.COMPLETED.value,
            ReservationStatus.NO_SHOW.value,
        }:
            return reservation

        reservation.status = ReservationStatus.CANCELLED.value
        reservation.cancelled_at = _utc_now()
        reservation.cancelled_by = cancelled_by
        reservation.cancel_reason = reason

        if reservation.table_id is not None:
            table = self.table_repo.get(str(reservation.table_id))
            if table and table.restaurant_id == reservation.restaurant_id:
                has_other_active = self._table_has_other_active_reservations(
                    table.id, reservation.id
                )
                table_in_use_session = self.session_repo.get_session_by_table(
                    reservation.restaurant_id, table.id
                )
                if not has_other_active and table_in_use_session is None:
                    if table.statut == TableStatut.RESERVEE.value:
                        self.table_repo.update(
                            table, {"statut": TableStatut.LIBRE.value}
                        )

        self.db.flush()
        self.db.refresh(reservation)
        logger.info(f"Reservation cancelled: {reservation_id} by {cancelled_by}")
        return reservation

    def _table_has_other_active_reservations(
        self,
        table_id: uuid.UUID,
        exclude_reservation_id: uuid.UUID,
    ) -> bool:
        today_start = _utc_now() - timedelta(hours=12)
        today_end = _utc_now() + timedelta(hours=12)
        conflicts = self.reservation_repo.list_active_for_table_range(
            table_id,
            today_start,
            today_end,
            exclude_reservation_id=exclude_reservation_id,
        )
        return len(conflicts) > 0

    def list_reservations(
        self,
        restaurant_id: uuid.UUID,
        filters: Optional[ReservationListFilters] = None,
    ) -> List[Reservation]:
        return self.reservation_repo.list_for_restaurant(restaurant_id, filters)


class WaitlistService:
    def __init__(self, db: Session):
        self.db = db
        self.waitlist_repo = WaitlistEntryRepository(db)
        self.restaurant_repo = RestaurantRepository(db)
        self.table_repo = TableRepository(db)

    def add_to_waitlist(
        self,
        restaurant_id: uuid.UUID,
        data: WaitlistCreate,
    ) -> WaitlistEntry:
        if not self.restaurant_repo.get(str(restaurant_id)):
            raise NotFoundError("Restaurant not found")
        if data.nombre_personnes <= 0:
            raise ValidationError("Party size must be positive")

        next_position = self.waitlist_repo.max_position(restaurant_id) + 1
        entry_data = {
            "restaurant_id": restaurant_id,
            "customer_name": data.nom_client.strip(),
            "customer_phone": _normalize(data.phone_client),
            "party_size": data.nombre_personnes,
            "position": next_position,
            "estimated_wait_minutes": getattr(data, "temps_attente_estime", None),
            "status": "WAITING",
            "source": "POS",
            "notes": _normalize(data.notes),
            "preferences_jsonb": getattr(data, "metadata_jsonb", None),
        }
        entry = self.waitlist_repo.create(entry_data)
        logger.info(
            f"WaitlistEntry added: {entry.id} restaurant={restaurant_id} position={next_position}"
        )
        return entry

    def seat_party(
        self,
        waitlist_id: uuid.UUID,
        table_id: Optional[uuid.UUID] = None,
    ) -> WaitlistEntry:
        entry = self.waitlist_repo.get(str(waitlist_id))
        if not entry:
            raise NotFoundError("Waitlist entry not found")
        if entry.status != "WAITING":
            raise BusinessLogicError(f"Cannot seat entry in status '{entry.status}'")

        if table_id is not None:
            table = self.table_repo.get(str(table_id))
            if not table or table.restaurant_id != entry.restaurant_id:
                raise ValidationError("Invalid table for this restaurant")
            if table.statut == TableStatut.MAINTENANCE.value:
                raise BusinessLogicError("Table is under maintenance")
            if table.statut != TableStatut.LIBRE.value:
                raise BusinessLogicError("Table is not available")
            self.table_repo.update(table, {"statut": TableStatut.OCCUPEE.value})
            entry.assigned_table_id = table_id

        entry.status = "SEATED"
        entry.seated_at = _utc_now()
        old_position = entry.position
        self.waitlist_repo.decrement_positions_after(entry.restaurant_id, old_position)
        entry.position = 0
        self.db.flush()
        self.db.refresh(entry)
        logger.info(
            f"WaitlistEntry seated: {waitlist_id} table={table_id}, position cleared"
        )
        return entry

    def promote_next(
        self,
        restaurant_id: uuid.UUID,
        table_id: uuid.UUID,
    ) -> Optional[WaitlistEntry]:
        if not self.restaurant_repo.get(str(restaurant_id)):
            raise NotFoundError("Restaurant not found")
        table = self.table_repo.get(str(table_id))
        if not table or table.restaurant_id != restaurant_id:
            raise ValidationError("Invalid table for this restaurant")

        next_entry = self.waitlist_repo.find_next_waiting(restaurant_id)
        if next_entry is None:
            logger.info(f"No waiting entry found for restaurant {restaurant_id}")
            return None
        return self.seat_party(next_entry.id, table_id=table_id)

    def expire_entry(self, waitlist_id: uuid.UUID) -> WaitlistEntry:
        entry = self.waitlist_repo.get(str(waitlist_id))
        if not entry:
            raise NotFoundError("Waitlist entry not found")
        if entry.status != "WAITING":
            return entry
        old_position = entry.position
        entry.status = "EXPIRED"
        entry.expired_at = _utc_now()
        self.waitlist_repo.decrement_positions_after(entry.restaurant_id, old_position)
        entry.position = 0
        self.db.flush()
        self.db.refresh(entry)
        logger.info(f"WaitlistEntry expired: {waitlist_id}")
        return entry
