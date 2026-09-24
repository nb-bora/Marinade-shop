from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import os
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.easy_transact import EasyTransactClient, EasyTransactError
from app.models.payment import PaymentConfiguration, PaymentEvent, PaymentIntent, PaymentLedgerEntry
from app.models.restaurant import Restaurant
from app.schemas.payment import EasyTransactCheckoutCreate, EasyTransactInitiateRequest, PaymentConfigurationUpsert
from app.services.restaurant_service import CommandeService
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _status(value: str) -> str:
    return value.strip().lower()


def _amount(value: Any) -> int:
    try:
        return int(Decimal(str(value)))
    except Exception as exc:
        raise ValueError("Invalid Easy Transact amount") from exc


class EasyTransactPaymentService:
    def __init__(self, db: Session):
        self.db = db

    def configuration(self, restaurant_id: uuid.UUID) -> PaymentConfiguration:
        config = self.db.query(PaymentConfiguration).filter(
            PaymentConfiguration.restaurant_id == restaurant_id,
            PaymentConfiguration.provider == "easytransact",
            PaymentConfiguration.enabled == True,
        ).first()
        if config is None:
            raise HTTPException(status_code=503, detail="Easy Transact is not configured for this restaurant")
        return config

    def upsert_configuration(self, data: PaymentConfigurationUpsert) -> PaymentConfiguration:
        config = self.db.query(PaymentConfiguration).filter(
            PaymentConfiguration.restaurant_id == data.restaurant_id,
            PaymentConfiguration.provider == "easytransact",
        ).first()
        if config is None:
            config = PaymentConfiguration(restaurant_id=data.restaurant_id, provider="easytransact")
            self.db.add(config)
        for key, value in data.model_dump(exclude={"restaurant_id"}).items():
            setattr(config, key, value)
        self.db.flush()
        self.db.refresh(config)
        return config

    def _validate_reference(self, data: EasyTransactCheckoutCreate) -> None:
        if bool(data.commande_id) == bool(data.subscription_id):
            raise HTTPException(status_code=400, detail="Provide exactly one commande_id or subscription_id")
        restaurant = self.db.query(Restaurant).filter(Restaurant.id == data.restaurant_id).first()
        if restaurant is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        if data.commande_id:
            commande = CommandeService(self.db).get_commande(data.commande_id)
            if commande is None or commande.restaurant_id != data.restaurant_id:
                raise HTTPException(status_code=404, detail="Commande not found")
            if commande.statut in {"payee", "annulee"}:
                raise HTTPException(status_code=409, detail="Commande cannot be paid in its current state")
            if _amount(commande.total) != data.amount_fcfa:
                raise HTTPException(status_code=400, detail="Payment amount must equal commande total")
        if data.subscription_id:
            subscription = self.db.query(__import__("app.models.subscription", fromlist=["Subscription"]).Subscription).filter_by(id=data.subscription_id).first()
            if subscription is None or subscription.restaurant_id != data.restaurant_id:
                raise HTTPException(status_code=404, detail="Subscription not found")

    def create_checkout(self, data: EasyTransactCheckoutCreate) -> PaymentIntent:
        self._validate_reference(data)
        config = self.configuration(data.restaurant_id)
        existing = self.db.query(PaymentIntent).filter(
            PaymentIntent.restaurant_id == data.restaurant_id,
            PaymentIntent.idempotency_key == data.idempotency_key,
        ).first()
        if existing:
            if existing.amount_fcfa != data.amount_fcfa or existing.commande_id != data.commande_id or existing.subscription_id != data.subscription_id:
                raise HTTPException(status_code=409, detail="idempotency_key was already used with different payment data")
            return existing

        vendor_reference = f"{config.vendor_reference_prefix}-{uuid.uuid4().hex}"[:100]
        intent = PaymentIntent(
            restaurant_id=data.restaurant_id,
            commande_id=data.commande_id,
            subscription_id=data.subscription_id,
            provider="easytransact",
            vendor_reference=vendor_reference,
            idempotency_key=data.idempotency_key,
            amount_fcfa=data.amount_fcfa,
            currency="XAF",
            status="initiated",
        )
        self.db.add(intent)
        self.db.flush()
        try:
            response = EasyTransactClient.from_settings().create_checkout_link(
                description=data.description,
                amount_xaf=data.amount_fcfa,
                vendor_reference=vendor_reference,
                service_code=config.service_code,
                success_url=config.success_url,
                cancel_url=config.failure_url,
            )
        except EasyTransactError as exc:
            intent.status = "manual_review"
            intent.metadata_jsonb = {"error": str(exc)}
            self.db.flush()
            raise HTTPException(status_code=502, detail="Easy Transact checkout failed") from exc
        intent.checkout_url = response.get("checkout_url") or response.get("payment_url") or response.get("url")
        intent.provider_transaction_id = response.get("provider_transaction_id") or response.get("transaction_id")
        intent.metadata_jsonb = response
        self.db.flush()
        return intent

    def initiate(self, data: EasyTransactInitiateRequest) -> dict[str, Any]:
        self.configuration(data.restaurant_id)
        payload = {
            "vendor_reference": data.vendor_reference,
            "amount": str(Decimal(data.amount_fcfa)),
            "currency_code": data.currency_code,
            "service_code": data.service_code,
        }
        if data.operator_id:
            payload["operator_id"] = data.operator_id
        if data.sender_number:
            payload["sender_number"] = data.sender_number
        if data.receiver_number:
            payload["receiver_number"] = data.receiver_number
        try:
            return EasyTransactClient.from_settings().initiate_transaction(payload)
        except EasyTransactError as exc:
            raise HTTPException(status_code=502, detail="Easy Transact initiation failed") from exc

    def verify_webhook(self, raw_body: bytes, signature: str | None, config: PaymentConfiguration | None = None) -> None:
        secret_name = config.webhook_secret_env_key if config else settings.EASYTRANSACT_WEBHOOK_SECRET
        secret = os.environ.get(secret_name) if config else settings.EASYTRANSACT_WEBHOOK_SECRET
        if not secret or not signature:
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        supplied = signature.removeprefix("sha256=")
        if not hmac.compare_digest(expected, supplied):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    def process_webhook(self, payload: dict[str, Any], raw_body: bytes, signature: str | None) -> tuple[PaymentIntent, bool]:
        vendor_reference = payload.get("vendor_reference")
        provider_event_id = payload.get("event_id") or payload.get("id")
        provider_status = _status(str(payload.get("status", "")))
        if not vendor_reference or not provider_event_id or provider_status not in {"initiated", "pending", "processing", "success", "failed", "timeout", "reversed", "refunded", "expired"}:
            raise HTTPException(status_code=400, detail="Invalid Easy Transact webhook payload")
        intent = self.db.query(PaymentIntent).filter(PaymentIntent.vendor_reference == vendor_reference).first()
        if intent is None:
            raise HTTPException(status_code=404, detail="Payment intent not found")
        config = self.configuration(intent.restaurant_id)
        self.verify_webhook(raw_body, signature, config)
        existing = self.db.query(PaymentEvent).filter(PaymentEvent.provider_event_id == str(provider_event_id)).first()
        if existing:
            return intent, True
        event = PaymentEvent(payment_intent_id=intent.id, provider_event_id=str(provider_event_id), provider_status=provider_status, raw_payload=payload, signature=signature)
        self.db.add(event)
        previous = intent.status
        if provider_status == "success" and previous != "success":
            if intent.commande_id is not None:
                CommandeService(self.db).confirm_payment(intent.commande_id, intent.id)
            self.db.add(PaymentLedgerEntry(payment_intent_id=intent.id, restaurant_id=intent.restaurant_id, entry_type="capture", amount_fcfa=intent.amount_fcfa, currency=intent.currency, idempotency_key=f"capture:{intent.id}", reference=str(provider_event_id)))
        intent.status = provider_status
        event.processed_at = datetime.now(timezone.utc)
        self.db.flush()
        return intent, False
