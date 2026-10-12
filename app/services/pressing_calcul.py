"""Calcul de tarification d'un pressing : service PUR (aucun accès base de données).

Toutes les règles de facturation vivent ici pour être testées sans base :

* poids facturable : arrondi du poids en grammes au ``pas`` du restaurant, ``superieur``
  (plafond) ou ``proche`` (demi vers le haut, au moins un pas) ;
* lavage et séchage : ``round_half_up(grammes * prix_kg / 1000)`` en entiers (aucun flottant) ;
* articles : quantité x prix unitaire ; combinaisons : quantité x PRIX FIXÉ de la combinaison
  (jamais la somme de ses articles) ;
* remise : entier, au plus égale au sous-total.

Tous les montants sont des entiers FCFA. La quantité de la ligne de lavage/séchage est le
poids facturable en kg (``Decimal``, 3 décimales) ; celle des articles/combinaisons est entière.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from app.utils.exceptions import BusinessLogicError

DEVISE = "FCFA"
PAS_AUTORISES = (1, 100, 500, 1000)
MODES_ARRONDI = ("superieur", "proche")
POIDS_MAX_GRAMMES = 1_000_000  # une tonne : au-delà, c'est une faute de saisie


class PressingRegleError(BusinessLogicError):
    """Règle métier non respectée (HTTP 422 côté API)."""


@dataclass(frozen=True)
class Tarif:
    prix_kg: int
    prix_sechage_kg: Optional[int]
    pas_grammes: int
    mode: str


@dataclass(frozen=True)
class ArticleTarifie:
    nom: str
    prix_unitaire: int
    actif: bool = True


@dataclass(frozen=True)
class CombinaisonTarifee:
    nom: str
    prix: int
    actif: bool = True


@dataclass
class DemandeCalcul:
    poids_grams: Optional[int] = None
    lavage: bool = True
    sechage: bool = False
    articles: List[tuple] = field(default_factory=list)  # [(article_id, quantite)]
    combinaisons: List[tuple] = field(default_factory=list)  # [(combinaison_id, quantite)]
    remise_fcfa: int = 0


def arrondir_demi_haut(numerateur: int, denominateur: int) -> int:
    """Division entière arrondie au plus proche, demi vers le haut (valeurs positives)."""
    return (2 * numerateur + denominateur) // (2 * denominateur)


def poids_facturable(poids_grams: int, pas_grammes: int, mode: str) -> int:
    """Poids facturé en grammes.

    ``superieur`` : multiple du pas immédiatement supérieur ou égal (3400 g, pas 1000 -> 4000).
    ``proche`` : multiple du pas le plus proche, demi vers le haut (3449 -> 3400, 3450 -> 3500,
    pas 100). Un poids positif n'est jamais facturé 0 : le minimum est un pas.
    """
    if poids_grams is None or poids_grams < 1:
        raise PressingRegleError("Le poids doit être d'au moins 1 gramme")
    if poids_grams > POIDS_MAX_GRAMMES:
        raise PressingRegleError("Le poids dépasse 1 000 kg : vérifiez la saisie")
    if pas_grammes not in PAS_AUTORISES:
        raise PressingRegleError(f"Pas d'arrondi invalide : {pas_grammes}")
    if mode == "superieur":
        blocs = -(-poids_grams // pas_grammes)
    elif mode == "proche":
        blocs = arrondir_demi_haut(poids_grams, pas_grammes)
    else:
        raise PressingRegleError(f"Mode d'arrondi invalide : {mode}")
    return max(blocs, 1) * pas_grammes


def montant_au_kilo(grammes: int, prix_kg: int) -> int:
    """``grammes * prix_kg / 1000`` arrondi au franc, demi vers le haut."""
    return arrondir_demi_haut(grammes * prix_kg, 1000)


def kilos(grammes: int) -> Decimal:
    """Poids en kg avec 3 décimales exactes (3400 -> Decimal('3.400'))."""
    return (Decimal(grammes) / Decimal(1000)).quantize(Decimal("0.001"))


def calculer(
    tarif: Tarif,
    demande: DemandeCalcul,
    articles: Dict[object, ArticleTarifie],
    combinaisons: Dict[object, CombinaisonTarifee],
) -> dict:
    """Aperçu d'une commande. ``articles`` et ``combinaisons`` ne contiennent que ceux du
    restaurant : un identifiant absent est refusé comme introuvable."""
    lignes: List[dict] = []
    facturable: Optional[int] = None

    if demande.remise_fcfa < 0:
        raise PressingRegleError("La remise ne peut pas être négative")

    if demande.lavage or demande.sechage:
        if demande.poids_grams is None:
            raise PressingRegleError(
                "Le poids est obligatoire pour un lavage ou un séchage"
            )
        facturable = poids_facturable(demande.poids_grams, tarif.pas_grammes, tarif.mode)

    if demande.lavage:
        lignes.append(
            {
                "type": "lavage",
                "libelle": "Lavage, rinçage et essorage",
                "quantite": kilos(facturable),
                "prix_unitaire": tarif.prix_kg,
                "montant": montant_au_kilo(facturable, tarif.prix_kg),
            }
        )

    if demande.sechage:
        if tarif.prix_sechage_kg is None:
            raise PressingRegleError("Le séchage n'est pas proposé par ce pressing")
        lignes.append(
            {
                "type": "sechage",
                "libelle": "Séchage",
                "quantite": kilos(facturable),
                "prix_unitaire": tarif.prix_sechage_kg,
                "montant": montant_au_kilo(facturable, tarif.prix_sechage_kg),
            }
        )

    for article_id, quantite in demande.articles:
        article = articles.get(article_id)
        if article is None:
            raise PressingRegleError(
                f"Article introuvable pour ce restaurant : {article_id}"
            )
        if not article.actif:
            raise PressingRegleError(f"L'article « {article.nom} » est désactivé")
        _verifier_quantite(quantite)
        lignes.append(
            {
                "type": "article",
                "libelle": article.nom,
                "quantite": Decimal(quantite),
                "prix_unitaire": article.prix_unitaire,
                "montant": quantite * article.prix_unitaire,
            }
        )

    for combinaison_id, quantite in demande.combinaisons:
        combinaison = combinaisons.get(combinaison_id)
        if combinaison is None:
            raise PressingRegleError(
                f"Combinaison introuvable pour ce restaurant : {combinaison_id}"
            )
        if not combinaison.actif:
            raise PressingRegleError(
                f"La combinaison « {combinaison.nom} » est désactivée"
            )
        _verifier_quantite(quantite)
        lignes.append(
            {
                "type": "combinaison",
                "libelle": combinaison.nom,
                "quantite": Decimal(quantite),
                "prix_unitaire": combinaison.prix,
                "montant": quantite * combinaison.prix,
            }
        )

    if not lignes:
        raise PressingRegleError("Aucune ligne à facturer")

    sous_total = sum(ligne["montant"] for ligne in lignes)
    if demande.remise_fcfa > sous_total:
        raise PressingRegleError(
            f"La remise ({demande.remise_fcfa} {DEVISE}) dépasse le sous-total ({sous_total} {DEVISE})"
        )
    return {
        "poids_facturable_grams": facturable,
        "lignes": lignes,
        "sous_total": sous_total,
        "remise_fcfa": demande.remise_fcfa,
        "total": sous_total - demande.remise_fcfa,
        "devise": DEVISE,
    }


def _verifier_quantite(quantite: int) -> None:
    if quantite < 1:
        raise PressingRegleError("Les quantités doivent être d'au moins 1")
