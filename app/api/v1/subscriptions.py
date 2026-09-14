from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.services.subscription_service import SubscriptionService
from app.schemas.subscription import (
    SubscriptionTierResponse,
    SubscriptionTierCreate,
    SubscriptionTierUpdate,
    SubscriptionResponse,
    SubscriptionCreate,
    SubscriptionUpdate,
    DailyBalanceResponse,
    DailyBalanceCreate,
    DailyBalanceUpdate
)
from app.api.dependencies import get_current_user, require_admin
import uuid

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


# Subscription Tiers
@router.get("/tiers", response_model=List[SubscriptionTierResponse])
def get_tiers(db: Session = Depends(get_db)):
    subscription_service = SubscriptionService(db)
    return subscription_service.get_all_tiers()


@router.get("/tiers/{tier_id}", response_model=SubscriptionTierResponse)
def get_tier(tier_id: int, db: Session = Depends(get_db)):
    subscription_service = SubscriptionService(db)
    tier = subscription_service.get_tier(tier_id)
    if not tier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    return tier


@router.post("/tiers", response_model=SubscriptionTierResponse, status_code=status.HTTP_201_CREATED)
def create_tier(
    tier_data: SubscriptionTierCreate,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    try:
        return subscription_service.create_tier(tier_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/tiers/{tier_id}", response_model=SubscriptionTierResponse)
def update_tier(
    tier_id: int,
    tier_data: SubscriptionTierUpdate,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    try:
        tier = subscription_service.update_tier(tier_id, tier_data.model_dump(exclude_unset=True))
        if not tier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
        return tier
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Subscriptions
@router.get("/me", response_model=SubscriptionResponse)
def get_my_subscription(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    subscription = subscription_service.get_user_subscription(current_user.id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active subscription found")
    return subscription


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
def get_subscription(
    subscription_id: uuid.UUID,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    subscription = subscription_service.get_subscription(subscription_id)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    return subscription


@router.post("/", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
def create_subscription(
    subscription_data: SubscriptionCreate,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    try:
        return subscription_service.create_subscription(subscription_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{subscription_id}/status", response_model=SubscriptionResponse)
def update_subscription_status(
    subscription_id: uuid.UUID,
    status: str,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    subscription = subscription_service.update_subscription_status(subscription_id, status)
    if not subscription:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    return subscription


# Daily Balances
@router.get("/{subscription_id}/balances", response_model=List[DailyBalanceResponse])
def get_subscription_balances(
    subscription_id: uuid.UUID,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from app.repositories.subscription_repository import DailyBalanceRepository
    balance_repo = DailyBalanceRepository(db)
    return balance_repo.get_by_subscription_id(subscription_id)


@router.get("/{subscription_id}/balances/current", response_model=DailyBalanceResponse)
def get_current_balance(
    subscription_id: uuid.UUID,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    balance = subscription_service.get_current_balance(subscription_id)
    if not balance:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No current balance found")
    return balance


@router.post("/{subscription_id}/balances", response_model=DailyBalanceResponse, status_code=status.HTTP_201_CREATED)
def create_daily_balance(
    subscription_id: uuid.UUID,
    balance_data: DailyBalanceCreate,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    balance_data.subscription_id = subscription_id
    try:
        return subscription_service.create_daily_balance(balance_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{subscription_id}/reset", response_model=DailyBalanceResponse)
def reset_daily_balance(
    subscription_id: uuid.UUID,
    current_user = Depends(require_admin),
    db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    try:
        return subscription_service.process_daily_reset(subscription_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
