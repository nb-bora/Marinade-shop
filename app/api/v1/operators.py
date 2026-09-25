from typing import List
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.core.database import get_db
from app.schemas.operator import (
    MobileOperatorPrefixCreate,
    MobileOperatorPrefixResponse,
    MobileOperatorPrefixUpdate,
)
from app.services.operator_service import OperatorService

router = APIRouter(
    prefix="/admin/mobile-operator-prefixes", tags=["mobile-operator-prefixes"]
)


@router.get("", response_model=List[MobileOperatorPrefixResponse])
def list_prefixes(db: Session = Depends(get_db), _: object = Depends(require_admin)):
    return OperatorService(db).list_prefixes(include_inactive=True)


@router.post(
    "", response_model=MobileOperatorPrefixResponse, status_code=status.HTTP_201_CREATED
)
def create_prefix(
    data: MobileOperatorPrefixCreate,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    try:
        return OperatorService(db).create_prefix(data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/{prefix_id}", response_model=MobileOperatorPrefixResponse)
def update_prefix(
    prefix_id: uuid.UUID,
    data: MobileOperatorPrefixUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    prefix = OperatorService(db).update_prefix(prefix_id, data)
    if not prefix:
        raise HTTPException(status_code=404, detail="Prefix not found")
    return prefix
