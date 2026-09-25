from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    POS = "pos"
    RESTAURANT = "restaurant"
    WAITER = "waiter"
    CASHIER = "cashier"
    CHEF = "chef"
    MANAGER = "manager"
    DELIVERY = "delivery"


class StaffRole(str, Enum):
    WAITER = "waiter"
    CASHIER = "cashier"
    CHEF = "chef"
    SOUS_CHEF = "sous_chef"
    MANAGER = "manager"
    DELIVERY = "delivery"
    BARTENDER = "bartender"
    HOST = "host"


class SubscriptionStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TableStatut(str, Enum):
    LIBRE = "libre"
    OCCUPEE = "occupee"
    RESERVEE = "reservee"
    MAINTENANCE = "maintenance"


class CommandeStatut(str, Enum):
    EN_COURS = "en_cours"
    SERVIE = "servie"
    ANNULEE = "annulee"
    PAYEE = "payee"
    PAYMENT_PENDING = "paiement_en_attente"
    PAYMENT_REVIEW = "paiement_a_verifier"


class ReservationStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class RefundStatus(str, Enum):
    NONE = "none"
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    EXPIRED = "expired"


class PaymentStatus(str, Enum):
    INITIATED = "initiated"
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REVERSED = "reversed"
    REFUNDED = "refunded"
    EXPIRED = "expired"
    MANUAL_REVIEW = "manual_review"
