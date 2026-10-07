from __future__ import annotations

import uuid
from typing import Iterable, List, Set, Union

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import get_db, get_session_local, set_db_context
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
from app.models.ros import ProductionTicket, ServiceSession
from app.models.subscription import Subscription
from app.models.tenant import RestaurantMember
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.enums import StaffRole

security = HTTPBearer(auto_error=False)

# ``set_db_context`` vit désormais dans app.core.database (les services en ont
# besoin) ; le nom reste importable d'ici pour les modules existants.
__all__ = ["set_db_context"]


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


def _user_id_from_access_token(token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"require": ["exp", "sub", "type"]},
        )
        if payload.get("type") != "access" or not payload.get("sub"):
            raise JWTError("Invalid token")
        return payload["sub"]
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _load_active_user(db: Session, user_id: str) -> User:
    """Load the caller and install the RLS context (user and platform-admin flag)."""
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
    return user


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
    user = _load_active_user(db, _user_id_from_access_token(credentials.credentials))
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


# --------------------------------------------------------------------------- #
# Rôles de l'équipe d'un restaurant
# --------------------------------------------------------------------------- #
# Le propriétaire (Restaurant.user_id) et les membres « owner » / « manager »
# passent TOUS les contrôles : un manager gère son établissement de bout en bout.
# Les autres rôles ne passent que là où ils sont explicitement listés.
_ALL_ACCESS_ROLES = frozenset({"owner", "manager"})
# Anciennes valeurs de restaurant_members.role, antérieures à staff_role.
_LEGACY_ROLE_ALIASES = {"kitchen": "chef"}


def _role_names(roles: Iterable[Union[StaffRole, str]]) -> Set[str]:
    return {r.value if isinstance(r, StaffRole) else str(r) for r in roles}


def _member_roles(member: RestaurantMember | None) -> Set[str]:
    """Effective roles of a membership: granular staff_role plus the legacy role."""
    if member is None:
        return set()
    raw = {member.staff_role, member.role}
    raw.discard(None)
    raw.discard("staff")  # ancien rôle générique : n'accorde aucun privilège
    return {_LEGACY_ROLE_ALIASES.get(role, role) for role in raw}


def ensure_tenant_role(
    db: Session,
    user: User,
    tenant_id: uuid.UUID,
    accepted_roles: Iterable[Union[StaffRole, str]],
) -> Restaurant:
    """Authorize ``user`` on a restaurant AND check the role they hold there.

    Usable directly when the restaurant id comes from a request body rather than
    the URL. Raises 404 when the user has no access to the restaurant at all (so
    its existence is not revealed) and 403 when they belong to it without a role
    that is allowed to perform the action.
    """
    restaurant = _authorize_tenant(db, user, tenant_id)
    if user.role == "admin" or restaurant.user_id == user.id:
        return restaurant
    member = (
        db.query(RestaurantMember)
        .filter(
            RestaurantMember.restaurant_id == tenant_id,
            RestaurantMember.user_id == user.id,
            RestaurantMember.is_active == True,
        )
        .first()
    )
    accepted = _role_names(accepted_roles)
    if _member_roles(member) & (_ALL_ACCESS_ROLES | accepted):
        return restaurant
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Insufficient permissions. Required roles: {sorted(accepted | _ALL_ACCESS_ROLES)}",
    )


def _parse_uuid(raw: object, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label} must be a UUID") from exc


# Paramètres de chemin qui désignent une ressource appartenant à un restaurant.
_RESOURCE_MODELS = {
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
    "refund_id": CommandeRefund,
    "reservation_id": Reservation,
    "waitlist_id": WaitlistEntry,
    "ticket_id": ProductionTicket,
    "session_id": ServiceSession,
}


def _resource_tenant(db: Session, resource: object) -> uuid.UUID | None:
    """Restaurant owning a resource, including those that only reference a parent."""
    tenant_id = getattr(resource, "restaurant_id", None)
    if tenant_id is not None:
        return tenant_id
    if isinstance(resource, PlatComposant):
        parent = db.get(Plat, resource.plat_id)
    elif isinstance(resource, CommandeRefund):
        parent = db.get(Commande, resource.commande_id)
    else:
        return None
    return parent.restaurant_id if parent is not None else None


