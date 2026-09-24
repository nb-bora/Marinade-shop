from typing import Optional, List
from datetime import date
from sqlalchemy.orm import Session
import uuid

from app.models.subscription import Subscription, SubscriptionTier, DailyBalance
from app.repositories.base import BaseRepository


class SubscriptionTierRepository(BaseRepository[SubscriptionTier]):
    def __init__(self, db: Session):
        super().__init__(SubscriptionTier, db)

    def get_by_name(self, name: str) -> Optional[SubscriptionTier]:
        return self.db.query(SubscriptionTier).filter(SubscriptionTier.name == name).first()

    def get_active_tiers(self) -> List[SubscriptionTier]:
        return self.db.query(SubscriptionTier).filter(SubscriptionTier.is_active == True).all()


class SubscriptionRepository(BaseRepository[Subscription]):
    def __init__(self, db: Session):
        super().__init__(Subscription, db)

    def get_by_user_id(self, user_id: uuid.UUID, restaurant_id: uuid.UUID | None = None) -> Optional[Subscription]:
        query = self.db.query(Subscription).filter(Subscription.user_id == user_id)
        if restaurant_id is not None:
            query = query.filter(Subscription.restaurant_id == restaurant_id)
        return query.first()

    def get_active_subscription(self, user_id: uuid.UUID, restaurant_id: uuid.UUID | None = None) -> Optional[Subscription]:
        query = self.db.query(Subscription).filter(Subscription.user_id == user_id, Subscription.status == "active")
        if restaurant_id is not None:
            query = query.filter(Subscription.restaurant_id == restaurant_id)
        return query.first()

    def get_by_status(self, status: str, restaurant_id: uuid.UUID | None = None, skip: int = 0, limit: int = 100) -> List[Subscription]:
        query = self.db.query(Subscription).filter(Subscription.status == status)
        if restaurant_id is not None:
            query = query.filter(Subscription.restaurant_id == restaurant_id)
        return query.offset(skip).limit(limit).all()

    def get_by_tier_id(self, tier_id: int, restaurant_id: uuid.UUID | None = None, skip: int = 0, limit: int = 100) -> List[Subscription]:
        query = self.db.query(Subscription).filter(Subscription.tier_id == tier_id)
        if restaurant_id is not None:
            query = query.filter(Subscription.restaurant_id == restaurant_id)
        return query.offset(skip).limit(limit).all()


class DailyBalanceRepository(BaseRepository[DailyBalance]):
    def __init__(self, db: Session):
        super().__init__(DailyBalance, db)

    def get_by_subscription_and_date(self, subscription_id: uuid.UUID, balance_date) -> Optional[DailyBalance]:
        return self.db.query(DailyBalance).filter(DailyBalance.subscription_id == subscription_id, DailyBalance.balance_date == balance_date).first()

    def get_by_subscription_id(self, subscription_id: uuid.UUID, restaurant_id: uuid.UUID | None = None, skip: int = 0, limit: int = 100) -> List[DailyBalance]:
        query = self.db.query(DailyBalance).filter(DailyBalance.subscription_id == subscription_id)
        if restaurant_id is not None:
            query = query.filter(DailyBalance.restaurant_id == restaurant_id)
        return query.offset(skip).limit(limit).all()

    def get_current_balance(self, subscription_id: uuid.UUID, restaurant_id: uuid.UUID | None = None) -> Optional[DailyBalance]:
        balance = self.get_by_subscription_and_date(subscription_id, date.today())
        if balance is not None and restaurant_id is not None and balance.restaurant_id != restaurant_id:
            return None
        return balance

    def get_current_balance_for_update(self, subscription_id: uuid.UUID, restaurant_id: uuid.UUID | None = None) -> Optional[DailyBalance]:
        query = self.db.query(DailyBalance).filter(DailyBalance.subscription_id == subscription_id, DailyBalance.balance_date == date.today())
        if restaurant_id is not None:
            query = query.filter(DailyBalance.restaurant_id == restaurant_id)
        return query.with_for_update().first()
