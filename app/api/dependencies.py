from __future__ import annotations

import uuid
from typing import Iterable, List, Set, Union

from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import (
    _ACCESS_KEY,
    get_db,
    get_db_context,
    get_session_local,
    set_db_context,
    set_db_contexts,
)
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
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.enums import StaffRole

security = HTTPBearer(auto_error=False)

# ``set_db_context`` vit désormais dans app.core.database (les services en ont
# besoin) ; le nom reste importable d'ici pour les modules existants.
__all__ = ["set_db_context"]


def current_tenant_id(db: Session) -> uuid.UUID | None:
    """Restaurant the current request is scoped to (no database round trip)."""
    value = get_db_context(db, "app.current_tenant_id")
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Accès à un restaurant : qui est l'utilisateur ICI, et avec quel rôle
# --------------------------------------------------------------------------- #
# Rôles qui passent tous les contrôles d'un restaurant. Les autres ne passent que
# là où ils sont explicitement listés (voir app/api/permissions.py).
_ALL_ACCESS_ROLES = frozenset({"owner", "manager"})
# Anciennes valeurs de restaurant_members.role, antérieures à staff_role.
_LEGACY_ROLE_ALIASES = {"kitchen": "chef"}


def _role_names(roles: Iterable[Union[StaffRole, str]]) -> Set[str]:
    return {r.value if isinstance(r, StaffRole) else str(r) for r in roles}


def _effective_roles(staff_role: str | None, role: str | None) -> frozenset[str]:
    """Roles of a membership: the granular staff_role plus the legacy role column."""
    raw = {staff_role, role}
    raw.discard(None)
    raw.discard("staff")  # ancien rôle générique : n'accorde aucun privilège
    return frozenset(_LEGACY_ROLE_ALIASES.get(r, r) for r in raw)


@dataclass(frozen=True)
class TenantAccess:
    """What a user is allowed to be inside one restaurant. Pure data, no database."""

    tenant_id: uuid.UUID
    is_admin: bool = False
    is_owner: bool = False
    is_member: bool = False
    roles: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_access(self) -> bool:
        return self.is_admin or self.is_owner or self.is_member

    def allows(self, accepted_roles: Iterable[Union[StaffRole, str]]) -> bool:
        if self.is_admin or self.is_owner:
            return True
        return bool(self.roles & (_ALL_ACCESS_ROLES | _role_names(accepted_roles)))


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Restaurant not found")


_ACCESS_SQL = text(
    """
    SELECT EXISTS (
               SELECT 1 FROM restaurants r
               WHERE r.id = CAST(:tenant AS uuid) AND r.user_id = CAST(:user AS uuid)
           ) AS is_owner,
           (m.id IS NOT NULL) AS is_member,
           m.role AS role,
           m.staff_role AS staff_role
    FROM (SELECT 1) AS one
    LEFT JOIN restaurant_members m
           ON m.restaurant_id = CAST(:tenant AS uuid)
          AND m.user_id = CAST(:user AS uuid)
          AND m.is_active
    """
)


def _access_cache(db: Session) -> dict:
    return db.info.setdefault(_ACCESS_KEY, {})


def _tenant_access(db: Session, user: User, tenant_id: uuid.UUID) -> TenantAccess:
    """Access of ``user`` to ``tenant_id`` in ONE query, remembered for the request.

    Raises 404 (not 403) when the user has no link to the restaurant, so its
    existence is not revealed. The result does not depend on the active tenant
    context: the policies on ``restaurants`` and ``restaurant_members`` expose a
    user's own rows as soon as ``app.current_user_id`` is set.
    """
    cache = _access_cache(db)
    key = (user.id, tenant_id)
    cached = cache.get(key)
    if cached is not None:
        if not cached.has_access:
            raise _not_found()
        return cached

    if user.role == "admin":
        exists = db.execute(
            text("SELECT 1 FROM restaurants WHERE id = CAST(:tenant AS uuid)"),
            {"tenant": str(tenant_id)},
        ).first()
        access = TenantAccess(tenant_id, is_admin=exists is not None)
    else:
        row = db.execute(
            _ACCESS_SQL, {"tenant": str(tenant_id), "user": str(user.id)}
        ).one()
        access = TenantAccess(
            tenant_id,
            is_owner=bool(row.is_owner),
            is_member=bool(row.is_member),
            roles=_effective_roles(row.staff_role, row.role)
            if row.is_member
            else frozenset(),
        )
    cache[key] = access
    if not access.has_access:
        raise _not_found()
    return access


