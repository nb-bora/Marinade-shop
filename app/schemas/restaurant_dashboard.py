"""Tableau de bord du restaurant : un seul document, calculé côté serveur.

Montants en unité principale de la devise (XAF : 1 = 1 FCFA). Noms préfixés ``RestoDash`` pour
ne pas entrer en collision avec les autres schémas dans l'OpenAPI.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class RestoDashKpi(BaseModel):
    ca_jour: float
    ca_reference: float  # même jour de la semaine précédente, jusqu'à la même heure
    variation_pct: Optional[float] = None  # None : pas de référence
    commandes: int
    commandes_reference: int
    panier_moyen: float
    tables_servies: int
    en_cours: int  # commandes ouvertes (non terminées)
    reste_a_encaisser: float  # factures émises / partiellement payées


class RestoDashHeure(BaseModel):
    heure: int
    ca: float
    commandes: int
    ca_reference: float


class RestoDashJour(BaseModel):
    jour: str  # AAAA-MM-JJ
    ca: float
    commandes: int


class RestoDashProduit(BaseModel):
    nom: str
    quantite: int
    montant: float


class RestoDashMoyen(BaseModel):
    moyen: str
    montant: float
    paiements: int


class RestoDashSalle(BaseModel):
    total: int
    libres: int
    occupees: int
    reservees: int
    maintenance: int
    sessions_ouvertes: int


class RestoDashPoste(BaseModel):
    poste: str
    en_attente: int
    en_preparation: int
    pretes: int


class RestoDashCuisine(BaseModel):
    en_attente: int
    en_preparation: int
    pretes: int
    attente_max_min: int
    postes: List[RestoDashPoste]


class RestoDashReservation(BaseModel):
    id: str
    heure: datetime
    nom: str
    couverts: int
    statut: str
    table: Optional[str] = None


class RestoDashReservations(BaseModel):
    total_jour: int
    couverts_jour: int
    a_confirmer: int
    prochaines: List[RestoDashReservation]


class RestoDashStockBas(BaseModel):
    nom: str
    quantite: float
    seuil: float
    unite: str


class RestoDashStock(BaseModel):
    sous_seuil: int
    ruptures: int
    articles: List[RestoDashStockBas]


class RestoDashCaisse(BaseModel):
    ouvertes: int
    caissiers: List[str]


class RestoDashAlerte(BaseModel):
    niveau: str  # critique | avertissement | info
    type: str
    message: str
    lien: Optional[str] = None


class RestoDashboardResponse(BaseModel):
    genere_le: datetime
    fuseau: str
    devise: str
    kpi: RestoDashKpi
    heures: List[RestoDashHeure]
    semaine: List[RestoDashJour]
    top_produits: List[RestoDashProduit]
    moyens_paiement: List[RestoDashMoyen]
    salle: RestoDashSalle
    cuisine: RestoDashCuisine
    reservations: RestoDashReservations
    stock: RestoDashStock
    caisse: RestoDashCaisse
    alertes: List[RestoDashAlerte]
