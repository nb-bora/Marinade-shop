"""Coût de revient des fiches techniques (et marge, food cost).

Règle (spec « Carte et stock », §2) : le coût d'un plat est la somme, sur chaque ligne de sa fiche, de
``quantité convertie en unité de stock / rendement x coût unitaire du composant``. Le coût unitaire d'un composant
(``composants.cout_unitaire``) est un coût d'achat par UNITÉ DE STOCK : une fiche en grammes pour un composant
géré en kilogrammes est convertie avant de multiplier (``stock_units``), jamais après.

Contrat avec les autres pistes (le catalogue l'appelle pour afficher coût et marge sur les plats) :

* ``cost_of_plat(db, plat_id)`` : coût d'un plat, ou ``None`` si aucune ligne n'a de coût connu ;
* ``costs_for_restaurant(db, restaurant_id)`` : ``{plat_id: coût | None}`` pour tous les plats actifs, en un
  nombre FIXE de requêtes (pas de N+1) ;
* ``summaries_for_restaurant`` / ``fiche_detail`` : même calcul avec le détail (lignes, coût partiel signalé).

Un coût PARTIEL (au moins une ligne sans coût : composant sans prix d'achat, ou unité incompatible héritée
d'anciennes données) vaut la somme des lignes connues ; ``PlatCostSummary.partiel`` le signale et l'interface
affiche « au moins ». Aucune de ces fonctions n'écrit en base.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.restaurant import Composant, MenuCategory, Plat, PlatComposant
from app.models.stock import UniteConversion
from app.services.stock_units import normalize_unit, round_quantity, unit_factor

ZERO = Decimal(0)
HUNDRED = Decimal(100)
MONEY_PLACES = Decimal("0.01")
PERCENT_PLACES = Decimal("0.1")

#: Seuil de food cost (en %) au-delà duquel un plat est signalé, tant que le restaurant n'en a pas fixé un autre.
DEFAULT_FOOD_COST_TARGET = Decimal(35)

#: Raisons pour lesquelles une ligne n'a pas de coût.
NO_COST_UNKNOWN = "cout_inconnu"
NO_COST_UNIT = "unite_incompatible"


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def percent(value: Decimal) -> Decimal:
    return Decimal(value).quantize(PERCENT_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RawLine:
    """Une ligne de fiche telle que lue en base, avec ce qu'il faut du composant pour la chiffrer."""

    plat_id: uuid.UUID
    composant_id: uuid.UUID
    composant_nom: str
    quantite: Decimal
    unite: str
    rendement: Decimal
    ordre: int
    stock_unite: str
    cout_unitaire: Optional[Decimal]
    composant_archive: bool = False


@dataclass(frozen=True)
class LineCost:
    composant_id: uuid.UUID
    composant_nom: str
    quantite: Decimal
    unite: str
    rendement: Decimal
    ordre: int
    stock_unite: str
    cout_unitaire: Optional[Decimal]
    #: Quantité réellement sortie du stock (unité de stock, rendement compris), arrondie à 3 décimales.
    quantite_stock: Optional[Decimal]
    cout: Optional[Decimal]
    #: ``None`` si la ligne est chiffrée, sinon ``cout_inconnu`` ou ``unite_incompatible``.
    motif_sans_cout: Optional[str]
    composant_archive: bool = False


@dataclass(frozen=True)
class PlatCostSummary:
    plat_id: uuid.UUID
    nb_lignes: int
    nb_sans_cout: int
    #: Somme des lignes chiffrées ; ``None`` si la fiche est vide ou si aucune ligne n'a de coût.
    cout: Optional[Decimal]
    #: Vrai si ``cout`` ne couvre pas toutes les lignes.
    partiel: bool
    lignes: List[LineCost] = field(default_factory=list)

    @property
    def statut(self) -> str:
        if self.nb_lignes == 0:
            return "sans_fiche"
        return "complete" if self.nb_sans_cout == 0 else "partielle"


