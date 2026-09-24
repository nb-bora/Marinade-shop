from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_payment_intent_access, require_restaurant_access, set_db_context
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
        require_restaurant_access(data.restaurant_id, current_user, db)
        return EasyTransactPaymentService(db).upsert_configuration(data)
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
        require_restaurant_access(data.restaurant_id, current_user, db)
        intent = EasyTransactPaymentService(db).create_checkout(data)
        response.status_code = status.HTTP_201_CREATED if intent.status == "initiated" else status.HTTP_200_OK
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
        require_restaurant_access(data.restaurant_id, current_user, db)
        return EasyTransactPaymentService(db).initiate(data)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{payment_intent_id}/status", response_model=PaymentIntentResponse)
def get_payment_status(
    payment_intent_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    intent: PaymentIntent = require_payment_intent_access(payment_intent_id, current_user, db)
    return intent


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
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    signature = request.headers.get(settings.EASYTRANSACT_WEBHOOK_SIGNATURE_HEADER)
    intent, duplicate = EasyTransactPaymentService(db).process_webhook(payload, raw_body, signature)
    if intent.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="Payment intent not found")
    return {"accepted": True, "duplicate": duplicate, "status": intent.status}


# Kept as an explicit rejection rather than an unscoped webhook. A provider must
# call the tenant-specific URL so the database can establish RLS context.
@router.post("/webhook", response_model=EasyTransactWebhookResponse)
async def unscoped_webhook(request: Request):
    raise HTTPException(status_code=400, detail="A tenant-specific webhook URL is required")
