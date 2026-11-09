"""Approvisionnement : fournisseurs, catalogue d'achat, suggestions, bons de commande, réceptions.

Les quantités sont exprimées dans l'unité de stock du composant (``composants.stock_unite``), avec trois
décimales au plus ; les prix unitaires sont par unité de stock. Une ligne peut préciser ``unite`` (un
sac, une caisse, des grammes...) : elle est convertie en unité de stock avant d'être écrite.
"""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


StatutBon = Literal["brouillon", "envoye", "recu_partiel", "recu", "annule"]
EtatLigne = Literal["a_recevoir", "partiel", "recu", "depasse"]
NiveauFiabilite = Literal["bon", "moyen", "faible", "inconnu"]

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _texte(valeur: Optional[str]) -> Optional[str]:
    """Texte nettoyé ; vide = absent."""
    if valeur is None:
        return None
    valeur = " ".join(valeur.split()) if "\n" not in valeur else valeur.strip()
    return valeur or None


def _telephone(valeur: Optional[str]) -> Optional[str]:
    """Numéro international ; la saisie locale camerounaise (9 chiffres) reçoit +237."""
    valeur = _texte(valeur)
    if valeur is None:
        return None
    brut = re.sub(r"[\s().-]", "", valeur)
    if brut.startswith("00"):
        brut = "+" + brut[2:]
    if re.fullmatch(r"[26]\d{8}", brut):
        brut = "+237" + brut
    elif re.fullmatch(r"237\d{9}", brut):
        brut = "+" + brut
    if not re.fullmatch(r"\+[1-9]\d{6,14}", brut):
        raise ValueError(
            "Numéro de téléphone invalide : saisissez-le au format international (+237 6 77 12 34 56)."
        )
    return brut


def _email(valeur: Optional[str]) -> Optional[str]:
    valeur = _texte(valeur)
    if valeur is None:
        return None
    valeur = valeur.lower()
    if len(valeur) > 254 or ".." in valeur or not _EMAIL.match(valeur):
        raise ValueError("Adresse e-mail invalide.")
    return valeur


# ------------------------------------------------------------------------------ fournisseurs


