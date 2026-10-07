from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from decimal import Decimal
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


# CUSTOMER SCHEMAS
class CustomerCreate(BaseModel):
    customer_type: CustomerType = CustomerType.GUEST
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    preferences_jsonb: Optional[Dict[str, Any]] = None


class CustomerResponse(BaseModel):
    id: UUID
    restaurant_id: UUID
    customer_type: CustomerType
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    preferences_jsonb: Optional[Dict[str, Any]] = None
    loyalty_points: int
    created_at: datetime

    model_config = {"from_attributes": True}


# SESSION SCHEMAS
class SessionCreate(BaseModel):
    customer_id: Optional[UUID] = None
    table_id: Optional[UUID] = None
    table_context: Optional[str] = None  # e.g., 'Terrasse Gauche', 'Comptoir Bar', NULL


class SessionResponse(BaseModel):
    id: UUID
    restaurant_id: UUID
    customer_id: Optional[UUID] = None
    table_id: Optional[UUID] = None
    table_context: Optional[str] = None
    status: SessionStatus
    opened_at: datetime
    closed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ORDER SCHEMAS
class OrderItemCreate(BaseModel):
    # Article du catalogue (plat, combinaison, boisson) : le serveur impose le nom, le
    # prix et la TVA du catalogue, et ignore product_name / unit_price / tax_rate.
    # Article libre (sans product_id) : product_name et unit_price sont requis et
    # l'appel est réservé au management.
    product_id: Optional[UUID] = None
    product_name: Optional[str] = Field(None, min_length=1, max_length=255)
    quantity: int = Field(gt=0, description="Quantité doit être > 0")
    unit_price: Optional[Decimal] = Field(None, ge=0, description="Prix des articles libres")
    tax_rate: Decimal = Field(Decimal("19.25"), ge=0, le=100)
    destination_station: ProductionStation = ProductionStation.KITCHEN
    notes: Optional[str] = None
    details_jsonb: Optional[Dict[str, Any]] = None


class OrderCreate(BaseModel):
    session_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    fulfillment_type: FulfillmentType = FulfillmentType.DINE_IN
    order_channel: OrderChannel = OrderChannel.POS
    items: List[OrderItemCreate]
    idempotency_key: Optional[UUID] = None


class OrderItemResponse(BaseModel):
    id: UUID
    order_id: UUID
    product_id: Optional[UUID] = None
    product_name: str
    quantity: int
    unit_price: Decimal
    tax_rate: Decimal
    destination_station: ProductionStation
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrderResponse(BaseModel):
    id: UUID
    restaurant_id: UUID
    session_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    fulfillment_type: FulfillmentType
    order_channel: OrderChannel
    status: RosOrderStatus
    total_amount: Decimal
    idempotency_key: UUID
    # Facture à encaisser via /payments. Pour une session, c'est la facture
    # partagée par toutes les commandes de la session.
    invoice_id: Optional[UUID] = None
    invoice_number: Optional[str] = None
    items: List[OrderItemResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# PRODUCTION TICKET SCHEMAS
class TicketResponse(BaseModel):
    id: UUID
    restaurant_id: UUID
    order_id: UUID
    station: ProductionStation
    status: TicketStatus
    items_jsonb: Optional[List[Dict[str, Any]]] = None
    created_at: datetime
    ready_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TicketStatusUpdate(BaseModel):
    status: TicketStatus


# INVOICE SCHEMAS
class InvoiceResponse(BaseModel):
    id: UUID
    restaurant_id: UUID
    session_id: Optional[UUID] = None
    order_id: Optional[UUID] = None
    invoice_number: str
    subtotal: Decimal
    tax_amount: Decimal
    service_charge: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    amount_paid: Decimal
    amount_due: Decimal
    status: InvoiceStatus
    fiscal_hash: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# PAYMENT SCHEMAS
class PaymentCreate(BaseModel):
    invoice_id: UUID
    payment_method: RosPaymentMethod
    amount: Decimal = Field(gt=0, description="Montant du paiement doit être > 0")
    external_reference: Optional[str] = None
    idempotency_key: Optional[UUID] = None


class SplitPaymentItem(BaseModel):
    payment_method: RosPaymentMethod
    amount: Decimal = Field(gt=0)
    external_reference: Optional[str] = None


class SplitPaymentRequest(BaseModel):
    invoice_id: UUID
    payments: List[SplitPaymentItem]
    idempotency_key: Optional[UUID] = None


class PaymentResponse(BaseModel):
    id: UUID
    restaurant_id: UUID
    invoice_id: UUID
    payment_method: RosPaymentMethod
    amount: Decimal
    status: str
    external_reference: Optional[str] = None
    idempotency_key: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# CASH SHIFT SCHEMAS
class ShiftOpenRequest(BaseModel):
    opening_balance: Decimal = Field(ge=0, description="Fond de caisse initial")


class ShiftCloseRequest(BaseModel):
    closing_balance_counted: Decimal = Field(
        ge=0, description="Solde compté dans le tiroir caisse"
    )


class ShiftResponse(BaseModel):
    id: UUID
    restaurant_id: UUID
    operator_user_id: UUID
    opening_balance: Decimal
    closing_balance_expected: Optional[Decimal] = None
    closing_balance_counted: Optional[Decimal] = None
    variance: Optional[Decimal] = None
    status: CashShiftStatus
    opened_at: datetime
    closed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# AUDIT SCHEMAS
class AuditLogResponse(BaseModel):
    id: UUID
    restaurant_id: UUID
    actor_id: Optional[UUID] = None
    action: str
    entity_name: str
    entity_id: UUID
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# OFFLINE SYNC SCHEMAS
class SyncBatchRequest(BaseModel):
    orders: List[OrderCreate] = []
    payments: List[PaymentCreate] = []


class SyncBatchResponse(BaseModel):
    processed_orders: int
    processed_payments: int
    errors: List[Dict[str, Any]] = []


# PROCUREMENT SCHEMAS
class ProcurementSuggestionItem(BaseModel):
    composant_id: UUID
    composant_name: str
    current_stock: Decimal
    seuil_alerte: Decimal
    suggested_order_qty: Decimal
    unit: str


class ProcurementSuggestionResponse(BaseModel):
    restaurant_id: UUID
    generated_at: datetime
    items: List[ProcurementSuggestionItem] = []


# GROUP CONSOLIDATED REPORTING SCHEMAS
class GroupReportingResponse(BaseModel):
    total_restaurants: int
    total_revenue: Decimal
    total_orders: int
    revenue_by_channel: Dict[str, Decimal]
    payment_method_breakdown: Dict[str, Decimal]
