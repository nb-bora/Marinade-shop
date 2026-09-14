from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from app.repositories.restaurant_repository import (
    RestaurantRepository,
    MenuRepository,
    MenuCategoryRepository,
    PlatRepository,
    BoissonRepository,
    TableRepository,
    CommandeRepository,
    CommandeItemRepository
)
from app.schemas.restaurant import (
    RestaurantCreate,
    RestaurantUpdate,
    MenuCreate,
    MenuUpdate,
    MenuCategoryCreate,
    MenuCategoryUpdate,
    PlatCreate,
    PlatUpdate,
    BoissonCreate,
    BoissonUpdate,
    TableCreate,
    TableUpdate,
    CommandeCreate,
    CommandeUpdate,
    CommandeItemCreate
)
from app.models.restaurant import (
    Restaurant,
    Menu,
    MenuCategory,
    Plat,
    Boisson,
    Table,
    Commande,
    CommandeItem
)
from app.utils.logging import get_logger
import uuid

logger = get_logger(__name__)


class RestaurantService:
    def __init__(self, db: Session):
        self.db = db
        self.restaurant_repo = RestaurantRepository(db)

    def create_restaurant(self, restaurant_data: RestaurantCreate, user_id: uuid.UUID) -> Restaurant:
        existing = self.restaurant_repo.get_by_user_id(user_id)
        if existing:
            logger.warning(f"User already has a restaurant: {user_id}")
            raise ValueError("User already has a restaurant")

        restaurant = self.restaurant_repo.create({
            **restaurant_data.model_dump(),
            "user_id": user_id
        })
        logger.info(f"Restaurant created: {restaurant.id}")
        return restaurant

    def get_restaurant(self, restaurant_id: uuid.UUID) -> Optional[Restaurant]:
        return self.restaurant_repo.get(str(restaurant_id))

    def get_user_restaurant(self, user_id: uuid.UUID) -> Optional[Restaurant]:
        return self.restaurant_repo.get_by_user_id(user_id)

    def update_restaurant(self, restaurant_id: uuid.UUID, restaurant_data: RestaurantUpdate) -> Optional[Restaurant]:
        restaurant = self.restaurant_repo.get(str(restaurant_id))
        if not restaurant:
            logger.warning(f"Restaurant not found for update: {restaurant_id}")
            return None

        updated_restaurant = self.restaurant_repo.update(
            restaurant,
            restaurant_data.model_dump(exclude_unset=True)
        )
        logger.info(f"Restaurant updated: {restaurant_id}")
        return updated_restaurant


class MenuService:
    def __init__(self, db: Session):
        self.db = db
        self.menu_repo = MenuRepository(db)
        self.category_repo = MenuCategoryRepository(db)

    def create_menu(self, menu_data: MenuCreate, restaurant_id: uuid.UUID) -> Menu:
        menu = self.menu_repo.create({
            **menu_data.model_dump(),
            "restaurant_id": restaurant_id
        })
        logger.info(f"Menu created: {menu.id}")
        return menu

    def get_menu(self, menu_id: uuid.UUID) -> Optional[Menu]:
        return self.menu_repo.get(str(menu_id))

    def get_restaurant_menus(self, restaurant_id: uuid.UUID) -> List[Menu]:
        return self.menu_repo.get_by_restaurant_id(restaurant_id)

    def update_menu(self, menu_id: uuid.UUID, menu_data: MenuUpdate) -> Optional[Menu]:
        menu = self.menu_repo.get(str(menu_id))
        if not menu:
            logger.warning(f"Menu not found for update: {menu_id}")
            return None

        updated_menu = self.menu_repo.update(
            menu,
            menu_data.model_dump(exclude_unset=True)
        )
        logger.info(f"Menu updated: {menu_id}")
        return updated_menu

    def create_category(self, category_data: MenuCategoryCreate, restaurant_id: uuid.UUID) -> MenuCategory:
        category = self.category_repo.create({
            **category_data.model_dump(),
            "restaurant_id": restaurant_id
        })
        logger.info(f"Menu category created: {category.id}")
        return category

    def get_menu_categories(self, menu_id: uuid.UUID) -> List[MenuCategory]:
        return self.category_repo.get_by_menu_id(menu_id)

    def update_category(self, category_id: uuid.UUID, category_data: MenuCategoryUpdate) -> Optional[MenuCategory]:
        category = self.category_repo.get(str(category_id))
        if not category:
            logger.warning(f"Category not found for update: {category_id}")
            return None

        updated_category = self.category_repo.update(
            category,
            category_data.model_dump(exclude_unset=True)
        )
        logger.info(f"Category updated: {category_id}")
        return updated_category


class PlatService:
    def __init__(self, db: Session):
        self.db = db
        self.plat_repo = PlatRepository(db)

    def create_plat(self, plat_data: PlatCreate, restaurant_id: uuid.UUID) -> Plat:
        plat = self.plat_repo.create({
            **plat_data.model_dump(),
            "restaurant_id": restaurant_id
        })
        logger.info(f"Plat created: {plat.id}")
        return plat

    def get_plat(self, plat_id: uuid.UUID) -> Optional[Plat]:
        return self.plat_repo.get(str(plat_id))

    def get_restaurant_plats(self, restaurant_id: uuid.UUID) -> List[Plat]:
        return self.plat_repo.get_by_restaurant_id(restaurant_id)

    def get_category_plats(self, category_id: uuid.UUID) -> List[Plat]:
        return self.plat_repo.get_by_category_id(category_id)

    def update_plat(self, plat_id: uuid.UUID, plat_data: PlatUpdate) -> Optional[Plat]:
        plat = self.plat_repo.get(str(plat_id))
        if not plat:
            logger.warning(f"Plat not found for update: {plat_id}")
            return None

        updated_plat = self.plat_repo.update(
            plat,
            plat_data.model_dump(exclude_unset=True)
        )
        logger.info(f"Plat updated: {plat_id}")
        return updated_plat


