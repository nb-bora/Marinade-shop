from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import case, func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.easy_transact import EasyTransactClient, EasyTransactError
from app.models.payment import (
    PaymentConfiguration,
    PaymentEvent,
    PaymentIntent,
    PaymentLedgerEntry,
)
from app.models.restaurant import Restaurant
from app.schemas.payment import (
    EasyTransactCheckoutCreate,
    EasyTransactInitiateRequest,
    PaymentConfigurationUpsert,
)
from app.services.restaurant_service import CommandeService
from app.utils.logging import get_logger
from app.utils.payment_references import (
    InvalidCursor,
    decode_cursor,
    encode_cursor,
    net_amount_fcfa,
    new_reference_prefix,
    new_vendor_reference,
)
from app.utils.payment_secrets import (
    DEFAULT_CREDENTIAL_ENV_KEY,
    DEFAULT_WEBHOOK_SECRET_ENV_KEY,
    is_allowed_credential_env_key,
    is_allowed_webhook_secret_env_key,
    resolve_secret,
)

logger = get_logger(__name__)


def _status(value: str) -> str:
    return value.strip().lower()


# Statuts de la passerelle (en minuscules) + l'etat interne « manual_review ».
PROVIDER_STATUSES = frozenset(
    {
        "initiated",
        "pending",
        "processing",
        "success",
        "failed",
        "timeout",
        "reversed",
        "refunded",
        "expired",
    }
)
TERMINAL_STATUSES = frozenset({"success", "failed", "reversed", "refunded", "expired"})
FAILURE_STATUSES = frozenset({"failed", "timeout", "expired", "reversed"})


def _amount(value: Any) -> int:
    try:
        return int(Decimal(str(value)))
    except Exception as exc:
        raise ValueError("Invalid Easy Transact amount") from exc


