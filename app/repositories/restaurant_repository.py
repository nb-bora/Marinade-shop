from typing import Optional, List
from sqlalchemy.orm import Session
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
from app.repositories.base import BaseRepository
import uuid


class RestaurantRepository(BaseRepository[Restaurant]):
    def __init__(self, db: Session):
        super().__init__(Restaurant, db)

    def get_by_user_id(self, user_id: uuid.UUID) -> Optional[Restaurant]:
        return self.db.query(Restaurant).filter(Restaurant.user_id == user_id).first()

    def get_active_restaurants(self) -> List[Restaurant]:
        return self.db.query(Restaurant).filter(Restaurant.is_active == True).all()


class MenuRepository(BaseRepository[Menu]):
    def __init__(self, db: Session):
        super().__init__(Menu, db)

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[Menu]:
        return self.db.query(Menu).filter(Menu.restaurant_id == restaurant_id).all()

    def get_active_menus(self, restaurant_id: uuid.UUID) -> List[Menu]:
        return self.db.query(Menu).filter(
            Menu.restaurant_id == restaurant_id,
            Menu.actif == True
        ).all()


class MenuCategoryRepository(BaseRepository[MenuCategory]):
    def __init__(self, db: Session):
        super().__init__(MenuCategory, db)

    def get_by_menu_id(self, menu_id: uuid.UUID) -> List[MenuCategory]:
        return self.db.query(MenuCategory).filter(
            MenuCategory.menu_id == menu_id
        ).order_by(MenuCategory.ordre).all()

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[MenuCategory]:
        return self.db.query(MenuCategory).filter(
            MenuCategory.restaurant_id == restaurant_id
        ).all()


class ComposantRepository(BaseRepository[Composant]):
    def __init__(self, db: Session):
        super().__init__(Composant, db)

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[Composant]:
        return self.db.query(Composant).filter(
            Composant.restaurant_id == restaurant_id
        ).all()

    def get_available_by_ids(self, restaurant_id: uuid.UUID, component_ids: List[uuid.UUID]) -> List[Composant]:
        return self.db.query(Composant).filter(
            Composant.restaurant_id == restaurant_id,
            Composant.id.in_(component_ids),
            Composant.disponible == True
        ).all()


class CombinaisonRepository(BaseRepository[Combinaison]):
    def __init__(self, db: Session):
        super().__init__(Combinaison, db)

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[Combinaison]:
        return self.db.query(Combinaison).filter(
            Combinaison.restaurant_id == restaurant_id
        ).all()

    def get_active_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[Combinaison]:
        return self.db.query(Combinaison).filter(
            Combinaison.restaurant_id == restaurant_id,
            Combinaison.disponible == True
        ).all()


class CombinaisonComposantRepository(BaseRepository[CombinaisonComposant]):
    def __init__(self, db: Session):
        super().__init__(CombinaisonComposant, db)

    def get_by_combinaison_id(self, combinaison_id: uuid.UUID) -> List[CombinaisonComposant]:
        return self.db.query(CombinaisonComposant).filter(
            CombinaisonComposant.combinaison_id == combinaison_id
        ).all()

    def replace_for_combinaison(self, combinaison_id: uuid.UUID, component_ids: List[uuid.UUID]) -> None:
        self.db.query(CombinaisonComposant).filter(
            CombinaisonComposant.combinaison_id == combinaison_id
        ).delete(synchronize_session=False)
        for component_id in component_ids:
            self.create({
                "combinaison_id": combinaison_id,
                "composant_id": component_id,
                "obligatoire": True
            })


class StockComposantRepository(BaseRepository[StockComposant]):
    def __init__(self, db: Session):
        super().__init__(StockComposant, db)

    def get_by_composant_id(self, composant_id: uuid.UUID, lock: bool = False) -> Optional[StockComposant]:
        query = self.db.query(StockComposant).filter(StockComposant.composant_id == composant_id)
        if lock:
            query = query.with_for_update()
        return query.first()

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[StockComposant]:
        return self.db.query(StockComposant).join(Composant).filter(
            Composant.restaurant_id == restaurant_id
        ).all()


class StockMouvementRepository(BaseRepository[StockMouvement]):
    def __init__(self, db: Session):
        super().__init__(StockMouvement, db)

    def get_by_composant_id(self, composant_id: uuid.UUID) -> List[StockMouvement]:
        return self.db.query(StockMouvement).filter(
            StockMouvement.composant_id == composant_id
        ).order_by(StockMouvement.created_at.desc()).all()