# --------------------------------------------------------------------------------------- calcul pur
def cost_line(raw: RawLine, custom: Optional[Mapping[str, Decimal]] = None) -> LineCost:
    """Chiffre une ligne : conversion vers l'unité de stock, rendement, puis coût unitaire."""
    factor = unit_factor(raw.stock_unite, raw.unite, custom)
    rendement = Decimal(raw.rendement) if raw.rendement and Decimal(raw.rendement) > ZERO else Decimal(1)
    if factor is None:
        return LineCost(
            raw.composant_id, raw.composant_nom, Decimal(raw.quantite), raw.unite, rendement, raw.ordre,
            raw.stock_unite, raw.cout_unitaire, None, None, NO_COST_UNIT, raw.composant_archive,
        )
    exact = Decimal(raw.quantite) * factor / rendement
    unit_cost = Decimal(raw.cout_unitaire) if raw.cout_unitaire is not None else None
    cost = money(exact * unit_cost) if unit_cost is not None else None
    return LineCost(
        raw.composant_id, raw.composant_nom, Decimal(raw.quantite), raw.unite, rendement, raw.ordre,
        raw.stock_unite, unit_cost, round_quantity(exact), cost,
        None if cost is not None else NO_COST_UNKNOWN, raw.composant_archive,
    )


def summarize(plat_id: uuid.UUID, lines: Sequence[LineCost]) -> PlatCostSummary:
    costed = [line.cout for line in lines if line.cout is not None]
    without = len(lines) - len(costed)
    total = money(sum(costed, ZERO)) if costed else None
    return PlatCostSummary(
        plat_id=plat_id,
        nb_lignes=len(lines),
        nb_sans_cout=without,
        cout=total,
        partiel=total is not None and without > 0,
        lignes=list(lines),
    )


def margins(prix: Optional[Decimal], cout: Optional[Decimal]) -> tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    """``(marge, marge en % du prix, food cost en % du prix)``, ou des ``None`` si on ne peut pas les calculer."""
    if cout is None or prix is None or Decimal(prix) <= ZERO:
        return None, None, None
    prix = Decimal(prix)
    marge = money(prix - cout)
    return marge, percent(marge / prix * HUNDRED), percent(cout / prix * HUNDRED)


def food_cost_target(config: Optional[Mapping]) -> Decimal:
    """Seuil de food cost du restaurant (``config_jsonb.fiches.food_cost_cible``), 35 % par défaut."""
    try:
        raw = ((config or {}).get("fiches") or {}).get("food_cost_cible")
        value = Decimal(str(raw)) if raw is not None else DEFAULT_FOOD_COST_TARGET
    except Exception:  # noqa: BLE001 - une valeur illisible retombe sur le défaut, jamais sur une erreur
        return DEFAULT_FOOD_COST_TARGET
    return value if ZERO < value <= HUNDRED else DEFAULT_FOOD_COST_TARGET


# -------------------------------------------------------------------------------------- lecture SQL
def load_custom_conversions(
    db: Session, composant_ids: Iterable[uuid.UUID]
) -> Dict[uuid.UUID, Dict[str, Decimal]]:
    """Unités propres aux composants (``1 carton = 12 bouteilles``), en UNE requête."""
    ids = set(composant_ids)
    found: Dict[uuid.UUID, Dict[str, Decimal]] = {}
    if not ids:
        return found
    rows = db.execute(
        select(UniteConversion.composant_id, UniteConversion.unite, UniteConversion.facteur).where(
            UniteConversion.composant_id.in_(ids)
        )
    )
    for composant_id, unit, factor in rows:
        found.setdefault(composant_id, {})[normalize_unit(unit)] = Decimal(factor)
    return found


def _raw_lines_query():
    return (
        select(
            PlatComposant.plat_id,
            PlatComposant.composant_id,
            Composant.nom,
            PlatComposant.quantite,
            PlatComposant.unite,
            PlatComposant.rendement,
            PlatComposant.ordre,
            Composant.stock_unite,
            Composant.cout_unitaire,
            Composant.deleted_at,
        )
        .join(Composant, Composant.id == PlatComposant.composant_id)
        .order_by(PlatComposant.plat_id, PlatComposant.ordre, Composant.nom)
    )


def _build(db: Session, rows) -> Dict[uuid.UUID, PlatCostSummary]:
    raws = [
        RawLine(
            plat_id=r[0], composant_id=r[1], composant_nom=r[2], quantite=r[3], unite=r[4],
            rendement=r[5] if r[5] is not None else Decimal(1), ordre=r[6] or 0, stock_unite=r[7],
            cout_unitaire=r[8], composant_archive=r[9] is not None,
        )
        for r in rows
    ]
    custom = load_custom_conversions(db, {raw.composant_id for raw in raws})
    by_plat: Dict[uuid.UUID, List[LineCost]] = {}
    for raw in raws:
        by_plat.setdefault(raw.plat_id, []).append(cost_line(raw, custom.get(raw.composant_id)))
    return {plat_id: summarize(plat_id, lines) for plat_id, lines in by_plat.items()}


