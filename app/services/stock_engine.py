"""Moteur de stock : l'unique endroit qui modifie quantités et réservations.

Invariants, vérifiés ici ET par la base (CHECK quantite >= 0, reservee >= 0,
reservee <= quantite) :

    quantite  = stock physique
    reservee  = stock promis à des commandes ouvertes (pas encore consommé)
    disponible = quantite - reservee

Cycle de vie d'une ligne vendue :

    reserve  -> consume_reserved   (commande payée)
    reserve  -> release            (commande annulée)
    consume_direct                 (vente consommée tout de suite : moteur ROS)
    restock                        (retour en stock, jamais automatique)

Concurrence : toutes les lignes de stock concernées sont verrouillées en UNE requête
``SELECT ... FOR UPDATE ORDER BY composant_id``. L'ordre fixe évite les interblocages
entre deux commandes qui partagent des composants, et le nombre de requêtes ne dépend
pas du nombre d'articles. ``populate_existing`` force la relecture après l'attente du
verrou : sans lui on calculerait sur des valeurs périmées.
"""

import uuid
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.restaurant import Composant, StockComposant, StockMouvement
from app.utils.exceptions import InsufficientStockError

Requirements = Dict[uuid.UUID, Decimal]

ZERO = Decimal("0")


def merge_requirements(*parts: Requirements) -> Requirements:
    merged: Requirements = {}
    for part in parts:
        for composant_id, quantity in part.items():
            merged[composant_id] = merged.get(composant_id, ZERO) + quantity
    return merged


def scale_requirements(requirements: Requirements, factor: Decimal) -> Requirements:
    return {cid: qty * factor for cid, qty in requirements.items()}


def requirements_to_json(requirements: Requirements) -> List[dict]:
    """Forme stockée sur la ligne de commande, pour pouvoir libérer / rendre ensuite."""
    return [
        {"composant_id": str(cid), "quantite": str(qty)}
        for cid, qty in requirements.items()
    ]


def requirements_from_json(raw: Optional[Iterable[dict]]) -> Requirements:
    return merge_requirements(
        *[{uuid.UUID(r["composant_id"]): Decimal(r["quantite"])} for r in raw or []]
    )


class StockEngine:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ verrous
    def _lock(self, requirements: Requirements) -> Dict[uuid.UUID, StockComposant]:
        if not requirements:
            return {}
        rows = (
            self.db.execute(
                select(StockComposant)
                .where(StockComposant.composant_id.in_(list(requirements)))
                .order_by(StockComposant.composant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            .scalars()
            .all()
        )
        return {row.composant_id: row for row in rows}

    def _shortage(
        self,
        stocks: Dict[uuid.UUID, StockComposant],
        requirements: Requirements,
        *,
        from_reserved: bool,
    ) -> None:
        """Lève InsufficientStockError listant TOUS les composants en défaut."""
        short: List[tuple] = []
        for composant_id, required in requirements.items():
            stock = stocks.get(composant_id)
            if stock is None:
                short.append((composant_id, required, ZERO))
                continue
            available = stock.reservee if from_reserved else stock.quantite - stock.reservee
            if from_reserved and stock.quantite < required:
                available = min(available, stock.quantite)
            if available < required:
                short.append((composant_id, required, available))
        if not short:
            return
        names = {
            row.id: row.nom
            for row in self.db.execute(
                select(Composant.id, Composant.nom).where(
                    Composant.id.in_([cid for cid, _, _ in short])
                )
            )
        }
        details = [
            {
                "composant_id": str(cid),
                "nom": names.get(cid, "composant inconnu"),
                "requis": str(required),
                "disponible": str(available),
            }
            for cid, required, available in short
        ]
        listing = ", ".join(
            f"{d['nom']} (besoin {d['requis']}, disponible {d['disponible']})"
            for d in details
        )
        raise InsufficientStockError(f"Stock insuffisant : {listing}", details=details)

    # --------------------------------------------------------------- opérations
    def reserve(self, requirements: Requirements) -> None:
        """Promet du stock à une commande ouverte (rien n'est encore consommé)."""
        stocks = self._lock(requirements)
        self._shortage(stocks, requirements, from_reserved=False)
        for composant_id, required in requirements.items():
            stocks[composant_id].reservee += required
        self.db.flush()

    def release(self, requirements: Requirements) -> None:
        """Annule une promesse de stock (commande annulée)."""
        stocks = self._lock(requirements)
        for composant_id, required in requirements.items():
            stock = stocks.get(composant_id)
            if stock is not None:
                stock.reservee = max(ZERO, stock.reservee - required)
        self.db.flush()

    def consume_reserved(
        self,
        requirements: Requirements,
        reference_type: str,
        reference_id: uuid.UUID,
        notes: str = "",
    ) -> List[StockComposant]:
        """Transforme une promesse en sortie réelle (commande payée)."""
        stocks = self._lock(requirements)
        self._shortage(stocks, requirements, from_reserved=True)
        for composant_id, required in requirements.items():
            stock = stocks[composant_id]
            stock.reservee -= required
            stock.quantite -= required
        return self._record(stocks, requirements, "sortie", reference_type, reference_id, notes)

    def consume_direct(
        self,
        requirements: Requirements,
        reference_type: str,
        reference_id: uuid.UUID,
        notes: str = "",
    ) -> List[StockComposant]:
        """Sort du stock libre immédiatement (vente consommée sur place)."""
        stocks = self._lock(requirements)
        self._shortage(stocks, requirements, from_reserved=False)
        for composant_id, required in requirements.items():
            stocks[composant_id].quantite -= required
        return self._record(stocks, requirements, "sortie", reference_type, reference_id, notes)

    def restock(
        self,
        requirements: Requirements,
        reference_type: str,
        reference_id: uuid.UUID,
        notes: str = "",
    ) -> None:
        """Remet en rayon. Jamais déclenché automatiquement : un plat préparé ne
        retourne pas au stock, c'est une décision du manager."""
        stocks = self._lock(requirements)
        for composant_id, quantity in requirements.items():
            stock = stocks.get(composant_id)
            if stock is not None:
                stock.quantite += quantity
        self._record(
            {cid: s for cid, s in stocks.items()},
            requirements,
            "retour",
            reference_type,
            reference_id,
            notes,
        )

    # ------------------------------------------------------------------ journal
    def _record(
        self,
        stocks: Dict[uuid.UUID, StockComposant],
        requirements: Requirements,
        movement_type: str,
        reference_type: str,
        reference_id: uuid.UUID,
        notes: str,
    ) -> List[StockComposant]:
        self.db.add_all(
            [
                StockMouvement(
                    composant_id=composant_id,
                    type=movement_type,
                    quantite=quantity,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    notes=notes or None,
                )
                for composant_id, quantity in requirements.items()
                if quantity > 0 and composant_id in stocks
            ]
        )
        self.db.flush()
        return [
            stock
            for stock in stocks.values()
            if movement_type == "sortie" and stock.quantite <= stock.seuil_alerte
        ]
