"""Schémas de l'espace pressing : zones, machines, états, maintenances, historique, plan.

Conventions : pourcentages du plan (``x``, ``y``, ``w``, ``h``, ``position_x/y``) en nombres JSON ;
``capacite_kg`` et les consommations sont des ``Decimal`` sérialisés en CHAÎNE (comme les autres
quantités de l'API).
"""

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ZoneType = Literal["lavage", "sechage", "reception", "attente", "pliage", "stockage", "autre"]
MachineCategorie = Literal["lave_linge", "seche_linge"]
TypeFonctionnement = Literal["semi_automatique", "automatique", "autre"]
EtatOperationnel = Literal[
    "libre",
    "reservee",
    "en_cycle",
    "cycle_termine",
    "attente_dechargement",
    "maintenance",
    "hors_service",
]
EvenementType = Literal["etat_change", "maintenance", "note"]
MaintenanceType = Literal["entretien", "panne", "reparation"]

Pourcentage = Field(..., ge=0, le=100, description="Pourcentage 0-100 de la largeur/hauteur du plan")
_COULEUR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _texte(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Ce champ ne peut pas être vide")
    return value


def _texte_optionnel(value: Optional[str]) -> Optional[str]:
    return (value.strip() or None) if value is not None else None


def _deux_decimales(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(float(value), 2)


# ---------------------------------------------------------------------------- zones
class ZoneIn(BaseModel):
    nom: str = Field(..., min_length=1, max_length=120)
    type: ZoneType = "autre"
    couleur: str = Field("#94A3B8", description="Couleur hexadécimale #RRGGBB")
    x: float = Pourcentage
    y: float = Pourcentage
    w: float = Field(..., gt=0, le=100, description="Largeur en % du plan (> 0)")
    h: float = Field(..., gt=0, le=100, description="Hauteur en % du plan (> 0)")

    @field_validator("nom")
    @classmethod
    def _nom(cls, value: str) -> str:
        return _texte(value)

    @field_validator("couleur")
    @classmethod
    def _couleur(cls, value: str) -> str:
        if not _COULEUR.match(value):
            raise ValueError("La couleur doit être au format #RRGGBB")
        return value.upper()

    @field_validator("x", "y", "w", "h")
    @classmethod
    def _arrondi(cls, value: float) -> float:
        return _deux_decimales(value)

    @model_validator(mode="after")
    def _geometrie(self):
        if self.x + self.w > 100 or self.y + self.h > 100:
            raise ValueError("La zone dépasse du plan : x + w et y + h doivent rester ≤ 100")
        return self


class ZoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    type: ZoneType
    couleur: str
    x: float
    y: float
    w: float
    h: float


# ------------------------------------------------------------------------ programmes
class EtapeProgramme(BaseModel):
    nom: str = Field(..., min_length=1, max_length=80)
    duree_min: int = Field(..., ge=1, le=720)

    @field_validator("nom")
    @classmethod
    def _nom(cls, value: str) -> str:
        return _texte(value)


class ProgrammeMachine(BaseModel):
    nom: str = Field(..., min_length=1, max_length=80)
    duree_min: int = Field(..., ge=1, le=720, description="Durée du programme en minutes")
    types_linge: List[str] = Field(
        default_factory=list,
        max_length=20,
        description='Ex. "coton", "delicat", "synthetique", "drap", "couette", "tout"',
    )
    intervention_humaine: bool = Field(
        False, description="Un opérateur doit intervenir pendant le cycle (semi-automatique)"
    )
    etapes: Optional[List[EtapeProgramme]] = Field(None, max_length=30)

    @field_validator("nom")
    @classmethod
    def _nom(cls, value: str) -> str:
        return _texte(value)

    @field_validator("types_linge")
    @classmethod
    def _types(cls, values: List[str]) -> List[str]:
        propres = []
        for value in values:
            value = value.strip()
            if not value or len(value) > 40:
                raise ValueError("Un type de linge fait de 1 à 40 caractères")
            if value not in propres:
                propres.append(value)
        return propres


# ----------------------------------------------------------------------------- machines
class MachineIn(BaseModel):
    """Champs de saisie d'une machine (création et modification ; jamais l'état)."""

    nom: str = Field(..., min_length=1, max_length=120)
    categorie: MachineCategorie
    marque: Optional[str] = Field(None, max_length=120)
    modele: Optional[str] = Field(None, max_length=120)
    numero_serie: Optional[str] = Field(None, max_length=120)
    type_fonctionnement: TypeFonctionnement = "automatique"
    capacite_kg: Decimal = Field(..., gt=0, le=200, decimal_places=2)
    programmes: List[ProgrammeMachine] = Field(default_factory=list, max_length=30)
    zone_id: Optional[uuid.UUID] = None
    position_x: Optional[float] = Field(None, ge=0, le=100)
    position_y: Optional[float] = Field(None, ge=0, le=100)
    conso_electrique_kwh_cycle: Optional[Decimal] = Field(None, ge=0, le=100000, decimal_places=3)
    conso_eau_litres_cycle: Optional[Decimal] = Field(None, ge=0, le=100000, decimal_places=2)
    date_mise_en_service: Optional[date] = None
    remarques: Optional[str] = Field(None, max_length=1000)
    contraintes: Optional[str] = Field(None, max_length=1000)

    @field_validator("nom")
    @classmethod
    def _nom(cls, value: str) -> str:
        return _texte(value)

    @field_validator("marque", "modele", "numero_serie", "remarques", "contraintes")
    @classmethod
    def _optionnels(cls, value: Optional[str]) -> Optional[str]:
        return _texte_optionnel(value)

    @field_validator("position_x", "position_y")
    @classmethod
    def _arrondi(cls, value: Optional[float]) -> Optional[float]:
        return _deux_decimales(value)

    @model_validator(mode="after")
    def _regles_metier(self):
        if self.categorie == "seche_linge" and not self.programmes:
            raise ValueError("Un sèche-linge doit avoir au moins un programme")
        if self.type_fonctionnement != "semi_automatique" and any(
            p.intervention_humaine for p in self.programmes
        ):
            raise ValueError(
                "Une intervention humaine n'est possible que sur une machine semi-automatique"
            )
        return self


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    categorie: MachineCategorie
    marque: Optional[str] = None
    modele: Optional[str] = None
    numero_serie: Optional[str] = None
    type_fonctionnement: TypeFonctionnement
    capacite_kg: Decimal
    programmes: List[ProgrammeMachine]
    zone_id: Optional[uuid.UUID] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    conso_electrique_kwh_cycle: Optional[Decimal] = None
    conso_eau_litres_cycle: Optional[Decimal] = None
    date_mise_en_service: Optional[date] = None
    remarques: Optional[str] = None
    contraintes: Optional[str] = None
    etat_operationnel: EtatOperationnel
    commande_courante_id: Optional[uuid.UUID] = None
    fin_estimee: Optional[datetime] = None
    actif: bool
    cree_le: datetime = Field(validation_alias="created_at")
    modifie_le: datetime = Field(validation_alias="updated_at")


class ChangementEtat(BaseModel):
    etat: EtatOperationnel
    motif: Optional[str] = Field(None, max_length=1000)

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: Optional[str]) -> Optional[str]:
        return _texte_optionnel(value)


# --------------------------------------------------------------------------- historique
class EvenementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: datetime = Field(validation_alias="date_evenement")
    type: EvenementType
    ancien_etat: Optional[EtatOperationnel] = None
    nouvel_etat: Optional[EtatOperationnel] = None
    motif: Optional[str] = None
    auteur_id: Optional[uuid.UUID] = None
    maintenance_id: Optional[uuid.UUID] = Field(
        None, description="Maintenance à l'origine de l'événement, s'il y en a une"
    )


class NoteIn(BaseModel):
    motif: str = Field(..., min_length=1, max_length=1000, description="Texte de la note")

    @field_validator("motif")
    @classmethod
    def _motif(cls, value: str) -> str:
        return _texte(value)


# -------------------------------------------------------------------------- maintenances
def _aware(value: Optional[datetime]) -> Optional[datetime]:
    """Une date sans fuseau est lue en UTC (jamais de comparaison naïf/aware)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class MaintenanceIn(BaseModel):
    type: MaintenanceType
    description: str = Field(..., min_length=1, max_length=1000)
    debut: Optional[datetime] = Field(None, description="Défaut : maintenant")
    fin: Optional[datetime] = Field(
        None, description="Absente : intervention ouverte, la machine passe en maintenance"
    )
    duree_estimee_min: Optional[int] = Field(
        None, ge=1, le=100_000, description="Durée prévue de l'indisponibilité, en minutes"
    )

    @field_validator("description")
    @classmethod
    def _description(cls, value: str) -> str:
        return _texte(value)

    @field_validator("debut", "fin")
    @classmethod
    def _fuseau(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _aware(value)

    @model_validator(mode="after")
    def _ordre(self):
        if self.debut and self.fin and self.fin < self.debut:
            raise ValueError("La fin de la maintenance précède son début")
        return self


class MaintenanceCloture(BaseModel):
    fin: Optional[datetime] = Field(None, description="Défaut : maintenant")

    @field_validator("fin")
    @classmethod
    def _fuseau(cls, value: Optional[datetime]) -> Optional[datetime]:
        return _aware(value)


class MaintenanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    machine_id: uuid.UUID
    type: MaintenanceType
    description: str
    debut: datetime
    fin: Optional[datetime] = None
    duree_estimee_min: Optional[int] = None
    indisponibilite_min: Optional[int] = Field(
        None, description="Indisponibilité mesurée = fin - debut, en minutes (null tant qu'ouverte)"
    )
    auteur_id: Optional[uuid.UUID] = None


# ------------------------------------------------------------------------------- plan
class PlanMachine(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    categorie: MachineCategorie
    type_fonctionnement: TypeFonctionnement
    etat_operationnel: EtatOperationnel
    zone_id: Optional[uuid.UUID] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    capacite_kg: Decimal
    actif: bool


class PlanOut(BaseModel):
    zones: List[ZoneOut]
    machines: List[PlanMachine]
