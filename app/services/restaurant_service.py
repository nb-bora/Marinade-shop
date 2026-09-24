from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import Session
from app.repositories.restaurant_repository import (
    RestaurantRepository,
    MenuRepository,
    MenuCategoryRepository,
    ComposantRepository,
    CombinaisonRepository,
    CombinaisonComposantRepository,
    StockComposantRepository,
    StockMouvementRepository,
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
    ComposantCreate,
    ComposantUpdate,
    CombinaisonCreate,
    CombinaisonUpdate,
    StockMouvementCreate,
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
    Composant,
    Combinaison,
    CombinaisonComposant,
    StockComposant,
    StockMouvement,
    Plat,
    Boisson,
    Table,
    Commande,
    CommandeItem
)
from app.utils.logging import get_logger
from app.utils.enums import CommandeStatut
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
        self.restaurant_repo = RestaurantRepository(db)

    def create_menu(self, menu_data: MenuCreate, restaurant_id: uuid.UUID) -> Menu:
        # Valider que le restaurant existe
        restaurant = self.restaurant_repo.get(str(restaurant_id))
        if not restaurant:
            logger.warning(f"Restaurant not found: {restaurant_id}")
            raise ValueError("Restaurant not found")

        # Valider l'unicité du nom dans le restaurant
        existing_menus = self.menu_repo.get_by_restaurant_id(restaurant_id)
        if any(menu.name == menu_data.name for menu in existing_menus):
            logger.warning(f"Menu name already exists in restaurant: {menu_data.name}")
            raise ValueError("Menu name already exists in this restaurant")

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

    def get_active_menus(self, restaurant_id: uuid.UUID) -> List[Menu]:
        return self.menu_repo.get_active_menus(restaurant_id)

    def update_menu(self, menu_id: uuid.UUID, menu_data: MenuUpdate) -> Optional[Menu]:
        menu = self.menu_repo.get(str(menu_id))
        if not menu:
            logger.warning(f"Menu not found for update: {menu_id}")
            return None

        # Valider l'unicité du nom si modifié
        if menu_data.name and menu_data.name != menu.name:
            existing_menus = self.menu_repo.get_by_restaurant_id(menu.restaurant_id)
            if any(existing_menu.name == menu_data.name and existing_menu.id != menu.id for existing_menu in existing_menus):
                logger.warning(f"Menu name already exists in restaurant: {menu_data.name}")
                raise ValueError("Menu name already exists in this restaurant")

        updated_menu = self.menu_repo.update(
            menu,
            menu_data.model_dump(exclude_unset=True)
        )
        
        # Si le menu est désactivé, logique cascade pourrait être ajoutée ici
        if menu_data.actif == False:
            logger.info(f"Menu deactivated: {menu_id}")
        
        logger.info(f"Menu updated: {menu_id}")
        return updated_menu

    def create_category(self, category_data: MenuCategoryCreate, restaurant_id: uuid.UUID) -> MenuCategory:
        # Valider que le menu existe et appartient au restaurant
        menu = self.menu_repo.get(str(category_data.menu_id))
        if not menu:
            logger.warning(f"Menu not found: {category_data.menu_id}")
            raise ValueError("Menu not found")
        
        if menu.restaurant_id != restaurant_id:
            logger.warning(f"Menu does not belong to restaurant: {category_data.menu_id}")
            raise ValueError("Menu does not belong to this restaurant")

        # Valider l'unicité de l'ordre dans le menu
        existing_categories = self.category_repo.get_by_menu_id(category_data.menu_id)
        if any(cat.ordre == category_data.ordre for cat in existing_categories):
            logger.warning(f"Category order already exists in menu: {category_data.ordre}")
            raise ValueError("Category order already exists in this menu")

        category = self.category_repo.create({
            **category_data.model_dump(),
            "restaurant_id": restaurant_id
        })
        logger.info(f"Menu category created: {category.id}")
        return category

    def get_menu_categories(self, menu_id: uuid.UUID) -> List[MenuCategory]:
        return self.category_repo.get_by_menu_id(menu_id)

    def get_restaurant_categories(self, restaurant_id: uuid.UUID) -> List[MenuCategory]:
        return self.category_repo.get_by_restaurant_id(restaurant_id)

    def update_category(self, category_id: uuid.UUID, category_data: MenuCategoryUpdate) -> Optional[MenuCategory]:
        category = self.category_repo.get(str(category_id))
        if not category:
            logger.warning(f"Category not found for update: {category_id}")
            return None

        # Valider l'unicité de l'ordre si modifié
        if category_data.ordre is not None and category_data.ordre != category.ordre:
            existing_categories = self.category_repo.get_by_menu_id(category.menu_id)
            if any(cat.ordre == category_data.ordre and cat.id != category.id for cat in existing_categories):
                logger.warning(f"Category order already exists in menu: {category_data.ordre}")
                raise ValueError("Category order already exists in this menu")

        updated_category = self.category_repo.update(
            category,
            category_data.model_dump(exclude_unset=True)
        )
        logger.info(f"Category updated: {category_id}")
        return updated_category


