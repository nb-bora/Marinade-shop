from __future__ import annotations

import uuid
from typing import Set, Union

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.payment import PaymentIntent
from app.models.reservation import Reservation, WaitlistEntry
from app.models.restaurant import (
    Boisson,
    Combinaison,
    Commande,
    CommandeRefund,
    Composant,
    Menu,
    MenuCategory,
    Plat,
    PlatComposant,
    Restaurant,
    Table,
)
from app.models.subscription import Subscription
from app.models.tenant import RestaurantMember
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.enums import StaffRole

security = HTTPBearer(auto_error=False)


def set_db_context(db: Session, name: str, value: str | None) -> None:
    """Set a transaction-local PostgreSQL setting used by RLS."""
    db.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": name, "value": value or ""},
    )


def current_tenant_id(db: Session) -> uuid.UUID | None:
    value = db.execute(
        text("SELECT current_setting('app.current_tenant_id', true)")
    ).scalar()
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _authorize_tenant(db: Session, user: User, tenant_id: uuid.UUID) -> Restaurant:
    if user.role == "admin":
        set_db_context(db, "app.current_tenant_id", str(tenant_id))
        restaurant = db.query(Restaurant).filter(Restaurant.id == tenant_id).first()
    else:
        member = (
            db.query(RestaurantMember)
            .filter(
                RestaurantMember.restaurant_id == tenant_id,
                RestaurantMember.user_id == user.id,
                RestaurantMember.is_active == True,
            )
            .first()
        )
        owned = (
            db.query(Restaurant)
            .filter(
                Restaurant.id == tenant_id,
                Restaurant.user_id == user.id,
            )
            .first()
        )
        if member is None and owned is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        set_db_context(db, "app.current_tenant_id", str(tenant_id))
        restaurant = db.query(Restaurant).filter(Restaurant.id == tenant_id).first()
    if restaurant is None:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant


def _set_requested_tenant(db: Session, user: User, request: Request) -> None:
    requested = request.headers.get("X-Tenant-ID")
    if requested:
        try:
            tenant_id = uuid.UUID(requested)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="X-Tenant-ID must be a UUID"
            ) from exc
        _authorize_tenant(db, user, tenant_id)
        return

    owned = db.query(Restaurant).filter(Restaurant.user_id == user.id).first()
    if owned is not None:
        set_db_context(db, "app.current_tenant_id", str(owned.id))
        return

    memberships = (
        db.query(RestaurantMember)
        .filter(
            RestaurantMember.user_id == user.id,
            RestaurantMember.is_active == True,
        )
        .all()
    )
    if len(memberships) > 1:
        raise HTTPException(
            status_code=400,
            detail="X-Tenant-ID is required for a user with multiple restaurants",
        )
    if memberships:
        _authorize_tenant(db, user, memberships[0].restaurant_id)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
        )
        if payload.get("type") != "access" or not payload.get("sub"):
            raise JWTError("Invalid token")
        user_id = payload["sub"]
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    set_db_context(db, "app.current_user_id", str(user_id))
    set_db_context(db, "app.is_platform_admin", "false")
    set_db_context(db, "app.current_tenant_id", "")
    user = UserRepository(db).get(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    set_db_context(
        db, "app.is_platform_admin", "true" if user.role == "admin" else "false"
    )
    if user.role != "admin":
        _set_requested_tenant(db, user, request)
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user


def require_pos(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {"pos", "restaurant", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="POS access required"
        )
    return current_user


def require_staff_role(accepted_roles: Set[Union[StaffRole, str]]):
    accepted_role_strs = {
        r.value if isinstance(r, StaffRole) else r for r in accepted_roles
    }

    def _require_staff_role(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if current_user.role == "admin":
            return current_user
        tenant_id_str = request.headers.get("X-Tenant-ID")
        if not tenant_id_str:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Tenant-ID header is required",
            )
        try:
            tenant_id = uuid.UUID(tenant_id_str)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="X-Tenant-ID must be a UUID"
            ) from exc
        member = (
            db.query(RestaurantMember)
            .filter(
                RestaurantMember.restaurant_id == tenant_id,
                RestaurantMember.user_id == current_user.id,
                RestaurantMember.is_active == True,
            )
            .first()
        )
        if member is None or member.staff_role not in accepted_role_strs:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {sorted(accepted_role_strs)}",
            )
        return current_user

    return _require_staff_role


def require_restaurant_access(
    restaurant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Restaurant:
    return _authorize_tenant(db, current_user, restaurant_id)


def require_tenant_path(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Authorize nested restaurant resources without trusting their UUID alone."""
    raw_tenant = request.path_params.get("restaurant_id")
    if raw_tenant:
        try:
            tenant_id = uuid.UUID(str(raw_tenant))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="restaurant_id must be a UUID"
            ) from exc
        _authorize_tenant(db, current_user, tenant_id)
        return current_user

    resource_models = {
        "menu_id": Menu,
        "category_id": MenuCategory,
        "composant_id": Composant,
        "combinaison_id": Combinaison,
        "plat_id": Plat,
        "plat_composant_id": PlatComposant,
        "boisson_id": Boisson,
        "table_id": Table,
        "commande_id": Commande,
        "commande_refund_id": CommandeRefund,
        "reservation_id": Reservation,
        "waitlist_id": WaitlistEntry,
    }
    for param, model in resource_models.items():
        raw_id = request.path_params.get(param)
        if raw_id is None:
            continue
        try:
            resource_id = uuid.UUID(str(raw_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"{param} must be a UUID"
            ) from exc
        resource = db.get(model, resource_id)
        if resource is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        _authorize_tenant(db, current_user, resource.restaurant_id)
    return current_user


def require_subscription_access(
    subscription_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Subscription:
    subscription = (
        db.query(Subscription).filter(Subscription.id == subscription_id).first()
    )
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found"
        )
    if current_user.role != "admin":
        _authorize_tenant(db, current_user, subscription.restaurant_id)
    return subscription


def require_transaction_access(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if current_user.role != "admin":
        _authorize_tenant(db, current_user, transaction.restaurant_id)
    return transaction


def require_payment_intent_access(
    payment_intent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentIntent:
    intent = (
        db.query(PaymentIntent).filter(PaymentIntent.id == payment_intent_id).first()
    )
    if intent is None:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    if current_user.role != "admin":
        _authorize_tenant(db, current_user, intent.restaurant_id)
    return intent
