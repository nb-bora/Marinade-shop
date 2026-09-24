from typing import Optional, List
from sqlalchemy.orm import Session
import uuid

from app.models.transaction import Transaction
from app.repositories.subscription_repository import DailyBalanceRepository, SubscriptionRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.transaction import TransactionCreate
from app.utils.logging import get_logger

logger = get_logger(__name__)


class TransactionService:
    def __init__(self, db: Session):
        self.db = db
        self.transaction_repo = TransactionRepository(db)
        self.subscription_repo = SubscriptionRepository(db)
        self.balance_repo = DailyBalanceRepository(db)

    def create_transaction(self, transaction_data: TransactionCreate) -> Transaction:
        existing = self.transaction_repo.get_by_idempotency_key(transaction_data.idempotency_key, transaction_data.restaurant_id)
        if existing:
            return existing
        if transaction_data.pos_transaction_id and self.transaction_repo.pos_transaction_id_exists(transaction_data.pos_transaction_id, transaction_data.restaurant_id):
            raise ValueError("POS transaction ID already exists")
        subscription = self.subscription_repo.get(str(transaction_data.subscription_id))
        if not subscription or subscription.restaurant_id != transaction_data.restaurant_id or subscription.status != "active":
            raise ValueError("Subscription is not active for this restaurant")
        balance = self.balance_repo.get_current_balance_for_update(transaction_data.subscription_id, transaction_data.restaurant_id)
        if not balance:
            raise ValueError("No daily balance found for today")
        if balance.used_balance_fcfa + transaction_data.amount_fcfa > balance.initial_balance_fcfa:
            raise ValueError("Insufficient daily balance")
        transaction = self.transaction_repo.create(transaction_data.model_dump())
        balance.used_balance_fcfa += transaction_data.amount_fcfa
        self.db.flush()
        return transaction

    def get_transaction(self, transaction_id: uuid.UUID) -> Optional[Transaction]:
        return self.transaction_repo.get(str(transaction_id))

    def get_subscription_transactions(self, subscription_id: uuid.UUID, restaurant_id: uuid.UUID | None = None, skip: int = 0, limit: int = 100) -> List[Transaction]:
        return self.transaction_repo.get_by_subscription_id(subscription_id, restaurant_id, skip, limit)

    def get_transaction_by_pos_id(self, pos_transaction_id: str, restaurant_id: uuid.UUID | None = None) -> Optional[Transaction]:
        return self.transaction_repo.get_by_pos_transaction_id(pos_transaction_id, restaurant_id)

    def get_user_transactions(self, user_id: uuid.UUID, restaurant_id: uuid.UUID | None = None, skip: int = 0, limit: int = 100) -> List[Transaction]:
        subscription = self.subscription_repo.get_active_subscription(user_id, restaurant_id)
        if not subscription:
            return []
        return self.transaction_repo.get_by_subscription_id(subscription.id, restaurant_id or subscription.restaurant_id, skip, limit)