def _path_tenant_ids(request: Request, db: Session) -> List[uuid.UUID]:
    """Every restaurant implied by the URL: ``restaurant_id`` and owned resources."""
    tenant_ids: List[uuid.UUID] = []
    raw_tenant = request.path_params.get("restaurant_id")
    if raw_tenant:
        tenant_ids.append(_parse_uuid(raw_tenant, "restaurant_id"))
    for param, model in _RESOURCE_MODELS.items():
        raw_id = request.path_params.get(param)
        if raw_id is None:
            continue
        resource = db.get(model, _parse_uuid(raw_id, param))
        tenant_id = _resource_tenant(db, resource) if resource is not None else None
        if tenant_id is None:
            raise HTTPException(status_code=404, detail="Resource not found")
        tenant_ids.append(tenant_id)
    return tenant_ids


def require_staff_role(accepted_roles: Iterable[Union[StaffRole, str]]):
    """Dependency factory: the caller must hold one of ``accepted_roles`` on the
    restaurant targeted by the request (path, owned resource, or X-Tenant-ID).

    Owners, managers and platform admins always pass.
    """
    accepted = _role_names(accepted_roles)

    def _require_staff_role(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        tenant_ids = _path_tenant_ids(request, db)
        if not tenant_ids:
            header = request.headers.get("X-Tenant-ID")
            if header:
                tenant_ids = [_parse_uuid(header, "X-Tenant-ID")]
            elif current_user.role != "admin":
                tenant_id = current_tenant_id(db)
                if tenant_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="X-Tenant-ID header is required",
                    )
                tenant_ids = [tenant_id]
        for tenant_id in tenant_ids:
            ensure_tenant_role(db, current_user, tenant_id, accepted)
        return current_user

    # Nom unique par jeu de rôles : FastAPI met en cache les dépendances par
    # identité de fonction, et le nom rend les traces et les tests lisibles.
    _require_staff_role.__name__ = "require_staff_role_" + "_".join(sorted(accepted))
    _require_staff_role.required_roles = frozenset(accepted)  # type: ignore[attr-defined]
    return _require_staff_role


def require_restaurant_access(
    restaurant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Restaurant:
    return _authorize_tenant(db, current_user, restaurant_id)


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
# Les dépendances HTTP ne conviennent pas ici : un navigateur ne peut pas poser
# l'en-tête Authorization sur un WebSocket. Le jeton voyage donc soit dans cet
# en-tête (applications natives), soit comme sous-protocole : le client ouvre
# ``new WebSocket(url, ["bearer", accessToken])``. Il n'est jamais dans l'URL,
# qui finirait dans les journaux d'accès.
WEBSOCKET_SUBPROTOCOL = "bearer"


def websocket_token(websocket: WebSocket) -> tuple[str | None, bool]:
    """Return (token, used_subprotocol) from an upgrade request."""
    authorization = websocket.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None, False
    offered = [
        p.strip()
        for p in websocket.headers.get("sec-websocket-protocol", "").split(",")
    ]
    if len(offered) == 2 and offered[0] == WEBSOCKET_SUBPROTOCOL and offered[1]:
        return offered[1], True
    return None, False


def _authorize_websocket_sync(
    token: str, tenant_id: uuid.UUID, accepted_roles: Iterable[Union[StaffRole, str]]
) -> bool:
    db = get_session_local()()
    try:
        user = _load_active_user(db, _user_id_from_access_token(token))
        ensure_tenant_role(db, user, tenant_id, accepted_roles)
        return True
    except HTTPException:
        return False
    finally:
        db.close()


async def authenticate_websocket(
    websocket: WebSocket,
    tenant_id: uuid.UUID,
    accepted_roles: Iterable[Union[StaffRole, str]],
) -> str | None:
    """Authenticate a WebSocket upgrade for one restaurant and role set.

    Returns the subprotocol the server must echo in ``accept()`` ("" when the
    token came from the Authorization header), or None when access is refused.
    The caller must then close the connection BEFORE accepting it.
    """
    token, used_subprotocol = websocket_token(websocket)
    if token is None:
        return None
    allowed = await run_in_threadpool(
        _authorize_websocket_sync, token, tenant_id, accepted_roles
    )
    if not allowed:
        return None
    return WEBSOCKET_SUBPROTOCOL if used_subprotocol else ""


def require_tenant_path(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """Authorize nested restaurant resources without trusting their UUID alone."""
    for tenant_id in _path_tenant_ids(request, db):
        _authorize_tenant(db, current_user, tenant_id)
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
