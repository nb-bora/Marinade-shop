from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.services.user_service import UserService
from app.schemas.user import UserResponse, UserCreate, UserUpdate
from app.api.dependencies import get_current_user, require_admin
import uuid

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "",
    response_model=List[UserResponse],
    summary="Lister les utilisateurs",
    description="""
    Retourne la liste paginée des comptes utilisateurs du système.

    Cette route est réservée aux administrateurs. Elle permet de filtrer les résultats via `skip` et `limit`.
    """,
    responses={
        200: {"description": "Liste des utilisateurs récupérée avec succès."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "L’utilisateur n’a pas les droits administrateurs."},
    },
)
def get_users(
    skip: int = 0,
    limit: int = 100,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_service = UserService(db)
    return user_service.get_all_users(skip, limit)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Voir mon profil",
    description="""
    Retourne le profil complet de l’utilisateur authentifié.

    Cette route est utile pour récupérer les informations du compte courant sans devoir savoir son identifiant explicite.
    """,
    responses={
        200: {"description": "Profil utilisateur récupéré avec succès."},
        401: {"description": "Token absent ou invalide."},
    },
)
def get_current_user_info(current_user=Depends(get_current_user)):
    return current_user


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Détails d’un utilisateur",
    description="""
    Récupère les informations d’un utilisateur particulier à partir de son identifiant unique.

    Cette route est réservée aux administrateurs pour le support et la gestion des comptes.
    """,
    responses={
        200: {"description": "Utilisateur trouvé."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
        404: {"description": "Utilisateur introuvable."},
    },
)
def get_user(
    user_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_service = UserService(db)
    user = user_service.get_user(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un utilisateur",
    description="""
    Crée un nouveau compte utilisateur directement via l’interface d’administration.

    Cette route est réservée aux admins, contrairement à la route d’inscription publique qui est dédiée aux utilisateurs finaux.
    """,
    responses={
        201: {"description": "Utilisateur créé avec succès."},
        400: {"description": "Données de création invalides."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
    },
)
def create_user(
    user_data: UserCreate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_service = UserService(db)
    try:
        return user_service.create_user(user_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    summary="Mettre à jour un utilisateur",
    description="""
    Modifie les informations d’un utilisateur existant.

    Cette route est stricte pour les administrateurs et sert à maintenir la cohérence des profils, rôles et coordonnées de contact.
    """,
    responses={
        200: {"description": "Utilisateur mis à jour."},
        400: {"description": "Données invalides ou format incorrect."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
        404: {"description": "Utilisateur introuvable."},
    },
)
def update_user(
    user_id: uuid.UUID,
    user_data: UserUpdate,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_service = UserService(db)
    try:
        user = user_service.update_user(user_id, user_data)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer un utilisateur",
    description="""
    Supprime définitivement un utilisateur du système.

    Cette action est irréversible et ne doit être utilisée que dans le cadre d’une gestion administrative stricte.
    """,
    responses={
        204: {"description": "Utilisateur supprimé avec succès."},
        401: {"description": "Token absent ou invalide."},
        403: {"description": "Accès interdit : droits insuffisants."},
        404: {"description": "Utilisateur introuvable."},
    },
)
def delete_user(
    user_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_service = UserService(db)
    if not user_service.delete_user(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return None