class FournisseurBase(BaseModel):
    nom: str = Field(..., min_length=1, max_length=255)
    contact: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=254)
    telephone: Optional[str] = Field(None, max_length=30)
    adresse: Optional[str] = Field(None, max_length=1000)
    delai_jours: int = Field(2, ge=0, le=365, description="Délai de livraison habituel, en jours")
    conditions_paiement: Optional[str] = Field(None, max_length=255)
    note: Optional[str] = Field(None, max_length=2000)

    @field_validator("nom")
    @classmethod
    def _nom(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Indiquez le nom du fournisseur.")
        return value

    @field_validator("contact", "adresse", "conditions_paiement", "note")
    @classmethod
    def _libres(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)

    @field_validator("email")
    @classmethod
    def _courriel(cls, value: Optional[str]) -> Optional[str]:
        return _email(value)

    @field_validator("telephone")
    @classmethod
    def _tel(cls, value: Optional[str]) -> Optional[str]:
        return _telephone(value)


class FournisseurCreate(FournisseurBase):
    pass


class FournisseurUpdate(BaseModel):
    nom: Optional[str] = Field(None, min_length=1, max_length=255)
    contact: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=254)
    telephone: Optional[str] = Field(None, max_length=30)
    adresse: Optional[str] = Field(None, max_length=1000)
    delai_jours: Optional[int] = Field(None, ge=0, le=365)
    conditions_paiement: Optional[str] = Field(None, max_length=255)
    note: Optional[str] = Field(None, max_length=2000)
    actif: Optional[bool] = None

    @field_validator("nom")
    @classmethod
    def _nom(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("Le nom du fournisseur ne peut pas être vide.")
        return value

    @field_validator("contact", "adresse", "conditions_paiement", "note")
    @classmethod
    def _libres(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)

    @field_validator("email")
    @classmethod
    def _courriel(cls, value: Optional[str]) -> Optional[str]:
        return _email(value)

    @field_validator("telephone")
    @classmethod
    def _tel(cls, value: Optional[str]) -> Optional[str]:
        return _telephone(value)


class FournisseurResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    contact: Optional[str] = None
    email: Optional[str] = None
    telephone: Optional[str] = None
    adresse: Optional[str] = None
    delai_jours: int
    conditions_paiement: Optional[str] = None
    note: Optional[str] = None
    actif: bool
    archive: bool = False
    nb_articles: int = 0
    bons_en_cours: int = 0
    dernier_achat: Optional[datetime] = None
    created_at: Optional[datetime] = None


class Fiabilite(BaseModel):
    """Fiabilité d'un fournisseur, calculée sur ses bons de commande et ses réceptions."""

    nb_bons: int = 0
    nb_bons_clos: int = 0
    livraisons_completes: int = 0
    taux_livraison_complete: Optional[float] = Field(None, description="Part des bons clos livrés en une fois, 0 à 1")
    bons_avec_date: int = 0
    retards: int = 0
    taux_ponctualite: Optional[float] = Field(None, description="Part des bons livrés à temps, 0 à 1")
    delai_moyen_jours: Optional[float] = None
    total_achete: Decimal = Decimal("0")
    niveau: NiveauFiabilite = "inconnu"


class FournisseurDetail(FournisseurResponse):
    fiabilite: Fiabilite


# ---------------------------------------------------------------------------- catalogue d'achat


def _quantite_trois_decimales(value: Optional[Decimal]) -> Optional[Decimal]:
    if value is None:
        return None
    if value != value.quantize(Decimal("0.001")):
        raise ValueError("Trois décimales au plus pour une quantité.")
    return value


class CatalogueAchatUpsert(BaseModel):
    reference: Optional[str] = Field(None, max_length=60, description="Référence chez le fournisseur")
    prix_unitaire: Optional[Decimal] = Field(None, ge=0, le=Decimal("9999999999.9999"), decimal_places=4,
                                             description="Prix par unité de stock")
    conditionnement: Optional[Decimal] = Field(None, gt=0, le=Decimal("999999999.999"),
                                               description="Contenu d'un colis, en unités de stock (sac de 25 kg : 25)")
    quantite_minimum: Optional[Decimal] = Field(None, gt=0, le=Decimal("999999999.999"))
    principal: bool = False

    @field_validator("reference")
    @classmethod
    def _ref(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)

    @field_validator("conditionnement", "quantite_minimum")
    @classmethod
    def _qte(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        return _quantite_trois_decimales(value)


class CatalogueAchatResponse(BaseModel):
    id: uuid.UUID
    fournisseur_id: uuid.UUID
    fournisseur_nom: str
    composant_id: uuid.UUID
    composant_nom: str
    unite: str
    reference: Optional[str] = None
    prix_unitaire: Optional[Decimal] = None
    conditionnement: Optional[Decimal] = None
    quantite_minimum: Optional[Decimal] = None
    principal: bool = False
    dernier_prix_recu: Optional[Decimal] = None
    dernier_achat: Optional[datetime] = None


class PointPrix(BaseModel):
    recu_le: datetime
    composant_id: uuid.UUID
    composant_nom: str
    unite: str
    prix_unitaire: Decimal
    quantite: Decimal
    numero_bl: Optional[str] = None
    bon_numero: Optional[str] = None


class ResumePrix(BaseModel):
    composant_id: uuid.UUID
    composant_nom: str
    unite: str
    nb_achats: int
    dernier_prix: Decimal
    premier_prix: Decimal
    prix_min: Decimal
    prix_max: Decimal
    variation_pct: Optional[float] = Field(None, description="Évolution entre le premier et le dernier prix, en %")


class HistoriquePrix(BaseModel):
    fournisseur_id: uuid.UUID
    devise: str
    resume: List[ResumePrix]
    points: List[PointPrix]


# -------------------------------------------------------------------------------- suggestions


class SuggestionLigne(BaseModel):
    composant_id: uuid.UUID
    composant_nom: str
    unite: str
    quantite_stock: Decimal
    reservee: Decimal
    disponible: Decimal
    seuil_alerte: Decimal
    stock_cible: Decimal
    niveau_cible: Decimal = Field(..., description="Niveau visé : stock cible, à défaut deux fois le seuil")
    deja_commande: Decimal = Field(..., description="Commandé chez un fournisseur et pas encore reçu (bons envoyés ou partiels)")
    en_brouillon: Decimal = Field(..., description="Prévu dans un bon encore en brouillon")
    quantite_suggeree: Decimal
    nb_conditionnements: Optional[Decimal] = None
    conditionnement: Optional[Decimal] = None
    quantite_minimum: Optional[Decimal] = None
    reference: Optional[str] = None
    prix_unitaire: Optional[Decimal] = None
    prix_source: Optional[Literal["catalogue", "cout_moyen"]] = None
    cout_estime: Decimal = Decimal("0")
    consommation_jour: Decimal = Field(Decimal("0"), description="Moyenne des sorties sur 7 jours, par jour")
    jours_couverture: Optional[float] = Field(None, description="Jours de stock disponible au rythme actuel")
    etat: Literal["rupture", "alerte"]
    couvert: bool = Field(False, description="Rien à commander : la quantité attendue est déjà commandée")
    fournisseur_principal: bool = True


class SuggestionGroupe(BaseModel):
    fournisseur_id: Optional[uuid.UUID] = None
    fournisseur_nom: Optional[str] = None
    delai_jours: Optional[int] = None
    email: Optional[str] = None
    lignes: List[SuggestionLigne]
    total_estime: Decimal = Decimal("0")
    nb_a_commander: int = 0


class SuggestionsResponse(BaseModel):
    restaurant_id: uuid.UUID
    generated_at: datetime
    devise: str
    groupes: List[SuggestionGroupe]
    nb_composants: int = 0
    nb_a_commander: int = 0
    nb_sans_fournisseur: int = 0
    total_estime: Decimal = Decimal("0")


# ------------------------------------------------------------------------------------ bons


class LigneSaisie(BaseModel):
    composant_id: uuid.UUID
    quantite: Decimal = Field(..., gt=0, le=Decimal("999999999.999"), description="Dans l'unité indiquée, à défaut l'unité de stock")
    unite: Optional[str] = Field(None, max_length=20)
    prix_unitaire: Optional[Decimal] = Field(None, ge=0, le=Decimal("9999999999.9999"), decimal_places=4,
                                             description="Par unité indiquée, à défaut par unité de stock")

    @field_validator("quantite")
    @classmethod
    def _qte(cls, value: Decimal) -> Decimal:
        return _quantite_trois_decimales(value)  # type: ignore[return-value]

    @field_validator("unite")
    @classmethod
    def _unite(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)


class BonCreate(BaseModel):
    fournisseur_id: uuid.UUID
    date_livraison_prevue: Optional[date] = None
    note: Optional[str] = Field(None, max_length=2000)
    lignes: List[LigneSaisie] = Field(..., min_length=1, max_length=200)

    @field_validator("note")
    @classmethod
    def _note(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)


class BonUpdate(BaseModel):
    date_livraison_prevue: Optional[date] = None
    note: Optional[str] = Field(None, max_length=2000)
    lignes: Optional[List[LigneSaisie]] = Field(None, min_length=1, max_length=200)
    # Permet d'effacer la date : ``True`` retire la date de livraison souhaitée.
    sans_date: bool = False

    @field_validator("note")
    @classmethod
    def _note(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)


class GroupeSaisie(BaseModel):
    fournisseur_id: uuid.UUID
    lignes: List[LigneSaisie] = Field(..., min_length=1, max_length=200)


class BonsDepuisSuggestions(BaseModel):
    groupes: List[GroupeSaisie] = Field(..., min_length=1, max_length=50)
    date_livraison_prevue: Optional[date] = None


class EnvoiBon(BaseModel):
    canal: Literal["email", "manuel"] = Field(
        "email", description="« manuel » : commande passée par téléphone ou messagerie, le bon est seulement marqué envoyé"
    )
    message: Optional[str] = Field(None, max_length=1000, description="Mot d'accompagnement ajouté dans l'e-mail")
    date_livraison_prevue: Optional[date] = None

    @field_validator("message")
    @classmethod
    def _message(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)


class AnnulationBon(BaseModel):
    motif: str = Field(..., min_length=3, max_length=500)

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: str) -> str:
        value = _texte(value) or ""
        if len(value) < 3:
            raise ValueError("Indiquez le motif (3 caractères au moins).")
        return value


class ClotureBon(BaseModel):
    motif: Optional[str] = Field(None, max_length=500)

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)


