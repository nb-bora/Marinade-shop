from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_tenant_path, require_pos
from app.core.database import get_db
from app.models.reservation import Reservation, ReservationGuest, WaitlistEntry
from app.models.user import User
from app.schemas.reservation import (
    ReservationCreate,
    ReservationUpdate,
    ReservationResponse,
    ReservationCancelRequest,
    ReservationConfirmRequest,
    ReservationListFilters,
    ReservationGuestCreate,
    ReservationGuestResponse,
    WaitlistCreate,
    WaitlistUpdate,
    WaitlistResponse,
)
from app.utils.enums import ReservationStatus

router = APIRouter(
    prefix="/reservations",
    tags=["reservations"],
    dependencies=[Depends(require_tenant_path), Depends(require_pos)],
)


def _reservation_to_response(
    db: Session, reservation: Reservation
) -> ReservationResponse:
    invites = (
        db.query(ReservationGuest)
        .filter(ReservationGuest.reservation_id == reservation.id)
        .all()
    )
    invite_responses = [ReservationGuestResponse.model_validate(i) for i in invites]
    data = {c.name: getattr(reservation, c.name) for c in reservation.__table__.columns}
    data["invites"] = invite_responses
    return ReservationResponse.model_validate(data)


def _create_reservation_guests(
    db: Session, reservation_id: uuid.UUID, invites: List[ReservationGuestCreate]
):
    for invite in invites:
        guest = ReservationGuest(
            reservation_id=reservation_id,
            name=invite.name,
            age_category=invite.age_category,
            is_vegetarian=invite.is_vegetarian,
            allergenes=invite.allergenes,
            notes=invite.notes,
        )
        db.add(guest)


@router.post(
    "/restaurants/{restaurant_id}/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reservation(
    restaurant_id: uuid.UUID,
    reservation_data: ReservationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = Reservation(
        restaurant_id=restaurant_id,
        table_id=reservation_data.table_id,
        customer_id=reservation_data.customer_id,
        created_by=current_user.id,
        customer_name=reservation_data.customer_name,
        customer_phone=reservation_data.customer_phone,
        customer_email=reservation_data.customer_email,
        status=reservation_data.status,
        party_size=reservation_data.party_size,
        reservation_date=reservation_data.reservation_date,
        duration_minutes=reservation_data.duration_minutes,
        notes=reservation_data.notes,
        source=reservation_data.source,
        reminder_sent=reservation_data.reminder_sent,
        arrival_notes=reservation_data.arrival_notes,
        preferences_jsonb=reservation_data.preferences_jsonb,
    )
    db.add(reservation)
    db.flush()
    _create_reservation_guests(db, reservation.id, reservation_data.invites)
    db.commit()
    db.refresh(reservation)
    return _reservation_to_response(db, reservation)


@router.get(
    "/restaurants/{restaurant_id}/reservations",
    response_model=List[ReservationResponse],
)
def list_reservations(
    restaurant_id: uuid.UUID,
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    status: Optional[str] = Query(None, max_length=30),
    table_id: Optional[uuid.UUID] = Query(None),
    search: Optional[str] = Query(None, max_length=255),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Reservation).filter(Reservation.restaurant_id == restaurant_id)
    if date_from:
        query = query.filter(Reservation.reservation_date >= date_from)
    if date_to:
        query = query.filter(Reservation.reservation_date <= date_to)
    if status:
        query = query.filter(Reservation.status == status)
    if table_id:
        query = query.filter(Reservation.table_id == table_id)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            or_(
                Reservation.customer_name.ilike(search_pattern),
                Reservation.customer_phone.ilike(search_pattern),
                Reservation.customer_email.ilike(search_pattern),
                Reservation.notes.ilike(search_pattern),
            )
        )
    query = query.order_by(Reservation.reservation_date.asc())
    reservations = query.all()
    return [_reservation_to_response(db, r) for r in reservations]


