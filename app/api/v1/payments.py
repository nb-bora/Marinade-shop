from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api import permissions as perm
from app.api.dependencies import (
    current_tenant_id,
    ensure_tenant_role,
    get_current_user,
    require_payment_intent_access,
    set_db_context,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.payment import PaymentIntent
from app.schemas.payment import (
    EasyTransactCheckoutCreate,
    EasyTransactInitiateRequest,
    EasyTransactWebhookResponse,
    PaymentConfigurationResponse,
    PaymentConfigurationUpsert,
    PaymentIntentResponse,
    PaymentSummaryResponse,
    PaymentTransactionDetail,
    PaymentTransactionPage,
    PaymentTransactionResponse,
)
from app.services.easy_transact_service import EasyTransactPaymentService

router = APIRouter(prefix="/payments/easytransact", tags=["payments"])


@router.put("/configuration", response_model=PaymentConfigurationResponse)
def upsert_configuration(
    data: PaymentConfigurationUpsert,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        # Seul le management d'un restaurant (ou un admin plateforme) change sa
        # configuration de paiement ; un serveur ou un caissier ne le peut pas.
        ensure_tenant_role(
            db, current_user, data.restaurant_id, perm.MANAGEMENT_ROLES
        )
        return EasyTransactPaymentService(db).upsert_configuration(
            data, allow_custom_env_keys=current_user.role == "admin"
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/checkout", response_model=PaymentIntentResponse)
def create_checkout(
    data: EasyTransactCheckoutCreate,
    response: Response,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ensure_tenant_role(db, current_user, data.restaurant_id, perm.CASH_DESK_ROLES)
        intent = EasyTransactPaymentService(db).create_checkout(data)
        response.status_code = (
            status.HTTP_201_CREATED
            if intent.status == "initiated"
            else status.HTTP_200_OK
        )
        return intent
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/initiate")
def initiate_transaction(
    data: EasyTransactInitiateRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        ensure_tenant_role(db, current_user, data.restaurant_id, perm.CASH_DESK_ROLES)
        return EasyTransactPaymentService(db).initiate(data)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _restaurant_of_request(
    db: Session, user, restaurant_id: Optional[uuid.UUID]
) -> uuid.UUID:
    """Restaurant dont on lit les transactions : `restaurant_id`, sinon celui de la
    requete (X-Tenant-ID ou restaurant du compte). Reserve a la caisse et au management :
    les transactions sont de l'argent."""
    restaurant_id = restaurant_id or current_tenant_id(db)
    if restaurant_id is None:
        raise HTTPException(
            status_code=400, detail="restaurant_id (or X-Tenant-ID) is required"
        )
    ensure_tenant_role(db, user, restaurant_id, perm.CASH_DESK_ROLES)
    return restaurant_id


def _intent_for_cash_desk(
    db: Session, user, payment_intent_id: uuid.UUID
) -> PaymentIntent:
    intent = require_payment_intent_access(payment_intent_id, user, db)
    ensure_tenant_role(db, user, intent.restaurant_id, perm.CASH_DESK_ROLES)
    return intent


@router.get(
    "/transactions",
    response_model=PaymentTransactionPage,
    summary="Mes transactions (les plus récentes d'abord)",
    description=(
        "Lu dans la base de Marinade, jamais chez la passerelle : la réponse ne dépend "
        "ni du réseau ni du nombre total de transactions. Pagination par curseur : "
        "renvoyer `next_cursor` dans `?cursor=` pour la page suivante."
    ),
)
def list_transactions(
    restaurant_id: Optional[uuid.UUID] = None,
    statuses: Optional[List[str]] = Query(None, alias="status"),
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
    reference: Optional[str] = Query(
        None, max_length=100, description="Début de référence (ex. le préfixe du restaurant)"
    ),
    commande_id: Optional[uuid.UUID] = None,
    cursor: Optional[str] = Query(None, max_length=300),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    restaurant_id = _restaurant_of_request(db, current_user, restaurant_id)
    service = EasyTransactPaymentService(db)
    items, next_cursor = service.list_transactions(
        restaurant_id,
        statuses=statuses,
        since=date_from,
        until=date_to,
        reference=reference,
        commande_id=commande_id,
        cursor=cursor,
        limit=limit,
    )
    return {"items": [service.view(i) for i in items], "next_cursor": next_cursor}


@router.get(
    "/transactions/summary",
    response_model=PaymentSummaryResponse,
    summary="Totaux de mes transactions par statut",
)
def transactions_summary(
    restaurant_id: Optional[uuid.UUID] = None,
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    restaurant_id = _restaurant_of_request(db, current_user, restaurant_id)
    return EasyTransactPaymentService(db).summarize(
        restaurant_id, since=date_from, until=date_to
    )


@router.get(
    "/transactions/{payment_intent_id}",
    response_model=PaymentTransactionDetail,
    summary="Détail d'une transaction et historique de ses statuts",
)
def get_transaction(
    payment_intent_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    intent = _intent_for_cash_desk(db, current_user, payment_intent_id)
    return EasyTransactPaymentService(db).transaction_detail(intent)


@router.post(
    "/transactions/{payment_intent_id}/refresh",
    response_model=PaymentTransactionResponse,
    summary="Redemander son statut à la passerelle",
    description=(
        "Pour un paiement dont le webhook n'est jamais arrivé. Le résultat suit le même "
        "chemin que le webhook ; en cas d'erreur de la passerelle, rien n'est modifié."
    ),
)
def refresh_transaction(
    payment_intent_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    intent = _intent_for_cash_desk(db, current_user, payment_intent_id)
    service = EasyTransactPaymentService(db)
    return service.view(service.refresh_from_gateway(intent))


@router.get("/{payment_intent_id}/status", response_model=PaymentIntentResponse)
def get_payment_status(
    payment_intent_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _intent_for_cash_desk(db, current_user, payment_intent_id)


@router.post("/webhook/{restaurant_id}", response_model=EasyTransactWebhookResponse)
async def webhook(
    restaurant_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    if len(raw_body) > settings.EASYTRANSACT_WEBHOOK_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload too large")
    # The webhook URL is tenant-specific. Set the transaction-local RLS context
    # before looking up the payment configuration; the signature is still
    # mandatory and is verified against that tenant's secret.
    set_db_context(db, "app.current_tenant_id", str(restaurant_id))
    signature = request.headers.get(settings.EASYTRANSACT_WEBHOOK_SIGNATURE_HEADER)
    service = EasyTransactPaymentService(db)
    service.authenticate_webhook(restaurant_id, raw_body, signature)
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    intent, duplicate = service.process_webhook(payload, raw_body, signature)
    if intent.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    return {"accepted": True, "duplicate": duplicate, "status": intent.status}
