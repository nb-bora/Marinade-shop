from typing import Dict, Optional, List
from datetime import datetime
from decimal import Decimal
from sqlalchemy import exists, func, not_, or_
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
    PlatComposant,
    Boisson,
    Table,
    Commande,
    CommandeItem,
    CommandeRefund,
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

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Menu]:
        return (
            self.db.query(Menu)
            .filter(Menu.restaurant_id == restaurant_id)
            .order_by(Menu.created_at, Menu.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_active_menus(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Menu]:
        return (
            self.db.query(Menu)
            .filter(Menu.restaurant_id == restaurant_id, Menu.actif == True)
            .order_by(Menu.created_at, Menu.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def name_taken(
        self,
        restaurant_id: uuid.UUID,
        name: str,
        exclude_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """Un menu du restaurant porte-t-il deja ce nom ? Une seule ligne lue."""
        query = self.db.query(Menu.id).filter(
            Menu.restaurant_id == restaurant_id, Menu.name == name
        )
        if exclude_id is not None:
            query = query.filter(Menu.id != exclude_id)
        return query.first() is not None


class MenuCategoryRepository(BaseRepository[MenuCategory]):
    def __init__(self, db: Session):
        super().__init__(MenuCategory, db)

    def get_by_menu_id(
        self, menu_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[MenuCategory]:
        return (
            self.db.query(MenuCategory)
            .filter(MenuCategory.menu_id == menu_id)
            .order_by(MenuCategory.ordre, MenuCategory.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def ordre_taken(
        self,
        menu_id: uuid.UUID,
        ordre: int,
        exclude_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """Une categorie du menu a-t-elle deja cet ordre ? Une seule ligne lue."""
        query = self.db.query(MenuCategory.id).filter(
            MenuCategory.menu_id == menu_id, MenuCategory.ordre == ordre
        )
        if exclude_id is not None:
            query = query.filter(MenuCategory.id != exclude_id)
        return query.first() is not None

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[MenuCategory]:
        return (
            self.db.query(MenuCategory)
            .filter(MenuCategory.restaurant_id == restaurant_id)
            .order_by(MenuCategory.created_at, MenuCategory.id)
            .offset(skip)
            .limit(limit)
            .all()
        )


class ComposantRepository(BaseRepository[Composant]):
    def __init__(self, db: Session):
        super().__init__(Composant, db)

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Composant]:
        return (
            self.db.query(Composant)
            .filter(Composant.restaurant_id == restaurant_id)
            .order_by(Composant.created_at, Composant.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_ids(
        self, restaurant_id: uuid.UUID, component_ids: List[uuid.UUID]
    ) -> Dict[uuid.UUID, Composant]:
        """Composants du restaurant parmi ces identifiants, en UNE requete indexee."""
        if not component_ids:
            return {}
        rows = (
            self.db.query(Composant)
            .filter(
                Composant.restaurant_id == restaurant_id,
                Composant.id.in_(set(component_ids)),
            )
            .all()
        )
        return {row.id: row for row in rows}

    def get_available_by_ids(
        self, restaurant_id: uuid.UUID, component_ids: List[uuid.UUID]
    ) -> List[Composant]:
        return (
            self.db.query(Composant)
            .filter(
                Composant.restaurant_id == restaurant_id,
                Composant.id.in_(component_ids),
                Composant.disponible == True,
            )
            .all()
        )


class CombinaisonRepository(BaseRepository[Combinaison]):
    def __init__(self, db: Session):
        super().__init__(Combinaison, db)

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Combinaison]:
        return (
            self.db.query(Combinaison)
            .filter(Combinaison.restaurant_id == restaurant_id)
            .order_by(Combinaison.created_at, Combinaison.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_sellable(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Combinaison]:
        """Combinaisons actives dont tous les composants obligatoires sont vendables.

        Un composant est vendable s'il est disponible ET si son stock libre
        (quantite - reservee) couvre la quantite exigee par la combinaison. Tout est
        evalue par la base, une page a la fois : aucune boucle par combinaison.
        """
        blocking_link = (
            exists()
            .where(CombinaisonComposant.combinaison_id == Combinaison.id)
            .where(CombinaisonComposant.obligatoire.is_(True))
            .where(
                exists()
                .where(Composant.id == CombinaisonComposant.composant_id)
                .where(
                    or_(
                        Composant.disponible.is_(False),
                        not_(
                            exists()
                            .where(StockComposant.composant_id == Composant.id)
                            .where(
                                StockComposant.quantite - StockComposant.reservee
                                >= CombinaisonComposant.quantite
                            )
                        ),
                    )
                )
            )
        )
        return (
            self.db.query(Combinaison)
            .filter(
                Combinaison.restaurant_id == restaurant_id,
                Combinaison.disponible.is_(True),
                not_(blocking_link),
            )
            .order_by(Combinaison.created_at, Combinaison.id)
            .offset(skip)
            .limit(limit)
            .all()
        )


class CombinaisonComposantRepository(BaseRepository[CombinaisonComposant]):
    def __init__(self, db: Session):
        super().__init__(CombinaisonComposant, db)

    def get_by_combinaison_id(
        self, combinaison_id: uuid.UUID
    ) -> List[CombinaisonComposant]:
        return (
            self.db.query(CombinaisonComposant)
            .filter(CombinaisonComposant.combinaison_id == combinaison_id)
            .all()
        )

    def get_by_combinaison_ids(
        self, combinaison_ids: List[uuid.UUID]
    ) -> Dict[uuid.UUID, List[CombinaisonComposant]]:
        """Liens de plusieurs combinaisons en UNE requete (evite un N+1)."""
        grouped: Dict[uuid.UUID, List[CombinaisonComposant]] = {
            combinaison_id: [] for combinaison_id in combinaison_ids
        }
        if not combinaison_ids:
            return grouped
        rows = (
            self.db.query(CombinaisonComposant)
            .filter(CombinaisonComposant.combinaison_id.in_(set(combinaison_ids)))
            .order_by(CombinaisonComposant.created_at, CombinaisonComposant.id)
            .all()
        )
        for row in rows:
            grouped[row.combinaison_id].append(row)
        return grouped

    def replace_for_combinaison(
        self, combinaison_id: uuid.UUID, component_ids: List[uuid.UUID]
    ) -> None:
        self.db.query(CombinaisonComposant).filter(
            CombinaisonComposant.combinaison_id == combinaison_id
        ).delete(synchronize_session=False)
        for component_id in component_ids:
            self.create(
                {
                    "combinaison_id": combinaison_id,
                    "composant_id": component_id,
                    "obligatoire": True,
                }
            )


class StockComposantRepository(BaseRepository[StockComposant]):
    def __init__(self, db: Session):
        super().__init__(StockComposant, db)

    def get_by_composant_id(
        self, composant_id: uuid.UUID, lock: bool = False
    ) -> Optional[StockComposant]:
        query = self.db.query(StockComposant).filter(
            StockComposant.composant_id == composant_id
        )
        if lock:
            query = query.with_for_update()
        return query.first()

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[StockComposant]:
        return (
            self.db.query(StockComposant)
            .join(Composant)
            .filter(Composant.restaurant_id == restaurant_id)
            .order_by(Composant.created_at, Composant.id)
            .offset(skip)
            .limit(limit)
            .all()
        )


class StockMouvementRepository(BaseRepository[StockMouvement]):
    def __init__(self, db: Session):
        super().__init__(StockMouvement, db)

    def get_by_composant_id(self, composant_id: uuid.UUID) -> List[StockMouvement]:
        return (
            self.db.query(StockMouvement)
            .filter(StockMouvement.composant_id == composant_id)
            .order_by(StockMouvement.created_at.desc())
            .all()
        )


class PlatRepository(BaseRepository[Plat]):
    def __init__(self, db: Session):
        super().__init__(Plat, db)

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Plat]:
        return (
            self.db.query(Plat)
            .filter(Plat.restaurant_id == restaurant_id)
            .order_by(Plat.created_at, Plat.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_category_id(self, category_id: uuid.UUID) -> List[Plat]:
        return self.db.query(Plat).filter(Plat.category_id == category_id).all()

    def get_available_plats(self, restaurant_id: uuid.UUID) -> List[Plat]:
        return (
            self.db.query(Plat)
            .filter(Plat.restaurant_id == restaurant_id, Plat.disponible == True)
            .all()
        )


class PlatComposantRepository(BaseRepository[PlatComposant]):
    def __init__(self, db: Session):
        super().__init__(PlatComposant, db)

    def get_by_plat_id(self, plat_id: uuid.UUID) -> List[PlatComposant]:
        return (
            self.db.query(PlatComposant)
            .filter(PlatComposant.plat_id == plat_id)
            .order_by(PlatComposant.ordre)
            .all()
        )

    def get_by_composant_id(self, composant_id: uuid.UUID) -> List[PlatComposant]:
        return (
            self.db.query(PlatComposant)
            .filter(PlatComposant.composant_id == composant_id)
            .all()
        )

    def get_by_plat_and_composant(
        self, plat_id: uuid.UUID, composant_id: uuid.UUID
    ) -> Optional[PlatComposant]:
        return (
            self.db.query(PlatComposant)
            .filter(
                PlatComposant.plat_id == plat_id,
                PlatComposant.composant_id == composant_id,
            )
            .first()
        )

    def replace_for_plat(self, plat_id: uuid.UUID, composant_data: List[dict]) -> None:
        self.db.query(PlatComposant).filter(PlatComposant.plat_id == plat_id).delete(
            synchronize_session=False
        )
        for data in composant_data:
            self.create(
                {
                    "plat_id": plat_id,
                    "composant_id": data["composant_id"],
                    "quantite": data.get("quantite", 1),
                    "unite": data.get("unite", "portion"),
                    "ordre": data.get("ordre", 0),
                }
            )


class BoissonRepository(BaseRepository[Boisson]):
    def __init__(self, db: Session):
        super().__init__(Boisson, db)

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Boisson]:
        return (
            self.db.query(Boisson)
            .filter(Boisson.restaurant_id == restaurant_id)
            .order_by(Boisson.created_at, Boisson.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_category(self, restaurant_id: uuid.UUID, category: str) -> List[Boisson]:
        return (
            self.db.query(Boisson)
            .filter(
                Boisson.restaurant_id == restaurant_id, Boisson.category == category
            )
            .all()
        )

    def get_available_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return (
            self.db.query(Boisson)
            .filter(Boisson.restaurant_id == restaurant_id, Boisson.disponible == True)
            .all()
        )

    def get_alcoholic_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return (
            self.db.query(Boisson)
            .filter(
                Boisson.restaurant_id == restaurant_id,
                Boisson.alcool == True,
                Boisson.disponible == True,
            )
            .all()
        )

    def get_non_alcoholic_boissons(self, restaurant_id: uuid.UUID) -> List[Boisson]:
        return (
            self.db.query(Boisson)
            .filter(
                Boisson.restaurant_id == restaurant_id,
                Boisson.alcool == False,
                Boisson.disponible == True,
            )
            .all()
        )


class TableRepository(BaseRepository[Table]):
    def __init__(self, db: Session):
        super().__init__(Table, db)

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Table]:
        return (
            self.db.query(Table)
            .filter(Table.restaurant_id == restaurant_id)
            .order_by(Table.created_at, Table.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_statut(self, restaurant_id: uuid.UUID, statut: str) -> List[Table]:
        return (
            self.db.query(Table)
            .filter(Table.restaurant_id == restaurant_id, Table.statut == statut)
            .all()
        )

    def get_free_tables(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Table]:
        return (
            self.db.query(Table)
            .filter(Table.restaurant_id == restaurant_id, Table.statut == "libre")
            .order_by(Table.created_at, Table.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_numero(self, restaurant_id: uuid.UUID, numero: str) -> Optional[Table]:
        return (
            self.db.query(Table)
            .filter(Table.restaurant_id == restaurant_id, Table.numero == numero)
            .first()
        )


class CommandeRepository(BaseRepository[Commande]):
    def __init__(self, db: Session):
        super().__init__(Commande, db)

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Commande]:
        return (
            self.db.query(Commande)
            .filter(Commande.restaurant_id == restaurant_id)
            .order_by(Commande.created_at.desc(), Commande.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_table_id(self, table_id: uuid.UUID) -> List[Commande]:
        return self.db.query(Commande).filter(Commande.table_id == table_id).all()

    def get_by_statut(self, restaurant_id: uuid.UUID, statut: str) -> List[Commande]:
        return (
            self.db.query(Commande)
            .filter(Commande.restaurant_id == restaurant_id, Commande.statut == statut)
            .all()
        )

    def get_active_commandes(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[Commande]:
        return (
            self.db.query(Commande)
            .filter(
                Commande.restaurant_id == restaurant_id,
                Commande.statut.in_(["en_cours", "servie"]),
            )
            .order_by(Commande.created_at, Commande.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def update_refund_status(
        self,
        commande_id: uuid.UUID,
        refund_status: str,
        refunded_amount: Optional[float] = None,
        refund_reason: Optional[str] = None,
        refunded_by: Optional[uuid.UUID] = None,
        refunded_at: Optional[datetime] = None,
    ) -> Optional[Commande]:
        commande = self.get(commande_id)
        if commande:
            commande.refund_status = refund_status
            if refunded_amount is not None:
                commande.refunded_amount = refunded_amount
            if refund_reason is not None:
                commande.refund_reason = refund_reason
            if refunded_by is not None:
                commande.refunded_by = refunded_by
            commande.refunded_at = refunded_at or datetime.utcnow()
            self.db.flush()
            self.db.refresh(commande)
        return commande

    def create_refund(
        self,
        commande_id: uuid.UUID,
        amount: float,
        reason: Optional[str] = None,
        initiated_by: Optional[uuid.UUID] = None,
        status: str = "requested",
        notes_jsonb: Optional[dict] = None,
    ) -> CommandeRefund:
        refund = CommandeRefund(
            commande_id=commande_id,
            amount=amount,
            reason=reason,
            status=status,
            initiated_by=initiated_by,
            notes_jsonb=notes_jsonb,
        )
        self.db.add(refund)
        self.db.flush()
        self.db.refresh(refund)
        return refund

    def get_refunds(self, commande_id: uuid.UUID) -> List[CommandeRefund]:
        return (
            self.db.query(CommandeRefund)
            .filter(CommandeRefund.commande_id == commande_id)
            .order_by(CommandeRefund.created_at.desc())
            .all()
        )


class CommandeItemRepository(BaseRepository[CommandeItem]):
    def __init__(self, db: Session):
        super().__init__(CommandeItem, db)

    def get_by_commande_id(self, commande_id: uuid.UUID) -> List[CommandeItem]:
        return (
            self.db.query(CommandeItem)
            .filter(CommandeItem.commande_id == commande_id)
            .all()
        )

    def get_by_plat_id(self, plat_id: uuid.UUID) -> List[CommandeItem]:
        return self.db.query(CommandeItem).filter(CommandeItem.plat_id == plat_id).all()

    def get_by_boisson_id(self, boisson_id: uuid.UUID) -> List[CommandeItem]:
        return (
            self.db.query(CommandeItem)
            .filter(CommandeItem.boisson_id == boisson_id)
            .all()
        )


class CommandeRefundRepository(BaseRepository[CommandeRefund]):
    def __init__(self, db: Session):
        super().__init__(CommandeRefund, db)

    def get_by_commande_id(self, commande_id: uuid.UUID) -> List[CommandeRefund]:
        return (
            self.db.query(CommandeRefund)
            .filter(CommandeRefund.commande_id == commande_id)
            .order_by(CommandeRefund.created_at.desc())
            .all()
        )

    def pending_amount(self, commande_id: uuid.UUID) -> Decimal:
        """Somme des demandes en attente d'une commande (une ligne d'agregat)."""
        total = (
            self.db.query(func.coalesce(func.sum(CommandeRefund.amount), 0))
            .filter(
                CommandeRefund.commande_id == commande_id,
                CommandeRefund.status == "requested",
            )
            .scalar()
        )
        return Decimal(str(total))

    def get_by_status(
        self, status: str, skip: int = 0, limit: int = 100
    ) -> List[CommandeRefund]:
        return (
            self.db.query(CommandeRefund)
            .filter(CommandeRefund.status == status)
            .order_by(CommandeRefund.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_by_restaurant_id(
        self, restaurant_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[CommandeRefund]:
        return (
            self.db.query(CommandeRefund)
            .join(Commande)
            .filter(Commande.restaurant_id == restaurant_id)
            .order_by(CommandeRefund.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def update_status(
        self,
        refund_id: uuid.UUID,
        status: str,
        processed_by: Optional[uuid.UUID] = None,
        processed_at: Optional[datetime] = None,
        external_reference: Optional[str] = None,
    ) -> Optional[CommandeRefund]:
        refund = self.get(refund_id)
        if refund:
            refund.status = status
            if processed_by is not None:
                refund.processed_by = processed_by
            refund.processed_at = processed_at or datetime.utcnow()
            if external_reference is not None:
                refund.external_reference = external_reference
            self.db.flush()
            self.db.refresh(refund)
        return refund