@router.get(
    "/{reservation_id}",
    response_model=ReservationResponse,
)
def get_reservation(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    return _reservation_to_response(db, reservation)


@router.put(
    "/{reservation_id}",
    response_model=ReservationResponse,
)
def update_reservation(
    reservation_id: uuid.UUID,
    update_data: ReservationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    for field, value in update_data.model_dump(exclude_unset=True).items():
        setattr(reservation, field, value)
    db.commit()
    db.refresh(reservation)
    return _reservation_to_response(db, reservation)


@router.delete(
    "/{reservation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_reservation(
    reservation_id: uuid.UUID,
    reason: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    db.query(ReservationGuest).filter(
        ReservationGuest.reservation_id == reservation_id
    ).delete()
    db.delete(reservation)
    db.commit()
    return None


@router.post(
    "/{reservation_id}/confirm",
    response_model=ReservationResponse,
)
def confirm_reservation(
    reservation_id: uuid.UUID,
    request_data: Optional[ReservationConfirmRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    reservation.status = ReservationStatus.CONFIRMED.value
    reservation.confirmed_at = datetime.now(timezone.utc)
    if request_data and request_data.notes and reservation.notes:
        reservation.notes = reservation.notes + "\n" + request_data.notes
    elif request_data and request_data.notes:
        reservation.notes = request_data.notes
    db.commit()
    db.refresh(reservation)
    return _reservation_to_response(db, reservation)


@router.post(
    "/{reservation_id}/check-in",
    response_model=ReservationResponse,
)
def check_in_reservation(
    reservation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    reservation.status = ReservationStatus.CHECKED_IN.value
    reservation.checked_in_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reservation)
    return _reservation_to_response(db, reservation)


@router.post(
    "/{reservation_id}/cancel",
    response_model=ReservationResponse,
)
def cancel_reservation(
    reservation_id: uuid.UUID,
    cancel_data: ReservationCancelRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Reservation not found"
        )
    reservation.status = ReservationStatus.CANCELLED.value
    reservation.cancelled_at = datetime.now(timezone.utc)
    reservation.cancelled_by = current_user.id
    reservation.cancel_reason = cancel_data.reason
    db.commit()
    db.refresh(reservation)
    return _reservation_to_response(db, reservation)


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
    max_position = (
        db.query(WaitlistEntry)
        .filter(
            WaitlistEntry.restaurant_id == restaurant_id,
            WaitlistEntry.status == "WAITING",
        )
        .count()
    )
    entry = WaitlistEntry(
        restaurant_id=restaurant_id,
        customer_name=waitlist_data.customer_name,
        customer_phone=waitlist_data.customer_phone,
        customer_email=waitlist_data.customer_email,
        party_size=waitlist_data.party_size,
        requested_table_id=waitlist_data.requested_table_id,
        position=max_position + 1,
        estimated_wait_minutes=waitlist_data.estimated_wait_minutes,
        status="WAITING",
        source=waitlist_data.source,
        notes=waitlist_data.notes,
        preferences_jsonb=waitlist_data.preferences_jsonb,
        joined_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return WaitlistResponse.model_validate(entry)


@router.get(
    "/restaurants/{restaurant_id}/waitlist",
    response_model=List[WaitlistResponse],
)
def list_waitlist(
    restaurant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entries = (
        db.query(WaitlistEntry)
        .filter(WaitlistEntry.restaurant_id == restaurant_id)
        .order_by(WaitlistEntry.position.asc())
        .all()
    )
    return [WaitlistResponse.model_validate(e) for e in entries]


@router.post(
    "/waitlist/{waitlist_id}/seat",
    response_model=WaitlistResponse,
)
def seat_waitlist_entry(
    waitlist_id: uuid.UUID,
    table_id: Optional[uuid.UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_id).first()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Waitlist entry not found"
        )
    entry.status = "SEATED"
    entry.seated_at = datetime.now(timezone.utc)
    if table_id:
        entry.assigned_table_id = table_id
    db.commit()
    db.refresh(entry)
    return WaitlistResponse.model_validate(entry)


@router.delete(
    "/waitlist/{waitlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_waitlist_entry(
    waitlist_id: uuid.UUID,
    reason: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == waitlist_id).first()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Waitlist entry not found"
        )
    entry.status = "REMOVED"
    entry.removed_at = datetime.now(timezone.utc)
    if reason and entry.notes:
        entry.notes = entry.notes + "\n" + reason
    elif reason:
        entry.notes = reason
    db.commit()
    return None
