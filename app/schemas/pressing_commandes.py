"""Schémas des commandes de pressing : commandes, affectation, paiements, caisse, clients,
tableau de bord, rapports.

Montants : entiers FCFA. Quantités des lignes de lavage/séchage : chaîne décimale en kg
(comme ``PressingCalculLigne``). Dates : ISO 8601 avec fuseau.
"""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.pressing import PressingCalculArticle, PressingCalculCombinaison
from app.schemas.pressing_machines import EtatOperationnel, MachineCategorie, MaintenanceType
from app.utils.phone import normalize_cameroon_phone

CommandeStatut = Literal[
    "recue",
    "en_attente_machine",
    "en_lavage",
    "attente_sechage",
    "en_sechage",
    "pret",
    "livre",
    "annulee",
]
Etape = Literal["lavage", "sechage"]
ModePaiement = Literal["especes", "mobile_money", "carte", "autre"]
FinEstimeeSource = Literal["estimation_initiale", "affectation", "cycle"]


def _motif_obligatoire(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Un motif est obligatoire")
    return value


def _motif_optionnel(value: Optional[str]) -> Optional[str]:
    return (value.strip() or None) if value is not None else None


# ------------------------------------------------------------------------- paiement (entrée)
class PressingPaiementIn(BaseModel):
    montant: int = Field(..., gt=0, le=1_000_000_000)
    mode: ModePaiement
    reference: Optional[str] = Field(None, max_length=80)

    @field_validator("reference")
    @classmethod
    def _reference(cls, value: Optional[str]) -> Optional[str]:
        return (value.strip() or None) if value is not None else None


# ------------------------------------------------------------------------------ commandes
class PressingCommandeBase(BaseModel):
    client_nom: str = Field(..., min_length=1, max_length=120)
    client_telephone: Optional[str] = Field(
        None, description="Mobile camerounais (ex. 6 77 12 34 56) ; normalisé en +237..."
    )
    poids_grams: Optional[int] = Field(
        None, ge=1, le=1_000_000, description="Grammes ; obligatoire si lavage ou séchage"
    )
    lavage: bool = True
    sechage: bool = False
    types_linge: List[str] = Field(
        default_factory=list, max_length=20, description='Ex. "coton", "drap", "delicat"'
    )
    articles: List[PressingCalculArticle] = Field(default_factory=list, max_length=200)
    combinaisons: List[PressingCalculCombinaison] = Field(default_factory=list, max_length=200)
    remise_fcfa: int = Field(0, ge=0, le=1_000_000_000)
    instructions: Optional[str] = Field(None, max_length=500)

    @field_validator("client_nom")
    @classmethod
    def _nom(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Le nom du client ne peut pas être vide")
        return value

    @field_validator("client_telephone")
    @classmethod
    def _telephone(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        brut = re.sub(r"[\s().-]", "", value)
        if re.fullmatch(r"6\d{8}", brut):  # saisie locale : 677123456
            brut = "+237" + brut
        try:
            return normalize_cameroon_phone(brut)
        except ValueError:
            raise ValueError(
                "Numéro de téléphone camerounais invalide (mobile à 9 chiffres, ex. 677123456)"
            )

    @field_validator("instructions")
    @classmethod
    def _instructions(cls, value: Optional[str]) -> Optional[str]:
        return (value.strip() or None) if value is not None else None

    @field_validator("types_linge")
    @classmethod
    def _types(cls, values: List[str]) -> List[str]:
        propres: List[str] = []
        for value in values:
            value = value.strip().lower()
            if not value or len(value) > 40:
                raise ValueError("Un type de linge fait de 1 à 40 caractères")
            if value not in propres:
                propres.append(value)
        return propres


class PressingCommandeCreate(PressingCommandeBase):
    paiement: Optional[PressingPaiementIn] = Field(
        None,
        description="Paiement au dépôt (montant ≤ total), enregistré dans la même transaction : "
        "s'il est refusé, la commande n'est pas créée.",
    )


class PressingCommandeUpdate(PressingCommandeBase):
    """Remplace le contenu d'une commande encore « reçue » (mêmes champs qu'à la création)."""


class LigneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal["lavage", "sechage", "article", "combinaison"]
    libelle: str
    quantite: Decimal = Field(description="kg (3 décimales) pour lavage/séchage, entier sinon")
    prix_unitaire: int
    montant: int


class PressingCommandeMachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    machine_id: uuid.UUID
    machine_nom: Optional[str] = None
    etape: Etape
    charge_kg: float
    programme: Optional[str] = None
    duree_min: Optional[int] = None
    intervention_humaine: bool
    debut_prevu: Optional[datetime] = None
    fin_prevue: Optional[datetime] = None
    debut_reel: Optional[datetime] = None
    fin_reelle: Optional[datetime] = None
    dechargee_le: Optional[datetime] = None
    interrompue_le: Optional[datetime] = Field(
        None, description="Cycle interrompu (panne, coupure...) : fin_reelle = interrompue_le"
    )
    motif_interruption: Optional[str] = None
    actif: bool = Field(
        description="Faux : affectation abandonnée (libérée, annulée, ou cycle interrompu dont "
        "la charge n'a pas été traitée) ; sa charge redevient à affecter"
    )


class PressingCommandeOut(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    numero: str
    client_nom: str
    client_telephone: Optional[str] = None
    poids_grams: Optional[int] = None
    poids_facturable_grams: Optional[int] = None
    lavage: bool
    sechage: bool
    instructions: Optional[str] = None
    types_linge: List[str]
    statut: CommandeStatut
    etape: Optional[Etape] = Field(
        None, description="Étape machine à traiter ; null (articles seuls, prête, livrée, annulée)"
    )
    sous_total: int
    remise_fcfa: int
    montant_total: int
    montant_paye: int
    reste_a_payer: int
    devise: Literal["FCFA"] = "FCFA"
    cree_le: datetime
    pris_en_charge_le: Optional[datetime] = None
    pret_le: Optional[datetime] = None
    livre_le: Optional[datetime] = None
    debut_prevu: Optional[datetime] = None
    fin_estimee: Optional[datetime] = Field(
        None, description="ESTIMATION de fin (voir fin_estimee_source), jamais une mesure"
    )
    fin_estimee_source: Optional[FinEstimeeSource] = Field(
        None,
        description="estimation_initiale : calculée à la création (meilleure option + séchage) ; "
        "affectation : machines réservées ; cycle : cycle démarré ou prolongé",
    )
    fin_reelle: Optional[datetime] = None
    annule_le: Optional[datetime] = None
    motif_annulation: Optional[str] = None
    charge_engagee_kg: float = Field(
        0, description="Charge de l'étape courante déjà engagée (réservée, en cycle ou terminée)"
    )
    charge_restante_kg: Optional[float] = Field(
        None, description="Charge de l'étape courante encore à affecter ; null sans étape"
    )
    a_reaffecter: bool = Field(
        False,
        description="Vrai quand l'étape est entamée, qu'il reste de la charge et qu'aucune "
        "machine n'est réservée ou en cycle pour elle (charges successives, cycle interrompu)",
    )
    lignes: List[LigneOut]
    machines: List[PressingCommandeMachineOut]


class PressingCommandeListe(BaseModel):
    items: List[PressingCommandeOut]
    total: int


class AnnulationIn(BaseModel):
    motif: str = Field(..., min_length=1, max_length=500)

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Un motif d'annulation est obligatoire")
        return value


# ---------------------------------------------------------------------------- recommandation
class PressingMachineProposeeOut(BaseModel):
    machine_id: uuid.UUID
    nom: str
    charge_kg: float
    programme: str
    duree_min: int
    debut_prevu: datetime
    fin_prevue: datetime
    attente_min: int
    intervention_humaine: bool


class PressingOptionAffectationOut(BaseModel):
    type: Literal["machine_unique", "repartition", "partielle"] = Field(
        description="partielle : la machine est remplie à sa capacité, le reste de la charge "
        "sera affecté après ce cycle (charges successives)"
    )
    score: int
    machines: List[PressingMachineProposeeOut]
    raisons: List[str]
    avertissements: List[str]


class PressingMachineExclueOut(BaseModel):
    machine_id: uuid.UUID
    nom: str
    raison: str


class PressingRecommandationOut(BaseModel):
    faisable: bool
    etape: Etape
    options: List[PressingOptionAffectationOut]
    motif_si_non_faisable: Optional[str] = None
    action_conseillee: Optional[Literal["attendre", "decision_responsable"]] = None
    machines_exclues: List[PressingMachineExclueOut] = Field(default_factory=list)


class PressingAffectationIn(BaseModel):
    options_choisie: Optional[int] = Field(
        None, ge=0, le=2, description="Index de l'option de la recommandation (0 à 2)"
    )
    machine_ids: Optional[List[uuid.UUID]] = Field(
        None, min_length=1, max_length=20, description="Machines choisies à la main (alternative)"
    )
    programmes: Dict[uuid.UUID, str] = Field(
        default_factory=dict, description="Programme choisi par machine (sinon le plus court)"
    )
    accepter_partiel: bool = Field(
        False,
        description="Avec machine_ids : si leur capacité cumulée est inférieure à la charge "
        "restante, chaque machine est remplie à sa capacité et le reste demeure à affecter",
    )

    @model_validator(mode="after")
    def _un_choix(self):
        if (self.options_choisie is None) == (self.machine_ids is None):
            raise ValueError("Indiquez soit options_choisie, soit machine_ids")
        return self


class PressingAffectationOut(BaseModel):
    commande: PressingCommandeOut
    etape: Etape


class DemarrageIn(BaseModel):
    commande_id: uuid.UUID
    programme: str = Field(..., min_length=1, max_length=80)
    charge_kg: Optional[Decimal] = Field(
        None,
        gt=0,
        le=200,
        decimal_places=3,
        description="Départ direct sur une machine libre seulement : charge mise dans la machine "
        "(défaut : le minimum de la charge restante et de la capacité). 422 si elle dépasse "
        "la capacité ou la charge restante.",
    )


class PressingLibererIn(BaseModel):
    ligne_ids: Optional[List[uuid.UUID]] = Field(
        None,
        min_length=1,
        max_length=20,
        description="Affectations à libérer (identifiants de `machines[].id`) ; absent : toutes "
        "les affectations non démarrées de l'étape courante",
    )
    motif: Optional[str] = Field(None, max_length=500)

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: Optional[str]) -> Optional[str]:
        return _motif_optionnel(value)


class PressingInterruptionIn(BaseModel):
    motif: str = Field(..., min_length=1, max_length=500, description="Panne, coupure, erreur...")
    charge_traitee: bool = Field(
        False,
        description="Vrai : la charge compte comme faite. Faux : elle redevient à affecter.",
    )

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: str) -> str:
        return _motif_obligatoire(value)


class PressingProlongationIn(BaseModel):
    minutes: int = Field(..., ge=1, le=240)
    motif: str = Field(..., min_length=1, max_length=500)

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: str) -> str:
        return _motif_obligatoire(value)


class PressingDechargementMaintenanceIn(BaseModel):
    type: MaintenanceType
    description: str = Field(..., min_length=1, max_length=1000)

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La description de la maintenance est obligatoire")
        return value


class PressingDechargementIn(BaseModel):
    apres: Literal["libre", "maintenance", "hors_service"] = Field(
        "libre", description="État de la machine une fois déchargée"
    )
    motif: Optional[str] = Field(
        None, max_length=1000, description="Obligatoire si `apres` vaut maintenance ou hors_service"
    )
    maintenance: Optional[PressingDechargementMaintenanceIn] = Field(
        None,
        description="Déclare une maintenance ouverte (entretien, panne, réparation) après le "
        "déchargement ; seulement avec `apres` = maintenance ou hors_service",
    )

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: Optional[str]) -> Optional[str]:
        return _motif_optionnel(value)

    @model_validator(mode="after")
    def _coherence(self):
        if self.apres != "libre" and not self.motif:
            raise ValueError(
                f"Un motif est obligatoire pour laisser la machine en « {self.apres} » "
                "après le déchargement"
            )
        if self.apres == "libre" and self.maintenance is not None:
            raise ValueError(
                "Une maintenance ne se déclare qu'avec apres = maintenance ou hors_service"
            )
        return self


