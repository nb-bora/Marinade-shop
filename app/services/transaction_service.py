from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.subscription_repository import SubscriptionRepository, DailyBalanceRepository
from app.schemas.transaction import TransactionCreate
from app.models.transaction import Transaction
from app.utils.logging import get_logger
import uuid

logger = get_logger(__name__)


class TransactionService:
    def __init__(self, db: Session):
        self.db = db
        self.transaction_repo = TransactionRepository(db)
        self.subscription_repo = SubscriptionRepository(db)
        self.balance_repo = DailyBalanceRepository(db)

    def create_transaction(self, transaction_data: TransactionCreate) -> Transaction:
        # Check idempotency
        if self.transaction_repo.idempotency_key_exists(transaction_data.idempotency_key):
            existing = self.transaction_repo.get_by_idempotency_key(transaction_data.idempotency_key)
            logger.info(f"Returning existing transaction for idempotency key: {transaction_data.idempotency_key}")
            return existing

        # Check POS transaction ID uniqueness if provided
        if transaction_data.pos_transaction_id:
            if self.transaction_repo.pos_transaction_id_exists(transaction_data.pos_transaction_id):
                logger.warning(f"POS transaction ID already exists: {transaction_data.pos_transaction_id}")
                raise ValueError("POS transaction ID already exists")

        # Verify subscription exists and is active
        subscription = self.subscription_repo.get(str(transaction_data.subscription_id))
        if not subscription:
            logger.warning(f"Subscription not found: {transaction_data.subscription_id}")
            raise ValueError("Subscription not found")

        if subscription.status != "active":
            logger.warning(f"Subscription is not active: {transaction_data.subscription_id}")
            raise ValueError("Subscription is not active")

        # Check daily balance
        current_balance = self.balance_repo.get_current_balance(transaction_data.subscription_id)
        if not current_balance:
            logger.warning(f"No daily balance found for today: {transaction_data.subscription_id}")
            raise ValueError("No daily balance found for today")

        if current_balance.used_balance_fcfa + transaction_data.amount_fcfa > current_balance.initial_balance_fcfa:
            logger.warning(f"Insufficient daily balance for transaction: {transaction_data.subscription_id}")
            raise ValueError("Insufficient daily balance")

        # Create transaction
        transaction = self.transaction_repo.create(transaction_data.model_dump())

        # Update daily balance
        self.balance_repo.update(
            current_balance,
            {"used_balance_fcfa": current_balance.used_balance_fcfa + transaction_data.amount_fcfa}
        )

        logger.info(f"Transaction created successfully: {transaction.id}")
        return transaction

    def get_transaction(self, transaction_id: uuid.UUID) -> Optional[Transaction]:
        return self.transaction_repo.get(str(transaction_id))

    def get_subscription_transactions(self, subscription_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[Transaction]:
        return self.transaction_repo.get_by_subscription_id(subscription_id, skip, limit)

    def get_transaction_by_pos_id(self, pos_transaction_id: str) -> Optional[Transaction]:
        return self.transaction_repo.get_by_pos_transaction_id(pos_transaction_id)

    def get_user_transactions(self, user_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[Transaction]:
        subscription = self.subscription_repo.get_active_subscription(user_id)
        if not subscription:
            return []

        return self.transaction_repo.get_by_subscription_id(subscription.id, skip, limit)
