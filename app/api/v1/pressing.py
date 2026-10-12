"""Tarification d'un pressing : tarifs, articles, combinaisons, calcul, import/modèle.

Préfixe : ``/v1/restaurants/{restaurant_id}/pressing``. Lecture et calcul : service en salle
et caisse (``perm.FRONT_OF_HOUSE``, qui inclut la caisse) ; écritures et import : management.
Erreurs : 404 introuvable / hors restaurant, 409 nom en double, 422 règle métier,
400 fichier d'import inutilisable, 413 fichier trop gros, 429 import trop fréquent.
"""

import uuid
from contextlib import contextmanager
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api import permissions as perm
from app.api.dependencies import get_current_user, require_tenant_path
from app.api.v1.restaurants import _enforce_import_rate_limit, _read_upload, _XLSX_MEDIA_TYPE
from app.core.database import get_db
from app.repositories.ros_repository import RosAuditLogRepository
from app.schemas.pressing import (
    PressingArticleCreate,
    PressingArticleResponse,
    PressingArticleUpdate,
    PressingCalculRequest,
    PressingCalculResponse,
    PressingCombinaisonCreate,
    PressingCombinaisonResponse,
    PressingCombinaisonUpdate,
    PressingTarif,
    PressingTarifUpdate,
)
from app.schemas.restaurant import CatalogImportResponse
from app.services import pressing_io_service as pressing_io
from app.services.catalog_io_service import FileFormatError
from app.services.pressing_calcul import DemandeCalcul, PressingRegleError
from app.services.pressing_service import PressingService
from app.utils.exceptions import ConflictError, NotFoundError
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/restaurants/{restaurant_id}/pressing",
    tags=["pressing"],
    dependencies=[Depends(require_tenant_path)],
)

_READ = [Depends(perm.FRONT_OF_HOUSE)]
_WRITE = [Depends(perm.MANAGEMENT)]
_TYPE_PATTERN = "^(articles|combinaisons)$"


@contextmanager
def _http_errors():
    """Traduit les exceptions métier du service en réponses HTTP (message en français)."""
    try:
        yield
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.message)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.message)
    except PressingRegleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    except FileFormatError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _service(db: Session, restaurant_id: uuid.UUID, user) -> PressingService:
    return PressingService(db, restaurant_id, getattr(user, "id", None))


def _tarif_response(tarif) -> dict:
    return {**PressingService.tarif_state(tarif), "devise": "FCFA"}


def _combinaison_response(combinaison) -> dict:
    lignes = [
        {
            "article_id": l.article_id,
            "article_nom": l.article_nom,
            "quantite": l.quantite,
            "prix_unitaire_reference": l.prix_unitaire_reference,
        }
        for l in combinaison.lignes_cache
    ]
    return {
        "id": combinaison.id,
        "nom": combinaison.nom,
        "prix": combinaison.prix,
        "actif": combinaison.actif,
        "lignes": lignes,
        "total_articles": sum(l["quantite"] * l["prix_unitaire_reference"] for l in lignes),
    }