class PressingMachineActionOut(BaseModel):
    machine_id: uuid.UUID
    etat: EtatOperationnel
    commande_id: Optional[uuid.UUID] = None
    commande_statut: Optional[CommandeStatut] = None
    fin_estimee: Optional[datetime] = None
    debut_reel: Optional[datetime] = None
    fin_reelle: Optional[datetime] = None
    duree_mesuree_min: Optional[float] = Field(
        None, description="MESURÉE : fin réelle - début réel du cycle"
    )
    dechargee_le: Optional[datetime] = None
    interrompue_le: Optional[datetime] = None
    maintenance_id: Optional[uuid.UUID] = Field(
        None, description="Maintenance déclarée au déchargement, s'il y en a une"
    )


# --------------------------------------------------------------------------------- paiements
class PressingPaiementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    commande_id: uuid.UUID
    montant: int = Field(description="Négatif pour une contre-passation (annulation)")
    mode: ModePaiement
    reference: Optional[str] = None
    cree_le: datetime
    auteur_id: Optional[uuid.UUID] = None
    annule_paiement_id: Optional[uuid.UUID] = Field(
        None, description="Contre-passation : paiement annulé par cette écriture"
    )
    annule_le: Optional[datetime] = Field(None, description="Paiement annulé : date d'annulation")
    annule_par: Optional[uuid.UUID] = None
    motif_annulation: Optional[str] = None


