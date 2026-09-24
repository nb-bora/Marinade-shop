from decimal import Decimal
from typing import Any, Dict

from app.utils.logging import get_logger
from app.utils.payment_methods import PaymentFactory, PaymentMethod

logger = get_logger(__name__)


class PaymentService:
    """Compatibility facade; the authoritative payment path is EasyTransactPaymentService."""

    def __init__(self, db: Any = None, payment_config: Dict[str, Any] | None = None):
        self.db = db
        self.payment_config = payment_config or {}

    def process_payment(self, method_type: Any, amount: Decimal, payment_details: Dict[str, Any], method_config: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if isinstance(method_type, (list, tuple, set)):
            methods = [str(item).strip().lower() for item in method_type if str(item).strip()]
        else:
            methods = [part.strip().lower() for part in str(method_type).split(",") if part.strip()]
        if len(methods) != 1:
            return {"success": False, "error": "Exactly one payment method is required", "status": "method_error"}
        method = methods[0]
        try:
            config = {**self.payment_config.get(method, {}), **(method_config or {})}
            payment_method = PaymentFactory.create_payment_method(method, config)
            if not payment_method.validate_payment_details({**payment_details, "amount": int(amount)}):
                return {"success": False, "error": "Invalid payment details", "status": "validation_failed", "payment_method": method}
            return payment_method.process_payment(amount, payment_details)
        except ValueError as exc:
            return {"success": False, "error": str(exc), "status": "method_error"}
        except Exception:
            logger.exception("Payment adapter failed")
            return {"success": False, "error": "Payment processing failed", "status": "processing_error", "payment_method": method}

    def refund_payment(self, method_type: str, transaction_id: str, amount: Decimal | None = None, method_config: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            method = PaymentFactory.create_payment_method(method_type, {**self.payment_config.get(method_type, {}), **(method_config or {})})
            return method.refund_payment(transaction_id, amount)
        except Exception:
            logger.exception("Refund adapter failed")
            return {"success": False, "error": "Refund processing failed", "status": "refund_error"}

    def get_payment_status(self, method_type: str, transaction_id: str, method_config: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            method = PaymentFactory.create_payment_method(method_type, {**self.payment_config.get(method_type, {}), **(method_config or {})})
            return method.get_payment_status(transaction_id)
        except Exception:
            logger.exception("Payment status adapter failed")
            return {"transaction_id": transaction_id, "status": "error", "error": "Payment status unavailable"}

    def get_supported_methods(self) -> list[str]:
        return PaymentFactory.get_supported_methods()

    def validate_payment_details(self, method_type: str, payment_details: Dict[str, Any]) -> bool:
        try:
            method: PaymentMethod = PaymentFactory.create_payment_method(method_type, self.payment_config.get(method_type, {}))
            return method.validate_payment_details(payment_details)
        except ValueError:
            return False