class StockService:
    def __init__(self, db: Session):
        self.db = db
        self.composant_repo = ComposantRepository(db)
        self.stock_repo = StockComposantRepository(db)
        self.mouvement_repo = StockMouvementRepository(db)

    def _stock_state(self, stock: StockComposant) -> dict:
        return {
            "composant_id": stock.composant_id,
            "quantite": stock.quantite,
            "reservee": stock.reservee,
            "disponible": stock.quantite - stock.reservee,
            "seuil_alerte": stock.seuil_alerte,
            "updated_at": stock.updated_at,
        }

    def get_restaurant_stock(self, restaurant_id: uuid.UUID) -> List[dict]:
        return [self._stock_state(stock) for stock in self.stock_repo.get_by_restaurant_id(restaurant_id)]

    def add_movement(self, composant_id: uuid.UUID, data: StockMouvementCreate) -> dict:
        composant = self.composant_repo.get(str(composant_id))
        if not composant:
            raise ValueError("Composant not found")
        stock = self.stock_repo.get_by_composant_id(composant_id, lock=True)
        if not stock:
            raise ValueError("Stock not initialized for component")
        if data.type == "entree":
            stock.quantite += data.quantite
        elif data.type == "ajustement":
            stock.quantite = data.quantite
            if stock.quantite < stock.reservee:
                raise ValueError("Stock cannot be lower than reserved quantity")
        else:
            available = stock.quantite - stock.reservee
            if data.quantite > available:
                raise ValueError("Insufficient available stock")
            stock.quantite -= data.quantite
        self.mouvement_repo.create({
            "composant_id": composant_id,
            "type": data.type,
            "quantite": data.quantite,
            "notes": data.notes,
        })
        self.db.refresh(stock)
        return self._stock_state(stock)

    def reserve(self, requirements: dict[uuid.UUID, Decimal]) -> None:
        stocks = {}
        for composant_id, required in requirements.items():
            stock = self.stock_repo.get_by_composant_id(composant_id, lock=True)
            if not stock or stock.quantite - stock.reservee < required:
                raise ValueError("Insufficient available stock for combination")
            stocks[composant_id] = stock
        for composant_id, required in requirements.items():
            stocks[composant_id].reservee += required

    def release(self, requirements: dict[uuid.UUID, Decimal]) -> None:
        for composant_id, required in requirements.items():
            stock = self.stock_repo.get_by_composant_id(composant_id, lock=True)
            if stock:
                stock.reservee = max(Decimal("0"), stock.reservee - required)

    def consume_reserved(self, requirements: dict[uuid.UUID, Decimal], reference_id: uuid.UUID) -> None:
        for composant_id, required in requirements.items():
            stock = self.stock_repo.get_by_composant_id(composant_id, lock=True)
            if not stock or stock.reservee < required or stock.quantite < required:
                raise ValueError("Reserved stock is no longer available")
            stock.reservee -= required
            stock.quantite -= required
            self.db.add(StockMouvement(
                composant_id=composant_id,
                type="sortie",
                quantite=required,
                reference_type="commande",
                reference_id=reference_id,
                notes="Consommation de commande",
            ))


