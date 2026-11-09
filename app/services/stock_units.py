"""Unités de mesure du stock : normalisation et conversion.

Règle : toutes les quantités d'un composant sont stockées dans son unité de stock
(``composants.stock_unite``). Une fiche technique, une réception ou un bon de commande peut s'exprimer
dans une autre unité : on convertit avant d'écrire, jamais après.

* Unités standard d'une même grandeur (masse : kg, g ; volume : l, dl, cl, ml) : conversion automatique.
* Unités de comptage (pièce, portion, bouteille, carton…) : aucune conversion implicite entre elles.
  Un facteur propre au composant (``unites_conversion``) : « 1 carton = 12 bouteilles ».
* Toute autre combinaison est refusée : mieux vaut une erreur claire qu'un facteur 1000 silencieux.
"""

from __future__ import annotations

import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping, Optional

QUANTITY_PLACES = Decimal("0.001")
QUANTITY_MIN = QUANTITY_PLACES
QUANTITY_MAX = Decimal("999999999.999")  # Numeric(12, 3)

# grandeur -> {unité normalisée: facteur vers l'unité de référence de la grandeur}
_MASS = {"kg": Decimal(1000), "g": Decimal(1), "mg": Decimal("0.001")}
_VOLUME = {"l": Decimal(1000), "dl": Decimal(100), "cl": Decimal(10), "ml": Decimal(1)}
_DIMENSIONS: dict[str, dict[str, Decimal]] = {"masse": _MASS, "volume": _VOLUME}

_ALIASES = {
    "litre": "l",
    "litres": "l",
    "kilo": "kg",
    "kilos": "kg",
    "kilogramme": "kg",
    "gramme": "g",
    "grammes": "g",
    "millilitre": "ml",
    "centilitre": "cl",
    "decilitre": "dl",
    "pieces": "piece",
    "unite": "piece",
    "unites": "piece",
    "portions": "portion",
    "bouteilles": "bouteille",
    "cartons": "carton",
}

#: Unités proposées par défaut dans l'interface (l'utilisateur peut en saisir d'autres).
STANDARD_UNITS = ("kg", "g", "l", "cl", "ml", "piece", "portion", "bouteille", "carton", "sachet", "boite")


def normalize_unit(unit: Optional[str]) -> str:
    """Minuscules, sans accents ni espaces superflus, pluriels courants ramenés au singulier."""
    text = (unit or "").strip().lower()
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    text = text.replace(".", "")
    return _ALIASES.get(text, text)


def dimension_of(unit: Optional[str]) -> Optional[str]:
    unit = normalize_unit(unit)
    for name, units in _DIMENSIONS.items():
        if unit in units:
            return name
    return None


def unit_factor(
    stock_unit: str, unit: str, custom: Optional[Mapping[str, Decimal]] = None
) -> Optional[Decimal]:
    """Combien d'unités de stock dans 1 ``unit`` ; ``None`` si la conversion est impossible.

    ``custom`` : conversions propres au composant, ``{unité normalisée: facteur vers l'unité de stock}``.
    """
    base = normalize_unit(stock_unit)
    wanted = normalize_unit(unit)
    if not wanted or wanted == base:
        return Decimal(1)
    if custom and wanted in custom:
        return Decimal(custom[wanted])
    dimension = dimension_of(base)
    if dimension and dimension == dimension_of(wanted):
        units = _DIMENSIONS[dimension]
        return units[wanted] / units[base]
    return None


def to_stock_quantity(
    quantity: Decimal,
    stock_unit: str,
    unit: str,
    custom: Optional[Mapping[str, Decimal]] = None,
) -> Optional[Decimal]:
    """Quantité exprimée en ``unit``, convertie en unité de stock et arrondie à 3 décimales."""
    factor = unit_factor(stock_unit, unit, custom)
    if factor is None:
        return None
    return round_quantity(Decimal(quantity) * factor)


def round_quantity(value: Decimal) -> Decimal:
    return Decimal(value).quantize(QUANTITY_PLACES, rounding=ROUND_HALF_UP)


def has_valid_precision(value: Decimal) -> bool:
    """Vrai si la valeur n'a pas plus de 3 décimales et reste dans les bornes de ``Numeric(12, 3)``."""
    value = Decimal(value)
    return value == value.quantize(QUANTITY_PLACES) and abs(value) <= QUANTITY_MAX


def convertible_units(stock_unit: str, custom: Optional[Mapping[str, Decimal]] = None) -> list[str]:
    """Unités dans lesquelles on peut exprimer une quantité de ce composant (unité de stock comprise)."""
    base = normalize_unit(stock_unit)
    units = [base]
    dimension = dimension_of(base)
    if dimension:
        units += [u for u in _DIMENSIONS[dimension] if u != base]
    units += [u for u in (custom or {}) if u not in units]
    return units
