from typing import Optional, List
from datetime import date
from sqlalchemy.orm import Session
import uuid

from app.models.restaurant import Restaurant
from app.models.subscription import DailyBalance, Subscription, SubscriptionTier
from app.repositories.subscription_repository import (
    DailyBalanceRepository,
    SubscriptionRepository,
    SubscriptionTierRepository,
)
from app.schemas.subscription import (
    DailyBalanceCreate,
    SubscriptionCreate,
    SubscriptionTierCreate,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)
VALID_STATUSES = {"pending", "active", "suspended", "cancelled", "expired"}


class SubscriptionService:
    def __init__(self, db: Session):
        self.db = db
        self.tier_repo = SubscriptionTierRepository(db)
        self.subscription_repo = SubscriptionRepository(db)
        self.balance_repo = DailyBalanceRepository(db)

    def create_tier(self, tier_data: SubscriptionTierCreate) -> SubscriptionTier:
        if self.tier_repo.get_by_name(tier_data.name):
            raise ValueError("Tier name already exists")
        return self.tier_repo.create(tier_data.model_dump())

    def get_tier(self, tier_id: int) -> Optional[SubscriptionTier]:
        return self.tier_repo.get(tier_id)

    def get_all_tiers(self) -> List[SubscriptionTier]:
        return self.tier_repo.get_active_tiers()

    def update_tier(self, tier_id: int, tier_data: dict) -> Optional[SubscriptionTier]:
        tier = self.tier_repo.get(tier_id)
        return self.tier_repo.update(tier, tier_data) if tier else None

    def create_subscription(
        self, subscription_data: SubscriptionCreate
    ) -> Subscription:
        restaurant = (
            self.db.query(Restaurant)
            .filter(Restaurant.id == subscription_data.restaurant_id)
            .first()
        )
        if not restaurant:
            raise ValueError("Restaurant not found")
        if self.subscription_repo.get_active_subscription(
            subscription_data.user_id, subscription_data.restaurant_id
        ):
            raise ValueError(
                "Restaurant already has an active subscription for this user"
            )
        if not self.tier_repo.get(subscription_data.tier_id):
            raise ValueError("Subscription tier not found")
        return self.subscription_repo.create(subscription_data.model_dump())

    def get_subscription(self, subscription_id: uuid.UUID) -> Optional[Subscription]:
        return self.subscription_repo.get(str(subscription_id))

    def get_user_subscription(
        self, user_id: uuid.UUID, restaurant_id: uuid.UUID | None = None
    ) -> Optional[Subscription]:
        return self.subscription_repo.get_active_subscription(user_id, restaurant_id)

    def update_subscription_status(
        self, subscription_id: uuid.UUID, status: str
    ) -> Optional[Subscription]:
        if status not in VALID_STATUSES:
            raise ValueError("Invalid subscription status")
        subscription = self.subscription_repo.get(str(subscription_id))
        return (
            self.subscription_repo.update(subscription, {"status": status})
            if subscription
            else None
        )

    def create_daily_balance(self, balance_data: DailyBalanceCreate) -> DailyBalance:
        subscription = self.subscription_repo.get(str(balance_data.subscription_id))
        if not subscription:
            raise ValueError("Subscription not found")
        if self.balance_repo.get_by_subscription_and_date(
            subscription.id, balance_data.balance_date
        ):
            raise ValueError("Daily balance already exists for this date")
        values = balance_data.model_dump()
        values["restaurant_id"] = subscription.restaurant_id
        return self.balance_repo.create(values)

    def get_daily_balance(
        self,
        subscription_id: uuid.UUID,
        balance_date: date,
        restaurant_id: uuid.UUID | None = None,
    ) -> Optional[DailyBalance]:
        balance = self.balance_repo.get_by_subscription_and_date(
            subscription_id, balance_date
        )
        if balance and restaurant_id and balance.restaurant_id != restaurant_id:
            return None
        return balance

    def get_current_balance(
        self, subscription_id: uuid.UUID, restaurant_id: uuid.UUID | None = None
    ) -> Optional[DailyBalance]:
        return self.balance_repo.get_current_balance(subscription_id, restaurant_id)

    def update_daily_balance(
        self, balance_id: uuid.UUID, used_amount: int
    ) -> Optional[DailyBalance]:
        balance = self.balance_repo.get(balance_id)
        if not balance:
            return None
        new_used = balance.used_balance_fcfa + used_amount
        if new_used > balance.initial_balance_fcfa:
            raise ValueError("Insufficient balance")
        return self.balance_repo.update(balance, {"used_balance_fcfa": new_used})

    def process_daily_reset(self, subscription_id: uuid.UUID) -> DailyBalance:
        subscription = self.subscription_repo.get(str(subscription_id))
        if not subscription:
            raise ValueError("Subscription not found")
        tier = self.tier_repo.get(subscription.tier_id)
        if not tier:
            raise ValueError("Tier not found")
        return self.create_daily_balance(
            DailyBalanceCreate(
                subscription_id=subscription_id,
                balance_date=date.today(),
                initial_balance_fcfa=tier.daily_limit_fcfa,
                used_balance_fcfa=0,
            )
        )
