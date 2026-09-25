from abc import ABC, abstractmethod
from decimal import Decimal
import secrets
from typing import Any, Dict

from app.utils.phone import normalize_cameroon_mobile
from app.utils.logging import get_logger

logger = get_logger(__name__)


class PaymentMethod(ABC):
    """Small compatibility interface for the legacy adapter boundary."""

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    def process_payment(
        self, amount: Decimal, payment_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def refund_payment(
        self, transaction_id: str, amount: Decimal | None = None
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_payment_status(self, transaction_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate_payment_details(self, payment_details: Dict[str, Any]) -> bool:
        raise NotImplementedError


class CashPayment(PaymentMethod):
    """Offline cash payment; no provider network call is implied."""

    def process_payment(
        self, amount: Decimal, payment_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        if amount <= 0:
            return {
                "success": False,
                "error": "Amount must be positive",
                "status": "failed",
                "payment_method": "cash",
            }
        return {
            "success": True,
            "status": "completed",
            "transaction_id": f"CASH_{secrets.token_hex(12)}",
            "amount": int(amount),
            "payment_method": "cash",
            "currency": payment_details.get("currency", "XAF"),
            "received_by": payment_details.get("received_by"),
        }

    def refund_payment(
        self, transaction_id: str, amount: Decimal | None = None
    ) -> Dict[str, Any]:
        return {
            "success": False,
            "status": "manual_review",
            "transaction_id": transaction_id,
            "amount": int(amount) if amount is not None else None,
            "payment_method": "cash",
            "requires_manual_verification": True,
        }

    def get_payment_status(self, transaction_id: str) -> Dict[str, Any]:
        return {
            "transaction_id": transaction_id,
            "status": "manual_review",
            "payment_method": "cash",
        }

    def validate_payment_details(self, payment_details: Dict[str, Any]) -> bool:
        if not isinstance(payment_details, dict) or "amount" not in payment_details:
            return False
        try:
            return Decimal(str(payment_details["amount"])) > 0
        except Exception:
            return False


class EasyTransactUnsupported(PaymentMethod):
    """Compatibility name for the retired random Mobile Money adapters."""

    def _unsupported(self, transaction_id: str | None = None) -> Dict[str, Any]:
        result = {
            "success": False,
            "error": "Mobile Money must be processed through Easy Transact",
            "status": "unsupported",
            "payment_method": "easytransact",
        }
        if transaction_id:
            result["transaction_id"] = transaction_id
        return result

    def process_payment(
        self, amount: Decimal, payment_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self._unsupported()

    def refund_payment(
        self, transaction_id: str, amount: Decimal | None = None
    ) -> Dict[str, Any]:
        return self._unsupported(transaction_id)

    def get_payment_status(self, transaction_id: str) -> Dict[str, Any]:
        return self._unsupported(transaction_id)

    def validate_payment_details(self, payment_details: Dict[str, Any]) -> bool:
        if not isinstance(payment_details, dict) or not payment_details.get(
            "phone_number"
        ):
            return False
        try:
            normalize_cameroon_mobile(str(payment_details["phone_number"]))
            return True
        except ValueError:
            return False


class OrangeMoneyPayment(EasyTransactUnsupported):
    """Orange Cameroon is routed through Easy Transact, not simulated here."""

    def _unsupported(self, transaction_id: str | None = None) -> Dict[str, Any]:
        result = super()._unsupported(transaction_id)
        result["operator"] = "ORANGE_CM"
        return result

    def validate_payment_details(self, payment_details: Dict[str, Any]) -> bool:
        if not isinstance(payment_details, dict) or not payment_details.get(
            "phone_number"
        ):
            return False
        try:
            _, operator = normalize_cameroon_mobile(
                str(payment_details["phone_number"])
            )
            return operator.code == "ORANGE_CM"
        except ValueError:
            return False


class MobileMoneyPayment(EasyTransactUnsupported):
    """Compatibility adapter for MTN/Orange; only Easy Transact is executable."""

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self.provider = str(self.config.get("provider", "")).upper()

    def _unsupported(self, transaction_id: str | None = None) -> Dict[str, Any]:
        result = super()._unsupported(transaction_id)
        if self.provider:
            result["provider"] = self.provider
        return result

    def validate_payment_details(self, payment_details: Dict[str, Any]) -> bool:
        if self.provider not in {"MTN", "MTN_CM", "ORANGE", "ORANGE_CM"}:
            return False
        if not isinstance(payment_details, dict) or not payment_details.get(
            "phone_number"
        ):
            return False
        try:
            _, operator = normalize_cameroon_mobile(
                str(payment_details["phone_number"])
            )
            expected = "MTN_CM" if self.provider.startswith("MTN") else "ORANGE_CM"
            return operator.code == expected
        except ValueError:
            return False


class PaymentFactory:
    _payment_methods = {
        "cash": CashPayment,
        "orange_money": OrangeMoneyPayment,
        "mobile_money": MobileMoneyPayment,
    }

    @classmethod
    def create_payment_method(
        cls, method_type: str, config: Dict[str, Any] | None = None
    ) -> PaymentMethod:
        method_class = cls._payment_methods.get(str(method_type).lower())
        if method_class is None:
            raise ValueError(f"Unsupported payment method: {method_type}")
        return method_class(config)

    @classmethod
    def get_supported_methods(cls) -> list[str]:
        return list(cls._payment_methods)

    @classmethod
    def register_payment_method(
        cls, method_type: str, payment_class: type[PaymentMethod]
    ) -> None:
        if not issubclass(payment_class, PaymentMethod):
            raise TypeError("Payment implementation must inherit PaymentMethod")
        cls._payment_methods[method_type.lower()] = payment_class
