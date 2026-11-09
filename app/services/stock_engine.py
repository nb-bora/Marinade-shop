"""Moteur de stock : l'unique endroit qui modifie quantités, réservations, lots et journal.

Invariants, vérifiés ici ET par la base (CHECK quantite >= 0, reservee >= 0, reservee <= quantite) :

    quantite   = stock physique (unité de stock du composant)
    reservee   = stock promis à des commandes ouvertes (pas encore consommé)
    disponible = quantite - reservee

Règle d'alerte UNIQUE (partout : moteur, approvisionnement, tableau de bord, interface) :

    rupture : disponible <= 0
    alerte  : seuil > 0 ET disponible <= seuil          (seuil 0 = pas d'alerte)

Cycle de vie d'une ligne vendue :

    reserve  -> consume_reserved   (commande payée)
    reserve  -> release            (commande annulée : rien n'est sorti, rien n'est rendu)
    consume_direct                 (vente consommée tout de suite : moteur ROS)
    restock                        (retour en stock, jamais automatique)

Entrées et ajustements manuels : ``receive`` (réception, lot, coût moyen pondéré),
``ajustement`` (nouvelle quantité constatée), ``sortie_manuelle`` (perte, casse, péremption...).

Journal : TOUT mouvement physique écrit ``restaurant_id``, ``delta`` signé, ``stock_apres``, ``motif``,
``acteur_user_id``, ``cout_unitaire`` et ``lot_id``. ``quantite`` reste positive. Les réservations ne sont
pas des mouvements physiques : elles ne sont pas journalisées.

Sorties FIFO : une sortie consomme d'abord les lots à la date de péremption la plus proche (puis le plus
ancien reçu). La part qui n'appartient à aucun lot (stock antérieur aux lots) sort en dernier ; chaque
tranche donne un mouvement.

Concurrence : toutes les lignes de stock concernées sont verrouillées en UNE requête
``SELECT ... FOR UPDATE ORDER BY composant_id``. ``populate_existing`` force la relecture après l'attente
du verrou : sans lui on calculerait sur des valeurs périmées.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.restaurant import Composant, StockComposant, StockMouvement
from app.models.stock import StockLot
from app.repositories.ros_repository import RosAuditLogRepository
from app.services import stock_motifs as motifs
from app.services.stock_errors import StockConflict, StockNotFound, StockValidationError
from app.services.stock_units import QUANTITY_MIN, has_valid_precision, round_quantity
from app.utils.exceptions import InsufficientStockError

Requirements = Dict[uuid.UUID, Decimal]

ZERO = Decimal("0")
PRICE_PLACES = Decimal("0.0001")
PRICE_MAX = Decimal("9999999999.9999")

ETAT_SUFFISANT = "suffisant"
ETAT_ALERTE = "alerte"
ETAT_RUPTURE = "rupture"


# --------------------------------------------------------------- fonctions pures
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


def etat_stock(quantite, reservee, seuil) -> str:
    """Règle d'alerte unique : rupture si disponible <= 0 ; alerte si seuil > 0 et disponible <= seuil."""
    disponible = Decimal(quantite) - Decimal(reservee)
    if disponible <= 0:
        return ETAT_RUPTURE
    if Decimal(seuil) > 0 and disponible <= Decimal(seuil):
        return ETAT_ALERTE
    return ETAT_SUFFISANT


def check_quantity(value, *, field: str = "quantite", minimum: Decimal = QUANTITY_MIN) -> Decimal:
    """Quantité saisie : nombre fini, au plus 3 décimales (422, jamais d'arrondi silencieux), >= minimum."""
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise StockValidationError(
            "stock.quantite_invalide", "La quantité doit être un nombre.", champ=field
        )
    if not quantity.is_finite():
        raise StockValidationError(
            "stock.quantite_invalide", "La quantité doit être un nombre.", champ=field
        )
    if not has_valid_precision(quantity):
        raise StockValidationError(
            "stock.precision",
            "La quantité ne peut pas avoir plus de 3 décimales (exemple : 0,250).",
            champ=field,
        )
    if quantity < minimum:
        if minimum > 0:
            raise StockValidationError(
                "stock.quantite_minimum",
                "La quantité doit être supérieure ou égale à 0,001.",
                champ=field,
            )
        raise StockValidationError(
            "stock.quantite_negative", "La quantité ne peut pas être négative.", champ=field
        )
    return quantity


#: Motifs qu'un utilisateur peut choisir pour une sortie hors vente (la vente et l'inventaire ont les leurs).
MOTIFS_SORTIE_MANUELLE = (
    motifs.PERTE,
    motifs.CASSE,
    motifs.PEREMPTION,
    motifs.USAGE_INTERNE,
    motifs.OFFERT,
    motifs.ERREUR_SAISIE,
    motifs.VOL,
    motifs.AUTRE,
)


