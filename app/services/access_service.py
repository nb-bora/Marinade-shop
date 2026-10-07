"""Restaurants auxquels un utilisateur a accès, avec son rôle et ses capacités."""

from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import permissions
from app.api.dependencies import TenantAccess, _effective_roles
from app.models.user import User
from app.schemas.user import RestaurantAccess

# Une seule requête, bornée : la RLS ne laisse voir que les restaurants de
# l'utilisateur (propriétaire ou membre actif) ; un administrateur voit tout.
_ACCESS_LIST_SQL = text(
    """
    SELECT r.id, r.name, r.city, r.currency,
           (r.user_id = CAST(:user AS uuid)) AS is_owner,
           (m.id IS NOT NULL) AS is_member,
           m.role AS role, m.staff_role AS staff_role
    FROM restaurants r
    LEFT JOIN restaurant_members m
           ON m.restaurant_id = r.id
          AND m.user_id = CAST(:user AS uuid)
          AND m.is_active
    WHERE r.is_active
      AND (:is_admin OR r.user_id = CAST(:user AS uuid) OR m.id IS NOT NULL)
      AND (CAST(:pattern AS text) IS NULL
           OR r.name ILIKE CAST(:pattern AS text) ESCAPE '\\')
    ORDER BY r.name, r.id
    LIMIT :limit
    """
)


def _like_pattern(query: Optional[str]) -> Optional[str]:
    if not query or not query.strip():
        return None
    escaped = (
        query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return f"%{escaped}%"


class AccessService:
    def __init__(self, db: Session):
        self.db = db

    def list_for(
        self, user: User, *, query: Optional[str] = None, limit: int = 50
    ) -> List[RestaurantAccess]:
        is_admin = user.role == "admin"
        rows = self.db.execute(
            _ACCESS_LIST_SQL,
            {
                "user": str(user.id),
                "is_admin": is_admin,
                "pattern": _like_pattern(query),
                "limit": limit,
            },
        ).all()
        items = []
        for row in rows:
            roles = (
                _effective_roles(row.staff_role, row.role)
                if row.is_member
                else frozenset()
            )
            access = TenantAccess(
                row.id,
                is_admin=is_admin,
                is_owner=bool(row.is_owner),
                is_member=bool(row.is_member),
                roles=roles,
            )
            if row.is_owner:
                relation, shown = "owner", ["owner"]
            elif row.is_member:
                relation, shown = "member", sorted(roles)
            else:
                relation, shown = "platform_admin", []
            items.append(
                RestaurantAccess(
                    restaurant_id=row.id,
                    name=row.name,
                    city=row.city,
                    currency=row.currency,
                    relation=relation,
                    roles=shown,
                    capabilities=permissions.capabilities_of(access),
                )
            )
        return items