# ----------------------------------------------------------------------- tarifs
@router.get(
    "/tarifs",
    dependencies=_READ,
    response_model=PressingTarif,
    summary="Tarifs du pressing",
    description="Prix au kilo, prix du séchage (`null` : non proposé) et règle d'arrondi du poids. "
    "La ligne est créée avec les défauts (500 FCFA/kg, pas 1000 g, supérieur) à la première lecture.",
)
def get_tarifs(
    restaurant_id: uuid.UUID, current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    return _tarif_response(_service(db, restaurant_id, current_user).get_tarif())


@router.put(
    "/tarifs",
    dependencies=_WRITE,
    response_model=PressingTarif,
    summary="Modifier les tarifs du pressing",
    description="Réservé au management. Chaque modification est journalisée (ancienne et nouvelle valeur).",
)
def put_tarifs(
    restaurant_id: uuid.UUID,
    body: PressingTarifUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        tarif = _service(db, restaurant_id, current_user).update_tarif(
            body.prix_kg, body.prix_sechage_kg, body.arrondi.pas_grammes, body.arrondi.mode
        )
    return _tarif_response(tarif)


# --------------------------------------------------------------------- articles
@router.get(
    "/articles",
    dependencies=_READ,
    response_model=List[PressingArticleResponse],
    summary="Lister les articles unitaires",
)
def list_articles(
    restaurant_id: uuid.UUID,
    actif: Optional[bool] = Query(None, description="Filtre actif/inactif (absent : tous)"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(db, restaurant_id, current_user).list_articles(actif)


@router.post(
    "/articles",
    dependencies=_WRITE,
    response_model=PressingArticleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un article unitaire",
    responses={409: {"description": "Un article porte déjà ce nom (casse ignorée)."}},
)
def create_article(
    restaurant_id: uuid.UUID,
    body: PressingArticleCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).create_article(
            body.nom, body.prix_unitaire, body.categorie, body.actif
        )


@router.get(
    "/articles/{pressing_article_id}",
    dependencies=_READ,
    response_model=PressingArticleResponse,
    summary="Détail d'un article",
)
def get_article(
    restaurant_id: uuid.UUID,
    pressing_article_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).get_article(pressing_article_id)


@router.put(
    "/articles/{pressing_article_id}",
    dependencies=_WRITE,
    response_model=PressingArticleResponse,
    summary="Modifier un article (permet aussi de le réactiver)",
    responses={409: {"description": "Un autre article porte déjà ce nom."}},
)
def update_article(
    restaurant_id: uuid.UUID,
    pressing_article_id: uuid.UUID,
    body: PressingArticleUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).update_article(
            pressing_article_id, body.nom, body.prix_unitaire, body.categorie, body.actif
        )


@router.delete(
    "/articles/{pressing_article_id}",
    dependencies=_WRITE,
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Désactiver un article",
    description="Ne supprime rien : `actif` passe à `false`. L'article ne peut plus entrer dans un "
    "calcul ni une nouvelle combinaison, mais reste lisible dans les combinaisons existantes.",
)
def delete_article(
    restaurant_id: uuid.UUID,
    pressing_article_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        _service(db, restaurant_id, current_user).deactivate_article(pressing_article_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- combinaisons
@router.get(
    "/combinaisons",
    dependencies=_READ,
    response_model=List[PressingCombinaisonResponse],
    summary="Lister les combinaisons",
)
def list_combinaisons(
    restaurant_id: uuid.UUID, current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    return [
        _combinaison_response(c)
        for c in _service(db, restaurant_id, current_user).list_combinaisons()
    ]


@router.post(
    "/combinaisons",
    dependencies=_WRITE,
    response_model=PressingCombinaisonResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Composer une combinaison à prix fixé",
    description="Le prix est celui que l'utilisateur fixe, indépendant de la somme des articles. "
    "Chaque article doit appartenir au restaurant et être actif.",
    responses={
        409: {"description": "Une combinaison porte déjà ce nom."},
        422: {"description": "Article introuvable, désactivé ou en double."},
    },
)
def create_combinaison(
    restaurant_id: uuid.UUID,
    body: PressingCombinaisonCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        combinaison = _service(db, restaurant_id, current_user).create_combinaison(
            body.nom, body.prix, [(l.article_id, l.quantite) for l in body.lignes], body.actif
        )
    return _combinaison_response(combinaison)


@router.get(
    "/combinaisons/{pressing_combinaison_id}",
    dependencies=_READ,
    response_model=PressingCombinaisonResponse,
    summary="Détail d'une combinaison",
)
def get_combinaison(
    restaurant_id: uuid.UUID,
    pressing_combinaison_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _combinaison_response(
            _service(db, restaurant_id, current_user).get_combinaison(pressing_combinaison_id)
        )


@router.put(
    "/combinaisons/{pressing_combinaison_id}",
    dependencies=_WRITE,
    response_model=PressingCombinaisonResponse,
    summary="Modifier une combinaison (les lignes sont remplacées)",
    responses={409: {"description": "Une autre combinaison porte déjà ce nom."}},
)
def update_combinaison(
    restaurant_id: uuid.UUID,
    pressing_combinaison_id: uuid.UUID,
    body: PressingCombinaisonUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        combinaison = _service(db, restaurant_id, current_user).update_combinaison(
            pressing_combinaison_id,
            body.nom,
            body.prix,
            [(l.article_id, l.quantite) for l in body.lignes],
            body.actif,
        )
    return _combinaison_response(combinaison)


@router.delete(
    "/combinaisons/{pressing_combinaison_id}",
    dependencies=_WRITE,
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Désactiver une combinaison",
)
def delete_combinaison(
    restaurant_id: uuid.UUID,
    pressing_combinaison_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        _service(db, restaurant_id, current_user).deactivate_combinaison(pressing_combinaison_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------- calcul
@router.post(
    "/calcul",
    dependencies=_READ,
    response_model=PressingCalculResponse,
    summary="Aperçu du prix d'une commande (aucune écriture)",
    description="Poids facturable arrondi selon le tarif, lavage/séchage au kilo, articles à "
    "l'unité, combinaisons au prix fixé, remise. Montants entiers FCFA (demi vers le haut). "
    "`quantite` est une chaîne décimale : kg à 3 décimales pour lavage/séchage, entier sinon.",
    responses={
        422: {
            "description": "Poids absent, séchage non proposé, article/combinaison inactif ou "
            "d'un autre restaurant, remise supérieure au sous-total, aucune ligne."
        }
    },
)
def calcul(
    restaurant_id: uuid.UUID,
    body: PressingCalculRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    demande = DemandeCalcul(
        poids_grams=body.poids_grams,
        lavage=body.lavage,
        sechage=body.sechage,
        articles=[(a.article_id, a.quantite) for a in body.articles],
        combinaisons=[(c.combinaison_id, c.quantite) for c in body.combinaisons],
        remise_fcfa=body.remise_fcfa,
    )
    with _http_errors():
        return _service(db, restaurant_id, current_user).calculer(demande)


# ------------------------------------------------------------- modèle et import
@router.get(
    "/modele",
    dependencies=_WRITE,
    response_class=Response,
    summary="Modèle Excel vierge (articles ou combinaisons)",
    description="Articles : `nom, prix_unitaire, categorie`. Combinaisons : `nom, prix, "
    "article_1, quantite_1 … article_5, quantite_5` (noms d'articles actifs du restaurant).",
    responses={200: {"description": "Classeur Excel.", "content": {_XLSX_MEDIA_TYPE: {}}}},
)
def modele(import_type: str = Query(..., alias="type", pattern=_TYPE_PATTERN)):
    with _http_errors():
        content = pressing_io.template_xlsx(import_type)
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="modele-pressing-{import_type}.xlsx"'},
    )


@router.post(
    "/import",
    dependencies=_WRITE,
    response_model=CatalogImportResponse,
    summary="Importer des articles ou des combinaisons (XLSX ou CSV `;`)",
    description="Idempotent par nom (casse ignorée), partiel (les lignes valides passent, les autres "
    "sont listées dans `errors`). Limites : 5 Mo, 5000 lignes, 1 import par minute et par restaurant "
    "(429 + `Retry-After`). Les articles d'une combinaison sont désignés par leur nom : importez "
    "d'abord les articles.",
    responses={
        400: {"description": "Fichier inutilisable (extension, en-tête, encodage)."},
        413: {"description": "Fichier de plus de 5 Mo."},
        429: {"description": "Un import a déjà eu lieu dans la dernière minute."},
    },
)
def import_pressing(
    restaurant_id: uuid.UUID,
    file: UploadFile = File(...),
    import_type: str = Query(..., alias="type", pattern=_TYPE_PATTERN),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = (file.filename or "").lower()
    if filename.endswith(".xlsx"):
        file_format = "xlsx"
    elif filename.endswith(".csv"):
        file_format = "csv"
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Format de fichier attendu : .xlsx ou .csv"
        )
    content = _read_upload(file)
    _enforce_import_rate_limit(
        db, restaurant_id, action=pressing_io.ACTION_IMPORT, lock_prefix="pressing_import"
    )
    with _http_errors():
        result = pressing_io.import_rows(
            db, restaurant_id, current_user.id, content, file_format, import_type
        )
    RosAuditLogRepository(db).log_action(
        restaurant_id=restaurant_id,
        action=pressing_io.ACTION_IMPORT,
        entity_name="Restaurant",
        entity_id=restaurant_id,
        actor_id=current_user.id,
        after_state={
            "format": file_format,
            "type": import_type,
            "created": result.created,
            "updated": result.updated,
            "errors": len(result.errors),
        },
    )
    logger.info(
        "Import pressing (%s/%s) restaurant=%s user=%s created=%s updated=%s errors=%s",
        file_format, import_type, restaurant_id, current_user.id,
        result.created, result.updated, len(result.errors),
    )  # fmt: skip
    return result.as_dict()