class BoissonService:
    def __init__(self, db: Session):
        self.db = db
        self.boisson_repo = BoissonRepository(db)

    def create_boisson(self, boisson_data: BoissonCreate, restaurant_id: uuid.UUID) -> Boisson:
        boisson = self.boisson_repo.create({
            **boisson_data.model_dump(),
            "restaurant_id": restaurant_id
        })
        logger.info(f"Boisson created: {boisson.id}")
        return boisson

    def get_boisson(self, boisson_id: uuid.UUID) -> Optional[Boisson]:
        return self.boisson_repo.get(str(boisson_id))

    def get_restaurant_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return self.boisson_repo.get_by_restaurant_id(restaurant_id)

    def get_category_boissons(self, restaurant_id: uuid.UUID, category: str) -> List[Boisson]:
        return self.boisson_repo.get_by_category(restaurant_id, category)

    def update_boisson(self, boisson_id: uuid.UUID, boisson_data: BoissonUpdate) -> Optional[Boisson]:
        boisson = self.boisson_repo.get(str(boisson_id))
        if not boisson:
            logger.warning(f"Boisson not found for update: {boisson_id}")
            return None

        updated_boisson = self.boisson_repo.update(
            boisson,
            boisson_data.model_dump(exclude_unset=True)
        )
        logger.info(f"Boisson updated: {boisson_id}")
        return updated_boisson


class TableService:
    def __init__(self, db: Session):
        self.db = db
        self.table_repo = TableRepository(db)

    def create_table(self, table_data: TableCreate, restaurant_id: uuid.UUID) -> Table:
        # Vérifier que le numéro de table est unique pour ce restaurant
        existing = self.table_repo.get_by_numero(restaurant_id, table_data.numero)
        if existing:
            logger.warning(f"Table number already exists: {table_data.numero}")
            raise ValueError("Table number already exists")

        table = self.table_repo.create({
            **table_data.model_dump(),
            "restaurant_id": restaurant_id
        })
        logger.info(f"Table created: {table.id}")
        return table

    def get_table(self, table_id: uuid.UUID) -> Optional[Table]:
        return self.table_repo.get(str(table_id))

    def get_restaurant_tables(self, restaurant_id: uuid.UUID) -> List[Table]:
        return self.table_repo.get_by_restaurant_id(restaurant_id)

    def get_free_tables(self, restaurant_id: uuid.UUID) -> List[Table]:
        return self.table_repo.get_free_tables(restaurant_id)

    def update_table(self, table_id: uuid.UUID, table_data: TableUpdate) -> Optional[Table]:
        table = self.table_repo.get(str(table_id))
        if not table:
            logger.warning(f"Table not found for update: {table_id}")
            return None

        updated_table = self.table_repo.update(
            table,
            table_data.model_dump(exclude_unset=True)
        )
        logger.info(f"Table updated: {table_id}")
        return updated_table


class CommandeService:
    def __init__(self, db: Session):
        self.db = db
        self.commande_repo = CommandeRepository(db)
        self.item_repo = CommandeItemRepository(db)

    def create_commande(self, commande_data: CommandeCreate, restaurant_id: uuid.UUID) -> Commande:
        commande = self.commande_repo.create({
            **commande_data.model_dump(),
            "restaurant_id": restaurant_id
        })
        logger.info(f"Commande created: {commande.id}")
        return commande

    def get_commande(self, commande_id: uuid.UUID) -> Optional[Commande]:
        return self.commande_repo.get(str(commande_id))

    def get_restaurant_commandes(self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[Commande]:
        return self.commande_repo.get_by_restaurant_id(restaurant_id, skip, limit)

    def get_active_commandes(self, restaurant_id: uuid.UUID) -> List[Commande]:
        return self.commande_repo.get_active_commandes(restaurant_id)

    def update_commande(self, commande_id: uuid.UUID, commande_data: CommandeUpdate) -> Optional[Commande]:
        commande = self.commande_repo.get(str(commande_id))
        if not commande:
            logger.warning(f"Commande not found for update: {commande_id}")
            return None

        updated_commande = self.commande_repo.update(
            commande,
            commande_data.model_dump(exclude_unset=True)
        )
        logger.info(f"Commande updated: {commande_id}")
        return updated_commande

    def add_item(self, commande_id: uuid.UUID, item_data: CommandeItemCreate) -> CommandeItem:
        item = self.item_repo.create({
            **item_data.model_dump(),
            "commande_id": commande_id
        })
        logger.info(f"Commande item added: {item.id}")
        return item

    def get_commande_items(self, commande_id: uuid.UUID) -> List[CommandeItem]:
        return self.item_repo.get_by_commande_id(commande_id)