class PlatRepository(BaseRepository[Plat]):
    def __init__(self, db: Session):
        super().__init__(Plat, db)

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[Plat]:
        return self.db.query(Plat).filter(Plat.restaurant_id == restaurant_id).all()

    def get_by_category_id(self, category_id: uuid.UUID) -> List[Plat]:
        return self.db.query(Plat).filter(Plat.category_id == category_id).all()

    def get_available_plats(self, restaurant_id: uuid.UUID) -> List[Plat]:
        return self.db.query(Plat).filter(
            Plat.restaurant_id == restaurant_id,
            Plat.disponible == True
        ).all()


class BoissonRepository(BaseRepository[Boisson]):
    def __init__(self, db: Session):
        super().__init__(Boisson, db)

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return self.db.query(Boisson).filter(Boisson.restaurant_id == restaurant_id).all()

    def get_by_category(self, restaurant_id: uuid.UUID, category: str) -> List[Boisson]:
        return self.db.query(Boisson).filter(
            Boisson.restaurant_id == restaurant_id,
            Boisson.category == category
        ).all()

    def get_available_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return self.db.query(Boisson).filter(
            Boisson.restaurant_id == restaurant_id,
            Boisson.disponible == True
        ).all()

    def get_alcoholic_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return self.db.query(Boisson).filter(
            Boisson.restaurant_id == restaurant_id,
            Boisson.alcool == True,
            Boisson.disponible == True
        ).all()

    def get_non_alcoholic_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return self.db.query(Boisson).filter(
            Boisson.restaurant_id == restaurant_id,
            Boisson.alcool == False,
            Boisson.disponible == True
        ).all()


class TableRepository(BaseRepository[Table]):
    def __init__(self, db: Session):
        super().__init__(Table, db)

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID) -> List[Table]:
        return self.db.query(Table).filter(Table.restaurant_id == restaurant_id).all()

    def get_by_statut(self, restaurant_id: uuid.UUID, statut: str) -> List[Table]:
        return self.db.query(Table).filter(
            Table.restaurant_id == restaurant_id,
            Table.statut == statut
        ).all()

    def get_free_tables(self, restaurant_id: uuid.UUID) -> List[Table]:
        return self.db.query(Table).filter(
            Table.restaurant_id == restaurant_id,
            Table.statut == "libre"
        ).all()

    def get_by_numero(self, restaurant_id: uuid.UUID, numero: str) -> Optional[Table]:
        return self.db.query(Table).filter(
            Table.restaurant_id == restaurant_id,
            Table.numero == numero
        ).first()


class CommandeRepository(BaseRepository[Commande]):
    def __init__(self, db: Session):
        super().__init__(Commande, db)

    def get_by_restaurant_id(self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[Commande]:
        return self.db.query(Commande).filter(
            Commande.restaurant_id == restaurant_id
        ).order_by(Commande.created_at.desc()).offset(skip).limit(limit).all()

    def get_by_table_id(self, table_id: uuid.UUID) -> List[Commande]:
        return self.db.query(Commande).filter(Commande.table_id == table_id).all()

    def get_by_statut(self, restaurant_id: uuid.UUID, statut: str) -> List[Commande]:
        return self.db.query(Commande).filter(
            Commande.restaurant_id == restaurant_id,
            Commande.statut == stat
        ).all()

    def get_active_commandes(self, restaurant_id: uuid.UUID) -> List[Commande]:
        return self.db.query(Commande).filter(
            Commande.restaurant_id == restaurant_id,
            Commande.statut.in_(["en_cours", "servie"])
        ).all()


class CommandeItemRepository(BaseRepository[CommandeItem]):
    def __init__(self, db: Session):
        super().__init__(CommandeItem, db)

    def get_by_commande_id(self, commande_id: uuid.UUID) -> List[CommandeItem]:
        return self.db.query(CommandeItem).filter(CommandeItem.commande_id == commande_id).all()

    def get_by_plat_id(self, plat_id: uuid.UUID) -> List[CommandeItem]:
        return self.db.query(CommandeItem).filter(CommandeItem.plat_id == plat_id).all()

    def get_by_boisson_id(self, boisson_id: uuid.UUID) -> List[CommandeItem]:
        return self.db.query(CommandeItem).filter(CommandeItem.boisson_id == boisson_id).all()
