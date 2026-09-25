from app.api.dependencies import get_current_user, require_admin, require_tenant_path
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.services.restaurant_service import (
    RestaurantService,
    MenuService,
    PlatService,
    BoissonService,
    TableService,
    CommandeService,
    CombinaisonService,
    StockService,
    PlatComposantService,
)
from app.schemas.restaurant import (
    RestaurantResponse,
    RestaurantCreate,
    RestaurantUpdate,
    MenuResponse,
    MenuCreate,
    MenuUpdate,
    MenuCategoryResponse,
    MenuCategoryCreate,
    MenuCategoryUpdate,
    ComposantResponse,
    ComposantCreate,
    ComposantUpdate,
    StockComposantResponse,
    StockMouvementCreate,
    CombinaisonResponse,
    CombinaisonCreate,
    CombinaisonUpdate,
    PlatResponse,
    PlatCreate,
    PlatUpdate,
    PlatComposantResponse,
    PlatComposantCreate,
    PlatComposantUpdate,
    BoissonResponse,
    BoissonCreate,
    BoissonUpdate,
    TableResponse,
    TableCreate,
    TableUpdate,
    CommandeResponse,
    CommandeCreate,
    CommandeUpdate,
    CommandeItemResponse,
    CommandeItemCreate,
    CommandeRefundCreate,
    CommandeRefundResponse,
)
from app.utils.logging import get_logger
import uuid
import warnings

logger = get_logger(__name__)

router = APIRouter(prefix="/restaurants", dependencies=[Depends(require_tenant_path)])


_DEPRECATED_CMD_HEADER = {"X-Deprecated-Endpoint": "use-ros-orders"}


def _mark_deprecated_commande(request: Request, response: Response):
    warnings.warn(
        "Legacy Commande model is deprecated. Use ROS Orders (service_sessions → ros_orders) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning(
        "Deprecated legacy Commande endpoint called: %s %s by user=%s",
        request.method,
        request.url.path,
        request.headers.get("X-User-ID", "unknown"),
    )
    for k, v in _DEPRECATED_CMD_HEADER.items():
        response.headers[k] = v