def summaries_for_restaurant(db: Session, restaurant_id: uuid.UUID) -> Dict[uuid.UUID, PlatCostSummary]:
    """Coût détaillé de tous les plats actifs du restaurant qui ont une fiche : 2 requêtes, quel que soit leur nombre."""
    rows = db.execute(
        _raw_lines_query()
        .join(Plat, Plat.id == PlatComposant.plat_id)
        .where(Plat.restaurant_id == restaurant_id, Plat.deleted_at.is_(None))
    ).all()
    return _build(db, rows)


def costs_for_restaurant(db: Session, restaurant_id: uuid.UUID) -> Dict[uuid.UUID, Optional[Decimal]]:
    """``{plat_id: coût de revient | None}`` pour TOUS les plats actifs (``None`` : fiche vide ou sans aucun coût).

    Trois requêtes fixes : lignes de fiches, conversions propres aux composants, identifiants des plats.
    """
    summaries = summaries_for_restaurant(db, restaurant_id)
    plat_ids = db.execute(
        select(Plat.id).where(Plat.restaurant_id == restaurant_id, Plat.deleted_at.is_(None))
    ).scalars()
    return {plat_id: (summaries[plat_id].cout if plat_id in summaries else None) for plat_id in plat_ids}


def summary_for_plat(db: Session, plat_id: uuid.UUID) -> PlatCostSummary:
    rows = db.execute(_raw_lines_query().where(PlatComposant.plat_id == plat_id)).all()
    return _build(db, rows).get(plat_id) or summarize(plat_id, [])


def cost_of_plat(db: Session, plat_id: uuid.UUID) -> Optional[Decimal]:
    """Coût de revient d'un plat (``None`` s'il n'a pas de fiche ou si aucune ligne n'a de coût)."""
    return summary_for_plat(db, plat_id).cout


# --------------------------------------------------------------------------------------- fiche détaillée
@dataclass(frozen=True)
class FicheLine:
    composant_id: uuid.UUID
    composant_nom: str
    quantite: Decimal
    unite: str
    rendement: Decimal
    ordre: int
    stock_unite: str
    cout_unitaire: Optional[Decimal]
    quantite_stock: Optional[Decimal]
    cout: Optional[Decimal]
    #: Part de cette ligne dans le coût total, en % (``None`` si la ligne n'est pas chiffrée).
    part: Optional[Decimal]
    motif_sans_cout: Optional[str]
    composant_archive: bool
    #: Unités dans lesquelles on peut exprimer ce composant (l'interface les propose).
    unites: List[str]


@dataclass(frozen=True)
class PlusChere:
    composant_id: uuid.UUID
    composant_nom: str
    cout: Decimal
    part: Decimal


@dataclass(frozen=True)
class FicheDetail:
    plat_id: uuid.UUID
    plat_nom: str
    prix: Decimal
    devise: str
    lignes: List[FicheLine]
    nb_lignes: int
    nb_sans_cout: int
    cout: Optional[Decimal]
    partiel: bool
    statut: str
    marge: Optional[Decimal]
    marge_pct: Optional[Decimal]
    food_cost_pct: Optional[Decimal]
    food_cost_cible: Decimal
    au_dessus_de_la_cible: bool
    ligne_la_plus_chere: Optional[PlusChere]


