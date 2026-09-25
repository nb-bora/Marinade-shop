from enum import Enum


class CustomerType(str, Enum):
    GUEST = "GUEST"
    REGISTERED = "REGISTERED"
    VIP = "VIP"
    BUSINESS = "BUSINESS"
    HOTEL_GUEST = "HOTEL_GUEST"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class FulfillmentType(str, Enum):
    DINE_IN = "DINE_IN"
    TAKEAWAY = "TAKEAWAY"
    DELIVERY = "DELIVERY"
    COUNTER = "COUNTER"


class OrderChannel(str, Enum):
    POS = "POS"
    QR = "QR"
    WHATSAPP = "WHATSAPP"
    KIOSK = "KIOSK"
    WEB = "WEB"
    PHONE = "PHONE"


class RosOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    SENT_TO_PRODUCTION = "SENT_TO_PRODUCTION"
    READY = "READY"
    SERVED = "SERVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class ProductionStation(str, Enum):
    KITCHEN = "KITCHEN"
    BAR = "BAR"
    DESSERT = "DESSERT"
    PACKAGING = "PACKAGING"


class TicketStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PREPARATION = "IN_PREPARATION"
    READY = "READY"
    SERVED = "SERVED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class RosPaymentMethod(str, Enum):
    CASH = "CASH"
    MTN_MOMO = "MTN_MOMO"
    ORANGE_MONEY = "ORANGE_MONEY"
    CARD = "CARD"
    WAVE = "WAVE"
    BANK_TRANSFER = "BANK_TRANSFER"


class CashShiftStatus(str, Enum):
    OPEN = "OPEN"
    COUNTING = "COUNTING"
    CLOSED = "CLOSED"
