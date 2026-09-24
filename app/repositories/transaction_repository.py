from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
import uuid

from app.models.transaction import Transaction, RefreshToken
from app.repositories.base import BaseRepository


class TransactionRepository(BaseRepository[Transaction]):
    def __init__(self, db: Session):
        super().__init__(Transaction, db)

    def get_by_subscription_id(self, subscription_id: uuid.UUID, restaurant_id: uuid.UUID | None = None, skip: int = 0, limit: int = 100) -> List[Transaction]:
        query = self.db.query(Transaction).filter(Transaction.subscription_id == subscription_id)
        if restaurant_id is not None:
            query = query.filter(Transaction.restaurant_id == restaurant_id)
        return query.offset(skip).limit(limit).all()

    def get_by_pos_transaction_id(self, pos_transaction_id: str, restaurant_id: uuid.UUID | None = None) -> Optional[Transaction]:
        query = self.db.query(Transaction).filter(Transaction.pos_transaction_id == pos_transaction_id)
        if restaurant_id is not None:
            query = query.filter(Transaction.restaurant_id == restaurant_id)
        return query.first()

    def get_by_idempotency_key(self, idempotency_key: str, restaurant_id: uuid.UUID | None = None) -> Optional[Transaction]:
        query = self.db.query(Transaction).filter(Transaction.idempotency_key == idempotency_key)
        if restaurant_id is not None:
            query = query.filter(Transaction.restaurant_id == restaurant_id)
        return query.first()

    def pos_transaction_id_exists(self, pos_transaction_id: str, restaurant_id: uuid.UUID | None = None) -> bool:
        return self.get_by_pos_transaction_id(pos_transaction_id, restaurant_id) is not None


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    def __init__(self, db: Session):
        super().__init__(RefreshToken, db)

    def get_by_token_hash(self, token_hash: str) -> Optional[RefreshToken]:
        return self.db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    def get_by_user_id(self, user_id: uuid.UUID) -> List[RefreshToken]:
        return self.db.query(RefreshToken).filter(RefreshToken.user_id == user_id).all()

    def delete_by_user_id(self, user_id: uuid.UUID) -> int:
        deleted = self.db.query(RefreshToken).filter(RefreshToken.user_id == user_id).delete(synchronize_session=False)
        self.db.flush()
        return deleted

    def delete_expired_tokens(self) -> int:
        deleted = self.db.query(RefreshToken).filter(RefreshToken.expires_at < datetime.now(timezone.utc)).delete(synchronize_session=False)
        self.db.flush()
        return deleted
