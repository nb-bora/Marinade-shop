import hashlib
import uuid
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session

from app.utils.exceptions import (
    ValidationError,
    NotFoundError,
    BusinessLogicError,
    ConflictError,
)
from app.utils.ros_enums import (
    CustomerType,
    SessionStatus,
    FulfillmentType,
    OrderChannel,
    RosOrderStatus,
    ProductionStation,
    TicketStatus,
    InvoiceStatus,
    RosPaymentMethod,
    CashShiftStatus,
)
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
from app.models.restaurant import (
    StockComposant,
    StockMouvement,
    CombinaisonComposant,
    Composant,
    Restaurant,
)


from app.repositories.ros_repository import (
    RosCustomerRepository,
    ServiceSessionRepository,
    RosOrderRepository,
    ProductionTicketRepository,
    RosInvoiceRepository,
    RosPaymentRepository,
    RosCashShiftRepository,
    RosAuditLogRepository,
)
from app.schemas.ros import (
    CustomerCreate,
    SessionCreate,
    OrderCreate,
    PaymentCreate,
    SplitPaymentRequest,
    ShiftOpenRequest,
    ShiftCloseRequest,
)


class RosService:
    def __init__(self, db: Session):
        self.db = db
        self.customer_repo = RosCustomerRepository(db)
        self.session_repo = ServiceSessionRepository(db)
        self.order_repo = RosOrderRepository(db)
        self.ticket_repo = ProductionTicketRepository(db)
        self.invoice_repo = RosInvoiceRepository(db)
        self.payment_repo = RosPaymentRepository(db)
        self.shift_repo = RosCashShiftRepository(db)
        self.audit_repo = RosAuditLogRepository(db)

    # -------------------------------------------------------------------------
    # CUSTOMER MANAGEMENT
    # -------------------------------------------------------------------------
    def create_customer(
        self, restaurant_id: uuid.UUID, data: CustomerCreate
    ) -> RosCustomer:
        customer_dict = data.model_dump()
        customer_dict["restaurant_id"] = restaurant_id
        customer = self.customer_repo.create(customer_dict)
        self.audit_repo.log_action(
            restaurant_id=restaurant_id,
            action="CREATE_CUSTOMER",
            entity_name="RosCustomer",
            entity_id=customer.id,
            after_state={"name": customer.name, "type": customer.customer_type},
        )
        return customer

    # -------------------------------------------------------------------------
    # SERVICE SESSION MANAGEMENT
    # -------------------------------------------------------------------------
    def open_session(
        self, restaurant_id: uuid.UUID, data: SessionCreate
    ) -> ServiceSession:
        session_dict = data.model_dump()
        session_dict["restaurant_id"] = restaurant_id
        session_dict["status"] = SessionStatus.OPEN.value

        session = self.session_repo.create(session_dict)
        self.audit_repo.log_action(
            restaurant_id=restaurant_id,
            action="OPEN_SESSION",
            entity_name="ServiceSession",
            entity_id=session.id,
            after_state={
                "table_context": session.table_context,
                "status": session.status,
            },
        )
        return session

    def get_active_sessions(self, restaurant_id: uuid.UUID) -> List[ServiceSession]:
        return self.session_repo.get_active_sessions(restaurant_id)

    def close_session(
        self,
        restaurant_id: uuid.UUID,
        session_id: uuid.UUID,
        actor_id: Optional[uuid.UUID] = None,
    ) -> ServiceSession:
        session = self.session_repo.get(str(session_id))
        if not session or session.restaurant_id != restaurant_id:
            raise NotFoundError(f"Session {session_id} introuvable")

        # Check invoice status if exists
        invoice = self.invoice_repo.get_by_session(session_id)
        if (
            invoice
            and invoice.amount_due > Decimal("0.00")
            and invoice.status != InvoiceStatus.PAID.value
        ):
            raise BusinessLogicError(
                f"Impossible de fermer la session {session_id}: solde restant dû de {invoice.amount_due} XAF"
            )

        updated_session = self.session_repo.update(
            session, {"status": SessionStatus.CLOSED.value, "closed_at": datetime.now()}
        )

        self.audit_repo.log_action(
            restaurant_id=restaurant_id,
            action="CLOSE_SESSION",
            entity_name="ServiceSession",
            entity_id=session.id,
            actor_id=actor_id,
            before_state={"status": session.status},
            after_state={"status": updated_session.status},
        )
        return updated_session

    # -------------------------------------------------------------------------
    # ORDER ENGINE & PRODUCTION ROUTING
    # -------------------------------------------------------------------------
    def create_order(self, restaurant_id: uuid.UUID, data: OrderCreate) -> RosOrder:
        # Idempotency Check
        if data.idempotency_key:
            existing_order = self.order_repo.get_by_idempotency_key(
                data.idempotency_key
            )
            if existing_order:
                return existing_order

        if not data.items:
            raise ValidationError("Une commande doit contenir au moins un article")

        # Calculate totals
        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")
        items_data = []

        for item in data.items:
            item_total = item.unit_price * Decimal(item.quantity)
            subtotal += item_total
            tax_amount = (item_total * item.tax_rate) / Decimal("100.00")
            tax_total += tax_amount
            items_data.append(item)

        total_amount = subtotal + tax_total

        # Determine Payment Policy
        # Prepaid for Takeaway/Delivery/Counter, Postpaid for Dine-In
        is_prepaid = data.fulfillment_type in [
            FulfillmentType.TAKEAWAY,
            FulfillmentType.DELIVERY,
            FulfillmentType.COUNTER,
        ]
        initial_status = (
            RosOrderStatus.PENDING_PAYMENT.value
            if is_prepaid
            else RosOrderStatus.CONFIRMED.value
        )

        idempotency_key = data.idempotency_key or uuid.uuid4()

        order_dict = {
            "restaurant_id": restaurant_id,
            "session_id": data.session_id,
            "customer_id": data.customer_id,
            "fulfillment_type": data.fulfillment_type.value,
            "order_channel": data.order_channel.value,
            "status": initial_status,
            "total_amount": total_amount,
            "idempotency_key": idempotency_key,
        }

        order = self.order_repo.create(order_dict)

        # Save order items & Deduct stock
        station_items: Dict[str, List[dict]] = {}
        for item in items_data:
            item_dict = item.model_dump()
            item_dict["order_id"] = order.id
            item_dict["destination_station"] = item.destination_station.value

            # Persist order item
            db_item = RosOrderItem(**item_dict)
            self.db.add(db_item)

            # Automatic ingredient stock deduction if product_id provided
            if item.product_id:
                self._process_stock_deduction(
                    restaurant_id, order.id, item.product_id, item.quantity
                )

            # Group items for production ticket routing
            station = item.destination_station.value
            if station not in station_items:
                station_items[station] = []
            station_items[station].append(
                {
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "notes": item.notes,
                }
            )

        self.db.flush()

        # Generate Production Tickets for each station if CONFIRMED
        if order.status == RosOrderStatus.CONFIRMED.value or not is_prepaid:
            for station, ticket_items in station_items.items():
                self.ticket_repo.create(
                    {
                        "restaurant_id": restaurant_id,
                        "order_id": order.id,
                        "station": station,
                        "status": TicketStatus.QUEUED.value,
                        "items_jsonb": ticket_items,
                    }
                )

        # Create or update Invoice
        self._ensure_invoice_for_order(
            restaurant_id, order, subtotal, tax_total, total_amount
        )

        self.audit_repo.log_action(
            restaurant_id=restaurant_id,
            action="CREATE_ORDER",
            entity_name="RosOrder",
            entity_id=order.id,
            after_state={"total_amount": str(total_amount), "status": order.status},
        )

        return order

    def _ensure_invoice_for_order(
        self,
        restaurant_id: uuid.UUID,
        order: RosOrder,
        subtotal: Decimal,
        tax_total: Decimal,
        total_amount: Decimal,
    ) -> RosInvoice:
        invoice = None
        if order.session_id:
            invoice = self.invoice_repo.get_by_session(order.session_id)

        if not invoice:
            inv_number = f"INV-{str(restaurant_id)[:8].upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
            fiscal_content = f"{inv_number}:{total_amount}:{datetime.now().isoformat()}"
            fiscal_hash = hashlib.sha256(fiscal_content.encode("utf-8")).hexdigest()

            invoice = self.invoice_repo.create(
                {
                    "restaurant_id": restaurant_id,
                    "session_id": order.session_id,
                    "order_id": order.id,
                    "invoice_number": inv_number,
                    "subtotal": subtotal,
                    "tax_amount": tax_total,
                    "service_charge": Decimal("0.00"),
                    "discount_amount": Decimal("0.00"),
                    "total_amount": total_amount,
                    "amount_paid": Decimal("0.00"),
                    "status": InvoiceStatus.ISSUED.value,
                    "fiscal_hash": fiscal_hash,
                }
            )
        else:
            # Update existing session invoice
            new_subtotal = invoice.subtotal + subtotal
            new_tax = invoice.tax_amount + tax_total
            new_total = invoice.total_amount + total_amount
            self.invoice_repo.update(
                invoice,
                {
                    "subtotal": new_subtotal,
                    "tax_amount": new_tax,
                    "total_amount": new_total,
                },
            )

        return invoice

    # -------------------------------------------------------------------------
    # PRODUCTION TICKETS (KDS / BAR DISPLAY)
    # -------------------------------------------------------------------------
    def get_pending_tickets(
        self, restaurant_id: uuid.UUID, station: ProductionStation
    ) -> List[ProductionTicket]:
        return self.ticket_repo.get_pending_by_station(restaurant_id, station.value)

    def update_ticket_status(
        self, restaurant_id: uuid.UUID, ticket_id: uuid.UUID, new_status: TicketStatus
    ) -> ProductionTicket:
        ticket = self.ticket_repo.get(str(ticket_id))
        if not ticket or ticket.restaurant_id != restaurant_id:
            raise NotFoundError(f"Ticket {ticket_id} introuvable")

        update_fields = {"status": new_status.value}
        if new_status == TicketStatus.READY:
            update_fields["ready_at"] = datetime.now()

        updated_ticket = self.ticket_repo.update(ticket, update_fields)
        return updated_ticket

    # -------------------------------------------------------------------------
    # PAYMENT PROCESSING & SPLIT BILL
    # -------------------------------------------------------------------------
    def process_payment(
        self, restaurant_id: uuid.UUID, data: PaymentCreate
    ) -> RosPaymentTransaction:
        # Idempotency check
        if data.idempotency_key:
            existing_pay = self.payment_repo.get_by_idempotency_key(
                data.idempotency_key
            )
            if existing_pay:
                return existing_pay

        invoice = self.invoice_repo.get(str(data.invoice_id))
        if not invoice or invoice.restaurant_id != restaurant_id:
            raise NotFoundError(f"Facture {data.invoice_id} introuvable")

        idempotency_key = data.idempotency_key or uuid.uuid4()

        pay_dict = {
            "restaurant_id": restaurant_id,
            "invoice_id": invoice.id,
            "payment_method": data.payment_method.value,
            "amount": data.amount,
            "status": "SUCCEEDED",
            "external_reference": data.external_reference,
            "idempotency_key": idempotency_key,
        }

        payment = self.payment_repo.create(pay_dict)

        # Update invoice amount paid
        new_paid = invoice.amount_paid + data.amount
        invoice_status = (
            InvoiceStatus.PAID.value
            if new_paid >= invoice.total_amount
            else InvoiceStatus.PARTIALLY_PAID.value
        )

        self.invoice_repo.update(
            invoice, {"amount_paid": new_paid, "status": invoice_status}
        )

        # If order was pending payment, release to production tickets
        if invoice.order_id:
            order = self.order_repo.get(str(invoice.order_id))
            if order and order.status == RosOrderStatus.PENDING_PAYMENT.value:
                self.order_repo.update(
                    order, {"status": RosOrderStatus.CONFIRMED.value}
                )
                # Dispatch tickets if not already created
                self._dispatch_deferred_tickets(restaurant_id, order)

        # If session is associated and fully paid, update session status
        if invoice.session_id:
            session = self.session_repo.get(str(invoice.session_id))
            if session:
                new_session_status = (
                    SessionStatus.SETTLED.value
                    if invoice_status == InvoiceStatus.PAID.value
                    else SessionStatus.PARTIALLY_PAID.value
                )
                self.session_repo.update(session, {"status": new_session_status})

        self.audit_repo.log_action(
            restaurant_id=restaurant_id,
            action="PROCESS_PAYMENT",
            entity_name="RosPaymentTransaction",
            entity_id=payment.id,
            after_state={
                "amount": str(data.amount),
                "method": data.payment_method.value,
            },
        )

        return payment

    def process_split_payment(
        self, restaurant_id: uuid.UUID, data: SplitPaymentRequest
    ) -> List[RosPaymentTransaction]:
        results = []
        for idx, item in enumerate(data.payments):
            item_idempotency = uuid.uuid4()
            if data.idempotency_key:
                # Namespace each split item idempotency key deterministically
                item_idempotency = uuid.uuid5(data.idempotency_key, f"split-{idx}")

            pay_create = PaymentCreate(
                invoice_id=data.invoice_id,
                payment_method=item.payment_method,
                amount=item.amount,
                external_reference=item.external_reference,
                idempotency_key=item_idempotency,
            )
            pay_txn = self.process_payment(restaurant_id, pay_create)
            results.append(pay_txn)
        return results

    def _dispatch_deferred_tickets(self, restaurant_id: uuid.UUID, order: RosOrder):
        items = (
            self.db.query(RosOrderItem).filter(RosOrderItem.order_id == order.id).all()
        )
        station_items: Dict[str, List[dict]] = {}
        for item in items:
            station = item.destination_station
            if station not in station_items:
                station_items[station] = []
            station_items[station].append(
                {
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "notes": item.notes,
                }
            )

        for station, t_items in station_items.items():
            self.ticket_repo.create(
                {
                    "restaurant_id": restaurant_id,
                    "order_id": order.id,
                    "station": station,
                    "status": TicketStatus.QUEUED.value,
                    "items_jsonb": t_items,
                }
            )

    # -------------------------------------------------------------------------
    # CASH SHIFT MANAGEMENT
    # -------------------------------------------------------------------------
    def open_shift(
        self,
        restaurant_id: uuid.UUID,
        operator_user_id: uuid.UUID,
        data: ShiftOpenRequest,
    ) -> RosCashShift:
        active_shift = self.shift_repo.get_active_shift(restaurant_id, operator_user_id)
        if active_shift:
            raise ConflictError("Un shift de caisse est déjà ouvert pour cet opérateur")

        shift = self.shift_repo.create(
            {
                "restaurant_id": restaurant_id,
                "operator_user_id": operator_user_id,
                "opening_balance": data.opening_balance,
                "status": CashShiftStatus.OPEN.value,
            }
        )

        self.audit_repo.log_action(
            restaurant_id=restaurant_id,
            action="OPEN_CASH_SHIFT",
            entity_name="RosCashShift",
            entity_id=shift.id,
            actor_id=operator_user_id,
            after_state={"opening_balance": str(data.opening_balance)},
        )
        return shift

    def close_shift(
        self,
        restaurant_id: uuid.UUID,
        operator_user_id: uuid.UUID,
        data: ShiftCloseRequest,
    ) -> RosCashShift:
        shift = self.shift_repo.get_active_shift(restaurant_id, operator_user_id)
        if not shift:
            raise NotFoundError(
                "Aucun shift de caisse ouvert trouvé pour cet opérateur"
            )

        # Calculate expected cash sales during shift
        cash_sales = (
            self.db.query(RosPaymentTransaction)
            .filter(
                RosPaymentTransaction.restaurant_id == restaurant_id,
                RosPaymentTransaction.payment_method == RosPaymentMethod.CASH.value,
                RosPaymentTransaction.created_at >= shift.opened_at,
                RosPaymentTransaction.status == "SUCCEEDED",
            )
            .all()
        )

        total_cash_sales = sum([p.amount for p in cash_sales], Decimal("0.00"))
        expected_closing = shift.opening_balance + total_cash_sales
        variance = data.closing_balance_counted - expected_closing

        closed_shift = self.shift_repo.update(
            shift,
            {
                "closing_balance_expected": expected_closing,
                "closing_balance_counted": data.closing_balance_counted,
                "variance": variance,
                "status": CashShiftStatus.CLOSED.value,
                "closed_at": datetime.now(),
            },
        )

        self.audit_repo.log_action(
            restaurant_id=restaurant_id,
            action="CLOSE_CASH_SHIFT",
            entity_name="RosCashShift",
            entity_id=shift.id,
            actor_id=operator_user_id,
            after_state={
                "expected": str(expected_closing),
                "counted": str(data.closing_balance_counted),
                "variance": str(variance),
            },
            reason=f"Shift caisse fermé avec écart de {variance} XAF"
            if variance != Decimal("0.00")
            else "Shift fermé sans écart",
        )

        return closed_shift

    # -------------------------------------------------------------------------
    # OFFLINE SYNC BATCH REPLAY
    # -------------------------------------------------------------------------
    def sync_offline_batch(
        self,
        restaurant_id: uuid.UUID,
        orders: List[OrderCreate],
        payments: List[PaymentCreate],
    ) -> Dict[str, Any]:
        processed_orders = 0
        processed_payments = 0
        errors = []

        for ord_data in orders:
            try:
                self.create_order(restaurant_id, ord_data)
                processed_orders += 1
            except Exception as e:
                errors.append(
                    {
                        "type": "order",
                        "idempotency_key": str(ord_data.idempotency_key),
                        "error": str(e),
                    }
                )

        for pay_data in payments:
            try:
                self.process_payment(restaurant_id, pay_data)
                processed_payments += 1
            except Exception as e:
                errors.append(
                    {
                        "type": "payment",
                        "idempotency_key": str(pay_data.idempotency_key),
                        "error": str(e),
                    }
                )

        return {
            "processed_orders": processed_orders,
            "processed_payments": processed_payments,
            "errors": errors,
        }

    # -------------------------------------------------------------------------
    # STOCK & INVENTORY DEDUCTION HELPER
    # -------------------------------------------------------------------------
    def _process_stock_deduction(
        self,
        restaurant_id: uuid.UUID,
        order_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: int,
    ):
        if not product_id:
            return

        # Check if product_id has multi-ingredient technical card (CombinaisonComposant)
        sub_components = (
            self.db.query(CombinaisonComposant)
            .filter(CombinaisonComposant.combinaison_id == product_id)
            .all()
        )
        if sub_components:
            for sub in sub_components:
                ingredient_qty = sub.quantite * Decimal(quantity)
                self._deduct_single_component_stock(
                    restaurant_id, order_id, sub.composant_id, ingredient_qty
                )
        else:
            self._deduct_single_component_stock(
                restaurant_id, order_id, product_id, Decimal(quantity)
            )

    def _deduct_single_component_stock(
        self,
        restaurant_id: uuid.UUID,
        order_id: uuid.UUID,
        composant_id: uuid.UUID,
        qty_dec: Decimal,
    ):
        stock = (
            self.db.query(StockComposant)
            .filter(StockComposant.composant_id == composant_id)
            .first()
        )
        if stock:
            stock.quantite -= qty_dec

            mouvement = StockMouvement(
                composant_id=composant_id,
                type="SORTIE",
                quantite=qty_dec,
                reference_type="ROS_ORDER",
                reference_id=order_id,
                notes=f"Consommation automatique pour la commande ROS {order_id}",
            )
            self.db.add(mouvement)

            if stock.quantite <= stock.seuil_alerte:
                self.audit_repo.log_action(
                    restaurant_id=restaurant_id,
                    action="STOCK_ALERT_LOW",
                    entity_name="StockComposant",
                    entity_id=stock.id,
                    after_state={
                        "quantite": str(stock.quantite),
                        "seuil_alerte": str(stock.seuil_alerte),
                    },
                    reason=f"Stock sous le seuil d'alerte suite à la commande ROS {order_id}",
                )

    # -------------------------------------------------------------------------
    # AUTO-PROCUREMENT ENGINE
    # -------------------------------------------------------------------------
    def generate_procurement_suggestions(
        self, restaurant_id: uuid.UUID
    ) -> Dict[str, Any]:
        stocks = (
            self.db.query(StockComposant)
            .join(Composant)
            .filter(
                Composant.restaurant_id == restaurant_id,
                StockComposant.quantite <= StockComposant.seuil_alerte,
            )
            .all()
        )

        items = []
        for s in stocks:
            comp = (
                self.db.query(Composant).filter(Composant.id == s.composant_id).first()
            )
            comp_name = comp.nom if comp else "Composant Inconnu"
            unit = comp.stock_unite if comp else "portion"
            suggested = max(
                (s.seuil_alerte * Decimal("2.0")) - s.quantite, Decimal("1.0")
            )

            items.append(
                {
                    "composant_id": s.composant_id,
                    "composant_name": comp_name,
                    "current_stock": s.quantite,
                    "seuil_alerte": s.seuil_alerte,
                    "suggested_order_qty": suggested,
                    "unit": unit,
                }
            )

        return {
            "restaurant_id": restaurant_id,
            "generated_at": datetime.now(),
            "items": items,
        }

    # -------------------------------------------------------------------------
    # MULTI-SITE GROUP REPORTING ENGINE
    # -------------------------------------------------------------------------
    def get_group_consolidated_reporting(self, user_id: uuid.UUID) -> Dict[str, Any]:
        user_restaurants = (
            self.db.query(Restaurant).filter(Restaurant.user_id == user_id).all()
        )
        rest_ids = [r.id for r in user_restaurants]

        if not rest_ids:
            return {
                "total_restaurants": 0,
                "total_revenue": Decimal("0.00"),
                "total_orders": 0,
                "revenue_by_channel": {},
                "payment_method_breakdown": {},
            }

        invoices = (
            self.db.query(RosInvoice)
            .filter(
                RosInvoice.restaurant_id.in_(rest_ids),
                RosInvoice.status == InvoiceStatus.PAID.value,
            )
            .all()
        )

        total_revenue = sum([inv.total_amount for inv in invoices], Decimal("0.00"))

        orders = (
            self.db.query(RosOrder).filter(RosOrder.restaurant_id.in_(rest_ids)).all()
        )

        total_orders = len(orders)
        revenue_by_channel: Dict[str, Decimal] = {}
        for ord_obj in orders:
            ch = ord_obj.order_channel
            revenue_by_channel[ch] = (
                revenue_by_channel.get(ch, Decimal("0.00")) + ord_obj.total_amount
            )

        payments = (
            self.db.query(RosPaymentTransaction)
            .filter(
                RosPaymentTransaction.restaurant_id.in_(rest_ids),
                RosPaymentTransaction.status == "SUCCEEDED",
            )
            .all()
        )

        pay_breakdown: Dict[str, Decimal] = {}
        for p in payments:
            pm = p.payment_method
            pay_breakdown[pm] = pay_breakdown.get(pm, Decimal("0.00")) + p.amount

        return {
            "total_restaurants": len(user_restaurants),
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "revenue_by_channel": revenue_by_channel,
            "payment_method_breakdown": pay_breakdown,
        }