# Restaurants
@router.post(
    "",
    response_model=RestaurantResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurants"],
    summary="Créer un restaurant",
    description="""
    Crée un restaurant associé à l’utilisateur authentifié.

    Un même utilisateur ne peut généralement pas posséder plusieurs restaurants actifs.
    Cette route sert à déclarer les informations principales du point de vente : nom, coordonnées, devise, description, ouverture, etc.
    """,
    responses={
        201: {"description": "Restaurant créé avec succès."},
        400: {
            "description": "Données invalides ou restaurant déjà existant pour cet utilisateur."
        },
        401: {"description": "Token JWT absent ou invalide."},
    },
)
def create_restaurant(
    restaurant_data: RestaurantCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    restaurant_service = RestaurantService(db)
    try:
        return restaurant_service.create_restaurant(restaurant_data, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/me",
    response_model=RestaurantResponse,
    tags=["restaurants"],
    summary="Voir mon restaurant",
    description="""
    Retourne le restaurant lié à l’utilisateur authentifié.

    Cette route est utile pour récupérer le profil du restaurant courant sans connaître son identifiant UUID.
    """,
    responses={
        200: {"description": "Restaurant trouvé."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Aucun restaurant associé à cet utilisateur."},
    },
)
def get_my_restaurant(
    current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    restaurant_service = RestaurantService(db)
    restaurant = restaurant_service.get_user_restaurant(current_user.id)
    if not restaurant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    return restaurant


@router.get(
    "/{restaurant_id}",
    response_model=RestaurantResponse,
    tags=["restaurants"],
    summary="Détails d’un restaurant",
    description="""
    Retourne les informations détaillées d’un restaurant donné.

    Cette route est utile pour consulter un restaurant par identifiant, notamment dans les flux d’administration ou de gestion des menus et commandes.
    """,
    responses={
        200: {"description": "Restaurant trouvé."},
        404: {"description": "Restaurant introuvable."},
    },
)
def get_restaurant(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    restaurant_service = RestaurantService(db)
    restaurant = restaurant_service.get_restaurant(restaurant_id)
    if not restaurant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    return restaurant


@router.put(
    "/{restaurant_id}",
    response_model=RestaurantResponse,
    tags=["restaurants"],
    summary="Mettre à jour un restaurant",
    description="""
    Met à jour les informations d’un restaurant existant.

    L’utilisateur doit être propriétaire du restaurant ou avoir le rôle administrateur pour modifier ses informations.
    """,
    responses={
        200: {"description": "Restaurant mis à jour."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit."},
        404: {"description": "Restaurant introuvable."},
    },
)
def update_restaurant(
    restaurant_id: uuid.UUID,
    restaurant_data: RestaurantUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    restaurant_service = RestaurantService(db)
    restaurant = restaurant_service.get_restaurant(restaurant_id)
    if not restaurant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )

    # Vérifier que l'utilisateur est le propriétaire ou admin
    if restaurant.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized"
        )

    try:
        updated_restaurant = restaurant_service.update_restaurant(
            restaurant_id, restaurant_data
        )
        if not updated_restaurant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
            )
        return updated_restaurant
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Menus
@router.post(
    "/{restaurant_id}/menus",
    response_model=MenuResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-menus"],
    summary="Créer un menu de restaurant",
    description="""
    Crée un menu associé à un restaurant.

    Un menu permet d’organiser les offres et de regrouper des catégories de plats pour une meilleure structure de carte.
    """,
    responses={
        201: {"description": "Menu créé avec succès."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
    },
)
def create_menu(
    restaurant_id: uuid.UUID,
    menu_data: MenuCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    menu_service = MenuService(db)
    try:
        return menu_service.create_menu(menu_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{restaurant_id}/menus",
    response_model=List[MenuResponse],
    tags=["restaurant-menus"],
    summary="Lister les menus d’un restaurant",
    description="""
    Retourne tous les menus associés à un restaurant donné.

    Cette route est utile pour alimenter la carte du restaurant et gérer les différentes offres proposées.
    """,
    responses={
        200: {"description": "Menus récupérés avec succès."},
        404: {"description": "Restaurant introuvable."},
    },
)
def get_restaurant_menus(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    menu_service = MenuService(db)
    return menu_service.get_restaurant_menus(restaurant_id)


@router.get(
    "/menus/{menu_id}",
    response_model=MenuResponse,
    tags=["restaurant-menus"],
    summary="Détails d’un menu",
    description="""
    Retourne les informations complètes d’un menu identifié par son UUID.

    Cette route est utilisée pour afficher la structure d’une carte, ses catégories et ses contenus détaillés sur un menu donné.
    """,
    responses={
        200: {"description": "Menu trouvé."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Menu introuvable."},
    },
)
def get_menu(menu_id: uuid.UUID, db: Session = Depends(get_db)):
    menu_service = MenuService(db)
    menu = menu_service.get_menu(menu_id)
    if not menu:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found"
        )
    return menu


@router.put(
    "/menus/{menu_id}",
    response_model=MenuResponse,
    tags=["restaurant-menus"],
    summary="Mettre à jour un menu",
    description="""
    Modifie les propriétés d’un menu existant.

    Cette route sert à ajuster le libellé, l’état, la visibilité ou toute autre donnée de gestion de la carte du restaurant.
    """,
    responses={
        200: {"description": "Menu mis à jour."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit."},
        404: {"description": "Menu introuvable."},
    },
)
def update_menu(
    menu_id: uuid.UUID,
    menu_data: MenuUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    menu_service = MenuService(db)
    try:
        updated_menu = menu_service.update_menu(menu_id, menu_data)
        if not updated_menu:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found"
            )
        return updated_menu
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Menu Categories
@router.post(
    "/menus/{menu_id}/categories",
    response_model=MenuCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-categories"],
    summary="Créer une catégorie de menu",
    description="""
    Ajoute une catégorie à un menu existant.

    Les catégories servent à organiser les plats et boissons selon le type de proposition : entrées, plats, desserts, boissons chaudes, etc.
    """,
    responses={
        201: {"description": "Catégorie créée avec succès."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Menu introuvable."},
    },
)
def create_menu_category(
    menu_id: uuid.UUID,
    category_data: MenuCategoryCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    menu_service = MenuService(db)
    try:
        return menu_service.create_category(category_data, menu_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/menus/{menu_id}/categories",
    response_model=List[MenuCategoryResponse],
    tags=["restaurant-categories"],
    summary="Lister les catégories d’un menu",
    description="""
    Retourne toutes les catégories associées à un menu donné.

    Cette route permet de reconstruire la structure de la carte du restaurant et d’afficher les sections de la carte dans l’ordre logique.
    """,
    responses={
        200: {"description": "Catégories récupérées avec succès."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Menu introuvable."},
    },
)
def get_menu_categories(menu_id: uuid.UUID, db: Session = Depends(get_db)):
    menu_service = MenuService(db)
    return menu_service.get_menu_categories(menu_id)


@router.put(
    "/categories/{category_id}",
    response_model=MenuCategoryResponse,
    tags=["restaurant-categories"],
    summary="Mettre à jour une catégorie de menu",
    description="""
    Modifie les détails d’une catégorie existante dans le système.

    Cette opération est utile pour renommer une section ou ajuster sa visibilité ou son ordre d’affichage sur la carte.
    """,
    responses={
        200: {"description": "Catégorie mise à jour."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit."},
        404: {"description": "Catégorie introuvable."},
    },
)
def update_menu_category(
    category_id: uuid.UUID,
    category_data: MenuCategoryUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    menu_service = MenuService(db)
    try:
        updated_category = menu_service.update_category(category_id, category_data)
        if not updated_category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Category not found"
            )
        return updated_category
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Composants et combinaisons
@router.post(
    "/{restaurant_id}/composants",
    response_model=ComposantResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-combinations"],
    summary="Créer un composant de plat",
    description="Enregistre un composant comme le riz, une sauce ou une protéine. Le composant peut être rendu indisponible lorsqu’il est épuisé.",
    responses={
        201: {"description": "Composant créé et stock initialisé à zéro."},
        400: {"description": "Données invalides ou restaurant introuvable."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit pour ce restaurant."},
    },
)
def create_composant(
    restaurant_id: uuid.UUID,
    composant_data: ComposantCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return CombinaisonService(db).create_composant(composant_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{restaurant_id}/composants",
    response_model=List[ComposantResponse],
    tags=["restaurant-combinations"],
    summary="Lister les composants d’un restaurant",
    description="Retourne les bases, sauces et protéines administrées pour construire les combinaisons de plats, avec leur disponibilité et leur prix de supplément.",
    responses={
        200: {"description": "Composants récupérés."},
        404: {"description": "Restaurant introuvable."},
    },
)
def get_restaurant_composants(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    return CombinaisonService(db).get_restaurant_composants(restaurant_id)


@router.get(
    "/{restaurant_id}/stock",
    response_model=List[StockComposantResponse],
    tags=["restaurant-stock"],
    summary="Consulter le stock des composants",
    description="Retourne le stock physique, le stock réservé et le stock réellement disponible pour chaque composant.",
    responses={
        200: {"description": "État du stock physique, réservé et disponible récupéré."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit pour ce restaurant."},
        404: {"description": "Restaurant introuvable."},
    },
)
def get_restaurant_stock(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    return StockService(db).get_restaurant_stock(restaurant_id)


@router.post(
    "/composants/{composant_id}/stock/mouvements",
    response_model=StockComposantResponse,
    tags=["restaurant-stock"],
    summary="Enregistrer un mouvement de stock",
    description="Ajoute une entrée, un ajustement d’inventaire ou une perte. Les sorties sont contrôlées pour ne jamais dépasser le stock disponible.",
    responses={
        200: {"description": "Stock mis à jour et mouvement journalisé."},
        400: {
            "description": "Mouvement invalide, stock insuffisant ou stock réservé trop élevé."
        },
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit pour ce composant."},
        404: {"description": "Composant ou stock introuvable."},
    },
)
def add_stock_movement(
    composant_id: uuid.UUID,
    movement_data: StockMouvementCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return StockService(db).add_movement(composant_id, movement_data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put(
    "/composants/{composant_id}",
    response_model=ComposantResponse,
    tags=["restaurant-combinations"],
    summary="Modifier la disponibilité ou le prix d’un composant",
    description="Permet notamment de désactiver une sauce épuisée ou de modifier le supplément d’une protéine.",
    responses={
        200: {"description": "Composant, disponibilité ou supplément mis à jour."},
        400: {"description": "Données de composant invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit pour ce composant."},
        404: {"description": "Composant introuvable."},
    },
)
def update_composant(
    composant_id: uuid.UUID,
    composant_data: ComposantUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    composant = CombinaisonService(db).update_composant(composant_id, composant_data)
    if not composant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Composant not found"
        )
    return composant


@router.post(
    "/{restaurant_id}/combinaisons",
    response_model=CombinaisonResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-combinations"],
    summary="Créer une combinaison tarifée",
    description="Crée une offre composée de plusieurs composants, par exemple riz + sauce tomate + poulet, avec un prix de vente propre à la combinaison.",
    responses={
        201: {"description": "Combinaison tarifée créée avec ses composants."},
        400: {
            "description": "Composants inexistants, dupliqués, indisponibles ou rattachés à un autre restaurant."
        },
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit pour ce restaurant."},
    },
)
def create_combinaison(
    restaurant_id: uuid.UUID,
    combinaison_data: CombinaisonCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return CombinaisonService(db).create_combinaison(
            combinaison_data, restaurant_id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{restaurant_id}/combinaisons/recommandations",
    response_model=List[CombinaisonResponse],
    tags=["restaurant-combinations"],
    summary="Recommander les combinaisons disponibles",
    description="Retourne uniquement les combinaisons actives dont tous les composants obligatoires sont disponibles. Une sauce épuisée retire donc les offres concernées.",
    responses={
        200: {
            "description": "Combinaisons actives et vendables retournées selon les composants disponibles et le stock restant."
        },
        404: {"description": "Restaurant introuvable."},
    },
)
def get_combinaison_recommandations(
    restaurant_id: uuid.UUID, db: Session = Depends(get_db)
):
    return CombinaisonService(db).get_recommandations(restaurant_id)


@router.get(
    "/{restaurant_id}/combinaisons",
    response_model=List[CombinaisonResponse],
    tags=["restaurant-combinations"],
    summary="Lister les combinaisons d’un restaurant",
    description="Retourne les offres composées et leurs prix configurés par l’administrateur.",
    responses={
        200: {
            "description": "Combinaisons récupérées avec leur prix et leurs composants."
        },
        404: {"description": "Restaurant introuvable."},
    },
)
def get_restaurant_combinaisons(
    restaurant_id: uuid.UUID, db: Session = Depends(get_db)
):
    return CombinaisonService(db).get_restaurant_combinaisons(restaurant_id)


@router.put(
    "/combinaisons/{combinaison_id}",
    response_model=CombinaisonResponse,
    tags=["restaurant-combinations"],
    summary="Modifier une combinaison tarifée",
    description="Met à jour le prix, les composants ou la disponibilité d’une combinaison.",
    responses={
        200: {
            "description": "Combinaison, prix, composants ou disponibilité mis à jour."
        },
        400: {
            "description": "Données invalides ou composant/menu rattaché à un autre restaurant."
        },
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit pour cette combinaison."},
        404: {"description": "Combinaison introuvable."},
    },
)
def update_combinaison(
    combinaison_id: uuid.UUID,
    combinaison_data: CombinaisonUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        combinaison = CombinaisonService(db).update_combinaison(
            combinaison_id, combinaison_data
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not combinaison:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Combinaison not found"
        )
    return combinaison


# Plats
@router.post(
    "/{restaurant_id}/plats",
    response_model=PlatResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-plats"],
    summary="Créer un plat",
    description="""
    Ajoute un plat à la carte d’un restaurant.

    Le plat peut être lié à une catégorie de menu, avoir des allergènes, un prix, un temps de préparation et une disponibilité spécifique.
    """,
    responses={
        201: {"description": "Plat créé avec succès."},
        400: {"description": "Données invalides ou logique métier non respectée."},
        401: {"description": "Token JWT absent ou invalide."},
    },
)
def create_plat(
    restaurant_id: uuid.UUID,
    plat_data: PlatCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plat_service = PlatService(db)
    try:
        return plat_service.create_plat(plat_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{restaurant_id}/plats",
    response_model=List[PlatResponse],
    tags=["restaurant-plats"],
    summary="Lister les plats d’un restaurant",
    description="""
    Retourne la liste des plats du restaurant, avec leurs informations principales pour affichage sur la carte et les commandes.
    """,
    responses={200: {"description": "Plats récupérés avec succès."}},
)
def get_restaurant_plats(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    plat_service = PlatService(db)
    return plat_service.get_restaurant_plats(restaurant_id)


@router.get(
    "/plats/{plat_id}",
    response_model=PlatResponse,
    tags=["restaurant-plats"],
    summary="Détails d’un plat",
    description="""
    Retourne les informations détaillées d’un plat donné.

    Cette route est utilisée pour afficher la fiche produit d’un plat : composition, prix, disponibilité, catégorie et contexte de restaurant.
    """,
    responses={
        200: {"description": "Plat trouvé."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Plat introuvable."},
    },
)
def get_plat(plat_id: uuid.UUID, db: Session = Depends(get_db)):
    plat_service = PlatService(db)
    plat = plat_service.get_plat(plat_id)
    if not plat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Plat not found"
        )
    return plat


@router.put(
    "/plats/{plat_id}",
    response_model=PlatResponse,
    tags=["restaurant-plats"],
    summary="Mettre à jour un plat",
    description="""
    Modifie les propriétés d’un plat existant.

    Cette route permet de mettre à jour le prix, la disponibilité, la description ou les métadonnées liées au produit.
    """,
    responses={
        200: {"description": "Plat mis à jour."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit."},
        404: {"description": "Plat introuvable."},
    },
)
def update_plat(
    plat_id: uuid.UUID,
    plat_data: PlatUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plat_service = PlatService(db)
    try:
        updated_plat = plat_service.update_plat(plat_id, plat_data)
        if not updated_plat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Plat not found"
            )
        return updated_plat
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# BOM (Bill of Materials) — Plats → Composants
@router.get(
    "/plats/{plat_id}/composants",
    response_model=List[PlatComposantResponse],
    tags=["restaurant-plats"],
    summary="Lister les composants d’un plat (BOM)",
    description="Retourne la nomenclature d’un plat : la liste des composants consommés à chaque commande, avec leur quantité et unité.",
    responses={
        200: {"description": "Liste PlatComposant retournée."},
        401: {"description": "Token invalide."},
        404: {"description": "Plat introuvable."},
    },
)
def get_plat_composants(plat_id: uuid.UUID, db: Session = Depends(get_db)):
    return PlatComposantService(db).get_by_plat_id(plat_id)


@router.post(
    "/plats/{plat_id}/composants",
    response_model=PlatComposantResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-plats"],
    summary="Ajouter un composant à un plat",
    description="Ajoute une ligne à la nomenclature d’un plat. Le plat et le composant doivent appartenir au même restaurant.",
    responses={
        201: {"description": "Ligne BOM créée."},
        400: {"description": "Restaurant incohérent ou doublon plat+composant."},
        404: {"description": "Plat ou composant introuvable."},
    },
)
def add_plat_composant(
    plat_id: uuid.UUID,
    data: PlatComposantCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return PlatComposantService(db).create(plat_id, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put(
    "/plats/{plat_id}/composants/{composant_id}",
    response_model=PlatComposantResponse,
    tags=["restaurant-plats"],
    summary="Modifier une ligne de nomenclature",
    description="Met à jour la quantité, l’unité ou l’ordre d’un composant dans un plat.",
    responses={
        200: {"description": "Mis à jour."},
        404: {"description": "Ligne BOM introuvable."},
    },
)
def update_plat_composant(
    plat_id: uuid.UUID,
    composant_id: uuid.UUID,
    data: PlatComposantUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    link = PlatComposantService(db).update(plat_id, composant_id, data)
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PlatComposant not found"
        )
    return link


@router.delete(
    "/plats/{plat_id}/composants/{composant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["restaurant-plats"],
    summary="Supprimer une ligne de nomenclature",
)
def delete_plat_composant(
    plat_id: uuid.UUID,
    composant_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = PlatComposantService(db).delete(plat_id, composant_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PlatComposant not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/plats/{plat_id}/composants",
    response_model=List[PlatComposantResponse],
    tags=["restaurant-plats"],
    summary="Remplacer toute la nomenclature d’un plat",
    description="Supprime toutes les lignes existantes et remplace par la liste fournie en une seule opération atomique.",
)
def replace_all_plat_composants(
    plat_id: uuid.UUID,
    data: List[PlatComposantCreate],
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return PlatComposantService(db).replace_all_for_plat(plat_id, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Boissons
@router.post(
    "/{restaurant_id}/boissons",
    response_model=BoissonResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-boissons"],
    summary="Créer une boisson",
    description="""
    Ajoute une boisson à la carte d’un restaurant.

    Cette route permet de gérer les boissons selon les catégories, le prix, le type et la disponibilité du point de vente.
    """,
    responses={
        201: {"description": "Boisson créée avec succès."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
    },
)
def create_boisson(
    restaurant_id: uuid.UUID,
    boisson_data: BoissonCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    boisson_service = BoissonService(db)
    try:
        return boisson_service.create_boisson(boisson_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{restaurant_id}/boissons",
    response_model=List[BoissonResponse],
    tags=["restaurant-boissons"],
    summary="Lister les boissons d’un restaurant",
    description="""
    Retourne l’ensemble des boissons associées à un restaurant.

    Cette route sert à alimenter la carte boissons et à gérer la disponibilité et les tarifs proposés au client.
    """,
    responses={
        200: {"description": "Boissons récupérées avec succès."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Restaurant introuvable."},
    },
)
def get_restaurant_boissons(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    boisson_service = BoissonService(db)
    return boisson_service.get_restaurant_boissons(restaurant_id)


@router.get(
    "/boissons/{boisson_id}",
    response_model=BoissonResponse,
    tags=["restaurant-boissons"],
    summary="Détails d’une boisson",
    description="""
    Retourne les informations détaillées d’une boisson donnée.

    Cette route permet de consulter la fiche produit d’une boisson avant de la servir ou de la modifier.
    """,
    responses={
        200: {"description": "Boisson trouvée."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Boisson introuvable."},
    },
)
def get_boisson(boisson_id: uuid.UUID, db: Session = Depends(get_db)):
    boisson_service = BoissonService(db)
    boisson = boisson_service.get_boisson(boisson_id)
    if not boisson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Boisson not found"
        )
    return boisson


@router.put(
    "/boissons/{boisson_id}",
    response_model=BoissonResponse,
    tags=["restaurant-boissons"],
    summary="Mettre à jour une boisson",
    description="""
    Modifie les propriétés d’une boisson existante.

    Cette route permet d’ajuster le prix, la disponibilité, le type ou la description commerciale de la boisson.
    """,
    responses={
        200: {"description": "Boisson mise à jour."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit."},
        404: {"description": "Boisson introuvable."},
    },
)
def update_boisson(
    boisson_id: uuid.UUID,
    boisson_data: BoissonUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    boisson_service = BoissonService(db)
    try:
        updated_boisson = boisson_service.update_boisson(boisson_id, boisson_data)
        if not updated_boisson:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Boisson not found"
            )
        return updated_boisson
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Tables
@router.post(
    "/{restaurant_id}/tables",
    response_model=TableResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-tables"],
    summary="Créer une table",
    description="""
    Enregistre une table dans le système pour un restaurant donné.

    Cette route comprend l’attribution d’un numéro, de la capacité et éventuellement de l’emplacement de la table dans le restaurant.
    """,
    responses={
        201: {"description": "Table créée avec succès."},
        400: {"description": "Données invalides ou numéro déjà utilisé."},
        401: {"description": "Token JWT absent ou invalide."},
    },
)
def create_table(
    restaurant_id: uuid.UUID,
    table_data: TableCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table_service = TableService(db)
    try:
        return table_service.create_table(table_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{restaurant_id}/tables",
    response_model=List[TableResponse],
    tags=["restaurant-tables"],
    summary="Lister les tables d’un restaurant",
    description="""
    Retourne l’ensemble des tables du restaurant, avec leur statut, capacité et localisation.

    Cette donnée est utilisée pour gérer le plan de salle et la gestion des commandes en cours.
    """,
    responses={200: {"description": "Tables récupérées avec succès."}},
)
def get_restaurant_tables(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    table_service = TableService(db)
    return table_service.get_restaurant_tables(restaurant_id)


@router.get(
    "/{restaurant_id}/tables/free",
    response_model=List[TableResponse],
    tags=["restaurant-tables"],
    summary="Lister les tables libres",
    description="""
    Retourne uniquement les tables actuellement disponibles pour accueillir un client.

    Cette route est essentielle pour la gestion du flux de clientèle dans les restaurants et le service de commande.
    """,
    responses={200: {"description": "Tables libres récupérées avec succès."}},
)
def get_free_tables(restaurant_id: uuid.UUID, db: Session = Depends(get_db)):
    table_service = TableService(db)
    return table_service.get_free_tables(restaurant_id)


@router.get(
    "/tables/{table_id}",
    response_model=TableResponse,
    tags=["restaurant-tables"],
    summary="Détails d’une table",
    description="""
    Retourne les informations d’une table donnée.

    Cette route est utile pour consulter l’état, la capacité et le statut d’occupation d’une table de restaurant.
    """,
    responses={
        200: {"description": "Table trouvée."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Table introuvable."},
    },
)
def get_table(table_id: uuid.UUID, db: Session = Depends(get_db)):
    table_service = TableService(db)
    table = table_service.get_table(table_id)
    if not table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Table not found"
        )
    return table


@router.put(
    "/tables/{table_id}",
    response_model=TableResponse,
    tags=["restaurant-tables"],
    summary="Mettre à jour une table",
    description="""
    Modifie une table existante.

    Cette route sert à ajuster la capacité, le statut, la localisation ou les informations de salle d’une table.
    """,
    responses={
        200: {"description": "Table mise à jour."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit."},
        404: {"description": "Table introuvable."},
    },
)
def update_table(
    table_id: uuid.UUID,
    table_data: TableUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    table_service = TableService(db)
    try:
        updated_table = table_service.update_table(table_id, table_data)
        if not updated_table:
            raise HTTPException(
                status_code.HTTP_404_NOT_FOUND, detail="Table not found"
            )
        return updated_table
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Commandes (LÉGACY — déprécié, utilisez ROS Orders)
_LEGACY_DEPRECATED_NOTICE = (
    "⚠️ Modèle Commande historique déprécié. Utilisez plutôt le moteur ROS : "
    "/v1/ros/* (service_sessions → ros_orders + production_tickets + ros_invoices)."
)


@router.post(
    "/{restaurant_id}/commandes",
    response_model=CommandeResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-orders"],
    summary="[DÉPRÉCIÉ] Créer une commande",
    description=_LEGACY_DEPRECATED_NOTICE,
    responses={
        201: {"description": "Commande créée avec succès."},
        400: {"description": "Données invalides ou logique de commande non respectée."},
        401: {"description": "Token JWT absent ou invalide."},
    },
    deprecated=True,
)
def create_commande(
    restaurant_id: uuid.UUID,
    commande_data: CommandeCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    _dep=Depends(_mark_deprecated_commande),
):
    commande_service = CommandeService(db)
    try:
        return commande_service.create_commande(commande_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{restaurant_id}/commandes",
    response_model=List[CommandeResponse],
    tags=["restaurant-orders"],
    summary="[DÉPRÉCIÉ] Historique des commandes d’un restaurant",
    description=_LEGACY_DEPRECATED_NOTICE,
    responses={200: {"description": "Commandes récupérées avec succès."}},
    deprecated=True,
)
def get_restaurant_commandes(
    restaurant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    _dep=Depends(_mark_deprecated_commande),
):
    commande_service = CommandeService(db)
    return commande_service.get_restaurant_commandes(restaurant_id, skip, limit)


@router.get(
    "/{restaurant_id}/commandes/active",
    response_model=List[CommandeResponse],
    tags=["restaurant-orders"],
    summary="[DÉPRÉCIÉ] Commandes actives d’un restaurant",
    description=_LEGACY_DEPRECATED_NOTICE,
    responses={
        200: {"description": "Commandes actives récupérées avec succès."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Restaurant introuvable."},
    },
    deprecated=True,
)
def get_active_commandes(
    restaurant_id: uuid.UUID,
    db: Session = Depends(get_db),
    _dep=Depends(_mark_deprecated_commande),
):
    commande_service = CommandeService(db)
    return commande_service.get_active_commandes(restaurant_id)


@router.get(
    "/commandes/{commande_id}",
    response_model=CommandeResponse,
    tags=["restaurant-orders"],
    summary="[DÉPRÉCIÉ] Détails d’une commande",
    description=_LEGACY_DEPRECATED_NOTICE,
    responses={
        200: {"description": "Commande trouvée."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Commande introuvable."},
    },
    deprecated=True,
)
def get_commande(
    commande_id: uuid.UUID,
    db: Session = Depends(get_db),
    _dep=Depends(_mark_deprecated_commande),
):
    commande_service = CommandeService(db)
    commande = commande_service.get_commande(commande_id)
    if not commande:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commande not found"
        )
    return commande


@router.put(
    "/commandes/{commande_id}",
    response_model=CommandeResponse,
    tags=["restaurant-orders"],
    summary="[DÉPRÉCIÉ] Mettre à jour une commande",
    description=_LEGACY_DEPRECATED_NOTICE,
    responses={
        200: {"description": "Commande mise à jour."},
        400: {"description": "Données invalides."},
        401: {"description": "Token JWT absent ou invalide."},
        403: {"description": "Accès interdit."},
        404: {"description": "Commande introuvable."},
    },
    deprecated=True,
)
def update_commande(
    commande_id: uuid.UUID,
    commande_data: CommandeUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    _dep=Depends(_mark_deprecated_commande),
):
    commande_service = CommandeService(db)
    try:
        updated_commande = commande_service.update_commande(commande_id, commande_data)
        if not updated_commande:
            raise HTTPException(
                status_code.HTTP_404_NOT_FOUND, detail="Commande not found"
            )
        return updated_commande
    except ValueError as e:
        raise HTTPException(status_code.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/commandes/{commande_id}/items",
    response_model=CommandeItemResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-orders"],
    summary="[DÉPRÉCIÉ] Ajouter un item à une commande",
    description=_LEGACY_DEPRECATED_NOTICE,
    responses={
        201: {"description": "Item ajouté avec succès."},
        400: {"description": "Données invalides ou item non compatible."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Commande introuvable."},
    },
    deprecated=True,
)
def add_commande_item(
    commande_id: uuid.UUID,
    item_data: CommandeItemCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    _dep=Depends(_mark_deprecated_commande),
):
    commande_service = CommandeService(db)
    try:
        return commande_service.add_item(commande_id, item_data)
    except ValueError as e:
        raise HTTPException(status_code.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/commandes/{commande_id}/items",
    response_model=List[CommandeItemResponse],
    tags=["restaurant-orders"],
    summary="[DÉPRÉCIÉ] Lister les items d’une commande",
    description=_LEGACY_DEPRECATED_NOTICE,
    responses={
        200: {"description": "Items de commande récupérés avec succès."},
        401: {"description": "Token JWT absent ou invalide."},
        404: {"description": "Commande introuvable."},
    },
    deprecated=True,
)
def get_commande_items(
    commande_id: uuid.UUID,
    db: Session = Depends(get_db),
    _dep=Depends(_mark_deprecated_commande),
):
    commande_service = CommandeService(db)
    return commande_service.get_commande_items(commande_id)


# Refunds (flux complet)
@router.post(
    "/commandes/{commande_id}/refunds",
    response_model=CommandeRefundResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["restaurant-orders-refunds"],
    summary="Demander un remboursement (total ou partiel)",
    description="""
    Dépose une demande de remboursement sur une commande payée.

    Le montant ne peut excéder `commande.total - commande.refunded_amount`.
    Une fois approuvée, le stock des composants des plats est restitué.
    """,
    responses={
        201: {"description": "Demande de remboursement créée."},
        400: {"description": "Montant invalide ou commande non remboursable."},
        404: {"description": "Commande introuvable."},
    },
)
def request_refund(
    commande_id: uuid.UUID,
    refund_data: CommandeRefundCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = CommandeService(db)
    try:
        return service.request_refund(
            commande_id,
            refund_data,
            initiated_by=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/commandes/{commande_id}/refunds",
    response_model=List[CommandeRefundResponse],
    tags=["restaurant-orders-refunds"],
    summary="Historique des remboursements d’une commande",
)
def get_commande_refunds(commande_id: uuid.UUID, db: Session = Depends(get_db)):
    service = CommandeService(db)
    return service.get_refunds(commande_id)


@router.post(
    "/commandes/{commande_id}/refunds/{refund_id}/approve",
    response_model=CommandeRefundResponse,
    tags=["restaurant-orders-refunds"],
    summary="Approuver un remboursement (manager/admin)",
    description="""
    Valide une demande de remboursement. Effectue :
    - la mise à jour de `commande.refunded_amount` et `refund_status` ;
    - le restockage des composants consommés par les articles concernés ;
    - l’horodatage et l’audit `processed_by`.
    """,
)
def approve_refund(
    commande_id: uuid.UUID,
    refund_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = CommandeService(db)
    try:
        return service.approve_refund(refund_id, processed_by=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/commandes/{commande_id}/refunds/{refund_id}/reject",
    response_model=CommandeRefundResponse,
    tags=["restaurant-orders-refunds"],
    summary="Rejeter une demande de remboursement",
)
def reject_refund(
    commande_id: uuid.UUID,
    refund_id: uuid.UUID,
    reason: str = "",
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = CommandeService(db)
    try:
        return service.reject_refund(
            refund_id, reason=reason, processed_by=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