class PressingPaiementJournalOut(PressingPaiementOut):
    commande_numero: str
    client_nom: str


class ParMode(BaseModel):
    especes: int = 0
    mobile_money: int = 0
    carte: int = 0
    autre: int = 0


class PressingClotureIn(BaseModel):
    date: date
    montant_compte: int = Field(..., ge=0, le=1_000_000_000)


class PressingClotureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: date
    total_encaisse: int
    especes_attendues: int
    montant_compte: int
    ecart: int = Field(description="montant compté - espèces attendues (négatif : il manque)")
    auteur_id: Optional[uuid.UUID] = None
    cree_le: datetime


class JournalCaisseOut(BaseModel):
    date: date
    fuseau: str
    total_encaisse: int = Field(description="Net : contre-passations déduites")
    par_mode: ParMode
    paiements: List[PressingPaiementJournalOut]
    cloture: Optional[PressingClotureOut] = None
    encaisse_apres_cloture: int = Field(
        0,
        description="Net des paiements du jour enregistrés après la clôture (contre-passations "
        "comprises) ; 0 sans clôture",
    )


# --------------------------------------------------------------------------------- clients
class PressingClientOut(BaseModel):
    nom: str
    telephone: Optional[str] = None
    nb_commandes: int
    total_depense: int
    reste_a_payer: int
    derniere_commande: datetime


