from datetime import datetime
from typing import Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select, func, and_, or_
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
            .order_by(RosCustomer.created_at, RosCustomer.id)
            .offset(skip)
            .limit(limit)
            .all()
        )


class ServiceSessionRepository(BaseRepository[ServiceSession]):
    def __init__(self, db: Session):
        super().__init__(ServiceSession, db)

    def get_active_sessions(
        self, restaurant_id: UUID, skip: int = 0, limit: int = 100
    ) -> List[ServiceSession]:
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
            .order_by(ServiceSession.opened_at, ServiceSession.id)
            .offset(skip)
            .limit(limit)
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
    OPEN = (TicketStatus.QUEUED.value, TicketStatus.IN_PREPARATION.value)

    def __init__(self, db: Session):
        super().__init__(ProductionTicket, db)

    def get_for_update(self, ticket_id: UUID) -> Optional[ProductionTicket]:
        """Ticket verrouillé jusqu'à la fin de la transaction : deux écrans qui
        cliquent en même temps ne peuvent pas se doubler (le second lit l'état
        déjà changé et reçoit un 409)."""
        return (
            self.db.query(ProductionTicket)
            .filter(ProductionTicket.id == ticket_id)
            .with_for_update()
            .populate_existing()
            .first()
        )

    def get_board(
        self,
        restaurant_id: UUID,
        station: str,
        *,
        window_start: datetime,
        ready_since: datetime,
        served_since: datetime,
        limit: int = 500,
    ) -> List[ProductionTicket]:
        """Tickets affichés sur l'écran d'un poste : à faire et en préparation créés
        dans la fenêtre, « Prêt » récents, et « Servi » encore rappelables. Tri : priorité,
        puis ancienneté."""
        return (
            self.db.query(ProductionTicket)
            .filter(
                ProductionTicket.restaurant_id == restaurant_id,
                ProductionTicket.station == station,
                or_(
                    and_(
                        ProductionTicket.status.in_(self.OPEN),
                        ProductionTicket.created_at >= window_start,
                    ),
                    and_(
                        ProductionTicket.status == TicketStatus.READY.value,
                        ProductionTicket.ready_at >= ready_since,
                    ),
                    and_(
                        ProductionTicket.status == TicketStatus.SERVED.value,
                        ProductionTicket.served_at >= served_since,
                    ),
                ),
            )
            .order_by(
                ProductionTicket.priority.desc(),
                ProductionTicket.created_at.asc(),
                ProductionTicket.id,
            )
            .limit(limit)
            .all()
        )

    def open_in_window(
        self, restaurant_id: UUID, station: str, window_start: datetime
    ) -> List[ProductionTicket]:
        """Tickets encore à faire, créés dans la fenêtre (base de la vue « tout le service »)."""
        return (
            self.db.query(ProductionTicket)
            .filter(
                ProductionTicket.restaurant_id == restaurant_id,
                ProductionTicket.station == station,
                ProductionTicket.status.in_(self.OPEN),
                ProductionTicket.created_at >= window_start,
            )
            .limit(5000)
            .all()
        )

    def open_older_than(
        self, restaurant_id: UUID, window_start: datetime
    ) -> List[ProductionTicket]:
        """Tickets encore à faire créés avant la fenêtre : ce sont des tickets périmés."""
        return (
            self.db.query(ProductionTicket)
            .filter(
                ProductionTicket.restaurant_id == restaurant_id,
                ProductionTicket.status.in_(self.OPEN),
                ProductionTicket.created_at < window_start,
            )
            .with_for_update()
            .all()
        )

    def open_for_session(self, session_id: UUID) -> List[ProductionTicket]:
        """Tickets encore à faire des commandes d'une session."""
        return (
            self.db.query(ProductionTicket)
            .join(RosOrder, RosOrder.id == ProductionTicket.order_id)
            .filter(
                RosOrder.session_id == session_id,
                ProductionTicket.status.in_(self.OPEN),
            )
            .with_for_update(of=ProductionTicket)
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

    def get_for_update(self, invoice_id: UUID) -> Optional[RosInvoice]:
        """Facture verrouillee jusqu'a la fin de la transaction, relue apres l'attente
        du verrou (populate_existing) pour ne pas calculer sur un montant perime."""
        return (
            self.db.query(RosInvoice)
            .filter(RosInvoice.id == invoice_id)
            .with_for_update()
            .populate_existing()
            .first()
        )


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
