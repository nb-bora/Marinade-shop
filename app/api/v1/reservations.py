"""Réservations et liste d'attente.

Les règles vivent dans ``app/services/reservation_service.py`` ; ces routes ne font que
l'autorisation, la lecture et le format de réponse.
"""

from datetime import date, datetime
from typing import Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api import permissions as perm
from app.api.dependencies import (
    _role_names,
    ensure_tenant_role,
    get_current_user,
    require_tenant_path,
)
from app.api.pagination import Page, page_params
from app.core.database import get_db
from app.models.reservation import Reservation, ReservationGuest, WaitlistEntry
from app.models.user import User
from app.schemas.reservation import (
    ClientRecherche,
    ClientResume,
    DisponibiliteResponse,
    ReservationCancelRequest,
    ReservationConfirmRequest,
    ReservationCreate,
    ReservationGuestResponse,
    ReservationResponse,
    ReservationUpdate,
    WaitlistCreate,
    WaitlistResponse,
)
from app.services import availability_service as av
from app.services.reservation_service import ReservationService, WaitlistService
from app.utils.exceptions import AuthorizationError
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/reservations",
    tags=["reservations"],
    dependencies=[Depends(require_tenant_path), Depends(perm.RESERVATION_DESK)],
)

DUREE_DEFAUT = 90


def _peut_gerer(db: Session, user: User, restaurant_id: uuid.UUID) -> bool:
    try:
        ensure_tenant_role(db, user, restaurant_id, perm.MANAGEMENT_ROLES)
    except HTTPException:
        return False
    return True


def _forcer(db: Session, user: User, restaurant_id: uuid.UUID, demande: bool) -> bool:
    """``force=true`` n'est accepté que pour la gestion : sinon 403 explicite."""
    if not demande:
        return False
    if not _peut_gerer(db, user, restaurant_id):
        raise AuthorizationError(
            "Seule la gestion peut forcer une réservation (capacité, horaires, date passée)."
        )
    return True


def _autoriser(db: Session, user: User, restaurant_id: uuid.UUID) -> None:
    """Contrôle explicite du restaurant de la ressource, en plus de la RLS."""
    ensure_tenant_role(db, user, restaurant_id, _role_names(perm.RESERVATION_ROLES))


def _charger(db: Session, reservation_id: uuid.UUID, user: User) -> Reservation:
    service = ReservationService(db)
    reservation = service.charger(reservation_id)
    _autoriser(db, user, reservation.restaurant_id)
    return reservation


def _charger_entree(db: Session, entry_id: uuid.UUID, user: User) -> WaitlistEntry:
    entry = WaitlistService(db).charger(entry_id)
    _autoriser(db, user, entry.restaurant_id)
    return entry


def _guests_by_reservation(
    db: Session, reservation_ids: List[uuid.UUID]
) -> Dict[uuid.UUID, List[ReservationGuest]]:
    """Invités de plusieurs réservations en UNE requête (évite un N+1)."""
    grouped: Dict[uuid.UUID, List[ReservationGuest]] = {r: [] for r in reservation_ids}
    if not reservation_ids:
        return grouped
    rows = (
        db.query(ReservationGuest)
        .filter(ReservationGuest.reservation_id.in_(set(reservation_ids)))
        .order_by(ReservationGuest.created_at, ReservationGuest.id)
        .all()
    )
    for row in rows:
        grouped[row.reservation_id].append(row)
    return grouped


def _reservation_out(
    reservation: Reservation, guests: Optional[List[ReservationGuest]] = None
) -> ReservationResponse:
    invites = [ReservationGuestResponse.model_validate(g) for g in (guests or [])]
    data = {c.name: getattr(reservation, c.name) for c in reservation.__table__.columns}
    data["invites"] = invites
    return ReservationResponse.model_validate(data)


def _reservation_detail(db: Session, reservation: Reservation) -> ReservationResponse:
    guests = _guests_by_reservation(db, [reservation.id])[reservation.id]
    return _reservation_out(reservation, guests)


def _waitlist_out(entry: WaitlistEntry) -> WaitlistResponse:
    return WaitlistResponse.model_validate(entry)


