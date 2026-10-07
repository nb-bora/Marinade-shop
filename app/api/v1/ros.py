from fastapi import (
    APIRouter,
    Depends,
    status,
    Query,
    Header,
    WebSocket,
    WebSocketDisconnect,
)
from app.utils.ws_manager import kds_manager

from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.dependencies import (
    authenticate_websocket,
    ensure_tenant_role,
    get_current_user,
    has_tenant_role,
    require_tenant_path,
)
from app.models.user import User
from app.services.ros_service import RosService
from app.schemas.ros import (
    CustomerCreate,
    CustomerResponse,
    SessionCreate,
    SessionResponse,
    OrderCreate,
    OrderResponse,
    TicketResponse,
    TicketStatusUpdate,
    InvoiceResponse,
    PaymentCreate,
    PaymentResponse,
    SplitPaymentRequest,
    ShiftOpenRequest,
    ShiftCloseRequest,
    ShiftResponse,
    SyncBatchRequest,
    SyncBatchResponse,
    ProcurementSuggestionResponse,
    GroupReportingResponse,
)

from app.utils.ros_enums import ProductionStation

from app.api import permissions as perm  # noqa: E402
from app.api.pagination import Page, page_params  # noqa: E402

# Fail-safe : toute route de ce routeur qui désigne un restaurant est d'abord
# autorisée sur CE restaurant, même si l'on oublie d'y ajouter un contrôle de rôle.
router = APIRouter(
    prefix="/ros",
    tags=["restaurant-operating-system"],
    dependencies=[Depends(require_tenant_path)],
)

# Routeur distinct : FastAPI applique les dépendances d'un routeur à ses
# WebSockets, or celles-ci attendent un en-tête Authorization qu'un navigateur ne
# peut pas envoyer. Le WebSocket s'authentifie lui-même (voir authenticate_websocket).
ws_router = APIRouter(prefix="/ros", tags=["restaurant-operating-system"])


