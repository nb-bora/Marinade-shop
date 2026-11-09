"""Règles pures de l'approvisionnement (aucun accès à la base) : niveau cible, arrondi au conditionnement,
couverture, statut d'un bon, fiabilité d'un fournisseur, écart de prix."""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from app.services.stock_units import round_quantity

ZERO = Decimal("0")
STATUTS_EN_COURS = ("brouillon", "envoye", "recu_partiel")
STATUTS_COMMANDES = ("envoye", "recu_partiel")  # commandé chez le fournisseur, pas encore soldé
ECART_PRIX_TOLERE_PCT = 0.5  # en dessous, l'écart de prix est du bruit d'arrondi


def target_level(seuil: Decimal, cible: Decimal) -> Decimal:
    """Niveau visé après réapprovisionnement : le stock cible s'il dépasse le seuil, sinon deux fois le seuil."""
    return cible if cible > seuil else seuil * 2


def is_alert(seuil: Decimal, disponible: Decimal) -> bool:
    """Règle unique : un seuil à 0 ne déclenche jamais d'alerte ; sinon alerte quand le disponible atteint le seuil."""
    return seuil > 0 and disponible <= seuil


def round_up_to_pack(quantity: Decimal, pack: Optional[Decimal]) -> Decimal:
    """Plus petit multiple du conditionnement qui couvre la quantité (sans conditionnement : inchangée)."""
    if not pack or pack <= 0:
        return round_quantity(quantity)
    packs = (quantity / pack).to_integral_value(rounding="ROUND_CEILING")
    return round_quantity(packs * pack)


def suggested_quantity(
    *,
    disponible: Decimal,
    seuil: Decimal,
    cible: Decimal,
    deja_prevu: Decimal = ZERO,
    conditionnement: Optional[Decimal] = None,
    quantite_minimum: Optional[Decimal] = None,
) -> Decimal:
    """Quantité à commander : niveau cible - disponible - déjà prévu, relevée à la quantité minimale du
    fournisseur puis arrondie au conditionnement. 0 si rien n'est à commander."""
    need = target_level(seuil, cible) - disponible - deja_prevu
    if need <= 0:
        return ZERO
    quantity = need
    if quantite_minimum and quantity < quantite_minimum:
        quantity = quantite_minimum
    return round_up_to_pack(quantity, conditionnement)


def coverage_days(disponible: Decimal, consommation_jour: Decimal) -> Optional[float]:
    """Jours de stock restants au rythme de consommation moyen (``None`` sans consommation)."""
    if consommation_jour <= 0:
        return None
    return round(float(disponible / consommation_jour), 1)


def line_state(commandee: Decimal, recue: Decimal) -> str:
    if recue <= 0:
        return "a_recevoir"
    if recue > commandee:
        return "depasse"
    if recue == commandee:
        return "recu"
    return "partiel"


def status_after_receipt(lines: Iterable[tuple[Decimal, Decimal]]) -> str:
    """Statut d'un bon d'après (commandée, reçue) de chaque ligne : soldé quand tout est arrivé."""
    pairs = list(lines)
    if pairs and all(recue >= commandee for commandee, recue in pairs):
        return "recu"
    return "recu_partiel" if any(recue > 0 for _, recue in pairs) else "envoye"


def progress_percent(lines: Sequence[tuple[Decimal, Decimal]]) -> int:
    """Part reçue de la quantité commandée (plafonnée par ligne), en pourcentage entier."""
    ordered = sum((c for c, _ in lines), ZERO)
    if ordered <= 0:
        return 0
    received = sum((min(r, c) for c, r in lines), ZERO)
    return int(math.floor(received / ordered * 100))


def is_late(statut: str, prevue: Optional[date], today: date) -> bool:
    return statut in STATUTS_COMMANDES and prevue is not None and prevue < today


def price_gap_percent(reel: Optional[Decimal], attendu: Optional[Decimal]) -> Optional[float]:
    """Écart du prix réel par rapport au prix attendu, en % (``None`` si l'un des deux manque ou si l'écart est négligeable)."""
    if reel is None or attendu is None or attendu <= 0:
        return None
    gap = float((reel - attendu) / attendu * 100)
    return None if abs(gap) < ECART_PRIX_TOLERE_PCT else round(gap, 1)


def reliability_level(taux_livraison: Optional[float], taux_ponctualite: Optional[float], nb_clos: int) -> str:
    """Niveau de confiance : « inconnu » tant que moins de trois bons sont clos (trop peu pour conclure)."""
    if nb_clos < 3:
        return "inconnu"
    rates = [r for r in (taux_livraison, taux_ponctualite) if r is not None]
    if not rates:
        return "inconnu"
    score = sum(rates) / len(rates)
    if score >= 0.85:
        return "bon"
    return "moyen" if score >= 0.6 else "faible"