class BonLigneResponse(BaseModel):
    id: uuid.UUID
    composant_id: uuid.UUID
    composant_nom: str
    unite: str
    reference: Optional[str] = None
    conditionnement: Optional[Decimal] = None
    quantite_commandee: Decimal
    quantite_recue: Decimal
    quantite_restante: Decimal
    prix_unitaire: Optional[Decimal] = None
    prix_catalogue: Optional[Decimal] = None
    total_ligne: Decimal
    etat: EtatLigne


class ActionsBon(BaseModel):
    modifier: bool = False
    envoyer: bool = False
    renvoyer: bool = False
    recevoir: bool = False
    cloturer: bool = False
    annuler: bool = False
    dupliquer: bool = True


class BonResponse(BaseModel):
    id: uuid.UUID
    numero: str
    fournisseur_id: uuid.UUID
    fournisseur_nom: str
    statut: StatutBon
    date_livraison_prevue: Optional[date] = None
    note: Optional[str] = None
    motif_annulation: Optional[str] = None
    total_estime: Decimal
    devise: str
    nb_lignes: int
    progression: int = Field(0, description="Part reçue de la quantité commandée, 0 à 100")
    en_retard: bool = False
    envoye_le: Optional[datetime] = None
    cloture_le: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ReceptionResume(BaseModel):
    id: uuid.UUID
    recu_le: datetime
    numero_bl: Optional[str] = None
    nb_lignes: int
    total: Decimal


