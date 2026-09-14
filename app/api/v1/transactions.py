from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.services.transaction_service import TransactionService
from app.schemas.transaction import TransactionResponse, TransactionCreate
from app.api.dependencies import get_current_user, require_pos
import uuid

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(
    transaction_data: TransactionCreate,
    current_user = Depends(require_pos),
    db: Session = Depends(get_db)
):
    transaction_service = TransactionService(db)
    try:
        return transaction_service.create_transaction(transaction_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/subscription/{subscription_id}", response_model=List[TransactionResponse])
def get_subscription_transactions(
    subscription_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    transaction_service = TransactionService(db)
    return transaction_service.get_subscription_transactions(subscription_id, skip, limit)


@router.get("/pos/{pos_transaction_id}", response_model=TransactionResponse)
def get_transaction_by_pos_id(
    pos_transaction_id: str,
    current_user = Depends(require_pos),
    db: Session = Depends(get_db)
):
    transaction_service = TransactionService(db)
    transaction = transaction_service.get_transaction_by_pos_id(pos_transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return transaction


@router.get("/my", response_model=List[TransactionResponse])
def get_my_transactions(
    skip: int = 0,
    limit: int = 100,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    transaction_service = TransactionService(db)
    return transaction_service.get_user_transactions(current_user.id, skip, limit)


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: uuid.UUID,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    transaction_service = TransactionService(db)
    transaction = transaction_service.get_transaction(transaction_id)
    if not transaction:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return transaction
