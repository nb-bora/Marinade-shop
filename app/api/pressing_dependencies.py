"""Garde « cet établissement est un pressing », réutilisable par tout routeur pressing.

À placer APRÈS ``require_tenant_path`` dans les dépendances du routeur : l'appelant est alors
déjà reconnu comme membre du restaurant, la garde ne révèle donc rien à un étranger.

    router = APIRouter(
        prefix="/restaurants/{restaurant_id}/pressing",
        dependencies=[Depends(require_tenant_path), Depends(require_pressing)],
    )
"""

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.restaurant import Restaurant

TYPE_PRESSING = "pressing"
MESSAGE_PAS_UN_PRESSING = "Cet établissement n'est pas un pressing"


def require_pressing(restaurant_id: uuid.UUID, db: Session = Depends(get_db)) -> uuid.UUID:
    """404 « Cet établissement n'est pas un pressing » si le restaurant n'est pas de type pressing."""
    type_etablissement = (
        db.query(Restaurant.type_etablissement).filter(Restaurant.id == restaurant_id).scalar()
    )
    if type_etablissement != TYPE_PRESSING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=MESSAGE_PAS_UN_PRESSING)
    return restaurant_id