class CombinaisonService:
    def __init__(self, db: Session):
        self.db = db
        self.restaurant_repo = RestaurantRepository(db)
        self.menu_repo = MenuRepository(db)
        self.composant_repo = ComposantRepository(db)
        self.combinaison_repo = CombinaisonRepository(db)
        self.link_repo = CombinaisonComposantRepository(db)
        self.stock_repo = StockComposantRepository(db)

    def create_composant(self, data: ComposantCreate, restaurant_id: uuid.UUID) -> Composant:
        if not self.restaurant_repo.get(str(restaurant_id)):
            raise ValueError("Restaurant not found")
        composant = self.composant_repo.create({**data.model_dump(), "restaurant_id": restaurant_id})
        self.stock_repo.create({"composant_id": composant.id})
        return composant

    def get_restaurant_composants(self, restaurant_id: uuid.UUID) -> List[Composant]:
        return self.composant_repo.get_by_restaurant_id(restaurant_id)

    def update_composant(self, composant_id: uuid.UUID, data: ComposantUpdate) -> Optional[Composant]:
        composant = self.composant_repo.get(str(composant_id))
        if not composant:
            return None
        return self.composant_repo.update(composant, data.model_dump(exclude_unset=True))

    def _validate_component_ids(self, restaurant_id: uuid.UUID, component_ids: List[uuid.UUID]) -> List[Composant]:
        if not component_ids:
            raise ValueError("A combination must contain at least one component")
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("A combination cannot contain duplicate components")
        components = self.composant_repo.get_by_restaurant_id(restaurant_id)
        by_id = {component.id: component for component in components}
        missing = [component_id for component_id in component_ids if component_id not in by_id]
        if missing:
            raise ValueError("All components must belong to this restaurant")
        return [by_id[component_id] for component_id in component_ids]

    def _serialize_combinaison(self, combinaison: Combinaison) -> dict:
        links = self.link_repo.get_by_combinaison_id(combinaison.id)
        return {
            "id": combinaison.id,
            "restaurant_id": combinaison.restaurant_id,
            "menu_id": combinaison.menu_id,
            "nom": combinaison.nom,
            "description": combinaison.description,
            "prix": combinaison.prix,
            "devise": combinaison.devise,
            "disponible": combinaison.disponible,
            "created_at": combinaison.created_at,
            "updated_at": combinaison.updated_at,
            "composant_ids": [link.composant_id for link in links],
        }

    def create_combinaison(self, data: CombinaisonCreate, restaurant_id: uuid.UUID) -> dict:
        if not self.restaurant_repo.get(str(restaurant_id)):
            raise ValueError("Restaurant not found")
        if data.menu_id:
            menu = self.menu_repo.get(str(data.menu_id))
            if not menu or menu.restaurant_id != restaurant_id:
                raise ValueError("Menu does not belong to this restaurant")
        self._validate_component_ids(restaurant_id, data.composant_ids)
        combinaison = self.combinaison_repo.create({
            **data.model_dump(exclude={"composant_ids"}),
            "restaurant_id": restaurant_id
        })
        self.link_repo.replace_for_combinaison(combinaison.id, data.composant_ids)
        self.db.flush()
        return self._serialize_combinaison(combinaison)

    def get_restaurant_combinaisons(self, restaurant_id: uuid.UUID) -> List[dict]:
        return [self._serialize_combinaison(item) for item in self.combinaison_repo.get_by_restaurant_id(restaurant_id)]

    def get_recommandations(self, restaurant_id: uuid.UUID) -> List[dict]:
        recommendations = []
        for combinaison in self.combinaison_repo.get_active_by_restaurant_id(restaurant_id):
            links = self.link_repo.get_by_combinaison_id(combinaison.id)
            component_ids = [link.composant_id for link in links]
            available = self.composant_repo.get_available_by_ids(restaurant_id, component_ids)
            available_ids = {component.id for component in available}
            stocks = {
                stock.composant_id: stock
                for stock in self.stock_repo.get_by_restaurant_id(restaurant_id)
            }
            if all(
                not link.obligatoire
                or (
                    link.composant_id in available_ids
                    and stocks.get(link.composant_id)
                    and stocks[link.composant_id].quantite > stocks[link.composant_id].reservee
                )
                for link in links
            ):
                recommendations.append(self._serialize_combinaison(combinaison))
        return recommendations

    def update_combinaison(self, combinaison_id: uuid.UUID, data: CombinaisonUpdate) -> Optional[dict]:
        combinaison = self.combinaison_repo.get(str(combinaison_id))
        if not combinaison:
            return None
        if data.menu_id:
            menu = self.menu_repo.get(str(data.menu_id))
            if not menu or menu.restaurant_id != combinaison.restaurant_id:
                raise ValueError("Menu does not belong to this restaurant")
        if data.composant_ids is not None:
            self._validate_component_ids(combinaison.restaurant_id, data.composant_ids)
        self.combinaison_repo.update(combinaison, data.model_dump(exclude_unset=True, exclude={"composant_ids"}))
        if data.composant_ids is not None:
            self.link_repo.replace_for_combinaison(combinaison.id, data.composant_ids)
        self.db.flush()
        return self._serialize_combinaison(combinaison)


