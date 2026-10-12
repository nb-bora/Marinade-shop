"""Cœur opérationnel du pressing : commandes, affectation des machines, caisse, clients,
tableau de bord, rapports.

Préfixe : ``/v1/restaurants/{restaurant_id}/pressing``. Tout l'espace n'existe que pour un
établissement de type ``pressing`` (404 sinon, garde ``require_pressing``).

Droits (``app/api/permissions.py``, aucun rôle en dur) :
- lecture, création de commande, paiements, affectation et libération d'affectation,
  démarrer/terminer/interrompre/prolonger/décharger, livraison, journal de caisse, clients,
  tableau de bord, rapports : ``perm.FRONT_OF_HOUSE`` (agent de comptoir et de chaîne :
  manager, serveur, caissier, hôte, barman) ;
- annulation d'une commande, annulation d'un paiement (contre-passation), clôture de caisse et
  livraison FORCÉE d'une commande impayée (``forcer=true``) : ``perm.MANAGEMENT`` ;
- la correction de tarif reste ``PUT /tarifs`` (management, lot tarification).
``CASH_DESK`` (manager + caissier) n'est pas utilisé pour les paiements : le contrat les confie
à tout le personnel de comptoir.

Erreurs : 404 introuvable / hors restaurant / pas un pressing, 409 transition interdite ou
machine occupée, 422 règle métier.
"""

import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api import permissions as perm
from app.api.dependencies import get_current_user, has_tenant_role, require_tenant_path
from app.api.pressing_dependencies import require_pressing
from app.core.database import get_db
from app.schemas.pressing_commandes import (
    PressingAffectationIn,
    AnnulationIn,
    PressingClientOut,
    PressingClotureIn,
    PressingClotureOut,
    PressingCommandeCreate,
    PressingCommandeListe,
    PressingCommandeOut,
    CommandeStatut,
    PressingCommandeUpdate,
    JournalCaisseOut,
    PressingLibererIn,
    PressingPaiementIn,
    PressingPaiementOut,
    PressingRapportOut,
    PressingRecommandationOut,
    PressingTableauDeBordOut,
)
from app.services import pressing_temps as temps
from app.services.pressing_calcul import PressingRegleError
from app.services.pressing_commande_service import PressingCommandeService
from app.services.pressing_tableau_service import PressingTableauService
from app.utils.exceptions import ConflictError, NotFoundError

router = APIRouter(
    prefix="/restaurants/{restaurant_id}/pressing",
    tags=["pressing-commandes"],
    dependencies=[Depends(require_tenant_path), Depends(require_pressing)],
)

_FOH = [Depends(perm.FRONT_OF_HOUSE)]
_MGMT = [Depends(perm.MANAGEMENT)]
_ERREURS = {
    404: {"description": "Introuvable, hors restaurant, ou l'établissement n'est pas un pressing."},
    409: {"description": "Transition interdite, machine occupée, doublon."},
    422: {"description": "Règle métier non respectée."},
}


@contextmanager
def _http_errors():
    """Traduit les exceptions métier en réponses HTTP (message en français)."""
    try:
        yield
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=exc.message)
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=exc.message)
    except PressingRegleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)


def _service(db: Session, restaurant_id: uuid.UUID, user) -> PressingCommandeService:
    return PressingCommandeService(db, restaurant_id, getattr(user, "id", None))


