from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.services.restaurant_service import (
    RestaurantService,
    MenuService,
    PlatService,
    BoissonService,
    TableService,
    CommandeService
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
    PlatResponse,
    PlatCreate,
    PlatUpdate,
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
    CommandeItemCreate
)
from app.api.dependencies import get_current_user, require_admin
import uuid

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


# Restaurants
@router.post("/", response_model=RestaurantResponse, status_code=status.HTTP_201_CREATED)
def create_restaurant(
    restaurant_data: RestaurantCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    restaurant_service = RestaurantService(db)
    try:
        return restaurant_service.create_restaurant(restaurant_data, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/me", response_model=RestaurantResponse)
def get_my_restaurant(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    restaurant_service = RestaurantService(db)
    restaurant = restaurant_service.get_user_restaurant(current_user.id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.get("/{restaurant_id}", response_model=RestaurantResponse)
def get_restaurant(
    restaurant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    restaurant_service = RestaurantService(db)
    restaurant = restaurant_service.get_restaurant(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.put("/{restaurant_id}", response_model=RestaurantResponse)
def update_restaurant(
    restaurant_id: uuid.UUID,
    restaurant_data: RestaurantUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    restaurant_service = RestaurantService(db)
    restaurant = restaurant_service.get_restaurant(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    # Vérifier que l'utilisateur est le propriétaire ou admin
    if restaurant.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    try:
        updated_restaurant = restaurant_service.update_restaurant(restaurant_id, restaurant_data)
        if not updated_restaurant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
        return updated_restaurant
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Menus
@router.post("/{restaurant_id}/menus", response_model=MenuResponse, status_code=status.HTTP_201_CREATED)
def create_menu(
    restaurant_id: uuid.UUID,
    menu_data: MenuCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    menu_service = MenuService(db)
    try:
        return menu_service.create_menu(menu_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{restaurant_id}/menus", response_model=List[MenuResponse])
def get_restaurant_menus(
    restaurant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    menu_service = MenuService(db)
    return menu_service.get_restaurant_menus(restaurant_id)


@router.get("/menus/{menu_id}", response_model=MenuResponse)
def get_menu(
    menu_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    menu_service = MenuService(db)
    menu = menu_service.get_menu(menu_id)
    if not menu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
    return menu


@router.put("/menus/{menu_id}", response_model=MenuResponse)
def update_menu(
    menu_id: uuid.UUID,
    menu_data: MenuUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    menu_service = MenuService(db)
    try:
        updated_menu = menu_service.update_menu(menu_id, menu_data)
        if not updated_menu:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
        return updated_menu
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Menu Categories
@router.post("/menus/{menu_id}/categories", response_model=MenuCategoryResponse, status_code=status.HTTP_201_CREATED)
def create_menu_category(
    menu_id: uuid.UUID,
    category_data: MenuCategoryCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    menu_service = MenuService(db)
    try:
        return menu_service.create_category(category_data, menu_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/menus/{menu_id}/categories", response_model=List[MenuCategoryResponse])
def get_menu_categories(
    menu_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    menu_service = MenuService(db)
    return menu_service.get_menu_categories(menu_id)


@router.put("/categories/{category_id}", response_model=MenuCategoryResponse)
def update_menu_category(
    category_id: uuid.UUID,
    category_data: MenuCategoryUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    menu_service = MenuService(db)
    try:
        updated_category = menu_service.update_category(category_id, category_data)
        if not updated_category:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        return updated_category
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Plats
@router.post("/{restaurant_id}/plats", response_model=PlatResponse, status_code=status.HTTP_201_CREATED)
def create_plat(
    restaurant_id: uuid.UUID,
    plat_data: PlatCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    plat_service = PlatService(db)
    try:
        return plat_service.create_plat(plat_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{restaurant_id}/plats", response_model=List[PlatResponse])
def get_restaurant_plats(
    restaurant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    plat_service = PlatService(db)
    return plat_service.get_restaurant_plats(restaurant_id)


@router.get("/plats/{plat_id}", response_model=PlatResponse)
def get_plat(
    plat_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    plat_service = PlatService(db)
    plat = plat_service.get_plat(plat_id)
    if not plat:
        raise HTTPException(status_code=status_HTTP_404_NOT_FOUND, detail="Plat not found")
    return plat


@router.put("/plats/{plat_id}", response_model=PlatResponse)
def update_plat(
    plat_id: uuid.UUID,
    plat_data: PlatUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    plat_service = PlatService(db)
    try:
        updated_plat = plat_service.update_plat(plat_id, plat_data)
        if not updated_plat:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plat not found")
        return updated_plat
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Boissons
@router.post("/{restaurant_id}/boissons", response_model=BoissonResponse, status_code=status.HTTP_201_CREATED)
def create_boisson(
    restaurant_id: uuid.UUID,
    boisson_data: BoissonCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    boisson_service = BoissonService(db)
    try:
        return boisson_service.create_boisson(boisson_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{restaurant_id}/boissons", response_model=List[BoissonResponse])
def get_restaurant_boissons(
    restaurant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    boisson_service = BoissonService(db)
    return boisson_service.get_restaurant_boissons(restaurant_id)


@router.get("/boissons/{boisson_id}", response_model=BoissonResponse)
def get_boisson(
    boisson_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    boisson_service = BoissonService(db)
    boisson = boisson_service.get_boisson(boisson_id)
    if not boisson:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Boisson not found")
    return boisson


@router.put("/boissons/{boisson_id}", response_model=BoissonResponse)
def update_boisson(
    boisson_id: uuid.UUID,
    boisson_data: BoissonUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    boisson_service = BoissonService(db)
    try:
        updated_boisson = boisson_service.update_boisson(boisson_id, boisson_data)
        if not updated_boisson:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Boisson not found")
        return updated_boisson
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Tables
@router.post("/{restaurant_id}/tables", response_model=TableResponse, status_code=status.HTTP_201_CREATED)
def create_table(
    restaurant_id: uuid.UUID,
    table_data: TableCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    table_service = TableService(db)
    try:
        return table_service.create_table(table_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{restaurant_id}/tables", response_model=List[TableResponse])
def get_restaurant_tables(
    restaurant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    table_service = TableService(db)
    return table_service.get_restaurant_tables(restaurant_id)


@router.get("/{restaurant_id}/tables/free", response_model=List[TableResponse])
def get_free_tables(
    restaurant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    table_service = TableService(db)
    return table_service.get_free_tables(restaurant_id)


@router.get("/tables/{table_id}", response_model=TableResponse)
def get_table(
    table_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    table_service = TableService(db)
    table = table_service.get_table(table_id)
    if not table:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")
    return table


@router.put("/tables/{table_id}", response_model=TableResponse)
def update_table(
    table_id: uuid.UUID,
    table_data: TableUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    table_service = TableService(db)
    try:
        updated_table = table_service.update_table(table_id, table_data)
        if not updated_table:
            raise HTTPException(status_code.HTTP_404_NOT_FOUND, detail="Table not found")
        return updated_table
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# Commandes
@router.post("/{restaurant_id}/commandes", response_model=CommandeResponse, status_code=status.HTTP_201_CREATED)
def create_commande(
    restaurant_id: uuid.UUID,
    commande_data: CommandeCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    commande_service = CommandeService(db)
    try:
        return commande_service.create_commande(commande_data, restaurant_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{restaurant_id}/commandes", response_model=List[CommandeResponse])
def get_restaurant_commandes(
    restaurant_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    commande_service = CommandeService(db)
    return commande_service.get_restaurant_commandes(restaurant_id, skip, limit)


@router.get("/{restaurant_id}/commandes/active", response_model=List[CommandeResponse])
def get_active_commandes(
    restaurant_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    commande_service = CommandeService(db)
    return commande_service.get_active_commandes(restaurant_id)


@router.get("/commandes/{commande_id}", response_model=CommandeResponse)
def get_commande(
    commande_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    commande_service = CommandeService(db)
    commande = commande_service.get_commande(commande_id)
    if not commande:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commande not found")
    return commande


@router.put("/commandes/{commande_id}", response_model=CommandeResponse)
def update_commande(
    commande_id: uuid.UUID,
    commande_data: CommandeUpdate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    commande_service = CommandeService(db)
    try:
        updated_commande = commande_service.update_commande(commande_id, commande_data)
        if not updated_commande:
            raise HTTPException(status_code.HTTP_404_NOT_FOUND, detail="Commande not found")
        return updated_commande
    except ValueError as e:
        raise HTTPException(status_code.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/commandes/{commande_id}/items", response_model=CommandeItemResponse, status_code=status.HTTP_201_CREATED)
def add_commande_item(
    commande_id: uuid.UUID,
    item_data: CommandeItemCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    commande_service = CommandeService(db)
    try:
        return commande_service.add_item(commande_id, item_data)
    except ValueError as e:
        raise HTTPException(status_code.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/commandes/{commande_id}/items", response_model=List[CommandeItemResponse])
def get_commande_items(
    commande_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    commande_service = CommandeService(db)
    return commande_service.get_commande_items(commande_id)
