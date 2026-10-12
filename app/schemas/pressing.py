"""Schémas de la tarification pressing. Montants : entiers FCFA.

``quantite`` d'une ligne de calcul est un ``Decimal`` sérialisé en CHAÎNE (comme les autres
quantités de l'API) : « 4.000 » pour un lavage de 4 kg, « 2 » pour deux articles.
"""

import uuid
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PrixFcfa = Field(..., ge=0, le=100_000_000, description="Montant entier en FCFA")


def _nom_propre(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Le nom ne peut pas être vide")
    return value


class PressingArrondi(BaseModel):
    pas_grammes: Literal[1, 100, 500, 1000] = 1000
    mode: Literal["superieur", "proche"] = "superieur"


class PressingTarif(BaseModel):
    prix_kg: int = PrixFcfa
    prix_sechage_kg: Optional[int] = Field(
        None, ge=0, le=100_000_000, description="null : le séchage n'est pas proposé"
    )
    arrondi: PressingArrondi
    devise: Literal["FCFA"] = "FCFA"


class PressingTarifUpdate(BaseModel):
    prix_kg: int = PrixFcfa
    prix_sechage_kg: Optional[int] = Field(None, ge=0, le=100_000_000)
    arrondi: PressingArrondi
    devise: Literal["FCFA"] = "FCFA"


class PressingArticleBase(BaseModel):
    nom: str = Field(..., min_length=1, max_length=120)
    prix_unitaire: int = Field(..., ge=0, le=100_000_000)
    categorie: Optional[str] = Field(None, max_length=120)
    actif: bool = True

    @field_validator("nom")
    @classmethod
    def _nom(cls, value: str) -> str:
        return _nom_propre(value)

    @field_validator("categorie")
    @classmethod
    def _categorie(cls, value: Optional[str]) -> Optional[str]:
        return (value.strip() or None) if value is not None else None


class PressingArticleCreate(PressingArticleBase):
    pass


class PressingArticleUpdate(PressingArticleBase):
    pass


class PressingArticleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    prix_unitaire: int
    categorie: Optional[str] = None
    actif: bool


class PressingCombinaisonLigneCreate(BaseModel):
    article_id: uuid.UUID
    quantite: int = Field(..., ge=1, le=10_000)


class PressingCombinaisonLigneResponse(BaseModel):
    article_id: uuid.UUID
    article_nom: str
    quantite: int
    prix_unitaire_reference: int


class PressingCombinaisonBase(BaseModel):
    nom: str = Field(..., min_length=1, max_length=120)
    prix: int = Field(..., ge=0, le=100_000_000)
    lignes: List[PressingCombinaisonLigneCreate] = Field(..., min_length=1, max_length=50)
    actif: bool = True

    @field_validator("nom")
    @classmethod
    def _nom(cls, value: str) -> str:
        return _nom_propre(value)


class PressingCombinaisonCreate(PressingCombinaisonBase):
    pass


class PressingCombinaisonUpdate(PressingCombinaisonBase):
    pass


class PressingCombinaisonResponse(BaseModel):
    id: uuid.UUID
    nom: str
    prix: int
    actif: bool
    lignes: List[PressingCombinaisonLigneResponse]
    total_articles: int = Field(
        description="Somme des articles au prix unitaire : l'économie est total_articles - prix"
    )


class PressingCalculArticle(BaseModel):
    article_id: uuid.UUID
    quantite: int = Field(..., ge=1, le=10_000)


class PressingCalculCombinaison(BaseModel):
    combinaison_id: uuid.UUID
    quantite: int = Field(..., ge=1, le=10_000)


class PressingCalculRequest(BaseModel):
    poids_grams: Optional[int] = Field(
        None, ge=1, le=1_000_000, description="Grammes ; obligatoire si lavage ou séchage"
    )
    lavage: bool = True
    sechage: bool = False
    articles: List[PressingCalculArticle] = Field(default_factory=list, max_length=200)
    combinaisons: List[PressingCalculCombinaison] = Field(default_factory=list, max_length=200)
    remise_fcfa: int = Field(0, ge=0, le=1_000_000_000)


class PressingCalculLigne(BaseModel):
    type: Literal["lavage", "sechage", "article", "combinaison"]
    libelle: str
    quantite: Decimal = Field(description="kg (3 décimales) pour lavage/séchage, entier sinon")
    prix_unitaire: int
    montant: int


class PressingCalculResponse(BaseModel):
    poids_facturable_grams: Optional[int] = None
    lignes: List[PressingCalculLigne]
    sous_total: int
    remise_fcfa: int
    total: int
    devise: Literal["FCFA"] = "FCFA"
