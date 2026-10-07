import hashlib
import uuid
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime
from decimal import ROUND_HALF_UP
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.utils.exceptions import (
    AuthorizationError,
    ValidationError,
    NotFoundError,
    BusinessLogicError,
    ConflictError,
    MarinadeException,
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
from app.core.database import get_db_context, set_db_context
from app.services.stock_engine import StockEngine, requirements_to_json
from app.services.stock_requirements import (
    ProductLine,
    classify_products,
    requirements_for,
)
from app.models.restaurant import (
    StockComposant,
    StockMouvement,
    CombinaisonComposant,
    Composant,
    Restaurant,
    Table,
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
        self.stock_engine = StockEngine(db)

    # -------------------------------------------------------------------------
    # CUSTOMER MANAGEMENT
    # -------------------------------------------------------------------------
    def _ensure_references_belong_to(
        self,
        restaurant_id: uuid.UUID,
        *,
        session_id: Optional[uuid.UUID] = None,
        customer_id: Optional[uuid.UUID] = None,
        table_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Reject ids taken from a request body that belong to another restaurant.

        A foreign key only proves a row exists. Without this check a user who is
        authorized on restaurant A could attach restaurant B's session, customer
        or table to their own order just by knowing the UUID.
        """
        checks = (
            (session_id, self.session_repo.get, "session"),
            (customer_id, self.customer_repo.get, "customer"),
            (table_id, lambda pk: self.db.get(Table, pk), "table"),
        )
        for reference, load, label in checks:
            if reference is None:
                continue
            row = load(str(reference) if label != "table" else reference)
            if row is None or row.restaurant_id != restaurant_id:
                raise ValidationError(f"Invalid {label} for this restaurant")

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
        self._ensure_references_belong_to(
            restaurant_id, customer_id=data.customer_id, table_id=data.table_id
        )
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

    def get_active_sessions(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[ServiceSession]:
        return self.session_repo.get_active_sessions(restaurant_id, skip, limit)

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
    DEFAULT_VAT_RATE = Decimal("19.25")
    CENT = Decimal("0.01")

    def _vat_rate(self, restaurant_id: uuid.UUID) -> Decimal:
        """TVA appliquee aux articles du catalogue : celle du restaurant, jamais
        celle que la caisse envoie."""
        restaurant = self.db.get(Restaurant, restaurant_id)
        configured = ((restaurant.config_jsonb or {}).get("taxes") or {}).get("tva")
        try:
            return Decimal(str(configured)) if configured is not None else self.DEFAULT_VAT_RATE
        except ArithmeticError:
            return self.DEFAULT_VAT_RATE

    def create_order(
        self,
        restaurant_id: uuid.UUID,
        data: OrderCreate,
        *,
        allow_custom_price: bool = False,
    ) -> RosOrder:
        """Cree la commande, sa facture, ses tickets ET sort le stock, atomiquement.

        Prix : un article du catalogue (plat, combinaison, boisson) est toujours
        facture au prix du catalogue et a la TVA du restaurant. Un article libre
        (prix saisi a la caisse) est reserve au management (``allow_custom_price``).
        Stock : les composants consommes sont verrouilles puis sortis ; s'il en manque
        un seul, rien n'est cree et rien n'est sorti (409).
        """
        # Idempotency Check
        if data.idempotency_key:
            existing_order = self.order_repo.get_by_idempotency_key(
                data.idempotency_key
            )
            if existing_order:
                # La clé est unique sur toute la plateforme : ne jamais renvoyer
                # la commande d'un autre restaurant qui l'aurait déjà utilisée.
                if existing_order.restaurant_id != restaurant_id:
                    raise ConflictError("Idempotency key already used")
                return existing_order

        if not data.items:
            raise ValidationError("Une commande doit contenir au moins un article")

        self._ensure_references_belong_to(
            restaurant_id, session_id=data.session_id, customer_id=data.customer_id
        )

        refs = classify_products(
            self.db, restaurant_id, [i.product_id for i in data.items if i.product_id]
        )
        catalogue_vat = (
            self._vat_rate(restaurant_id)
            if any(r.kind != "composant" for r in refs.values())
            else self.DEFAULT_VAT_RATE
        )

        priced = []  # (item, nom, prix, tva, genre)
        stock_lines: List[ProductLine] = []
        for item in data.items:
            ref = refs.get(item.product_id) if item.product_id else None
            if item.product_id and ref is None:
                raise ValidationError(
                    f"Produit {item.product_id} introuvable dans ce restaurant"
                )
            if ref is not None and ref.kind != "composant":
                if not ref.disponible:
                    raise BusinessLogicError(f"« {ref.nom} » n'est pas disponible")
                priced.append((item, ref.nom, ref.prix, catalogue_vat, ref.kind))
            else:
                if not allow_custom_price:
                    raise AuthorizationError(
                        "Prix libre réservé au management : choisissez un article du catalogue"
                    )
                if item.unit_price is None or not item.product_name:
                    raise ValidationError(
                        "product_name et unit_price sont requis pour un article libre"
                    )
                kind = ref.kind if ref is not None else "libre"
                priced.append(
                    (item, item.product_name, item.unit_price, item.tax_rate, kind)
                )
            if ref is not None:
                stock_lines.append(ProductLine(ref.kind, ref.id, Decimal(item.quantity)))

        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")
        for item, _nom, price, vat, _kind in priced:
            line_total = (price * Decimal(item.quantity)).quantize(
                self.CENT, rounding=ROUND_HALF_UP
            )
            subtotal += line_total
            tax_total += (line_total * vat / Decimal("100")).quantize(
                self.CENT, rounding=ROUND_HALF_UP
            )
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

        order = self.order_repo.create(
            {
                "restaurant_id": restaurant_id,
                "session_id": data.session_id,
                "customer_id": data.customer_id,
                "fulfillment_type": data.fulfillment_type.value,
                "order_channel": data.order_channel.value,
                "status": initial_status,
                "total_amount": total_amount,
                "idempotency_key": idempotency_key,
            }
        )

        # Lignes de commande et routage vers les postes (cuisine, bar, dessert)
        station_items: Dict[str, List[dict]] = {}
        for item, nom, price, vat, kind in priced:
            self.db.add(
                RosOrderItem(
                    order_id=order.id,
                    product_id=item.product_id,
                    product_name=nom,
                    quantity=item.quantity,
                    unit_price=price,
                    tax_rate=vat,
                    destination_station=item.destination_station.value,
                    notes=item.notes,
                    details_jsonb={**(item.details_jsonb or {}), "kind": kind},
                )
            )
            station_items.setdefault(item.destination_station.value, []).append(
                {"product_name": nom, "quantity": item.quantity, "notes": item.notes}
            )

        # Sortie de stock : une requete de verrou pour toute la commande, quel que
        # soit le nombre d'articles. Echec = rien de cree, rien de sorti.
        requirements = requirements_for(self.db, restaurant_id, stock_lines)
        if requirements:
            low_stock = self.stock_engine.consume_direct(
                requirements,
                "ROS_ORDER",
                order.id,
                f"Consommation automatique pour la commande ROS {order.id}",
            )
            for stock in low_stock:
                self.audit_repo.log_action(
                    restaurant_id=restaurant_id,
                    action="STOCK_ALERT_LOW",
                    entity_name="StockComposant",
                    entity_id=stock.id,
                    after_state={
                        "quantite": str(stock.quantite),
                        "seuil_alerte": str(stock.seuil_alerte),
                    },
                    reason=f"Stock sous le seuil d'alerte suite à la commande ROS {order.id}",
                )

        self.db.flush()

        # Les commandes a payer d'avance n'arrivent en cuisine qu'une fois payees.
        if not is_prepaid:
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
            # Une commande de plus sur la facture de la session : si elle etait
            # soldee, elle ne l'est plus. Sans cela la table restait « payee » alors
            # qu'elle devait encore de l'argent.
            new_subtotal = invoice.subtotal + subtotal
            new_tax = invoice.tax_amount + tax_total
            new_total = invoice.total_amount + total_amount
            if invoice.amount_paid >= new_total:
                new_status = InvoiceStatus.PAID.value
            elif invoice.amount_paid > 0:
                new_status = InvoiceStatus.PARTIALLY_PAID.value
            else:
                new_status = InvoiceStatus.ISSUED.value
            self.invoice_repo.update(
                invoice,
                {
                    "subtotal": new_subtotal,
                    "tax_amount": new_tax,
                    "total_amount": new_total,
                    "status": new_status,
                },
            )
            if invoice.session_id and new_status != InvoiceStatus.PAID.value:
                session = self.session_repo.get(str(invoice.session_id))
                if session and session.status == SessionStatus.SETTLED.value:
                    self.session_repo.update(
                        session,
                        {
                            "status": SessionStatus.PARTIALLY_PAID.value
                            if invoice.amount_paid > 0
                            else SessionStatus.ACTIVE.value
                        },
                    )

        return invoice

    def get_invoice_for_order(self, order: RosOrder) -> Optional[RosInvoice]:
        if order.session_id:
            return self.invoice_repo.get_by_session(order.session_id)
        return self.invoice_repo.get_by_order(order.id)

    def get_invoice(self, restaurant_id: uuid.UUID, invoice_id: uuid.UUID) -> RosInvoice:
        invoice = self.invoice_repo.get(str(invoice_id))
        if not invoice or invoice.restaurant_id != restaurant_id:
            raise NotFoundError(f"Facture {invoice_id} introuvable")
        return invoice

    def get_session_invoice(
        self, restaurant_id: uuid.UUID, session_id: uuid.UUID
    ) -> RosInvoice:
        invoice = self.invoice_repo.get_by_session(session_id)
        if not invoice or invoice.restaurant_id != restaurant_id:
            raise NotFoundError(f"Aucune facture pour la session {session_id}")
        return invoice

    # -------------------------------------------------------------------------
    # PRODUCTION TICKETS (KDS / BAR DISPLAY)
    # -------------------------------------------------------------------------
    def get_pending_tickets(
        self,
        restaurant_id: uuid.UUID,
        station: ProductionStation,
        skip: int = 0,
        limit: int = 100,
    ) -> List[ProductionTicket]:
        return self.ticket_repo.get_pending_by_station(
            restaurant_id, station.value, skip, limit
        )

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
        self,
        restaurant_id: uuid.UUID,
        data: PaymentCreate,
        received_by: Optional[uuid.UUID] = None,
    ) -> RosPaymentTransaction:
        # Idempotency check
        if data.idempotency_key:
            existing_pay = self.payment_repo.get_by_idempotency_key(
                data.idempotency_key
            )
            if existing_pay:
                if existing_pay.restaurant_id != restaurant_id:
                    raise ConflictError("Idempotency key already used")
                return existing_pay

        # Verrou sur la facture : deux encaissements simultanes se serialisent au
        # lieu de lire chacun le meme « deja paye » et de depasser le total.
        invoice = self.invoice_repo.get_for_update(data.invoice_id)
        if not invoice or invoice.restaurant_id != restaurant_id:
            raise NotFoundError(f"Facture {data.invoice_id} introuvable")

        amount_due = invoice.total_amount - invoice.amount_paid
        if amount_due <= 0:
            raise BusinessLogicError("Cette facture est déjà soldée")
        if data.amount > amount_due:
            raise BusinessLogicError(
                f"Le montant dépasse le reste dû ({amount_due} XAF) : "
                "encaissez au plus ce qui est dû"
            )

        idempotency_key = data.idempotency_key or uuid.uuid4()

        pay_dict = {
            "restaurant_id": restaurant_id,
            "invoice_id": invoice.id,
            "payment_method": data.payment_method.value,
            "amount": data.amount,
            "status": "SUCCEEDED",
            "external_reference": data.external_reference,
            "idempotency_key": idempotency_key,
            "received_by": received_by,
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

        # Une commande a payer d'avance part en production seulement quand la facture
        # est SOLDEE : un acompte ne doit pas lancer la cuisine.
        if invoice.order_id and invoice_status == InvoiceStatus.PAID.value:
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
            actor_id=received_by,
            after_state={
                "amount": str(data.amount),
                "method": data.payment_method.value,
            },
        )

        return payment

    def process_split_payment(
        self,
        restaurant_id: uuid.UUID,
        data: SplitPaymentRequest,
        received_by: Optional[uuid.UUID] = None,
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
            # Tout ou rien : si un des reglements echoue, la requete est annulee.
            results.append(self.process_payment(restaurant_id, pay_create, received_by))
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

        # Especes encaissees PAR CET OPERATEUR depuis l'ouverture de son shift,
        # additionnees par la base. Avant : celles de tous les caissiers du restaurant.
        total_cash_sales = Decimal(
            str(
                self.db.execute(
                    select(func.coalesce(func.sum(RosPaymentTransaction.amount), 0)).where(
                        RosPaymentTransaction.restaurant_id == restaurant_id,
                        RosPaymentTransaction.received_by == operator_user_id,
                        RosPaymentTransaction.payment_method
                        == RosPaymentMethod.CASH.value,
                        RosPaymentTransaction.created_at >= shift.opened_at,
                        RosPaymentTransaction.status == "SUCCEEDED",
                    )
                ).scalar()
            )
        )
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
        *,
        allow_custom_price: bool = False,
        received_by: Optional[uuid.UUID] = None,
    ) -> Dict[str, Any]:
        """Rejoue un lot saisi hors ligne. Chaque element est isole par un point de
        sauvegarde : un element refuse (stock manquant, facture soldee...) est
        signale sans emporter ni corrompre les autres."""
        processed_orders = 0
        processed_payments = 0
        errors = []

        for ord_data in orders:
            try:
                with self.db.begin_nested():
                    self.create_order(
                        restaurant_id, ord_data, allow_custom_price=allow_custom_price
                    )
                processed_orders += 1
            except (MarinadeException, ValueError) as e:
                errors.append(
                    {
                        "type": "order",
                        "idempotency_key": str(ord_data.idempotency_key),
                        "error": getattr(e, "message", str(e)),
                    }
                )

        for pay_data in payments:
            try:
                with self.db.begin_nested():
                    self.process_payment(restaurant_id, pay_data, received_by)
                processed_payments += 1
            except (MarinadeException, ValueError) as e:
                errors.append(
                    {
                        "type": "payment",
                        "idempotency_key": str(pay_data.idempotency_key),
                        "error": getattr(e, "message", str(e)),
                    }
                )

        return {
            "processed_orders": processed_orders,
            "processed_payments": processed_payments,
            "errors": errors,
        }

    def generate_procurement_suggestions(
        self, restaurant_id: uuid.UUID
    ) -> Dict[str, Any]:
        # Une seule requete (stock + composant) ; avant : une requete par composant.
        rows = self.db.execute(
            select(StockComposant, Composant.nom, Composant.stock_unite)
            .join(Composant, Composant.id == StockComposant.composant_id)
            .where(
                Composant.restaurant_id == restaurant_id,
                StockComposant.quantite <= StockComposant.seuil_alerte,
            )
            .order_by(Composant.nom, Composant.id)
            .limit(500)
        ).all()

        items = [
            {
                "composant_id": stock.composant_id,
                "composant_name": nom,
                "current_stock": stock.quantite,
                "seuil_alerte": stock.seuil_alerte,
                "suggested_order_qty": max(
                    (stock.seuil_alerte * Decimal("2.0")) - stock.quantite,
                    Decimal("1.0"),
                ),
                "unit": unite,
            }
            for stock, nom, unite in rows
        ]

        return {
            "restaurant_id": restaurant_id,
            "generated_at": datetime.now(),
            "items": items,
        }

    def get_group_consolidated_reporting(self, user_id: uuid.UUID) -> Dict[str, Any]:
        user_restaurants = (
            self.db.query(Restaurant).filter(Restaurant.user_id == user_id).all()
        )

        total_revenue = Decimal("0.00")
        total_orders = 0
        revenue_by_channel: Dict[str, Decimal] = {}
        pay_breakdown: Dict[str, Decimal] = {}

        # Les politiques RLS isolent chaque établissement : une requête unique sur
        # plusieurs restaurants ne verrait que l'établissement courant. On se place
        # donc dans chacun à tour de rôle, puis on restaure le contexte d'origine.
        previous_tenant = get_db_context(self.db, "app.current_tenant_id")
        try:
            for restaurant in user_restaurants:
                set_db_context(self.db, "app.current_tenant_id", str(restaurant.id))
                figures = self._restaurant_figures(restaurant.id)
                total_revenue += figures["revenue"]
                total_orders += figures["orders"]
                for channel, amount in figures["by_channel"].items():
                    revenue_by_channel[channel] = (
                        revenue_by_channel.get(channel, Decimal("0.00")) + amount
                    )
                for method, amount in figures["by_method"].items():
                    pay_breakdown[method] = (
                        pay_breakdown.get(method, Decimal("0.00")) + amount
                    )
        finally:
            set_db_context(self.db, "app.current_tenant_id", previous_tenant)

        return {
            "total_restaurants": len(user_restaurants),
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "revenue_by_channel": revenue_by_channel,
            "payment_method_breakdown": pay_breakdown,
        }

    def _restaurant_figures(self, restaurant_id: uuid.UUID) -> Dict[str, Any]:
        """Chiffres d'UN restaurant (contexte restaurant deja positionne), agreges
        par la base : le volume lu ne depend plus du nombre de commandes."""
        zero = Decimal("0.00")
        revenue = self.db.execute(
            select(func.coalesce(func.sum(RosInvoice.total_amount), 0)).where(
                RosInvoice.restaurant_id == restaurant_id,
                RosInvoice.status == InvoiceStatus.PAID.value,
            )
        ).scalar()
        by_channel_rows = self.db.execute(
            select(
                RosOrder.order_channel,
                func.count(RosOrder.id),
                func.coalesce(func.sum(RosOrder.total_amount), 0),
            )
            .where(RosOrder.restaurant_id == restaurant_id)
            .group_by(RosOrder.order_channel)
        ).all()
        by_method_rows = self.db.execute(
            select(
                RosPaymentTransaction.payment_method,
                func.coalesce(func.sum(RosPaymentTransaction.amount), 0),
            )
            .where(
                RosPaymentTransaction.restaurant_id == restaurant_id,
                RosPaymentTransaction.status == "SUCCEEDED",
            )
            .group_by(RosPaymentTransaction.payment_method)
        ).all()
        return {
            "revenue": Decimal(str(revenue)) if revenue else zero,
            "orders": sum(count for _channel, count, _total in by_channel_rows),
            "by_channel": {c: Decimal(str(total)) for c, _n, total in by_channel_rows},
            "by_method": {m: Decimal(str(total)) for m, total in by_method_rows},
        }
