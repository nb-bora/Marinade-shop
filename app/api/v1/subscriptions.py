from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.services.subscription_service import SubscriptionService
from app.schemas.subscription import (
    SubscriptionTierResponse,
    SubscriptionTierCreate,
    SubscriptionTierUpdate,
    SubscriptionResponse,
    SubscriptionCreate,
    SubscriptionUpdate,
    DailyBalanceResponse,
    DailyBalanceCreate,
    DailyBalanceUpdate,
)
from app.api.dependencies import get_current_user, require_admin
import uuid

router = APIRouter(prefix="/subscriptions")


# Subscription Tiers
@router.get(
    "/tiers",
    response_model=List[SubscriptionTierResponse],
    tags=["subscription-tiers"],
    summary="Lister les offres d’abonnement",
    description="""
    Retourne les offres disponibles dans le système.

    Chaque tier définit une limite quotidienne et des prix associés selon la durée d’abonnement.
    Cette route est généralement utilisée pour présenter les options aux clients avant leur souscription.
    """,
    responses={200: {"description": "Offres récupérées avec succès."}},
)
def get_tiers(db: Session = Depends(get_db)):
    subscription_service = SubscriptionService(db)
    return subscription_service.get_all_tiers()


@router.get(
    "/tiers/{tier_id}",
    response_model=SubscriptionTierResponse,
    tags=["subscription-tiers"],
    summary="Détails d’un tier d’abonnement",
    description="""
    Récupère une offre d’abonnement précise selon son identifiant.

    Le tier regroupe les caractéristiques commerciales et de limite du service pour un niveau donné.
    """,
    responses={
        200: {"description": "Tier trouvé."},
        404: {"description": "Tier introuvable."},
    },
)
def get_tier(tier_id: int, db: Session = Depends(get_db)):
    subscription_service = SubscriptionService(db)
    tier = subscription_service.get_tier(tier_id)
    if not tier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found"
        )
    return tier


