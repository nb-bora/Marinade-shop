from typing import Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_
from app.repositories.base import BaseRepository
from app.models.ros import (
    RosCustomer,
    ServiceSession,
    RosOrder,
    RosOrderItem,
    ProductionTicket,
    RosInvoice,
    RosPaymentTransaction,
    RosCashShift,
    RosAuditLog,
)
from app.utils.ros_enums import (
    SessionStatus,
    RosOrderStatus,
    TicketStatus,
    InvoiceStatus,
    CashShiftStatus,
)


class RosCustomerRepository(BaseRepository[RosCustomer]):
    def __init__(self, db: Session):
        super().__init__(RosCustomer, db)

    def get_by_restaurant(
        self, restaurant_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[RosCustomer]:
        return (
            self.db.query(RosCustomer)
            .filter(RosCustomer.restaurant_id == restaurant_id)
            .offset(skip)
            .limit(limit)
            .all()
        )


class ServiceSessionRepository(BaseRepository[ServiceSession]):
    def __init__(self, db: Session):
        super().__init__(ServiceSession, db)

    def get_active_sessions(self, restaurant_id: UUID) -> List[ServiceSession]:
        return (
            self.db.query(ServiceSession)
            .filter(
                ServiceSession.restaurant_id == restaurant_id,
                ServiceSession.status.in_(
                    [
                        SessionStatus.OPEN.value,
                        SessionStatus.ACTIVE.value,
                        SessionStatus.PAYMENT_PENDING.value,
                        SessionStatus.PARTIALLY_PAID.value,
                    ]
                ),
            )
            .all()
        )

    def get_session_by_table(
        self, restaurant_id: UUID, table_id: UUID
    ) -> Optional[ServiceSession]:
        return (
            self.db.query(ServiceSession)
            .filter(
                ServiceSession.restaurant_id == restaurant_id,
                ServiceSession.table_id == table_id,
                ServiceSession.status != SessionStatus.CLOSED.value,
            )
            .order_by(ServiceSession.opened_at.desc())
            .first()
        )


class RosOrderRepository(BaseRepository[RosOrder]):
    def __init__(self, db: Session):
        super().__init__(RosOrder, db)

    def get_by_idempotency_key(self, idempotency_key: UUID) -> Optional[RosOrder]:
        return (
            self.db.query(RosOrder)
            .filter(RosOrder.idempotency_key == idempotency_key)
            .first()
        )

    def get_by_session(self, session_id: UUID) -> List[RosOrder]:
        return self.db.query(RosOrder).filter(RosOrder.session_id == session_id).all()

    def get_by_restaurant(
        self, restaurant_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[RosOrder]:
        return (
            self.db.query(RosOrder)
            .filter(RosOrder.restaurant_id == restaurant_id)
            .order_by(RosOrder.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )


class ProductionTicketRepository(BaseRepository[ProductionTicket]):
    def __init__(self, db: Session):
        super().__init__(ProductionTicket, db)

    def get_pending_by_station(
        self, restaurant_id: UUID, station: str
    ) -> List[ProductionTicket]:
        return (
            self.db.query(ProductionTicket)
            .filter(
                ProductionTicket.restaurant_id == restaurant_id,
                ProductionTicket.station == station,
                ProductionTicket.status.in_(
                    [TicketStatus.QUEUED.value, TicketStatus.IN_PREPARATION.value]
                ),
            )
            .order_by(ProductionTicket.created_at.asc())
            .all()
        )


class RosInvoiceRepository(BaseRepository[RosInvoice]):
    def __init__(self, db: Session):
        super().__init__(RosInvoice, db)

    def get_by_number(self, invoice_number: str) -> Optional[RosInvoice]:
        return (
            self.db.query(RosInvoice)
            .filter(RosInvoice.invoice_number == invoice_number)
            .first()
        )

    def get_by_session(self, session_id: UUID) -> Optional[RosInvoice]:
        return (
            self.db.query(RosInvoice)
            .filter(RosInvoice.session_id == session_id)
            .first()
        )

    def get_by_order(self, order_id: UUID) -> Optional[RosInvoice]:
        return self.db.query(RosInvoice).filter(RosInvoice.order_id == order_id).first()


class RosPaymentRepository(BaseRepository[RosPaymentTransaction]):
    def __init__(self, db: Session):
        super().__init__(RosPaymentTransaction, db)

    def get_by_idempotency_key(
        self, idempotency_key: UUID
    ) -> Optional[RosPaymentTransaction]:
        return (
            self.db.query(RosPaymentTransaction)
            .filter(RosPaymentTransaction.idempotency_key == idempotency_key)
            .first()
        )

    def get_by_invoice(self, invoice_id: UUID) -> List[RosPaymentTransaction]:
        return (
            self.db.query(RosPaymentTransaction)
            .filter(RosPaymentTransaction.invoice_id == invoice_id)
            .all()
        )


class RosCashShiftRepository(BaseRepository[RosCashShift]):
    def __init__(self, db: Session):
        super().__init__(RosCashShift, db)

    def get_active_shift(
        self, restaurant_id: UUID, operator_user_id: UUID
    ) -> Optional[RosCashShift]:
        return (
            self.db.query(RosCashShift)
            .filter(
                RosCashShift.restaurant_id == restaurant_id,
                RosCashShift.operator_user_id == operator_user_id,
                RosCashShift.status == CashShiftStatus.OPEN.value,
            )
            .first()
        )


class RosAuditLogRepository(BaseRepository[RosAuditLog]):
    def __init__(self, db: Session):
        super().__init__(RosAuditLog, db)

    def log_action(
        self,
        restaurant_id: UUID,
        action: str,
        entity_name: str,
        entity_id: UUID,
        actor_id: Optional[UUID] = None,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        reason: Optional[str] = None,
    ) -> RosAuditLog:
        return self.create(
            {
                "restaurant_id": restaurant_id,
                "actor_id": actor_id,
                "action": action,
                "entity_name": entity_name,
                "entity_id": entity_id,
                "before_state": before_state,
                "after_state": after_state,
                "reason": reason,
            }
        )
