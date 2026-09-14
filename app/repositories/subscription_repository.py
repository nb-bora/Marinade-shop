from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.subscription import Subscription, SubscriptionTier, DailyBalance
from app.repositories.base import BaseRepository
import uuid


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

    def get_by_user_id(self, user_id: uuid.UUID) -> Optional[Subscription]:
        return self.db.query(Subscription).filter(Subscription.user_id == user_id).first()

    def get_active_subscription(self, user_id: uuid.UUID) -> Optional[Subscription]:
        return self.db.query(Subscription).filter(
            Subscription.user_id == user_id,
            Subscription.status == "active"
        ).first()

    def get_by_status(self, status: str, skip: int = 0, limit: int = 100) -> List[Subscription]:
        return self.db.query(Subscription).filter(Subscription.status == status).offset(skip).limit(limit).all()

    def get_by_tier_id(self, tier_id: int, skip: int = 0, limit: int = 100) -> List[Subscription]:
        return self.db.query(Subscription).filter(Subscription.tier_id == tier_id).offset(skip).limit(limit).all()


class DailyBalanceRepository(BaseRepository[DailyBalance]):
    def __init__(self, db: Session):
        super().__init__(DailyBalance, db)

    def get_by_subscription_and_date(self, subscription_id: uuid.UUID, balance_date) -> Optional[DailyBalance]:
        return self.db.query(DailyBalance).filter(
            DailyBalance.subscription_id == subscription_id,
            DailyBalance.balance_date == balance_date
        ).first()

    def get_by_subscription_id(self, subscription_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[DailyBalance]:
        return self.db.query(DailyBalance).filter(
            DailyBalance.subscription_id == subscription_id
        ).offset(skip).limit(limit).all()

    def get_current_balance(self, subscription_id: uuid.UUID) -> Optional[DailyBalance]:
        from datetime import date
        return self.get_by_subscription_and_date(subscription_id, date.today())