class EasyTransactPaymentService:
    def __init__(self, db: Session):
        self.db = db

    def configuration(self, restaurant_id: uuid.UUID) -> PaymentConfiguration:
        config = (
            self.db.query(PaymentConfiguration)
            .filter(
                PaymentConfiguration.restaurant_id == restaurant_id,
                PaymentConfiguration.provider == "easytransact",
                PaymentConfiguration.enabled == True,
            )
            .first()
        )
        if config is None:
            raise HTTPException(
                status_code=503,
                detail="Easy Transact is not configured for this restaurant",
            )
        return config

    @staticmethod
    def _enforce_secret_references(
        data: PaymentConfigurationUpsert,
        existing: PaymentConfiguration | None,
        allow_custom_env_keys: bool,
    ) -> None:
        """Only a platform admin may point a restaurant at a non-default secret.

        A restaurant owner may keep the default references (or those an admin
        already set) but never choose a new one: the reference decides which
        server-side secret authenticates that restaurant's payment webhooks.
        """
        if allow_custom_env_keys:
            return
        for field, default in (
            ("credential_env_key", DEFAULT_CREDENTIAL_ENV_KEY),
            ("webhook_secret_env_key", DEFAULT_WEBHOOK_SECRET_ENV_KEY),
        ):
            requested = getattr(data, field)
            current = getattr(existing, field, None) if existing else None
            if requested not in (default, current):
                raise HTTPException(
                    status_code=403,
                    detail=f"Only a platform administrator can change {field}",
                )

    def upsert_configuration(
        self, data: PaymentConfigurationUpsert, allow_custom_env_keys: bool = False
    ) -> PaymentConfiguration:
        config = (
            self.db.query(PaymentConfiguration)
            .filter(
                PaymentConfiguration.restaurant_id == data.restaurant_id,
                PaymentConfiguration.provider == "easytransact",
            )
            .first()
        )
        self._enforce_secret_references(data, config, allow_custom_env_keys)
        values = data.model_dump(exclude={"restaurant_id"})
        if config is not None:
            # Le prefixe de reference n'est JAMAIS modifie : les references deja
            # envoyees a la passerelle doivent continuer a pointer vers ce restaurant.
            for key, value in values.items():
                setattr(config, key, value)
            self.db.flush()
            self.db.refresh(config)
            return config
        return self._create_configuration(data.restaurant_id, values)

    def _create_configuration(
        self, restaurant_id: uuid.UUID, values: dict
    ) -> PaymentConfiguration:
        """Cree la configuration avec un prefixe de reference unique sur la plateforme.

        La RLS cache les prefixes des autres restaurants : on ne peut pas verifier
        l'unicite par une lecture. On laisse donc l'index unique trancher, dans un
        point de sauvegarde, et on retire un autre prefixe en cas de collision
        (probabilite d'environ 1 sur 10^12 par tirage).
        """
        for _attempt in range(5):
            config = PaymentConfiguration(
                restaurant_id=restaurant_id,
                provider="easytransact",
                vendor_reference_prefix=new_reference_prefix(),
                **values,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(config)
                    self.db.flush()
            except IntegrityError as exc:
                if "uq_payment_configuration_reference_prefix" not in str(exc.orig):
                    raise
                continue
            self.db.refresh(config)
            return config
        raise HTTPException(
            status_code=503, detail="Could not allocate a payment reference prefix"
        )

    @staticmethod
    def _credential_for(config: PaymentConfiguration) -> str | None:
        if not is_allowed_credential_env_key(config.credential_env_key):
            raise HTTPException(
                status_code=503,
                detail="Payment configuration references a forbidden credential",
            )
        return resolve_secret(config.credential_env_key)

    def _validate_reference(self, data: EasyTransactCheckoutCreate) -> None:
        if bool(data.commande_id) == bool(data.subscription_id):
            raise HTTPException(
                status_code=400,
                detail="Provide exactly one commande_id or subscription_id",
            )
        restaurant = (
            self.db.query(Restaurant)
            .filter(Restaurant.id == data.restaurant_id)
            .first()
        )
        if restaurant is None:
            raise HTTPException(status_code=404, detail="Restaurant not found")
        if data.commande_id:
            commande = CommandeService(self.db).get_commande(data.commande_id)
            if commande is None or commande.restaurant_id != data.restaurant_id:
                raise HTTPException(status_code=404, detail="Commande not found")
            if commande.statut in {"payee", "annulee"}:
                raise HTTPException(
                    status_code=409,
                    detail="Commande cannot be paid in its current state",
                )
            if _amount(commande.total) != data.amount_fcfa:
                raise HTTPException(
                    status_code=400, detail="Payment amount must equal commande total"
                )
        if data.subscription_id:
            from app.models.subscription import Subscription

            subscription = (
                self.db.query(Subscription)
                .filter(
                    Subscription.id == data.subscription_id,
                    Subscription.restaurant_id == data.restaurant_id,
                )
                .first()
            )
            if subscription is None:
                raise HTTPException(status_code=404, detail="Subscription not found")

    def create_checkout(self, data: EasyTransactCheckoutCreate) -> PaymentIntent:
        self._validate_reference(data)
        config = self.configuration(data.restaurant_id)
        existing = (
            self.db.query(PaymentIntent)
            .filter(
                PaymentIntent.restaurant_id == data.restaurant_id,
                PaymentIntent.idempotency_key == data.idempotency_key,
            )
            .first()
        )
        if existing:
            if (
                existing.amount_fcfa != data.amount_fcfa
                or existing.commande_id != data.commande_id
                or existing.subscription_id != data.subscription_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="idempotency_key was already used with different payment data",
                )
            return existing

        vendor_reference = new_vendor_reference(config.vendor_reference_prefix)
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
            response = EasyTransactClient.from_settings(
                self._credential_for(config)
            ).create_checkout_link(
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
            raise HTTPException(
                status_code=502, detail="Easy Transact checkout failed"
            ) from exc
        intent.checkout_url = (
            response.get("checkout_url")
            or response.get("payment_url")
            or response.get("url")
        )
        intent.provider_transaction_id = response.get(
            "provider_transaction_id"
        ) or response.get("transaction_id")
        intent.metadata_jsonb = response
        self.db.flush()
        return intent

    def initiate(self, data: EasyTransactInitiateRequest) -> dict[str, Any]:
        config = self.configuration(data.restaurant_id)
        from app.services.operator_service import OperatorService

        operators = OperatorService(self.db)
        sender_operator = None
        receiver_operator = None
        if data.sender_number:
            _, sender_operator = operators.normalize_mobile(data.sender_number)
        if data.receiver_number:
            _, receiver_operator = operators.normalize_mobile(data.receiver_number)
        if data.operator_id:
            expected = sender_operator or receiver_operator
            if expected and data.operator_id.upper() != expected.code.upper():
                raise HTTPException(
                    status_code=400,
                    detail="operator_id does not match the Cameroon number",
                )
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
            return EasyTransactClient.from_settings(
                self._credential_for(config)
            ).initiate_transaction(payload)
        except EasyTransactError as exc:
            raise HTTPException(
                status_code=502, detail="Easy Transact initiation failed"
            ) from exc

    def verify_webhook(
        self,
        raw_body: bytes,
        signature: str | None,
        config: PaymentConfiguration | None = None,
    ) -> None:
        if config is not None:
            # Revalidé à l'usage : une ancienne ligne en base ou une écriture hors
            # API ne doit jamais pouvoir désigner une variable arbitraire.
            if not is_allowed_webhook_secret_env_key(config.webhook_secret_env_key):
                raise HTTPException(
                    status_code=503,
                    detail="Payment configuration references a forbidden secret",
                )
            secret = resolve_secret(config.webhook_secret_env_key)
        else:
            secret = settings.EASYTRANSACT_WEBHOOK_SECRET
        if not secret or not signature:
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        if settings.EASYTRANSACT_WEBHOOK_SIGNATURE_ALGORITHM.lower() not in {
            "hmac-sha256",
            "sha256",
        }:
            raise HTTPException(
                status_code=503, detail="Webhook signature algorithm is not supported"
            )
        expected = hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        supplied = signature.removeprefix("sha256=")
        if not hmac.compare_digest(expected.lower(), supplied.lower()):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    def authenticate_webhook(
        self, restaurant_id: uuid.UUID, raw_body: bytes, signature: str | None
    ) -> None:
        """Check the signature against the restaurant named in the URL.

        Called before the body is even parsed: an unauthenticated caller must not
        be able to tell an invalid payload (400) from an unknown payment (404) from
        a bad signature (401), since that would reveal which references exist.
        """
        self.verify_webhook(raw_body, signature, self.configuration(restaurant_id))

    def process_webhook(
        self, payload: dict[str, Any], raw_body: bytes, signature: str | None
    ) -> tuple[PaymentIntent, bool]:
        """Verify and apply one tenant-scoped provider event atomically."""
        vendor_reference = payload.get("vendor_reference")
        provider_event_id = payload.get("event_id") or payload.get("id")
        provider_status = _status(str(payload.get("status", "")))
        if (
            not vendor_reference
            or not provider_event_id
            or provider_status not in PROVIDER_STATUSES
        ):
            raise HTTPException(
                status_code=400, detail="Invalid Easy Transact webhook payload"
            )
        intent = (
            self.db.query(PaymentIntent)
            .filter(PaymentIntent.vendor_reference == vendor_reference)
            .first()
        )
        if intent is None:
            raise HTTPException(status_code=404, detail="Payment intent not found")
        config = self.configuration(intent.restaurant_id)
        self.verify_webhook(raw_body, signature, config)
        duplicate = self._apply_provider_status(
            intent, provider_status, str(provider_event_id), payload, signature
        )
        return intent, duplicate

    def _apply_provider_status(
        self,
        intent: PaymentIntent,
        provider_status: str,
        provider_event_id: str,
        payload: dict[str, Any],
        signature: str | None,
    ) -> bool:
        """Apply one provider status to a payment; True when it was already applied.

        Shared by the signed webhook and by the on-demand refresh, so a payment whose
        webhook was lost ends up in exactly the same state.
        """
        existing = (
            self.db.query(PaymentEvent)
            .filter(PaymentEvent.provider_event_id == provider_event_id)
            .first()
        )
        if existing:
            return True

        previous = intent.status
        if previous in TERMINAL_STATUSES and provider_status != previous:
            raise HTTPException(
                status_code=409,
                detail=f"Invalid payment transition from {previous} to {provider_status}",
            )

        event = PaymentEvent(
            payment_intent_id=intent.id,
            provider_event_id=provider_event_id,
            provider_status=provider_status,
            raw_payload=payload,
            signature=signature,
        )
        self.db.add(event)
        if provider_status == "success" and previous != "success":
            if intent.commande_id is not None:
                CommandeService(self.db).confirm_payment(intent.commande_id, intent.id)
            self.db.add(
                PaymentLedgerEntry(
                    payment_intent_id=intent.id,
                    restaurant_id=intent.restaurant_id,
                    entry_type="capture",
                    amount_fcfa=intent.amount_fcfa,
                    currency=intent.currency,
                    idempotency_key=f"capture:{intent.id}",
                    reference=provider_event_id,
                )
            )
        self._absorb_details(intent, provider_status, payload)
        intent.status = provider_status
        event.processed_at = datetime.now(timezone.utc)
        self.db.flush()
        return False

    @staticmethod
    def _absorb_details(
        intent: PaymentIntent, provider_status: str, payload: dict[str, Any]
    ) -> None:
        """Retient ce que la passerelle communique (frais, fin, motif d'echec).

        Les noms de champs suivent la reponse documentee de l'endpoint de statut
        (``fees``, ``is_fees_inclusive``, ``completed_at``, ``provider_transaction_id``).
        Un champ absent ou invalide est ignore : on ne devine jamais une valeur.
        """
        fees = payload.get("fees")
        if fees is not None:
            try:
                intent.fees_fcfa = Decimal(str(fees))
            except (InvalidOperation, ValueError):
                pass
        if isinstance(payload.get("is_fees_inclusive"), bool):
            intent.fees_inclusive = payload["is_fees_inclusive"]
        completed = payload.get("completed_at")
        if isinstance(completed, str):
            try:
                intent.completed_at = datetime.fromisoformat(completed.replace("Z", "+00:00"))
            except ValueError:
                pass
        if intent.completed_at is None and provider_status in TERMINAL_STATUSES:
            intent.completed_at = datetime.now(timezone.utc)
        transaction_id = payload.get("provider_transaction_id")
        if isinstance(transaction_id, str) and transaction_id:
            intent.provider_transaction_id = transaction_id
        if provider_status in FAILURE_STATUSES:
            for key in ("failure_reason", "message", "reason", "error"):
                reason = payload.get(key)
                if isinstance(reason, str) and reason.strip():
                    intent.failure_reason = reason.strip()[:1000]
                    break

    # ------------------------------------------------ historique du restaurant
    @staticmethod
    def view(intent: PaymentIntent) -> dict[str, Any]:
        """Transaction telle que la voit le restaurant (reference, net a recevoir...)."""
        return {
            "id": intent.id,
            "restaurant_id": intent.restaurant_id,
            "reference": intent.vendor_reference,
            "status": intent.status,
            "amount_fcfa": intent.amount_fcfa,
            "currency": intent.currency,
            "fees_fcfa": intent.fees_fcfa,
            "net_amount_fcfa": net_amount_fcfa(
                intent.amount_fcfa, intent.fees_fcfa, intent.fees_inclusive
            )
            if intent.status == "success"
            else None,
            "commande_id": intent.commande_id,
            "subscription_id": intent.subscription_id,
            "provider_transaction_id": intent.provider_transaction_id,
            "failure_reason": intent.failure_reason,
            "created_at": intent.created_at,
            "completed_at": intent.completed_at,
        }

    def list_transactions(
        self,
        restaurant_id: uuid.UUID,
        *,
        statuses: Optional[Iterable[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        reference: Optional[str] = None,
        commande_id: Optional[uuid.UUID] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> Tuple[List[PaymentIntent], Optional[str]]:
        """Les transactions du restaurant, les plus recentes d'abord.

        Pagination par curseur (cle ``created_at, id``) : chaque page est une descente
        d'index plus ``limit`` lignes, que l'on soit a la page 1 ou a la page 500, et
        deux pages ne se recoupent jamais meme si de nouveaux paiements arrivent.
        """
        query = select(PaymentIntent).where(PaymentIntent.restaurant_id == restaurant_id)
        if statuses:
            wanted = {_status(s) for s in statuses}
            unknown = wanted - PROVIDER_STATUSES - {"manual_review"}
            if unknown:
                raise HTTPException(
                    status_code=400, detail=f"Unknown status: {sorted(unknown)}"
                )
            query = query.where(PaymentIntent.status.in_(wanted))
        if since is not None:
            query = query.where(PaymentIntent.created_at >= since)
        if until is not None:
            query = query.where(PaymentIntent.created_at < until)
        if reference and reference.strip():
            start = reference.strip()
            # L'intervalle est ce que l'index sait parcourir (LIKE, lui, ne peut pas
            # servir de condition d'index sous RLS) ; le LIKE reste pour la justesse,
            # car l'ordre d'une collation locale n'est pas celui des octets.
            query = query.where(
                PaymentIntent.vendor_reference >= start,
                PaymentIntent.vendor_reference < start[:-1] + chr(ord(start[-1]) + 1),
                PaymentIntent.vendor_reference.startswith(start, autoescape=True),
            )
        if commande_id is not None:
            query = query.where(PaymentIntent.commande_id == commande_id)
        if cursor:
            try:
                after_time, after_id = decode_cursor(cursor)
            except InvalidCursor as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            query = query.where(
                tuple_(PaymentIntent.created_at, PaymentIntent.id)
                < tuple_(after_time, after_id)
            )
        rows = (
            self.db.execute(
                query.order_by(PaymentIntent.created_at.desc(), PaymentIntent.id.desc()).limit(
                    limit + 1
                )
            )
            .scalars()
            .all()
        )
        items = rows[:limit]
        next_cursor = (
            encode_cursor(items[-1].created_at, items[-1].id)
            if len(rows) > limit and items
            else None
        )
        return items, next_cursor

    def summarize(
        self,
        restaurant_id: uuid.UUID,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Totaux par statut, calcules par la base en une seule requete."""
        collected_net = case(
            (
                (PaymentIntent.status == "success")
                & (PaymentIntent.fees_inclusive.is_(True))
                & (PaymentIntent.fees_fcfa.is_not(None)),
                PaymentIntent.amount_fcfa - PaymentIntent.fees_fcfa,
            ),
            (PaymentIntent.status == "success", PaymentIntent.amount_fcfa),
            else_=0,
        )
        success_fees = case(
            (PaymentIntent.status == "success", func.coalesce(PaymentIntent.fees_fcfa, 0)),
            else_=0,
        )
        query = select(
            PaymentIntent.status,
            func.count(PaymentIntent.id),
            func.coalesce(func.sum(PaymentIntent.amount_fcfa), 0),
            func.coalesce(func.sum(collected_net), 0),
            func.coalesce(func.sum(success_fees), 0),
        ).where(PaymentIntent.restaurant_id == restaurant_id)
        if since is not None:
            query = query.where(PaymentIntent.created_at >= since)
        if until is not None:
            query = query.where(PaymentIntent.created_at < until)
        rows = self.db.execute(query.group_by(PaymentIntent.status)).all()

        by_status = {
            status: {"count": count, "amount_fcfa": int(amount)}
            for status, count, amount, _net, _fees in rows
        }
        return {
            "since": since,
            "until": until,
            "currency": "XAF",
            "transactions": sum(v["count"] for v in by_status.values()),
            "by_status": by_status,
            "collected_fcfa": by_status.get("success", {}).get("amount_fcfa", 0),
            "fees_fcfa": sum((Decimal(str(fees)) for *_x, fees in rows), Decimal("0")),
            "net_collected_fcfa": sum((Decimal(str(net)) for _s, _c, _a, net, _f in rows), Decimal("0")),
        }

    def transaction_detail(self, intent: PaymentIntent) -> dict[str, Any]:
        events = (
            self.db.execute(
                select(PaymentEvent)
                .where(PaymentEvent.payment_intent_id == intent.id)
                .order_by(PaymentEvent.received_at, PaymentEvent.id)
            )
            .scalars()
            .all()
        )
        return {
            **self.view(intent),
            "checkout_url": intent.checkout_url,
            "expires_at": intent.expires_at,
            "events": [
                {
                    "status": e.provider_status,
                    "received_at": e.received_at,
                    "processed_at": e.processed_at,
                }
                for e in events
            ],
        }

    def refresh_from_gateway(self, intent: PaymentIntent) -> PaymentIntent:
        """Interroge la passerelle pour un paiement dont le webhook n'est pas arrive.

        Le resultat suit exactement le chemin du webhook : meme transitions
        autorisees, meme effet sur la commande et le journal. En cas d'erreur ou de
        reponse incoherente, RIEN n'est modifie.
        """
        config = self.configuration(intent.restaurant_id)
        try:
            data = EasyTransactClient.from_settings(
                self._credential_for(config)
            ).get_transaction_status(vendor_reference=intent.vendor_reference)
        except EasyTransactError as exc:
            not_configured = "not configured" in str(exc)
            raise HTTPException(
                status_code=503 if not_configured else 502,
                detail="Easy Transact status lookup is not available"
                if not_configured
                else "Easy Transact status lookup failed",
            ) from exc
        provider_status = _status(str(data.get("status", "")))
        reported = data.get("vendor_reference")
        if provider_status not in PROVIDER_STATUSES or reported not in (
            None,
            intent.vendor_reference,
        ):
            raise HTTPException(
                status_code=502, detail="Easy Transact returned an unexpected status"
            )
        self._apply_provider_status(
            intent, provider_status, f"poll:{intent.id}:{provider_status}", data, None
        )
        return intent