@router.post(
    "/tiers",
    response_model=SubscriptionTierResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["subscription-tiers"],
    summary="Créer un tier d’abonnement",
    description="""
    Crée une nouvelle offre commerciale pour les abonnements.

    Cela permet de définir une limite quotidienne et les montants associés à un niveau d’abonnement.
    """,
    responses={
        201: {"description": "Tier créé avec succès."},
        400: {"description": "Données invalides."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
    },
)
def create_tier(
    tier_data: SubscriptionTierCreate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    subscription_service = SubscriptionService(db)
    try:
        return subscription_service.create_tier(tier_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put(
    "/tiers/{tier_id}",
    response_model=SubscriptionTierResponse,
    tags=["subscription-tiers"],
    summary="Modifier un tier d’abonnement",
    description="""
    Met à jour les propriétés d’un tier déjà existant.

    Cela permet d’ajuster le prix, la limite quotidienne ou l’état actif/inactif d’une offre.
    """,
    responses={
        200: {"description": "Tier mis à jour."},
        400: {"description": "Données invalides."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
        404: {"description": "Tier introuvable."},
    },
)
def update_tier(
    tier_id: int,
    tier_data: SubscriptionTierUpdate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    subscription_service = SubscriptionService(db)
    try:
        tier = subscription_service.update_tier(
            tier_id, tier_data.model_dump(exclude_unset=True)
        )
        if not tier:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found"
            )
        return tier
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Subscriptions
@router.get(
    "/me",
    response_model=SubscriptionResponse,
    tags=["subscriptions"],
    summary="Voir mon abonnement",
    description="""
    Retourne l’abonnement actif de l’utilisateur authentifié.

    Cette route est utilisée pour vérifier le niveau souscrit, l’état actuel et les informations associées.
    """,
    responses={
        200: {"description": "Abonnement trouvé."},
        401: {"description": "Token absent ou invalide."},
        404: {"description": "Aucun abonnement trouvé pour l’utilisateur."},
    },
)
def get_my_subscription(
    current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    subscription_service = SubscriptionService(db)
    subscription = subscription_service.get_user_subscription(current_user.id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active subscription found"
        )
    return subscription


@router.get(
    "/{subscription_id}",
    response_model=SubscriptionResponse,
    tags=["subscriptions"],
    summary="Détails d’un abonnement",
    description="""
    Récupère les informations détaillées d’un abonnement identifié par son UUID.

    Cette route est orientée administration afin de surveiller le statut et l’état des souscriptions propriétaires.
    """,
    responses={
        200: {"description": "Abonnement trouvé."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
        404: {"description": "Abonnement introuvable."},
    },
)
def get_subscription(
    subscription_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    subscription_service = SubscriptionService(db)
    subscription = subscription_service.get_subscription(subscription_id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found"
        )
    return subscription


@router.post(
    "",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["subscriptions"],
    summary="Créer un abonnement",
    description="""
    Crée une souscription pour un utilisateur sur un tier donné.

    Cette opération initialise le cycle de vie d’un abonnement, le statut et les soldes associés.
    """,
    responses={
        201: {"description": "Abonnement créé avec succès."},
        400: {"description": "Données invalides ou logique métier non respectée."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
    },
)
def create_subscription(
    subscription_data: SubscriptionCreate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    subscription_service = SubscriptionService(db)
    try:
        return subscription_service.create_subscription(subscription_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put(
    "/{subscription_id}/status",
    response_model=SubscriptionResponse,
    tags=["subscriptions"],
    summary="Mettre à jour le statut d’un abonnement",
    description="""
    Modifie le statut d’un abonnement existant : active, suspended, cancelled, expired, etc.

    Cette route est réservée à l’administration pour contrôler le cycle de vie commercial de la souscription.
    """,
    responses={
        200: {"description": "Statut mis à jour."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
        404: {"description": "Abonnement introuvable."},
    },
)
def update_subscription_status(
    subscription_id: uuid.UUID,
    status: str,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    subscription_service = SubscriptionService(db)
    subscription = subscription_service.update_subscription_status(
        subscription_id, status
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found"
        )
    return subscription


# Daily Balances
@router.get(
    "/{subscription_id}/balances",
    response_model=List[DailyBalanceResponse],
    tags=["subscription-balances"],
    summary="Historique des soldes quotidiens",
    description="""
    Retourne les soldes quotidiens associés à un abonnement.

    Chaque entrée représente le solde d’un jour particulier et permet de contrôler les consommations ou les réinitialisations.
    """,
    responses={
        200: {"description": "Soldes récupérés avec succès."},
        401: {"description": "Token absent ou invalide."},
        404: {"description": "Abonnement introuvable."},
    },
)
def get_subscription_balances(
    subscription_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.repositories.subscription_repository import DailyBalanceRepository

    balance_repo = DailyBalanceRepository(db)
    return balance_repo.get_by_subscription_id(subscription_id)


@router.get(
    "/{subscription_id}/balances/current",
    response_model=DailyBalanceResponse,
    tags=["subscription-balances"],
    summary="Solde quotidien courant",
    description="""
    Retourne le solde du jour en cours pour un abonnement donné.

    Cette information est essentielle pour connaître la consommation restante et décider d’une autorisation de transaction.
    """,
    responses={
        200: {"description": "Solde courant récupéré."},
        401: {"description": "Token absent ou invalide."},
        404: {"description": "Aucun solde courant trouvé."},
    },
)
def get_current_balance(
    subscription_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subscription_service = SubscriptionService(db)
    balance = subscription_service.get_current_balance(subscription_id)
    if not balance:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No current balance found"
        )
    return balance


@router.post(
    "/{subscription_id}/balances",
    response_model=DailyBalanceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["subscription-balances"],
    summary="Créer un solde quotidien",
    description="""
    Crée une entrée de solde quotidien pour un abonnement donné.

    Cette route sert à enregistrer les limites et les consommations actuelles d’un jour précis.
    """,
    responses={
        201: {"description": "Solde quotidien créé."},
        400: {"description": "Données invalides."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
    },
)
def create_daily_balance(
    subscription_id: uuid.UUID,
    balance_data: DailyBalanceCreate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    subscription_service = SubscriptionService(db)
    balance_data.subscription_id = subscription_id
    try:
        return subscription_service.create_daily_balance(balance_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{subscription_id}/reset",
    response_model=DailyBalanceResponse,
    tags=["subscription-balances"],
    summary="Réinitialiser le solde quotidien",
    description="""
    Réinitialise le solde d’un abonnement pour une nouvelle journée.

    Cette opération est utilisée pour repartir sur un nouveau cycle de consommation et est souvent déclenchée à minuit ou à la gestion quotidienne.
    """,
    responses={
        200: {"description": "Réinitialisation effectuée."},
        400: {"description": "Erreur de logique métier ou abonnement invalide."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
    },
)
def reset_daily_balance(
    subscription_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    subscription_service = SubscriptionService(db)
    try:
        return subscription_service.process_daily_reset(subscription_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