# ---------------------------------------------------------------------------- tableau de bord
class PressingMachinesResume(BaseModel):
    total_lave_linge: int
    total_seche_linge: int
    par_etat: Dict[str, int]


class PressingCommandesResume(BaseModel):
    par_statut: Dict[str, int]
    en_attente_prise_en_charge: int
    en_cours: int
    terminees_jour: int


class FinanceResume(BaseModel):
    ca_jour: int = Field(description="Facturé (commandes non annulées créées), remises déduites")
    ca_semaine: int
    ca_mois: int
    encaisse_jour: int = Field(description="Paiements reçus aujourd'hui")
    reste_a_payer_total: int
    source: Literal["transactions_pressing"] = "transactions_pressing"


class ActiviteResume(BaseModel):
    poids_traite_kg_jour: float
    poids_traite_kg_semaine: float
    nb_commandes_jour: int
    duree_moyenne_traitement_min_mesuree: Optional[float] = Field(
        None, description="MESURÉE, 30 derniers jours, cycles terminés uniquement"
    )
    duree_estimee_moyenne_min: Optional[float] = Field(
        None, description="ESTIMÉE (durées prévues des programmes), 30 derniers jours"
    )


class UtilisationResume(BaseModel):
    taux_pct_aujourdhui: float
    minutes_occupees: float
    minutes_disponibles: float


class OccupationOut(BaseModel):
    machine_id: uuid.UUID
    nom: str
    categorie: MachineCategorie
    commande_numero: Optional[str] = None
    debut_reel: Optional[datetime] = None
    fin_estimee: Optional[datetime] = None
    ecoule_min: Optional[int] = None
    restant_min: Optional[int] = None
    en_retard: bool


class LiberationOut(BaseModel):
    machine_id: uuid.UUID
    nom: str
    fin_estimee: datetime


class AlerteOut(BaseModel):
    niveau: Literal["info", "avertissement", "critique"]
    type: Literal[
        "retard",
        "panne",
        "intervention",
        "attente_dechargement",
        "dechargement_tardif",
        "reservation_non_demarree",
        "prise_en_charge",
        "charge_restante",
        "sechage_en_attente",
        "paiement_apres_cloture",
    ]
    message: str
    machine_id: Optional[uuid.UUID] = None
    commande_id: Optional[uuid.UUID] = None


class PressingTableauDeBordOut(BaseModel):
    genere_a: datetime
    fuseau: str
    machines: PressingMachinesResume
    commandes: PressingCommandesResume
    finance: FinanceResume
    activite: ActiviteResume
    utilisation: UtilisationResume
    occupations: List[OccupationOut]
    prochaines_liberations: List[LiberationOut]
    alertes: List[AlerteOut]


# --------------------------------------------------------------------------------- rapports
class PeriodeOut(BaseModel):
    du: date
    au: date
    jours: int
    granularite: Literal["jour"] = "jour"


class CaJourOut(BaseModel):
    date: date
    montant: int


class CaParService(BaseModel):
    lavage: int
    sechage: int
    articles: int
    combinaisons: int


class PressingRapportMachineOut(BaseModel):
    machine_id: uuid.UUID
    nom: str
    cycles: int
    heures_utilisation: float = Field(description="MESURÉES (somme des cycles terminés)")


class PannesOut(BaseModel):
    nombre: int
    indisponibilite_min: int


class PressingRapportOut(BaseModel):
    periode: PeriodeOut
    ca_par_jour: List[CaJourOut]
    ca_par_service: CaParService = Field(
        description="Montant des lignes avant remise (la somme peut dépasser le CA)"
    )
    nb_commandes: int
    poids_kg: float
    machines: List[PressingRapportMachineOut]
    pannes: PannesOut
    duree_moyenne_cycle_min_mesuree: Optional[float] = None