# -----------------------------------------------------------------------------
# CUSTOMER ENDPOINTS
# -----------------------------------------------------------------------------
@router.post(
    "/restaurants/{restaurant_id}/customers",
    dependencies=[Depends(perm.FRONT_OF_HOUSE)],
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un client (Guest, VIP, Business ou Enregistré)",
)
def create_customer(
    restaurant_id: UUID,
    data: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.create_customer(restaurant_id, data)


# -----------------------------------------------------------------------------
# SERVICE SESSION ENDPOINTS
# -----------------------------------------------------------------------------
@router.post(
    "/restaurants/{restaurant_id}/sessions",
    dependencies=[Depends(perm.FRONT_OF_HOUSE)],
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ouvrir une session de consommation (avec ou sans table)",
)
def open_session(
    restaurant_id: UUID,
    data: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.open_session(restaurant_id, data)


@router.get(
    "/restaurants/{restaurant_id}/sessions",
    dependencies=[Depends(perm.FRONT_OF_HOUSE)],
    response_model=List[SessionResponse],
    summary="Obtenir toutes les sessions actives d'un établissement",
)
def get_active_sessions(
    restaurant_id: UUID,
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.get_active_sessions(restaurant_id, page.skip, page.limit)


@router.post(
    "/restaurants/{restaurant_id}/sessions/{session_id}/close",
    dependencies=[Depends(perm.FRONT_OF_HOUSE)],
    response_model=SessionResponse,
    summary="Clôturer une session de consommation",
)
def close_session(
    restaurant_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.close_session(restaurant_id, session_id, current_user.id)


# -----------------------------------------------------------------------------
# ORDER ENGINE ENDPOINTS
# -----------------------------------------------------------------------------
@router.post(
    "/restaurants/{restaurant_id}/orders",
    dependencies=[Depends(perm.FRONT_OF_HOUSE)],
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une commande (Prepaid / Postpaid avec routage automatique)",
)
def create_order(
    restaurant_id: UUID,
    data: OrderCreate,
    x_idempotency_key: Optional[UUID] = Header(None, alias="X-Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if x_idempotency_key and not data.idempotency_key:
        data.idempotency_key = x_idempotency_key

    service = RosService(db)
    order = service.create_order(
        restaurant_id,
        data,
        allow_custom_price=has_tenant_role(
            db, current_user, restaurant_id, perm.MANAGEMENT_ROLES
        ),
    )
    invoice = service.get_invoice_for_order(order)
    response = OrderResponse.model_validate(order)
    if invoice is not None:
        response = response.model_copy(
            update={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number}
        )
    return response


@router.get(
    "/restaurants/{restaurant_id}/invoices/{invoice_id}",
    dependencies=[Depends(perm.FRONT_OF_HOUSE)],
    response_model=InvoiceResponse,
    summary="Consulter une facture (montant payé et reste dû)",
)
def get_invoice(
    restaurant_id: UUID,
    invoice_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return RosService(db).get_invoice(restaurant_id, invoice_id)


@router.get(
    "/restaurants/{restaurant_id}/sessions/{session_id}/invoice",
    dependencies=[Depends(perm.FRONT_OF_HOUSE)],
    response_model=InvoiceResponse,
    summary="Facture d'une session (l'addition de la table)",
)
def get_session_invoice(
    restaurant_id: UUID,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return RosService(db).get_session_invoice(restaurant_id, session_id)


# -----------------------------------------------------------------------------
# KITCHEN & BAR DISPLAY (KDS) ENDPOINTS
# -----------------------------------------------------------------------------
@router.get(
    "/restaurants/{restaurant_id}/tickets/{station}",
    dependencies=[Depends(perm.PRODUCTION_TICKETS)],
    response_model=List[TicketResponse],
    summary="Obtenir les tickets en attente pour une station (KITCHEN, BAR, DESSERT)",
)
def get_pending_tickets(
    restaurant_id: UUID,
    station: ProductionStation,
    page: Page = Depends(page_params),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.get_pending_tickets(restaurant_id, station, page.skip, page.limit)


@router.put(
    "/restaurants/{restaurant_id}/tickets/{ticket_id}/status",
    dependencies=[Depends(perm.PRODUCTION_TICKETS)],
    response_model=TicketResponse,
    summary="Mettre à jour le statut d'un ticket de production (QUEUED, IN_PREPARATION, READY, SERVED)",
)
def update_ticket_status(
    restaurant_id: UUID,
    ticket_id: UUID,
    data: TicketStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.update_ticket_status(restaurant_id, ticket_id, data.status)


# -----------------------------------------------------------------------------
# PAYMENT & SPLIT BILL ENDPOINTS
# -----------------------------------------------------------------------------
@router.post(
    "/restaurants/{restaurant_id}/payments",
    dependencies=[Depends(perm.CASH_DESK)],
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Effectuer un encaissement (Cash, Mobile Money, Card) avec idempotence",
)
def process_payment(
    restaurant_id: UUID,
    data: PaymentCreate,
    x_idempotency_key: Optional[UUID] = Header(None, alias="X-Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if x_idempotency_key and not data.idempotency_key:
        data.idempotency_key = x_idempotency_key

    service = RosService(db)
    return service.process_payment(restaurant_id, data, current_user.id)


@router.post(
    "/restaurants/{restaurant_id}/payments/split",
    dependencies=[Depends(perm.CASH_DESK)],
    response_model=List[PaymentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Effectuer un encaissement divisé (Split bill multi-méthodes)",
)
def process_split_payment(
    restaurant_id: UUID,
    data: SplitPaymentRequest,
    x_idempotency_key: Optional[UUID] = Header(None, alias="X-Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if x_idempotency_key and not data.idempotency_key:
        data.idempotency_key = x_idempotency_key

    service = RosService(db)
    return service.process_split_payment(restaurant_id, data, current_user.id)


# -----------------------------------------------------------------------------
# CASH SHIFT ENDPOINTS
# -----------------------------------------------------------------------------
@router.post(
    "/restaurants/{restaurant_id}/shifts/open",
    dependencies=[Depends(perm.CASH_DESK)],
    response_model=ShiftResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ouvrir un shift de caisse opérateur",
)
def open_shift(
    restaurant_id: UUID,
    data: ShiftOpenRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.open_shift(restaurant_id, current_user.id, data)


@router.post(
    "/restaurants/{restaurant_id}/shifts/close",
    dependencies=[Depends(perm.CASH_DESK)],
    response_model=ShiftResponse,
    summary="Clôturer un shift de caisse avec audit des écarts",
)
def close_shift(
    restaurant_id: UUID,
    data: ShiftCloseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.close_shift(restaurant_id, current_user.id, data)


# -----------------------------------------------------------------------------
# OFFLINE SYNC BATCH REPLAY
# -----------------------------------------------------------------------------
@router.post(
    "/restaurants/{restaurant_id}/sync",
    dependencies=[Depends(perm.FRONT_OF_HOUSE)],
    response_model=SyncBatchResponse,
    summary="Synchroniser un lot de transactions effectuées hors-ligne (Outbox Replay)",
)
def sync_offline_batch(
    restaurant_id: UUID,
    data: SyncBatchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Un serveur peut resynchroniser ses commandes, mais pas encaisser : si le lot
    # contient des paiements, le rôle de caisse est exigé comme sur /payments.
    if data.payments:
        ensure_tenant_role(db, current_user, restaurant_id, perm.CASH_DESK_ROLES)
    service = RosService(db)
    return service.sync_offline_batch(
        restaurant_id,
        data.orders,
        data.payments,
        allow_custom_price=has_tenant_role(
            db, current_user, restaurant_id, perm.MANAGEMENT_ROLES
        ),
        received_by=current_user.id,
    )


# -----------------------------------------------------------------------------
# REAL-TIME KDS & BAR DISPLAY WEBSOCKET STREAM
# -----------------------------------------------------------------------------
@ws_router.websocket("/ws/kds/{restaurant_id}/{station}")
async def websocket_kds_endpoint(
    websocket: WebSocket, restaurant_id: UUID, station: ProductionStation
):
    # Refusé avant l'`accept` : le client reçoit une réponse HTTP 403 à la
    # poignée de main et aucune connexion n'est ouverte.
    subprotocol = await authenticate_websocket(
        websocket, restaurant_id, perm.PRODUCTION_ROLES
    )
    if subprotocol is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    rest_str = str(restaurant_id)
    station_str = station.value
    await kds_manager.connect(
        websocket, rest_str, station_str, subprotocol=subprotocol or None
    )
    try:
        while True:
            # Keep connection open and await ping/heartbeat from screen
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        kds_manager.disconnect(websocket, rest_str, station_str)


# -----------------------------------------------------------------------------
# AUTO-PROCUREMENT SUGGESTIONS ENDPOINT
# -----------------------------------------------------------------------------
@router.get(
    "/restaurants/{restaurant_id}/procurement/suggestions",
    dependencies=[Depends(perm.STOCK_KEEPING)],
    response_model=ProcurementSuggestionResponse,
    summary="Générer des propositions récursives de bon de commande fournisseur (Auto-Procurement)",
)
def generate_procurement_suggestions(
    restaurant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RosService(db)
    return service.generate_procurement_suggestions(restaurant_id)


# -----------------------------------------------------------------------------
# MULTI-SITE GROUP CONSOLIDATED REPORTING ENDPOINT
# -----------------------------------------------------------------------------
@router.get(
    "/group/reporting",
    response_model=GroupReportingResponse,
    summary="Obtenir le reporting consolidé multi-établissements du propriétaire (Holding Group)",
)
def get_group_consolidated_reporting(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    service = RosService(db)
    return service.get_group_consolidated_reporting(current_user.id)
