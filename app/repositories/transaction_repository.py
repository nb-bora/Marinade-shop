from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.transaction import Transaction, RefreshToken
from app.repositories.base import BaseRepository
import uuid


class TransactionRepository(BaseRepository[Transaction]):
    def __init__(self, db: Session):
        super().__init__(Transaction, db)

    def get_by_subscription_id(self, subscription_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[Transaction]:
        return self.db.query(Transaction).filter(
            Transaction.subscription_id == subscription_id
        ).offset(skip).limit(limit).all()

    def get_by_pos_transaction_id(self, pos_transaction_id: str) -> Optional[Transaction]:
        return self.db.query(Transaction).filter(Transaction.pos_transaction_id == pos_transaction_id).first()

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Transaction]:
        return self.db.query(Transaction).filter(Transaction.idempotency_key == idempotency_key).first()

    def idempotency_key_exists(self, idempotency_key: str) -> bool:
        return self.db.query(Transaction).filter(Transaction.idempotency_key == idempotency_key).first() is not None

    def pos_transaction_id_exists(self, pos_transaction_id: str) -> bool:
        return self.db.query(Transaction).filter(Transaction.pos_transaction_id == pos_transaction_id).first() is not None


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    def __init__(self, db: Session):
        super().__init__(RefreshToken, db)

    def get_by_token_hash(self, token_hash: str) -> Optional[RefreshToken]:
        return self.db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    def get_by_user_id(self, user_id: uuid.UUID) -> List[RefreshToken]:
        return self.db.query(RefreshToken).filter(RefreshToken.user_id == user_id).all()

    def delete_by_user_id(self, user_id: uuid.UUID) -> int:
        deleted = self.db.query(RefreshToken).filter(RefreshToken.user_id == user_id).delete()
        self.db.commit()
        return deleted

    def delete_expired_tokens(self) -> int:
        from datetime import datetime
        deleted = self.db.query(RefreshToken).filter(RefreshToken.expires_at < datetime.utcnow()).delete()
        self.db.commit()
        return deleted