class FournisseurMini(BaseModel):
    id: uuid.UUID
    nom: str
    contact: Optional[str] = None
    email: Optional[str] = None
    telephone: Optional[str] = None
    delai_jours: int
    archive: bool = False


class BonDetail(BonResponse):
    fournisseur: FournisseurMini
    lignes: List[BonLigneResponse]
    receptions: List[ReceptionResume] = []
    actions: ActionsBon


class BonsCreesResponse(BaseModel):
    bons: List[BonResponse]


class BonDocument(BaseModel):
    numero: str
    titre: str
    html: str


class EnvoiResultat(BaseModel):
    bon: BonDetail
    canal: Literal["email", "manuel"]
    destinataire: Optional[str] = None
    transport: Optional[str] = Field(None, description="smtp, console, memory...")


# ------------------------------------------------------------------------------- réceptions


class ReceptionLigneSaisie(BaseModel):
    composant_id: uuid.UUID
    quantite: Decimal = Field(..., gt=0, le=Decimal("999999999.999"))
    unite: Optional[str] = Field(None, max_length=20)
    prix_unitaire: Optional[Decimal] = Field(None, ge=0, le=Decimal("9999999999.9999"), decimal_places=4,
                                             description="Prix réel facturé, par unité indiquée (par défaut le prix du bon)")
    lot_numero: Optional[str] = Field(None, max_length=60)
    date_peremption: Optional[date] = None

    @field_validator("quantite")
    @classmethod
    def _qte(cls, value: Decimal) -> Decimal:
        return _quantite_trois_decimales(value)  # type: ignore[return-value]

    @field_validator("unite", "lot_numero")
    @classmethod
    def _nettoyer(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)


class ReceptionCreate(BaseModel):
    numero_bl: Optional[str] = Field(None, max_length=60, description="Numéro du bon de livraison du fournisseur")
    note: Optional[str] = Field(None, max_length=2000)
    cle_idempotence: Optional[str] = Field(
        None, min_length=8, max_length=80,
        description="Clé unique de cette saisie : la rejouer ne crée pas une seconde réception",
    )
    maj_prix_catalogue: bool = Field(False, description="Met à jour le prix du catalogue d'achat avec le prix réel")
    lignes: List[ReceptionLigneSaisie] = Field(..., min_length=1, max_length=200)

    @field_validator("numero_bl", "note")
    @classmethod
    def _libres(cls, value: Optional[str]) -> Optional[str]:
        return _texte(value)


class ReceptionDirecteCreate(ReceptionCreate):
    fournisseur_id: Optional[uuid.UUID] = None


class Avertissement(BaseModel):
    code: str
    message: str
    composant_id: Optional[uuid.UUID] = None


class ReceptionLigneResponse(BaseModel):
    composant_id: uuid.UUID
    composant_nom: str
    unite: str
    quantite: Decimal
    prix_unitaire: Optional[Decimal] = None
    prix_attendu: Optional[Decimal] = None
    ecart_prix_pct: Optional[float] = None
    total_ligne: Decimal
    lot_numero: Optional[str] = None
    date_peremption: Optional[date] = None
    lot_id: Optional[uuid.UUID] = None


class ReceptionResponse(BaseModel):
    id: uuid.UUID
    bon_id: Optional[uuid.UUID] = None
    bon_numero: Optional[str] = None
    fournisseur_id: Optional[uuid.UUID] = None
    fournisseur_nom: Optional[str] = None
    numero_bl: Optional[str] = None
    note: Optional[str] = None
    recu_le: datetime
    recu_par_nom: Optional[str] = None
    nb_lignes: int
    total: Decimal
    devise: str


class ReceptionDetail(ReceptionResponse):
    lignes: List[ReceptionLigneResponse]


class ReceptionResultat(ReceptionDetail):
    avertissements: List[Avertissement] = []
    rejouee: bool = Field(False, description="Cette clé d'idempotence avait déjà été enregistrée : rien n'est ajouté")
    bon: Optional[BonResponse] = None


# ------------------------------------------------------------------------ indicateurs, dépenses


class Indicateurs(BaseModel):
    devise: str
    a_commander: int
    sans_fournisseur: int
    bons_brouillon: int
    bons_en_cours: int
    montant_engage: Decimal
    en_retard: int
    receptions_mois: int
    depenses_mois: Decimal


class DepenseFournisseur(BaseModel):
    fournisseur_id: Optional[uuid.UUID] = None
    fournisseur_nom: str
    total: Decimal
    nb_receptions: int


class DepenseMois(BaseModel):
    mois: str
    total: Decimal


class DepensesResponse(BaseModel):
    devise: str
    du: date
    au: date
    total: Decimal
    par_fournisseur: List[DepenseFournisseur]
    par_mois: List[DepenseMois]