class PlatService:
    def __init__(self, db: Session):
        self.db = db
        self.plat_repo = PlatRepository(db)
        self.category_repo = MenuCategoryRepository(db)
        self.restaurant_repo = RestaurantRepository(db)

    def create_plat(self, plat_data: PlatCreate, restaurant_id: uuid.UUID) -> Plat:
        # Valider que le restaurant existe
        restaurant = self.restaurant_repo.get(str(restaurant_id))
        if not restaurant:
            logger.warning(f"Restaurant not found: {restaurant_id}")
            raise ValueError("Restaurant not found")

        # Valider la catégorie si spécifiée
        if plat_data.category_id:
            category = self.category_repo.get(str(plat_data.category_id))
            if not category:
                logger.warning(f"Category not found: {plat_data.category_id}")
                raise ValueError("Category not found")
            
            if category.restaurant_id != restaurant_id:
                logger.warning(f"Category does not belong to restaurant: {plat_data.category_id}")
                raise ValueError("Category does not belong to this restaurant")

        # Valider le prix
        if plat_data.prix <= 0:
            logger.warning(f"Invalid price: {plat_data.prix}")
            raise ValueError("Price must be positive")

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

    def get_available_plats(self, restaurant_id: uuid.UUID) -> List[Plat]:
        return self.plat_repo.get_available_plats(restaurant_id)

    def get_category_plats(self, category_id: uuid.UUID) -> List[Plat]:
        return self.plat_repo.get_by_category_id(category_id)

    def update_plat(self, plat_id: uuid.UUID, plat_data: PlatUpdate) -> Optional[Plat]:
        plat = self.plat_repo.get(str(plat_id))
        if not plat:
            logger.warning(f"Plat not found for update: {plat_id}")
            return None

        # Valider la catégorie si modifiée
        if plat_data.category_id:
            category = self.category_repo.get(str(plat_data.category_id))
            if not category:
                logger.warning(f"Category not found: {plat_data.category_id}")
                raise ValueError("Category not found")
            
            if category.restaurant_id != plat.restaurant_id:
                logger.warning(f"Category does not belong to restaurant: {plat_data.category_id}")
                raise ValueError("Category does not belong to this restaurant")

        # Valider le prix si modifié
        if plat_data.prix is not None and plat_data.prix <= 0:
            logger.warning(f"Invalid price: {plat_data.prix}")
            raise ValueError("Price must be positive")

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
        self.restaurant_repo = RestaurantRepository(db)

    def create_boisson(self, boisson_data: BoissonCreate, restaurant_id: uuid.UUID) -> Boisson:
        # Valider que le restaurant existe
        restaurant = self.restaurant_repo.get(str(restaurant_id))
        if not restaurant:
            logger.warning(f"Restaurant not found: {restaurant_id}")
            raise ValueError("Restaurant not found")

        # Valider le prix
        if boisson_data.prix <= 0:
            logger.warning(f"Invalid price: {boisson_data.prix}")
            raise ValueError("Price must be positive")

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

    def get_available_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return self.boisson_repo.get_available_boissons(restaurant_id)

    def get_category_boissons(self, restaurant_id: uuid.UUID, category: str) -> List[Boisson]:
        return self.boisson_repo.get_by_category(restaurant_id, category)

    def get_alcoholic_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return self.boisson_repo.get_alcoholic_boissons(restaurant_id)

    def get_non_alcoholic_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return self.boisson_repo.get_non_alcoholic_boissons(restaurant_id)

    def update_boisson(self, boisson_id: uuid.UUID, boisson_data: BoissonUpdate) -> Optional[Boisson]:
        boisson = self.boisson_repo.get(str(boisson_id))
        if not boisson:
            logger.warning(f"Boisson not found for update: {boisson_id}")
            return None

        # Valider le prix si modifié
        if boisson_data.prix is not None and boisson_data.prix <= 0:
            logger.warning(f"Invalid price: {boisson_data.prix}")
            raise ValueError("Price must be positive")

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
        self.plat_repo = PlatRepository(db)
        self.boisson_repo = BoissonRepository(db)
        self.combinaison_repo = CombinaisonRepository(db)
        self.composant_repo = ComposantRepository(db)
        self.link_repo = CombinaisonComposantRepository(db)
        self.stock_service = StockService(db)
        self.table_repo = TableRepository(db)
        self.restaurant_repo = RestaurantRepository(db)

    def create_commande(self, commande_data: CommandeCreate, restaurant_id: uuid.UUID) -> Commande:
        # Valider que le restaurant existe
        restaurant = self.restaurant_repo.get(str(restaurant_id))
        if not restaurant:
            logger.warning(f"Restaurant not found: {restaurant_id}")
            raise ValueError("Restaurant not found")

        # Valider la table si spécifiée
        if commande_data.table_id:
            table = self.table_repo.get(str(commande_data.table_id))
            if not table or table.restaurant_id != restaurant_id:
                logger.warning(f"Invalid table for restaurant: {commande_data.table_id}")
                raise ValueError("Invalid table for this restaurant")
            
            # Vérifier que la table est libre
            if table.statut != "libre":
                logger.warning(f"Table is not available: {table.numero}")
                raise ValueError("Table is not available")

        # Créer la commande avec le taux de service du restaurant
        commande = self.commande_repo.create({
            **commande_data.model_dump(),
            "restaurant_id": restaurant_id,
            "taux_service": restaurant.taux_service
        })
        
        # Mettre à jour le statut de la table si assignée
        if commande_data.table_id:
            self.table_repo.update(table, {"statut": "occupee"})
        
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
        if commande_data.statut == CommandeStatut.PAYEE.value:
            raise ValueError("Payment status can only be changed by a confirmed payment provider event")
        allowed_statuses = {"en_cours", "servie", "annulee", "paiement_en_attente", "paiement_a_verifier"}
        if commande_data.statut is not None and commande_data.statut not in allowed_statuses:
            raise ValueError("Invalid commande status")
        previous_status = commande.statut
        if previous_status in {CommandeStatut.PAYEE.value, CommandeStatut.ANNULEE.value}:
            raise ValueError("A paid or cancelled commande cannot be edited")
        if commande_data.statut == CommandeStatut.ANNULEE.value:
            for item in self.item_repo.get_by_commande_id(commande_id):
                for requirement in (item.details_jsonb or {}).get("stock_requirements", []):
                    self.stock_service.release({uuid.UUID(requirement["composant_id"]): Decimal(requirement["quantite"])})
        for field, value in commande_data.model_dump(exclude_unset=True).items():
            setattr(commande, field, value)
        if commande_data.statut == CommandeStatut.ANNULEE.value and commande.table_id:
            table = self.table_repo.get(str(commande.table_id))
            if table and table.restaurant_id == commande.restaurant_id:
                self.table_repo.update(table, {"statut": "libre"})
        self.db.flush()
        logger.info(f"Commande updated: {commande_id}")
        return commande

    def confirm_payment(self, commande_id: uuid.UUID, payment_intent_id: uuid.UUID) -> Commande:
        commande = self.commande_repo.get(str(commande_id))
        if not commande:
            raise ValueError("Commande not found")
        if commande.statut == CommandeStatut.PAYEE.value:
            return commande
        if commande.statut in {CommandeStatut.ANNULEE.value}:
            raise ValueError("Cannot pay a cancelled commande")
        if commande.payment_intent_id is not None and commande.payment_intent_id != payment_intent_id:
            raise ValueError("Commande is linked to another payment intent")
        if commande.total is None or commande.total < 0:
            raise ValueError("Invalid commande total")
        for item in self.item_repo.get_by_commande_id(commande_id):
            for requirement in (item.details_jsonb or {}).get("stock_requirements", []):
                self.stock_service.consume_reserved({uuid.UUID(requirement["composant_id"]): Decimal(requirement["quantite"])}, commande_id)
        commande.statut = CommandeStatut.PAYEE.value
        commande.payment_intent_id = payment_intent_id
        commande.metadata_jsonb = {**(commande.metadata_jsonb or {}), "payment_intent_id": str(payment_intent_id), "payment_confirmed_at": datetime.now().isoformat()}
        if commande.table_id:
            table = self.table_repo.get(str(commande.table_id))
            if table and table.restaurant_id == commande.restaurant_id:
                self.table_repo.update(table, {"statut": "libre"})
        self.db.flush()
        return commande

    def add_item(self, commande_id: uuid.UUID, item_data: CommandeItemCreate) -> CommandeItem:
        commande = self.commande_repo.get(str(commande_id))
        if not commande:
            logger.warning(f"Commande not found: {commande_id}")
            raise ValueError("Commande not found")

        selected_types = sum(bool(value) for value in (
            item_data.plat_id,
            item_data.boisson_id,
            item_data.combinaison_id
        ))
        if selected_types != 1:
            raise ValueError("Item must have exactly one plat, boisson or combinaison")

        # Le prix est toujours déterminé par le catalogue, jamais par le client.
        prix_unitaire = None
        supplements_total = Decimal("0")
        details = {"supplements": []}
        stock_requirements = {}
        if item_data.combinaison_id:
            combinaison = self.combinaison_repo.get(str(item_data.combinaison_id))
            if not combinaison or combinaison.restaurant_id != commande.restaurant_id:
                raise ValueError("Invalid combinaison for this restaurant")
            if not combinaison.disponible:
                raise ValueError("Combinaison is not available")
            links = self.link_repo.get_by_combinaison_id(combinaison.id)
            component_ids = [link.composant_id for link in links]
            available_ids = {
                component.id for component in self.composant_repo.get_available_by_ids(
                    commande.restaurant_id,
                    component_ids
                )
            }
            if any(link.obligatoire and link.composant_id not in available_ids for link in links):
                raise ValueError("Combinaison contains an unavailable component")
            prix_unitaire = combinaison.prix
            details["combinaison"] = combinaison.nom
            for link in links:
                if link.obligatoire:
                    stock_requirements[link.composant_id] = (
                        stock_requirements.get(link.composant_id, Decimal("0"))
                        + Decimal(str(link.quantite)) * item_data.quantite
                    )

        elif item_data.plat_id:
            plat = self.plat_repo.get(str(item_data.plat_id))
            if not plat or plat.restaurant_id != commande.restaurant_id:
                logger.warning(f"Invalid plat for restaurant: {item_data.plat_id}")
                raise ValueError("Invalid plat for this restaurant")
            if not plat.disponible:
                logger.warning(f"Plat not available: {plat.nom}")
                raise ValueError("Plat is not available")
            prix_unitaire = plat.prix

        elif item_data.boisson_id:
            boisson = self.boisson_repo.get(str(item_data.boisson_id))
            if not boisson or boisson.restaurant_id != commande.restaurant_id:
                logger.warning(f"Invalid boisson for restaurant: {item_data.boisson_id}")
                raise ValueError("Invalid boisson for this restaurant")
            if not boisson.disponible:
                logger.warning(f"Boisson not available: {boisson.nom}")
                raise ValueError("Boisson is not available")
            prix_unitaire = boisson.prix

        if item_data.supplement_ids:
            supplements = self.composant_repo.get_available_by_ids(
                commande.restaurant_id,
                item_data.supplement_ids
            )
            if len(supplements) != len(item_data.supplement_ids):
                raise ValueError("One or more supplements are invalid or unavailable")
            supplements_by_id = {supplement.id: supplement for supplement in supplements}
            for supplement_id in item_data.supplement_ids:
                supplement = supplements_by_id.get(supplement_id)
                if not supplement:
                    raise ValueError("One or more supplements are invalid or unavailable")
                supplements_total += supplement.prix_supplement
                stock_requirements[supplement.id] = (
                    stock_requirements.get(supplement.id, Decimal("0"))
                    + item_data.quantite
                )
                details["supplements"].append({
                    "id": str(supplement.id),
                    "nom": supplement.nom,
                    "prix": str(supplement.prix_supplement),
                })

        if stock_requirements:
            self.stock_service.reserve(stock_requirements)
            details["stock_requirements"] = [
                {"composant_id": str(composant_id), "quantite": str(quantite)}
                for composant_id, quantite in stock_requirements.items()
            ]

        # Calculer le total de l'item
        prix_facture_unitaire = prix_unitaire + supplements_total
        total = prix_facture_unitaire * item_data.quantite

        # Créer l'item avec le prix calculé
        item = self.item_repo.create({
            "commande_id": commande_id,
            "plat_id": item_data.plat_id,
            "boisson_id": item_data.boisson_id,
            "combinaison_id": item_data.combinaison_id,
            "quantite": item_data.quantite,
            "prix_unitaire": prix_facture_unitaire,
            "total": total,
            "supplements_total": supplements_total,
            "details_jsonb": details,
            "notes": item_data.notes
        })
        
        # Recalculer le total de la commande
        self._recalculate_commande_total(commande_id)
        
        logger.info(f"Commande item added: {item.id}")
        return item

    def get_commande_items(self, commande_id: uuid.UUID) -> List[CommandeItem]:
        return self.item_repo.get_by_commande_id(commande_id)

    def _recalculate_commande_total(self, commande_id: uuid.UUID) -> None:
        """Recalculer le total de la commande en fonction de ses items"""
        commande = self.commande_repo.get(str(commande_id))
        if not commande:
            return

        items = self.item_repo.get_by_commande_id(commande_id)
        sous_total = sum(item.total for item in items)
        
        # Appliquer le taux de service
        total = sous_total * (1 + (commande.taux_service / 100)) if commande.taux_service else sous_total
        
        self.commande_repo.update(commande, {"total": total})