# ---------------------------------------------------------------------------- réservations


@router.post(
    "/restaurants/{restaurant_id}/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reservation(
    restaurant_id: uuid.UUID,
    reservation_data: ReservationCreate,
    force: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _autoriser(db, current_user, restaurant_id)
    forcer = _forcer(db, current_user, restaurant_id, force)
    reservation = ReservationService(db).create(
        restaurant_id, reservation_data, user_id=current_user.id, forcer=forcer
    )
    return _reservation_detail(db, reservation)


@router.get(
    "/restaurants/{restaurant_id}/reservations",
    response_model=List[ReservationResponse],
)
def list_reservations(
    restaurant_id: uuid.UUID,
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status", max_length=30),
    table_id: Optional[uuid.UUID] = Query(None),
    search: Optional[str] = Query(None, max_length=255),
    page: Page = Depends(page_params),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _autoriser(db, current_user, restaurant_id)
    query = db.query(Reservation).filter(
        Reservation.restaurant_id == restaurant_id, Reservation.deleted_at.is_(None)
    )
    if date_from:
        query = query.filter(Reservation.reservation_date >= date_from)
    if date_to:
        query = query.filter(Reservation.reservation_date <= date_to)
    if status_filter:
        query = query.filter(Reservation.status == status_filter)
    if table_id:
        query = query.filter(Reservation.table_id == table_id)
    if search:
        motif = f"%{search}%"
        query = query.filter(
            or_(
                Reservation.customer_name.ilike(motif),
                Reservation.customer_phone.ilike(motif),
                Reservation.customer_email.ilike(motif),
                Reservation.notes.ilike(motif),
            )
        )
    reservations = (
        query.order_by(Reservation.reservation_date.asc(), Reservation.id)
        .offset(page.skip)
        .limit(page.limit)
        .all()
    )
    guests = _guests_by_reservation(db, [r.id for r in reservations])
    return [_reservation_out(r, guests[r.id]) for r in reservations]


@router.get(
    "/restaurants/{restaurant_id}/availability",
    response_model=DisponibiliteResponse,
)
def get_availability(
    restaurant_id: uuid.UUID,
    date_jour: date = Query(..., alias="date"),
    party_size: int = Query(..., gt=0, le=500),
    duration: int = Query(DUREE_DEFAUT, gt=0, le=av.DUREE_MAX_MIN),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _autoriser(db, current_user, restaurant_id)
    return ReservationService(db).disponibilite(restaurant_id, date_jour, party_size, duration)


@router.get(
    "/restaurants/{restaurant_id}/customers/search",
    response_model=List[ClientRecherche],
)
def search_customers(
    restaurant_id: uuid.UUID,
    q: str = Query(..., min_length=2, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _autoriser(db, current_user, restaurant_id)
    clients = ReservationService(db).rechercher_clients(restaurant_id, q)
    return [
        ClientRecherche(id=c.id, name=c.name, phone=c.phone, email=c.email) for c in clients
    ]


@router.get(
    "/restaurants/{restaurant_id}/customers/{customer_id}/summary",
    response_model=ClientResume,
)
def customer_summary(
    restaurant_id: uuid.UUID,
    customer_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _autoriser(db, current_user, restaurant_id)
    return ClientResume(**ReservationService(db).resume_client(restaurant_id, customer_id))


@router.get(
    "/{reservation_id}",
    response_model=ReservationResponse,
)
def get_reservation(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _reservation_detail(db, _charger(db, reservation_id, current_user))


@router.put(
    "/{reservation_id}",
    response_model=ReservationResponse,
)
def update_reservation(
    reservation_id: uuid.UUID,
    update_data: ReservationUpdate,
    force: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = _charger(db, reservation_id, current_user)
    forcer = _forcer(db, current_user, reservation.restaurant_id, force)
    changes = update_data.model_dump(exclude_unset=True)
    updated = ReservationService(db).update(reservation, changes, forcer=forcer)
    return _reservation_detail(db, updated)


@router.delete(
    "/{reservation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_reservation(
    reservation_id: uuid.UUID,
    reason: Optional[str] = Query(None, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = _charger(db, reservation_id, current_user)
    # Suppression logique : la ligne et ses invités restent pour l'historique.
    ReservationService(db).supprimer(reservation, reason)
    logger.info("Reservation soft-deleted: %s by user=%s", reservation_id, current_user.id)
    return None


@router.post("/{reservation_id}/confirm", response_model=ReservationResponse)
def confirm_reservation(
    reservation_id: uuid.UUID,
    request_data: Optional[ReservationConfirmRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = _charger(db, reservation_id, current_user)
    notes = request_data.notes if request_data else None
    confirmed = ReservationService(db).confirmer(reservation, notes)
    return _reservation_detail(db, confirmed)


@router.post("/{reservation_id}/check-in", response_model=ReservationResponse)
def check_in_reservation(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = _charger(db, reservation_id, current_user)
    arrived = ReservationService(db).arriver(reservation)
    return _reservation_detail(db, arrived)


@router.post("/{reservation_id}/no-show", response_model=ReservationResponse)
def no_show_reservation(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = _charger(db, reservation_id, current_user)
    return _reservation_detail(db, ReservationService(db).absent(reservation))


@router.post("/{reservation_id}/complete", response_model=ReservationResponse)
def complete_reservation(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = _charger(db, reservation_id, current_user)
    return _reservation_detail(db, ReservationService(db).terminer(reservation))


@router.post("/{reservation_id}/cancel", response_model=ReservationResponse)
def cancel_reservation(
    reservation_id: uuid.UUID,
    cancel_data: ReservationCancelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = _charger(db, reservation_id, current_user)
    cancelled = ReservationService(db).annuler(reservation, current_user.id, cancel_data.reason)
    return _reservation_detail(db, cancelled)


# ---------------------------------------------------------------------------- liste d'attente


@router.post(
    "/restaurants/{restaurant_id}/waitlist",
    response_model=WaitlistResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_waitlist_entry(
    restaurant_id: uuid.UUID,
    waitlist_data: WaitlistCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _autoriser(db, current_user, restaurant_id)
    return _waitlist_out(WaitlistService(db).creer(restaurant_id, waitlist_data))


@router.get(
    "/restaurants/{restaurant_id}/waitlist",
    response_model=List[WaitlistResponse],
)
def list_waitlist(
    restaurant_id: uuid.UUID,
    status_filter: Optional[str] = Query(None, alias="status", max_length=30),
    page: Page = Depends(page_params),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _autoriser(db, current_user, restaurant_id)
    query = db.query(WaitlistEntry).filter(WaitlistEntry.restaurant_id == restaurant_id)
    if status_filter:
        query = query.filter(WaitlistEntry.status == status_filter)
    entries = (
        query.order_by(WaitlistEntry.position.asc(), WaitlistEntry.id)
        .offset(page.skip)
        .limit(page.limit)
        .all()
    )
    return [_waitlist_out(e) for e in entries]


@router.post("/waitlist/{waitlist_id}/seat", response_model=WaitlistResponse)
def seat_waitlist_entry(
    waitlist_id: uuid.UUID,
    table_id: Optional[uuid.UUID] = Query(None),
    force: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = _charger_entree(db, waitlist_id, current_user)
    forcer = _forcer(db, current_user, entry.restaurant_id, force)
    return _waitlist_out(WaitlistService(db).installer(entry, table_id, forcer=forcer))


@router.post("/waitlist/{waitlist_id}/notify", response_model=Dict[str, object])
def notify_waitlist_entry(
    waitlist_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = _charger_entree(db, waitlist_id, current_user)
    adresse = WaitlistService(db).prevenir(entry)
    return {"envoye": True, "destinataire": adresse}


@router.delete(
    "/waitlist/{waitlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_waitlist_entry(
    waitlist_id: uuid.UUID,
    reason: Optional[str] = Query(None, max_length=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = _charger_entree(db, waitlist_id, current_user)
    WaitlistService(db).retirer(entry, reason)
    return None