def validate_motif(kind: str, motif: Optional[str], notes: Optional[str]) -> str:
    """Motif obligatoire pour une sortie manuelle (``sortie``/``perte``) et un ajustement ; « autre » exige une note."""
    allowed = motifs.MOTIFS_AJUSTEMENT if kind == "ajustement" else MOTIFS_SORTIE_MANUELLE
    if not motif:
        raise StockValidationError(
            "stock.motif_obligatoire", "Indiquez le motif de ce mouvement.", champ="motif"
        )
    if motif not in allowed:
        raise StockValidationError(
            "stock.motif_inconnu", "Ce motif n'est pas disponible pour ce mouvement.", champ="motif"
        )
    if motif == motifs.AUTRE and not (notes or "").strip():
        raise StockValidationError(
            "stock.commentaire_obligatoire",
            "Précisez le motif dans le commentaire.",
            champ="notes",
        )
    return motif


def check_price(value, *, field: str = "cout_unitaire") -> Decimal:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise StockValidationError("stock.prix_invalide", "Le prix doit être un nombre.", champ=field)
    if not price.is_finite() or price < 0 or price > PRICE_MAX:
        raise StockValidationError("stock.prix_invalide", "Le prix doit être positif ou nul.", champ=field)
    if price != price.quantize(PRICE_PLACES):
        raise StockValidationError(
            "stock.prix_precision", "Le prix ne peut pas avoir plus de 4 décimales.", champ=field
        )
    return price


def weighted_cost(old_quantity: Decimal, old_cost: Optional[Decimal], quantity: Decimal, price: Decimal) -> Decimal:
    """Moyenne pondérée mobile : (valeur_stock + qte x prix) / (stock + qte).

    Repli sur le dernier prix si le stock était nul, ou si son coût n'est pas connu (on ne peut pas
    valoriser ce qui n'a pas de prix : le stock existant prend le prix reçu).
    """
    if old_quantity <= 0 or old_cost is None:
        return price.quantize(PRICE_PLACES, rounding=ROUND_HALF_UP)
    value = old_quantity * Decimal(old_cost) + quantity * price
    return (value / (old_quantity + quantity)).quantize(PRICE_PLACES, rounding=ROUND_HALF_UP)


@dataclass
class _Row:
    stock: StockComposant
    composant: Composant

    @property
    def restaurant_id(self) -> uuid.UUID:
        return self.composant.restaurant_id


