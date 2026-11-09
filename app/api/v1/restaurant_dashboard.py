"""Tableau de bord du restaurant (propriétaire / manager)."""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import permissions as perm
from app.api.dependencies import get_current_user, require_tenant_path
from app.core.database import get_db
from app.models.user import User
from app.schemas.restaurant_dashboard import RestoDashboardResponse
from app.services.restaurant_dashboard_service import RestaurantDashboardService

router = APIRouter(
    prefix="/ros",
    tags=["restaurant-dashboard"],
    dependencies=[Depends(require_tenant_path)],
)


@router.get(
    "/restaurants/{restaurant_id}/dashboard",
    response_model=RestoDashboardResponse,
    dependencies=[Depends(perm.MANAGEMENT)],
    summary="Tableau de bord du jour : chiffre d'affaires, salle, cuisine, réservations, stock, alertes",
)
def restaurant_dashboard(
    restaurant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return RestaurantDashboardService(db).build(restaurant_id)
