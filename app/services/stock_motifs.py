"""Motifs normalisés des mouvements de stock (colonne ``stock_mouvements.motif``).

Un motif est obligatoire pour toute sortie manuelle (perte, casse…) et tout ajustement ; les mouvements
automatiques (vente, réception, inventaire, annulation) posent le leur.
"""

from __future__ import annotations

# Entrées
RECEPTION = "reception"  # marchandise livrée (bon de commande ou livraison directe)
RETOUR_FOURNISSEUR_ANNULE = "retour"  # entrée de rattrapage
INVENTAIRE = "inventaire"  # régularisation à la validation d'un inventaire
ANNULATION = "annulation"  # restitution d'une commande annulée ou remboursée
PRODUCTION = "production"  # sous-préparation (fond, sauce) produite en cuisine

# Sorties
VENTE = "vente"  # consommation par une commande payée
PERTE = "perte"  # perte non expliquée ou accident
CASSE = "casse"  # bouteille ou plat cassé, renversé
PEREMPTION = "peremption"  # produit périmé jeté
USAGE_INTERNE = "usage_interne"  # repas du personnel, dégustation
OFFERT = "offert"  # geste commercial non facturé
ERREUR_SAISIE = "erreur_saisie"  # correction d'une erreur de saisie précédente
VOL = "vol"
AUTRE = "autre"  # exige un commentaire

MOTIFS_ENTREE = (RECEPTION, RETOUR_FOURNISSEUR_ANNULE, INVENTAIRE, ANNULATION, PRODUCTION, ERREUR_SAISIE, AUTRE)
MOTIFS_SORTIE = (VENTE, PERTE, CASSE, PEREMPTION, USAGE_INTERNE, OFFERT, ERREUR_SAISIE, VOL, INVENTAIRE, AUTRE)
MOTIFS_AJUSTEMENT = (INVENTAIRE, ERREUR_SAISIE, AUTRE)
MOTIFS_PERTE = (PERTE, CASSE, PEREMPTION, VOL)  # comptés comme « pertes » dans les rapports

ALL_MOTIFS = tuple(
    dict.fromkeys(MOTIFS_ENTREE + MOTIFS_SORTIE + MOTIFS_AJUSTEMENT)
)

#: Libellés français (interface et export).
LIBELLES = {
    RECEPTION: "Réception",
    RETOUR_FOURNISSEUR_ANNULE: "Retour",
    INVENTAIRE: "Inventaire",
    ANNULATION: "Commande annulée",
    PRODUCTION: "Production",
    VENTE: "Vente",
    PERTE: "Perte",
    CASSE: "Casse",
    PEREMPTION: "Péremption",
    USAGE_INTERNE: "Usage interne",
    OFFERT: "Offert",
    ERREUR_SAISIE: "Erreur de saisie",
    VOL: "Vol",
    AUTRE: "Autre",
}