class StockEngine:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ verrous
    def _lock(
        self, composant_ids: Iterable[uuid.UUID], restaurant_id: Optional[uuid.UUID] = None
    ) -> Dict[uuid.UUID, _Row]:
        ids = list(composant_ids)
        if not ids:
            return {}
        query = (
            select(StockComposant, Composant)
            .join(Composant, Composant.id == StockComposant.composant_id)
            .where(StockComposant.composant_id.in_(ids))
        )
        if restaurant_id is not None:
            query = query.where(Composant.restaurant_id == restaurant_id)
        rows = self.db.execute(
            query.order_by(StockComposant.composant_id)
            .with_for_update(of=StockComposant)
            .execution_options(populate_existing=True)
        ).all()
        return {stock.composant_id: _Row(stock=stock, composant=composant) for stock, composant in rows}

    def _lock_one(self, restaurant_id: uuid.UUID, composant_id: uuid.UUID) -> _Row:
        rows = self._lock([composant_id], restaurant_id)
        row = rows.get(composant_id)
        if row is None:
            composant_exists = self.db.execute(
                select(Composant.id).where(
                    Composant.id == composant_id, Composant.restaurant_id == restaurant_id
                )
            ).first()
            if composant_exists is None:
                raise StockNotFound("stock.composant_introuvable", "Composant introuvable dans ce restaurant.")
            # Composant sans ligne de stock (créé avant la gestion de stock) : on l'initialise à zéro.
            self.db.add(StockComposant(composant_id=composant_id))
            self.db.flush()
            row = self._lock([composant_id], restaurant_id)[composant_id]
        return row

    def _fifo_lots(self, composant_ids: Iterable[uuid.UUID]) -> Dict[uuid.UUID, List[StockLot]]:
        """Lots encore disponibles, dans l'ordre de sortie (FIFO par péremption puis réception)."""
        ids = list(composant_ids)
        if not ids:
            return {}
        lots = (
            self.db.execute(
                select(StockLot)
                .where(StockLot.composant_id.in_(ids), StockLot.quantite_restante > 0)
                .order_by(
                    StockLot.composant_id,
                    StockLot.date_peremption.asc().nulls_last(),
                    StockLot.recu_le,
                    StockLot.id,
                )
                .with_for_update()
            )
            .scalars()
            .all()
        )
        by_composant: Dict[uuid.UUID, List[StockLot]] = {}
        for lot in lots:
            by_composant.setdefault(lot.composant_id, []).append(lot)
        return by_composant

    def _shortage(self, rows: Dict[uuid.UUID, _Row], requirements: Requirements, *, from_reserved: bool) -> None:
        """Lève InsufficientStockError listant TOUS les composants en défaut."""
        short: List[tuple] = []
        for composant_id, required in requirements.items():
            row = rows.get(composant_id)
            if row is None:
                short.append((composant_id, required, ZERO))
                continue
            stock = row.stock
            available = stock.reservee if from_reserved else stock.quantite - stock.reservee
            if from_reserved and stock.quantite < required:
                available = min(available, stock.quantite)
            if available < required:
                short.append((composant_id, required, available))
        if not short:
            return
        names = {
            cid: nom
            for cid, nom in self.db.execute(
                select(Composant.id, Composant.nom).where(Composant.id.in_([cid for cid, _, _ in short]))
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
            f"{d['nom']} (besoin {d['requis']}, disponible {d['disponible']})" for d in details
        )
        raise InsufficientStockError(f"Stock insuffisant : {listing}", details=details)

    # ------------------------------------------------------------------ journal
    def _journal(
        self,
        row: _Row,
        *,
        movement_type: str,
        motif: str,
        delta: Decimal,
        quantite: Decimal,
        stock_apres: Decimal,
        lot_id: Optional[uuid.UUID] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[uuid.UUID] = None,
        acteur_user_id: Optional[uuid.UUID] = None,
        notes: Optional[str] = None,
    ) -> StockMouvement:
        movement = StockMouvement(
            restaurant_id=row.restaurant_id,
            composant_id=row.composant.id,
            type=movement_type,
            motif=motif,
            quantite=abs(quantite),
            delta=delta,
            stock_apres=stock_apres,
            cout_unitaire=row.composant.cout_unitaire,
            lot_id=lot_id,
            reference_type=reference_type,
            reference_id=reference_id,
            acteur_user_id=acteur_user_id,
            notes=notes or None,
        )
        self.db.add(movement)
        return movement

    def _alert_if_low(self, row: _Row, acteur_user_id: Optional[uuid.UUID], reason: str) -> None:
        """Journalise une alerte après toute sortie qui fait passer le composant en alerte ou rupture (seuil > 0)."""
        stock = row.stock
        if stock.seuil_alerte <= 0:
            return
        if etat_stock(stock.quantite, stock.reservee, stock.seuil_alerte) == ETAT_SUFFISANT:
            return
        RosAuditLogRepository(self.db).log_action(
            restaurant_id=row.restaurant_id,
            action="STOCK_ALERT_LOW",
            entity_name="StockComposant",
            entity_id=stock.id,
            actor_id=acteur_user_id,
            after_state={
                "quantite": str(stock.quantite),
                "reservee": str(stock.reservee),
                "seuil_alerte": str(stock.seuil_alerte),
                "etat": etat_stock(stock.quantite, stock.reservee, stock.seuil_alerte),
            },
            reason=reason,
        )

    def _debit(
        self,
        row: _Row,
        quantity: Decimal,
        lots: Dict[uuid.UUID, List[StockLot]],
        *,
        movement_type: str,
        motif: str,
        reference_type: Optional[str],
        reference_id: Optional[uuid.UUID],
        acteur_user_id: Optional[uuid.UUID],
        notes: Optional[str],
    ) -> List[StockMouvement]:
        """Sort ``quantity`` du stock physique, lots FIFO d'abord, un mouvement par tranche de lot."""
        remaining = quantity
        movements: List[StockMouvement] = []
        slices: List[tuple] = []
        for lot in lots.get(row.composant.id, []):
            if remaining <= 0:
                break
            take = min(lot.quantite_restante, remaining)
            if take <= 0:
                continue
            lot.quantite_restante -= take
            slices.append((lot.id, take))
            remaining -= take
        if remaining > 0:
            slices.append((None, remaining))
        for lot_id, part in slices:
            row.stock.quantite -= part
            movements.append(
                self._journal(
                    row,
                    movement_type=movement_type,
                    motif=motif,
                    delta=-part,
                    quantite=part,
                    stock_apres=row.stock.quantite,
                    lot_id=lot_id,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    acteur_user_id=acteur_user_id,
                    notes=notes,
                )
            )
        return movements

    # --------------------------------------------------------------- opérations
    def reserve(self, requirements: Requirements) -> None:
        """Promet du stock à une commande ouverte (rien n'est encore consommé)."""
        rows = self._lock(requirements)
        self._shortage(rows, requirements, from_reserved=False)
        for composant_id, required in requirements.items():
            rows[composant_id].stock.reservee += required
        self.db.flush()

    def release(self, requirements: Requirements) -> None:
        """Annule une promesse de stock (commande annulée). Aucun mouvement : rien n'est sorti."""
        rows = self._lock(requirements)
        for composant_id, required in requirements.items():
            row = rows.get(composant_id)
            if row is not None:
                row.stock.reservee = max(ZERO, row.stock.reservee - required)
        self.db.flush()

    def consume_reserved(
        self,
        requirements: Requirements,
        reference_type: str,
        reference_id: uuid.UUID,
        notes: str = "",
        *,
        acteur_user_id: Optional[uuid.UUID] = None,
        motif: str = motifs.VENTE,
    ) -> None:
        """Transforme une promesse en sortie réelle (commande payée)."""
        rows = self._lock(requirements)
        self._shortage(rows, requirements, from_reserved=True)
        lots = self._fifo_lots(requirements)
        for composant_id, required in requirements.items():
            row = rows[composant_id]
            row.stock.reservee -= required
            self._debit(
                row,
                required,
                lots,
                movement_type="sortie",
                motif=motif,
                reference_type=reference_type,
                reference_id=reference_id,
                acteur_user_id=acteur_user_id,
                notes=notes,
            )
            self._alert_if_low(row, acteur_user_id, "Stock sous le seuil d'alerte après une vente")
        self.db.flush()

    def consume_direct(
        self,
        requirements: Requirements,
        reference_type: str,
        reference_id: uuid.UUID,
        notes: str = "",
        *,
        acteur_user_id: Optional[uuid.UUID] = None,
        motif: str = motifs.VENTE,
    ) -> None:
        """Sort du stock libre immédiatement (vente consommée sur place)."""
        rows = self._lock(requirements)
        self._shortage(rows, requirements, from_reserved=False)
        lots = self._fifo_lots(requirements)
        for composant_id, required in requirements.items():
            row = rows[composant_id]
            self._debit(
                row,
                required,
                lots,
                movement_type="sortie",
                motif=motif,
                reference_type=reference_type,
                reference_id=reference_id,
                acteur_user_id=acteur_user_id,
                notes=notes,
            )
            self._alert_if_low(row, acteur_user_id, "Stock sous le seuil d'alerte après une vente")
        self.db.flush()

    def restock(
        self,
        requirements: Requirements,
        reference_type: str,
        reference_id: uuid.UUID,
        notes: str = "",
        *,
        acteur_user_id: Optional[uuid.UUID] = None,
        motif: str = motifs.ANNULATION,
    ) -> None:
        """Remet en rayon. Jamais déclenché automatiquement : un plat préparé ne
        retourne pas au stock, c'est une décision du manager."""
        rows = self._lock(requirements)
        for composant_id, quantity in requirements.items():
            row = rows.get(composant_id)
            if row is None:
                continue
            row.stock.quantite += quantity
            self._journal(
                row,
                movement_type="retour",
                motif=motif,
                delta=quantity,
                quantite=quantity,
                stock_apres=row.stock.quantite,
                reference_type=reference_type,
                reference_id=reference_id,
                acteur_user_id=acteur_user_id,
                notes=notes,
            )
        self.db.flush()

    def receive(
        self,
        restaurant_id: uuid.UUID,
        composant_id: uuid.UUID,
        quantite,
        *,
        cout_unitaire=None,
        lot_numero: Optional[str] = None,
        date_peremption: Optional[date] = None,
        fournisseur_id: Optional[uuid.UUID] = None,
        reference_type: str = "reception",
        reference_id: Optional[uuid.UUID] = None,
        acteur_user_id: Optional[uuid.UUID] = None,
        notes: Optional[str] = None,
    ) -> StockMouvement:
        """Entrée de marchandise : stock +quantité, lot si nécessaire, coût moyen pondéré mis à jour.

        Verrou ``FOR UPDATE`` sur la ligne de stock. Un lot est créé si ``date_peremption`` ou ``lot_numero``
        est fourni, ou si le composant suit la péremption. Renvoie le mouvement d'entrée.
        """
        composant_id = uuid.UUID(str(composant_id))
        quantity = check_quantity(quantite)
        price = check_price(cout_unitaire) if cout_unitaire is not None else None

        row = self._lock_one(restaurant_id, composant_id)
        stock = row.stock
        composant = row.composant
        old_quantity = stock.quantite

        if price is not None:
            composant.cout_unitaire = weighted_cost(old_quantity, composant.cout_unitaire, quantity, price)
            composant.cout_maj_le = datetime.now(timezone.utc)

        stock.quantite += quantity

        lot_id = None
        if date_peremption or lot_numero or composant.suit_peremption:
            lot = StockLot(
                restaurant_id=row.restaurant_id,
                composant_id=composant.id,
                numero=lot_numero or None,
                quantite_initiale=quantity,
                quantite_restante=quantity,
                date_peremption=date_peremption,
                fournisseur_id=fournisseur_id,
                cout_unitaire=price if price is not None else composant.cout_unitaire,
            )
            self.db.add(lot)
            self.db.flush()
            lot_id = lot.id

        movement = self._journal(
            row,
            movement_type="entree",
            motif=motifs.RECEPTION,
            delta=quantity,
            quantite=quantity,
            stock_apres=stock.quantite,
            lot_id=lot_id,
            reference_type=reference_type,
            reference_id=reference_id,
            acteur_user_id=acteur_user_id,
            notes=notes,
        )
        self.db.flush()
        return movement

    def ajustement(
        self,
        restaurant_id: uuid.UUID,
        composant_id: uuid.UUID,
        nouvelle_quantite,
        *,
        motif: str,
        notes: Optional[str] = None,
        acteur_user_id: Optional[uuid.UUID] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[uuid.UUID] = None,
    ) -> Optional[StockMouvement]:
        """Fixe le stock physique à ``nouvelle_quantite`` : journalise delta = nouvelle - ancienne.

        Renvoie ``None`` si la quantité ne change pas (rien à journaliser).
        """
        target = check_quantity(nouvelle_quantite, field="quantite", minimum=ZERO)
        row = self._lock_one(restaurant_id, composant_id)
        stock = row.stock
        if target < stock.reservee:
            raise StockConflict(
                "stock.reservee_superieure",
                f"Le stock ne peut pas descendre sous la quantité réservée ({stock.reservee}).",
                champ="quantite",
            )
        delta = target - stock.quantite
        if delta == 0:
            return None
        if delta < 0:
            lots = self._fifo_lots([composant_id])
            movements = self._debit(
                row,
                -delta,
                lots,
                movement_type="ajustement",
                motif=motif,
                reference_type=reference_type,
                reference_id=reference_id,
                acteur_user_id=acteur_user_id,
                notes=notes,
            )
            movement = movements[-1]
            self._alert_if_low(row, acteur_user_id, "Stock sous le seuil d'alerte après un ajustement")
        else:
            stock.quantite = target
            movement = self._journal(
                row,
                movement_type="ajustement",
                motif=motif,
                delta=delta,
                quantite=delta,
                stock_apres=stock.quantite,
                reference_type=reference_type,
                reference_id=reference_id,
                acteur_user_id=acteur_user_id,
                notes=notes,
            )
        self.db.flush()
        return movement

    def sortie_manuelle(
        self,
        restaurant_id: uuid.UUID,
        composant_id: uuid.UUID,
        quantite,
        *,
        motif: str,
        notes: Optional[str] = None,
        acteur_user_id: Optional[uuid.UUID] = None,
    ) -> List[StockMouvement]:
        """Sortie hors vente (perte, casse, péremption, usage interne...). Lots FIFO, alerte journalisée."""
        quantity = check_quantity(quantite)
        row = self._lock_one(restaurant_id, composant_id)
        stock = row.stock
        available = stock.quantite - stock.reservee
        if quantity > available:
            raise InsufficientStockError(
                f"Stock insuffisant : {row.composant.nom} (besoin {quantity}, disponible {available}).",
                details=[
                    {
                        "composant_id": str(composant_id),
                        "nom": row.composant.nom,
                        "requis": str(quantity),
                        "disponible": str(available),
                    }
                ],
            )
        lots = self._fifo_lots([composant_id])
        movements = self._debit(
            row,
            quantity,
            lots,
            movement_type="sortie",
            motif=motif,
            reference_type="manuel",
            reference_id=None,
            acteur_user_id=acteur_user_id,
            notes=notes,
        )
        self._alert_if_low(row, acteur_user_id, "Stock sous le seuil d'alerte après une sortie manuelle")
        self.db.flush()
        return movements

    # -------------------------------------------------------- compatibilité
    @staticmethod
    def alert_state(stock: StockComposant) -> str:
        return etat_stock(stock.quantite, stock.reservee, stock.seuil_alerte)