def _activate_tenant(db: Session, tenant_id: uuid.UUID) -> None:
    if get_db_context(db, "app.current_tenant_id") != str(tenant_id):
        set_db_context(db, "app.current_tenant_id", str(tenant_id))


def _authorize_tenant(db: Session, user: User, tenant_id: uuid.UUID) -> TenantAccess:
    """Check access to the restaurant, then scope the database session to it."""
    access = _tenant_access(db, user, tenant_id)
    _activate_tenant(db, tenant_id)
    return access


_DEFAULT_TENANT_SQL = text(
    """
    SELECT 'owner' AS kind, id AS restaurant_id, NULL AS role, NULL AS staff_role
    FROM restaurants WHERE user_id = CAST(:user AS uuid)
    UNION ALL
    SELECT 'member', restaurant_id, role, staff_role
    FROM restaurant_members WHERE user_id = CAST(:user AS uuid) AND is_active
    LIMIT 3
    """
)


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

    if user.role == "admin":
        # Un administrateur de la plateforme n'a pas de restaurant « par défaut » : sans
        # en-tête explicite, aucun contexte n'est établi et les routes réclament un
        # restaurant_id. Chercher parmi ses propres restaurants n'aurait pas de sens.
        return

    rows = db.execute(_DEFAULT_TENANT_SQL, {"user": str(user.id)}).all()
    owned = next((r for r in rows if r.kind == "owner"), None)
    if owned is not None:
        tenant_id = owned.restaurant_id
        _access_cache(db)[(user.id, tenant_id)] = TenantAccess(tenant_id, is_owner=True)
        _activate_tenant(db, tenant_id)
        return

    memberships = {r.restaurant_id: r for r in rows if r.kind == "member"}
    if len(memberships) > 1:
        raise HTTPException(
            status_code=400,
            detail="X-Tenant-ID is required for a user with multiple restaurants",
        )
    if memberships:
        tenant_id, member = next(iter(memberships.items()))
        _access_cache(db)[(user.id, tenant_id)] = TenantAccess(
            tenant_id,
            is_member=True,
            roles=_effective_roles(member.staff_role, member.role),
        )
        _activate_tenant(db, tenant_id)


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
    """Load the caller, then install the RLS context in a single round trip.

    ``users`` carries no row level security (it is the identity table, read before
    any context exists), so the lookup comes first. The context is then set once
    with the real platform-admin flag; it never has a window where an unknown user
    holds admin rights.
    """
    user = UserRepository(db).get(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    set_db_contexts(
        db,
        {
            "app.current_user_id": str(user.id),
            "app.is_platform_admin": "true" if user.role == "admin" else "false",
            "app.current_tenant_id": "",
        },
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


def ensure_tenant_role(
    db: Session,
    user: User,
    tenant_id: uuid.UUID,
    accepted_roles: Iterable[Union[StaffRole, str]],
) -> TenantAccess:
    """Authorize ``user`` on a restaurant AND check the role they hold there.

    Usable directly when the restaurant id comes from a request body rather than
    the URL. Raises 404 when the user has no access to the restaurant at all (so
    its existence is not revealed) and 403 when they belong to it without a role
    that is allowed to perform the action. The owner, managers and platform admins
    always pass.
    """
    access = _authorize_tenant(db, user, tenant_id)
    if not access.allows(accepted_roles):
        accepted = _role_names(accepted_roles)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required roles: {sorted(accepted | _ALL_ACCESS_ROLES)}",
        )
    return access


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


def has_tenant_role(
    db: Session,
    user: User,
    tenant_id: uuid.UUID,
    accepted_roles: Iterable[Union[StaffRole, str]],
) -> bool:
    """True si l'utilisateur a l'un de ces roles dans ce restaurant.

    Contrairement a ``ensure_tenant_role`` il ne leve rien quand le role manque :
    il sert a adapter un comportement (ex. prix libre reserve au management) sans
    refuser toute la requete. Un utilisateur sans aucun lien avec le restaurant
    recoit toujours 404.
    """
    return _authorize_tenant(db, user, tenant_id).allows(accepted_roles)


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
    _authorize_tenant(db, current_user, restaurant_id)
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise _not_found()
    return restaurant


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
