"""Ce qu'un article vendu consomme en stock, résolu en lot.

Un plat consomme sa nomenclature (``plat_composants``), une combinaison ses
composants obligatoires, une boisson le composant auquel elle est liée, un composant
lui-même. Tout est lu avec UNE requête par type d'article, quel que soit le nombre
de lignes de la commande, et toujours filtré par restaurant.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Literal, Optional

from sqlalchemy import null, select
from sqlalchemy.orm import Session

from app.models.restaurant import (
    Boisson,
    Combinaison,
    CombinaisonComposant,
    Composant,
    Plat,
    PlatComposant,
)
from app.services.stock_engine import ZERO, Requirements, merge_requirements

Kind = Literal["plat", "combinaison", "boisson", "composant"]


@dataclass(frozen=True)
class ProductRef:
    """Article du catalogue d'un restaurant, tel que trouvé par son identifiant."""

    kind: Kind
    id: uuid.UUID
    nom: str
    prix: Optional[Decimal]  # None pour un composant : il n'a pas de prix de vente
    disponible: bool


@dataclass(frozen=True)
class ProductLine:
    kind: Kind
    id: uuid.UUID
    quantity: Decimal


def classify_products(
    db: Session, restaurant_id: uuid.UUID, product_ids: Iterable[uuid.UUID]
) -> Dict[uuid.UUID, ProductRef]:
    """Retrouve, parmi les plats, combinaisons, boissons et composants du restaurant,
    ceux qui portent ces identifiants. Un identifiant d'un autre restaurant est
    simplement absent du résultat."""
    ids = set(product_ids)
    found: Dict[uuid.UUID, ProductRef] = {}
    if not ids:
        return found
    sources = (
        ("plat", Plat, True),
        ("combinaison", Combinaison, True),
        ("boisson", Boisson, True),
        ("composant", Composant, False),
    )
    for kind, model, priced in sources:
        remaining = ids - set(found)
        if not remaining:
            break
        price_column = model.prix if priced else null()
        rows = db.execute(
            select(model.id, model.nom, price_column, model.disponible).where(
                model.restaurant_id == restaurant_id, model.id.in_(remaining)
            )
        )
        for row in rows:
            found[row[0]] = ProductRef(
                kind=kind,
                id=row[0],
                nom=row[1],
                prix=row[2] if priced else None,
                disponible=bool(row[3]),
            )
    return found


def requirements_for(
    db: Session, restaurant_id: uuid.UUID, lines: Iterable[ProductLine]
) -> Requirements:
    """Composants (et quantités) consommés par ces lignes, agrégés par composant."""
    lines = list(lines)
    by_kind: Dict[str, List[ProductLine]] = {k: [] for k in ("plat", "combinaison", "boisson", "composant")}
    for line in lines:
        by_kind[line.kind].append(line)

    parts: List[Requirements] = []

    if by_kind["plat"]:
        quantities = _sum_by_id(by_kind["plat"])
        rows = db.execute(
            select(PlatComposant.plat_id, PlatComposant.composant_id, PlatComposant.quantite)
            .join(Plat, Plat.id == PlatComposant.plat_id)
            .where(Plat.restaurant_id == restaurant_id, PlatComposant.plat_id.in_(list(quantities)))
        )
        parts.extend({r.composant_id: Decimal(r.quantite) * quantities[r.plat_id]} for r in rows)

    if by_kind["combinaison"]:
        quantities = _sum_by_id(by_kind["combinaison"])
        rows = db.execute(
            select(
                CombinaisonComposant.combinaison_id,
                CombinaisonComposant.composant_id,
                CombinaisonComposant.quantite,
            )
            .join(Combinaison, Combinaison.id == CombinaisonComposant.combinaison_id)
            .where(
                Combinaison.restaurant_id == restaurant_id,
                CombinaisonComposant.obligatoire.is_(True),
                CombinaisonComposant.combinaison_id.in_(list(quantities)),
            )
        )
        parts.extend(
            {r.composant_id: Decimal(r.quantite) * quantities[r.combinaison_id]} for r in rows
        )

    if by_kind["boisson"]:
        quantities = _sum_by_id(by_kind["boisson"])
        rows = db.execute(
            select(Boisson.id, Boisson.composant_id, Boisson.stock_par_vente).where(
                Boisson.restaurant_id == restaurant_id,
                Boisson.id.in_(list(quantities)),
                Boisson.composant_id.is_not(None),
            )
        )
        parts.extend(
            {r.composant_id: Decimal(r.stock_par_vente) * quantities[r.id]} for r in rows
        )

    if by_kind["composant"]:
        quantities = _sum_by_id(by_kind["composant"])
        # Filtré par restaurant : on ne consomme jamais le stock d'un autre.
        owned = db.execute(
            select(Composant.id).where(
                Composant.restaurant_id == restaurant_id, Composant.id.in_(list(quantities))
            )
        )
        parts.extend({r.id: quantities[r.id]} for r in owned)

    merged = merge_requirements(*parts)
    return {cid: qty for cid, qty in merged.items() if qty > ZERO}


def _sum_by_id(lines: List[ProductLine]) -> Dict[uuid.UUID, Decimal]:
    totals: Dict[uuid.UUID, Decimal] = {}
    for line in lines:
        totals[line.id] = totals.get(line.id, ZERO) + line.quantity
    return totals