def fiche_detail(db: Session, plat: Plat, config: Optional[Mapping] = None) -> FicheDetail:
    """Fiche d'un plat avec le coût de chaque ligne, le total, la marge et le food cost."""
    from app.services.stock_units import convertible_units

    summary = summary_for_plat(db, plat.id)
    custom = load_custom_conversions(db, [line.composant_id for line in summary.lignes])
    total = summary.cout
    lines: List[FicheLine] = []
    for line in summary.lignes:
        part = (
            percent(line.cout / total * HUNDRED)
            if line.cout is not None and total is not None and total > ZERO
            else None
        )
        lines.append(
            FicheLine(
                composant_id=line.composant_id, composant_nom=line.composant_nom, quantite=line.quantite,
                unite=line.unite, rendement=line.rendement, ordre=line.ordre, stock_unite=line.stock_unite,
                cout_unitaire=line.cout_unitaire, quantite_stock=line.quantite_stock, cout=line.cout,
                part=part, motif_sans_cout=line.motif_sans_cout, composant_archive=line.composant_archive,
                unites=convertible_units(line.stock_unite, custom.get(line.composant_id)),
            )
        )
    priced = [line for line in lines if line.cout is not None]
    top = max(priced, key=lambda line: line.cout, default=None)  # type: ignore[arg-type,return-value]
    marge, marge_pct, food_cost = margins(plat.prix, total)
    target = food_cost_target(config)
    return FicheDetail(
        plat_id=plat.id, plat_nom=plat.nom, prix=Decimal(plat.prix), devise=plat.devise, lignes=lines,
        nb_lignes=summary.nb_lignes, nb_sans_cout=summary.nb_sans_cout, cout=total, partiel=summary.partiel,
        statut=summary.statut, marge=marge, marge_pct=marge_pct, food_cost_pct=food_cost, food_cost_cible=target,
        au_dessus_de_la_cible=food_cost is not None and food_cost > target,
        ligne_la_plus_chere=(
            PlusChere(top.composant_id, top.composant_nom, top.cout, top.part or ZERO) if top else None  # type: ignore[arg-type]
        ),
    )


@dataclass(frozen=True)
class FicheListItem:
    plat_id: uuid.UUID
    nom: str
    categorie: Optional[str]
    prix: Decimal
    devise: str
    disponible: bool
    nb_lignes: int
    nb_sans_cout: int
    cout: Optional[Decimal]
    partiel: bool
    statut: str
    marge: Optional[Decimal]
    marge_pct: Optional[Decimal]
    food_cost_pct: Optional[Decimal]
    au_dessus_de_la_cible: bool


@dataclass(frozen=True)
class FichesResume:
    total_plats: int
    fiches_completes: int
    fiches_partielles: int
    plats_sans_fiche: int
    #: Moyenne des food costs des plats chiffrés, en % (``None`` si aucun plat n'est chiffré).
    food_cost_moyen: Optional[Decimal]
    plats_hors_cible: int
    food_cost_cible: Decimal


def list_fiches(
    db: Session, restaurant_id: uuid.UUID, config: Optional[Mapping] = None
) -> tuple[List[FicheListItem], FichesResume]:
    """Tous les plats actifs avec coût, marge et food cost, plus l'indicateur d'ensemble (3 requêtes fixes)."""
    summaries = summaries_for_restaurant(db, restaurant_id)
    plats = db.execute(
        select(Plat.id, Plat.nom, MenuCategory.name, Plat.prix, Plat.devise, Plat.disponible)
        .outerjoin(MenuCategory, MenuCategory.id == Plat.category_id)
        .where(Plat.restaurant_id == restaurant_id, Plat.deleted_at.is_(None))
        .order_by(Plat.nom, Plat.id)
    ).all()
    target = food_cost_target(config)
    items: List[FicheListItem] = []
    for plat_id, nom, categorie, prix, devise, disponible in plats:
        summary = summaries.get(plat_id) or summarize(plat_id, [])
        marge, marge_pct, food_cost = margins(prix, summary.cout)
        items.append(
            FicheListItem(
                plat_id=plat_id, nom=nom, categorie=categorie, prix=Decimal(prix), devise=devise,
                disponible=bool(disponible), nb_lignes=summary.nb_lignes, nb_sans_cout=summary.nb_sans_cout,
                cout=summary.cout, partiel=summary.partiel, statut=summary.statut, marge=marge,
                marge_pct=marge_pct, food_cost_pct=food_cost,
                au_dessus_de_la_cible=food_cost is not None and food_cost > target,
            )
        )
    costed = [item.food_cost_pct for item in items if item.food_cost_pct is not None]
    resume = FichesResume(
        total_plats=len(items),
        fiches_completes=sum(1 for item in items if item.statut == "complete"),
        fiches_partielles=sum(1 for item in items if item.statut == "partielle"),
        plats_sans_fiche=sum(1 for item in items if item.statut == "sans_fiche"),
        food_cost_moyen=percent(sum(costed, ZERO) / len(costed)) if costed else None,
        plats_hors_cible=sum(1 for item in items if item.au_dessus_de_la_cible),
        food_cost_cible=target,
    )
    return items, resume
