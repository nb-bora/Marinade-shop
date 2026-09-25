from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.services.transaction_service import TransactionService
from app.schemas.transaction import TransactionResponse, TransactionCreate
from app.api.dependencies import get_current_user, require_pos
import uuid

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une transaction",
    description="""
    Enregistre une nouvelle transaction commerciale lié à un abonnement.

    Cette route est généralement utilisée par les terminaux de paiement (POS) ou les systèmes internes.
    Elle valide le montant, l’unicité de la clé d’idempotence et la conformité du solde disponible.
    """,
    responses={
        201: {"description": "Transaction créée avec succès."},
        400: {"description": "Données invalides ou logique financière non respectée."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : le rôle POS est requis."},
    },
)
def create_transaction(
    transaction_data: TransactionCreate,
    current_user=Depends(require_pos),
    db: Session = Depends(get_db),
):
    transaction_service = TransactionService(db)
    try:
        return transaction_service.create_transaction(transaction_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/subscription/{subscription_id}",
    response_model=List[TransactionResponse],
    summary="Historique des transactions d’un abonnement",
    description="""
    Retourne l’historique des transactions liées à un abonnement donné.

    Ce flux est utile pour le suivi financier, la vérification des achats et l’analyse des consommations d’un client.
    """,
    responses={
        200: {"description": "Transactions récupérées avec succès."},
        401: {"description": "Token absent ou invalide."},
        404: {"description": "Abonnement introuvable."},
    },
)
def get_subscription_transactions(
    subscription_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transaction_service = TransactionService(db)
    return transaction_service.get_subscription_transactions(
        subscription_id, skip, limit
    )


@router.get(
    "/pos/{pos_transaction_id}",
    response_model=TransactionResponse,
    summary="Rechercher une transaction du terminal POS",
    description="""
    Retourne une transaction à partir de l’identifiant unique fourni par le terminal de paiement.

    Cela permet au système POS de retrouver rapidement une transaction déjà enregistrée et d’éviter les doublons.
    """,
    responses={
        200: {"description": "Transaction trouvée."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : rôle POS requis."},
        404: {"description": "Transaction introuvable."},
    },
)
def get_transaction_by_pos_id(
    pos_transaction_id: str,
    current_user=Depends(require_pos),
    db: Session = Depends(get_db),
):
    transaction_service = TransactionService(db)
    transaction = transaction_service.get_transaction_by_pos_id(pos_transaction_id)
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )
    return transaction


@router.get(
    "/my",
    response_model=List[TransactionResponse],
    summary="Mes transactions",
    description="""
    Retourne les transactions de l’utilisateur authentifié.

    Cette route permet de répertorier sa propre activité d’achat ou de paiement, avec pagination pour les grands volumes.
    """,
    responses={
        200: {"description": "Transactions de l’utilisateur récupérées avec succès."},
        401: {"description": "Token absent ou invalide."},
    },
)
def get_my_transactions(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transaction_service = TransactionService(db)
    return transaction_service.get_user_transactions(current_user.id, skip, limit)


@router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    summary="Détails d’une transaction",
    description="""
    Récupère les informations détaillées d’une transaction à partir de son identifiant UUID.

    Cette route est utile pour le support, l’audit et le suivi financier d’une opération donnée.
    """,
    responses={
        200: {"description": "Transaction trouvée."},
        401: {"description": "Token absent ou invalide."},
        404: {"description": "Transaction introuvable."},
    },
)
def get_transaction(
    transaction_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transaction_service = TransactionService(db)
    transaction = transaction_service.get_transaction(transaction_id)
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found"
        )
    return transaction
