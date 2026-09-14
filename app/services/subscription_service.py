from typing import Optional, List
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from app.repositories.subscription_repository import (
    SubscriptionTierRepository,
    SubscriptionRepository,
    DailyBalanceRepository
)
from app.schemas.subscription import (
    SubscriptionTierCreate,
    SubscriptionCreate,
    DailyBalanceCreate
)
from app.models.subscription import Subscription, SubscriptionTier, DailyBalance
from app.utils.logging import get_logger
import uuid

logger = get_logger(__name__)


class SubscriptionService:
    def __init__(self, db: Session):
        self.db = db
        self.tier_repo = SubscriptionTierRepository(db)
        self.subscription_repo = SubscriptionRepository(db)
        self.balance_repo = DailyBalanceRepository(db)

    def create_tier(self, tier_data: SubscriptionTierCreate) -> SubscriptionTier:
        if self.tier_repo.get_by_name(tier_data.name):
            logger.warning(f"Tier name already exists: {tier_data.name}")
            raise ValueError("Tier name already exists")

        tier = self.tier_repo.create(tier_data.model_dump())
        logger.info(f"Subscription tier created: {tier.id}")
        return tier

    def get_tier(self, tier_id: int) -> Optional[SubscriptionTier]:
        return self.tier_repo.get(tier_id)

    def get_all_tiers(self) -> List[SubscriptionTier]:
        return self.tier_repo.get_active_tiers()

    def update_tier(self, tier_id: int, tier_data: dict) -> Optional[SubscriptionTier]:
        tier = self.tier_repo.get(tier_id)
        if not tier:
            logger.warning(f"Tier not found for update: {tier_id}")
            return None
        updated_tier = self.tier_repo.update(tier, tier_data)
        logger.info(f"Subscription tier updated: {tier_id}")
        return updated_tier

    def create_subscription(self, subscription_data: SubscriptionCreate) -> Subscription:
        # Check if user already has an active subscription
        existing_active = self.subscription_repo.get_active_subscription(subscription_data.user_id)
        if existing_active:
            logger.warning(f"User already has an active subscription: {subscription_data.user_id}")
            raise ValueError("User already has an active subscription")

        # Verify tier exists
        tier = self.tier_repo.get(subscription_data.tier_id)
        if not tier:
            logger.warning(f"Subscription tier not found: {subscription_data.tier_id}")
            raise ValueError("Subscription tier not found")

        subscription = self.subscription_repo.create(subscription_data.model_dump())
        logger.info(f"Subscription created: {subscription.id}")
        return subscription

    def get_subscription(self, subscription_id: uuid.UUID) -> Optional[Subscription]:
        return self.subscription_repo.get(str(subscription_id))

    def get_user_subscription(self, user_id: uuid.UUID) -> Optional[Subscription]:
        return self.subscription_repo.get_active_subscription(user_id)

    def update_subscription_status(self, subscription_id: uuid.UUID, status: str) -> Optional[Subscription]:
        subscription = self.subscription_repo.get(str(subscription_id))
        if not subscription:
            logger.warning(f"Subscription not found for status update: {subscription_id}")
            return None
        updated_subscription = self.subscription_repo.update(subscription, {"status": status})
        logger.info(f"Subscription status updated: {subscription_id} -> {status}")
        return updated_subscription

    def create_daily_balance(self, balance_data: DailyBalanceCreate) -> DailyBalance:
        # Check if balance already exists for this date
        existing = self.balance_repo.get_by_subscription_and_date(
            balance_data.subscription_id,
            balance_data.balance_date
        )
        if existing:
            logger.warning(f"Daily balance already exists for this date: {balance_data.balance_date}")
            raise ValueError("Daily balance already exists for this date")

        balance = self.balance_repo.create(balance_data.model_dump())
        logger.info(f"Daily balance created: {balance.id}")
        return balance

    def get_daily_balance(self, subscription_id: uuid.UUID, balance_date: date) -> Optional[DailyBalance]:
        return self.balance_repo.get_by_subscription_and_date(subscription_id, balance_date)

    def get_current_balance(self, subscription_id: uuid.UUID) -> Optional[DailyBalance]:
        return self.balance_repo.get_current_balance(subscription_id)

    def update_daily_balance(self, balance_id: uuid.UUID, used_amount: int) -> Optional[DailyBalance]:
        balance = self.balance_repo.get(str(balance_id))
        if not balance:
            logger.warning(f"Daily balance not found for update: {balance_id}")
            return None

        new_used = balance.used_balance_fcfa + used_amount
        if new_used > balance.initial_balance_fcfa:
            logger.warning(f"Insufficient balance for balance {balance_id}: {new_used} > {balance.initial_balance_fcfa}")
            raise ValueError("Insufficient balance")

        updated_balance = self.balance_repo.update(balance, {"used_balance_fcfa": new_used})
        logger.info(f"Daily balance updated: {balance_id}, used: {new_used}")
        return updated_balance

    def process_daily_reset(self, subscription_id: uuid.UUID) -> DailyBalance:
        subscription = self.subscription_repo.get(str(subscription_id))
        if not subscription:
            raise ValueError("Subscription not found")

        tier = self.tier_repo.get(subscription.tier_id)
        if not tier:
            raise ValueError("Tier not found")

        # Create new daily balance for today
        today = date.today()
        balance_data = DailyBalanceCreate(
            subscription_id=subscription_id,
            balance_date=today,
            initial_balance_fcfa=tier.daily_limit_fcfa,
            used_balance_fcfa=0
        )

        return self.create_daily_balance(balance_data)
