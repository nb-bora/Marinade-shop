from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    POS = "pos"
    RESTAURANT = "restaurant"


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