# ------------------------------------------------------------------------- commandes
@router.post(
    "/commandes",
    dependencies=_FOH,
    response_model=PressingCommandeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une commande",
    description="Le prix est calculé par le moteur de tarification (lignes figées). "
    "Le poids est obligatoire pour un lavage ou un séchage ; le séchage est refusé si le "
    "pressing ne le propose pas. Numéro `PR-AAAAMMJJ-NNN` (séquence du jour, fuseau Africa/Douala). "
    "`fin_estimee` reçoit une ESTIMATION initiale (`fin_estimee_source=estimation_initiale`) : "
    "fin de la meilleure option d'affectation de la première étape, plus le séchage le plus court "
    "si un séchage suit ; nulle si aucune machine ne convient. `paiement` (facultatif) encaisse au "
    "dépôt dans la même transaction : s'il est refusé (montant > total...), rien n'est créé.",
    responses={k: _ERREURS[k] for k in (404, 422)},
)
def create_commande(
    restaurant_id: uuid.UUID,
    body: PressingCommandeCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(db, restaurant_id, current_user)
    with _http_errors():
        return service.sortie(service.create_commande(body))


@router.get(
    "/commandes",
    dependencies=_FOH,
    response_model=PressingCommandeListe,
    summary="Lister les commandes",
    description="`q` cherche dans le numéro, le nom du client et son téléphone. "
    "Tri : plus récentes d'abord.",
    responses={404: _ERREURS[404]},
)
def list_commandes(
    restaurant_id: uuid.UUID,
    statut: Optional[CommandeStatut] = Query(None),
    q: Optional[str] = Query(None, max_length=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(db, restaurant_id, current_user)
    items, total = service.list_commandes(statut, q, skip, limit)
    return {"items": service.sorties(items), "total": total}


@router.get(
    "/commandes/{pressing_commande_id}",
    dependencies=_FOH,
    response_model=PressingCommandeOut,
    summary="Détail d'une commande (lignes figées et machines affectées)",
    responses={404: _ERREURS[404]},
)
def get_commande(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(db, restaurant_id, current_user)
    with _http_errors():
        return service.sortie(service.get_commande(pressing_commande_id))


@router.put(
    "/commandes/{pressing_commande_id}",
    dependencies=_FOH,
    response_model=PressingCommandeOut,
    summary="Modifier une commande (tant qu'elle est « reçue »)",
    description="Remplace poids, services, lignes, remise... Les lignes sont recalculées. "
    "409 dès que la commande a quitté le statut `recue`.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def update_commande(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    body: PressingCommandeUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(db, restaurant_id, current_user)
    with _http_errors():
        return service.sortie(service.update_commande(pressing_commande_id, body))


@router.post(
    "/commandes/{pressing_commande_id}/annuler",
    dependencies=_MGMT,
    response_model=PressingCommandeOut,
    summary="Annuler une commande (management, motif obligatoire)",
    description="Possible depuis `recue`, `en_attente_machine` et `attente_sechage`. Les machines "
    "réservées sont libérées. En lavage ou en séchage : 409 (terminer et décharger d'abord).",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def annuler_commande(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    body: AnnulationIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(db, restaurant_id, current_user)
    with _http_errors():
        return service.sortie(service.annuler(pressing_commande_id, body.motif))


@router.post(
    "/commandes/{pressing_commande_id}/pret",
    dependencies=_FOH,
    response_model=PressingCommandeOut,
    summary="Marquer prête une commande sans machine (articles seuls)",
    description="Réservé aux commandes sans lavage ni séchage (repassage, articles à l'unité). "
    "422 si la commande passe par les machines.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def marquer_pret(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(db, restaurant_id, current_user)
    with _http_errors():
        return service.sortie(service.marquer_pret(pressing_commande_id))


# ------------------------------------------------------------------ affectation
@router.post(
    "/commandes/{pressing_commande_id}/recommandation",
    dependencies=_FOH,
    response_model=PressingRecommandationOut,
    summary="Recommandation d'affectation de machines (aucune écriture)",
    description="Étape `lavage` pour une commande `recue`, `sechage` pour une commande en "
    "`attente_sechage` (ou `recue` en séchage seul) ; aussi une commande en attente de machine, "
    "en lavage ou en séchage tant qu'il reste de la charge à affecter (`charge_restante_kg`). "
    "Calculée sur la charge RESTANTE de l'étape. Jusqu'à 3 options classées (libres d'abord, puis "
    "score, plus petit = meilleur) : machine unique (meilleur ajustement de capacité, équilibrage), "
    "répartition si la charge dépasse la plus grande machine compatible, ou `partielle` (charges "
    "successives : la plus grande machine libre remplie à sa capacité, le reste à affecter après "
    "ce cycle) quand aucune machine libre ne peut tout prendre. Une machine occupée est proposée "
    "avec son `attente_min` mais ne peut pas être réservée. 409 si toute la charge est affectée.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def recommandation(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).recommandation(pressing_commande_id)


@router.post(
    "/commandes/{pressing_commande_id}/affectation",
    dependencies=_FOH,
    response_model=PressingCommandeOut,
    summary="Affecter des machines à la commande",
    description="`options_choisie` (index 0-2 de la recommandation) ou `machine_ids` ; `programmes` "
    "choisit le programme par machine. La recommandation est recalculée sous verrou : une machine "
    "déjà réservée ou en cycle -> 409. Les machines passent à `reservee` ; depuis `recue` ou "
    "`attente_sechage` la commande passe `en_attente_machine`, sinon (charges successives) son "
    "statut ne change pas. La charge affectée ne dépasse jamais la charge restante (409). Avec "
    "`machine_ids` dont la capacité cumulée est insuffisante : 422, sauf `accepter_partiel: true` "
    "(chaque machine remplie à sa capacité, le reste demeure à affecter).",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def affecter(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    body: PressingAffectationIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(db, restaurant_id, current_user)
    with _http_errors():
        return service.sortie(service.affecter(pressing_commande_id, body))


@router.post(
    "/commandes/{pressing_commande_id}/affectations/liberer",
    dependencies=_FOH,
    response_model=PressingCommandeOut,
    summary="Libérer des machines réservées (affectations non démarrées)",
    description="Libère les affectations actives NON DÉMARRÉES de l'étape courante (`ligne_ids` : "
    "identifiants de `machines[].id` ; absent : toutes). Chaque machine réservée pour la commande "
    "redevient `libre` et la charge redevient à affecter. S'il ne reste aucune affectation active "
    "sur l'étape, une commande `en_attente_machine` revient à `recue` (étape lavage, ou séchage "
    "seul ; estimation initiale recalculée) ou à `attente_sechage` (séchage après lavage). "
    "409 si rien n'est libérable (déjà démarré, terminé...), 404 si l'affectation n'existe pas.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def liberer_affectations(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    body: Optional[PressingLibererIn] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = _service(db, restaurant_id, current_user)
    body = body or PressingLibererIn()
    with _http_errors():
        return service.sortie(
            service.liberer(pressing_commande_id, body.ligne_ids, body.motif)
        )


# --------------------------------------------------------------------- paiements
@router.post(
    "/commandes/{pressing_commande_id}/paiements",
    dependencies=_FOH,
    response_model=PressingPaiementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Encaisser un paiement (partiel ou total)",
    description="422 « Le montant dépasse le reste à payer de X FCFA » ; 409 si la commande est annulée.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def payer(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    body: PressingPaiementIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).payer(pressing_commande_id, body)


@router.get(
    "/commandes/{pressing_commande_id}/paiements",
    dependencies=_FOH,
    response_model=List[PressingPaiementOut],
    summary="Paiements d'une commande",
    responses={404: _ERREURS[404]},
)
def list_paiements(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).list_paiements(pressing_commande_id)


@router.post(
    "/commandes/{pressing_commande_id}/paiements/{paiement_id}/annuler",
    dependencies=_MGMT,
    response_model=PressingPaiementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Annuler un paiement (management, motif obligatoire)",
    description="Remboursement ou correction traçable : écrit une contre-passation (montant "
    "négatif, même mode, `annule_paiement_id` = paiement annulé, référence « Annulation de … ») et "
    "la renvoie ; l'original reçoit `annule_le`, `annule_par`, `motif_annulation` ; `montant_paye` "
    "de la commande baisse d'autant. Le journal de caisse du jour de la contre-passation la compte "
    "en négatif dans son mode. Possible sur une commande annulée (remboursement). 409 : paiement "
    "déjà annulé, ou contre-passation (on n'annule pas une annulation).",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def annuler_paiement(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    paiement_id: uuid.UUID,
    body: AnnulationIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).annuler_paiement(
            pressing_commande_id, paiement_id, body.motif
        )


@router.post(
    "/commandes/{pressing_commande_id}/livrer",
    dependencies=_FOH,
    response_model=PressingCommandeOut,
    summary="Livrer une commande prête",
    description="409 si la commande n'est pas `pret`, ou s'il reste à payer. `forcer=true` livre "
    "malgré un reste à payer et écrit un audit « livraison forcée » : réservé au management "
    "(403 pour les autres rôles).",
    responses={
        **{k: _ERREURS[k] for k in (404, 409)},
        403: {"description": "`forcer=true` sans rôle de management."},
    },
)
def livrer(
    restaurant_id: uuid.UUID,
    pressing_commande_id: uuid.UUID,
    forcer: bool = Query(
        False, description="Livrer malgré un reste à payer (management seulement, audité)"
    ),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if forcer and not has_tenant_role(db, current_user, restaurant_id, perm.MANAGEMENT_ROLES):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Seul un responsable peut forcer la livraison d'une commande non soldée",
        )
    service = _service(db, restaurant_id, current_user)
    with _http_errors():
        return service.sortie(service.livrer(pressing_commande_id, forcer))


# ------------------------------------------------------------------------ caisse
@router.get(
    "/caisse/journal",
    dependencies=_FOH,
    response_model=JournalCaisseOut,
    summary="Journal de caisse d'un jour",
    description="`date` au format AAAA-MM-JJ (défaut : aujourd'hui, fuseau Africa/Douala). Totaux "
    "NETS : une contre-passation compte en négatif dans son mode. Les paiements restent acceptés "
    "après la clôture du jour ; `encaisse_apres_cloture` en donne le net.",
    responses={404: _ERREURS[404]},
)
def journal_caisse(
    restaurant_id: uuid.UUID,
    date_: Optional[date] = Query(None, alias="date"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(db, restaurant_id, current_user).journal(date_)


@router.post(
    "/caisse/clotures",
    dependencies=_MGMT,
    response_model=PressingClotureOut,
    status_code=status.HTTP_201_CREATED,
    summary="Clôturer la caisse d'un jour (management)",
    description="Une seule clôture par jour (409 sinon). `ecart` = montant compté - espèces attendues.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def cloturer_caisse(
    restaurant_id: uuid.UUID,
    body: PressingClotureIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).cloturer(body.date, body.montant_compte)


# ----------------------------------------------------------------------- clients
@router.get(
    "/clients",
    dependencies=_FOH,
    response_model=List[PressingClientOut],
    summary="Clients (dérivés des commandes)",
    description="Regroupés par téléphone, sinon par nom normalisé ; commandes annulées exclues.",
    responses={404: _ERREURS[404]},
)
def list_clients(
    restaurant_id: uuid.UUID,
    q: Optional[str] = Query(None, max_length=100),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(db, restaurant_id, current_user).clients(q, skip, limit)


# ----------------------------------------------------- tableau de bord et rapports
@router.get(
    "/tableau-de-bord",
    dependencies=_FOH,
    response_model=PressingTableauDeBordOut,
    summary="Tableau de bord du pressing",
    description="Champs `*_mesuree` : mesurés (horodatages réels) ; `*_estimee` : estimations. "
    "Finance : `source=transactions_pressing` ; `ca_*` = facturé (non annulé), "
    "`encaisse_jour` = paiements reçus (nets des contre-passations). Alertes (heures locales) : "
    "retard, panne, intervention, attente_dechargement (> 15 min, critique > 60), "
    "dechargement_tardif, reservation_non_demarree (> 15 min après le début prévu, critique > 45), "
    "prise_en_charge (commande reçue non affectée > 30 min, critique > 90), charge_restante "
    "(commande à réaffecter), sechage_en_attente (> 20 min après le dernier lavage, critique > 60), "
    "paiement_apres_cloture.",
    responses={404: _ERREURS[404]},
)
def tableau_de_bord(
    restaurant_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return PressingTableauService(db, restaurant_id).tableau_de_bord()


@router.get(
    "/rapports",
    dependencies=_FOH,
    response_model=PressingRapportOut,
    summary="Rapport d'activité sur une période",
    description="`du` / `au` (inclus, AAAA-MM-JJ, défaut : 30 derniers jours). Période max 366 jours "
    "(422 sinon).",
    responses={k: _ERREURS[k] for k in (404, 422)},
)
def rapports(
    restaurant_id: uuid.UUID,
    du: Optional[date] = Query(None),
    au: Optional[date] = Query(None),
    granularite: Literal["jour"] = Query("jour"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    au = au or temps.jour_local(temps.maintenant())
    du = du or (au - timedelta(days=29))
    with _http_errors():
        return PressingTableauService(db, restaurant_id).rapports(du, au)
