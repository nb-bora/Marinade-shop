"""Espace pressing : zones, plan, machines (lave-linge / sèche-linge), états, maintenances, historique.

Préfixe : ``/v1/restaurants/{restaurant_id}/pressing``. Tout l'espace n'existe que pour un
établissement de type ``pressing`` (404 « Cet établissement n'est pas un pressing » sinon).

Droits (``app/api/permissions.py``, aucun rôle en dur) :
- lecture (zones, machines, plan, historique, maintenances) : ``perm.FRONT_OF_HOUSE`` ;
- toutes les écritures (zones, machines, changements d'état, maintenances, notes) :
  ``perm.MANAGEMENT`` ;
- ``demarrer`` / ``terminer`` / ``interrompre`` / ``prolonger`` / ``decharger`` (conduite d'un
  cycle par l'agent de chaîne) : ``perm.FRONT_OF_HOUSE``, via ``PressingCommandeService`` (qui
  passe par ``changer_etat``). ``permissions.py`` ne prévoit aucun ensemble de rôles dédié aux
  changements d'état courants des machines ; plutôt que d'ouvrir ``FRONT_OF_HOUSE`` (serveur,
  caissier...) à des écritures sur le parc de machines, tout reste au management. Le lot
  « commandes » changera les états par ``PressingMachineService.changer_etat`` (droit de la
  route de commande), pas par la route ``/etat``.

Erreurs : 404 introuvable / hors restaurant, 409 doublon ou transition interdite, 422 règle
métier, 204 aux suppressions et désactivations.
"""

import uuid
from contextlib import contextmanager
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api import permissions as perm
from app.api.dependencies import get_current_user, require_tenant_path
from app.api.pressing_dependencies import require_pressing
from app.core.database import get_db
from app.schemas.pressing_machines import (
    ChangementEtat,
    EtatOperationnel,
    EvenementOut,
    MachineCategorie,
    MachineIn,
    MachineOut,
    MaintenanceCloture,
    MaintenanceIn,
    MaintenanceOut,
    NoteIn,
    PlanOut,
    ZoneIn,
    ZoneOut,
)
from app.schemas.pressing_commandes import (
    DemarrageIn,
    PressingDechargementIn,
    PressingInterruptionIn,
    PressingMachineActionOut,
    PressingProlongationIn,
)
from app.services.pressing_calcul import PressingRegleError
from app.services.pressing_commande_service import PressingCommandeService
from app.services.pressing_machine_service import PressingMachineService
from app.utils.exceptions import ConflictError, NotFoundError

router = APIRouter(
    prefix="/restaurants/{restaurant_id}/pressing",
    tags=["pressing-machines"],
    dependencies=[Depends(require_tenant_path), Depends(require_pressing)],
)

_READ = [Depends(perm.FRONT_OF_HOUSE)]
_WRITE = [Depends(perm.MANAGEMENT)]
_ERREURS = {
    404: {"description": "Introuvable, hors restaurant, ou l'établissement n'est pas un pressing."},
    409: {"description": "Doublon, transition d'état interdite ou machine occupée."},
    422: {"description": "Règle métier non respectée."},
}


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


def _service(db: Session, restaurant_id: uuid.UUID, user) -> PressingMachineService:
    return PressingMachineService(db, restaurant_id, getattr(user, "id", None))


def _maintenance_out(maintenance) -> dict:
    return {
        "id": maintenance.id,
        "machine_id": maintenance.machine_id,
        "type": maintenance.type,
        "description": maintenance.description,
        "debut": maintenance.debut,
        "fin": maintenance.fin,
        "duree_estimee_min": maintenance.duree_estimee_min,
        "indisponibilite_min": PressingMachineService.indisponibilite_min(maintenance),
        "auteur_id": maintenance.auteur_id,
    }


# ------------------------------------------------------------------------------ zones
@router.get(
    "/zones",
    dependencies=_READ,
    response_model=List[ZoneOut],
    summary="Lister les zones du pressing",
    description="Zones du plan : x, y, w, h en pourcentages (0-100) du plan.",
    responses={404: _ERREURS[404]},
)
def list_zones(
    restaurant_id: uuid.UUID, current_user=Depends(get_current_user), db: Session = Depends(get_db)
):
    return _service(db, restaurant_id, current_user).list_zones()


@router.post(
    "/zones",
    dependencies=_WRITE,
    response_model=ZoneOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une zone",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def create_zone(
    restaurant_id: uuid.UUID,
    body: ZoneIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).create_zone(body)


@router.put(
    "/zones/{zone_id}",
    dependencies=_WRITE,
    response_model=ZoneOut,
    summary="Modifier une zone (nom, type, couleur, position et taille sur le plan)",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def update_zone(
    restaurant_id: uuid.UUID,
    zone_id: uuid.UUID,
    body: ZoneIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).update_zone(zone_id, body)


@router.delete(
    "/zones/{zone_id}",
    dependencies=_WRITE,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une zone",
    description="Refusé (409) tant que des machines y sont rattachées.",
    responses={404: _ERREURS[404], 409: _ERREURS[409]},
)
def delete_zone(
    restaurant_id: uuid.UUID,
    zone_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        _service(db, restaurant_id, current_user).delete_zone(zone_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------------- plan
@router.get(
    "/plan",
    dependencies=_READ,
    response_model=PlanOut,
    summary="Plan du pressing : zones et machines positionnées",
    description="Machines actives uniquement, sauf `inclure_inactives=true`. "
    "La mise en page se fait par `PUT /zones/{id}` et `PUT /machines/{id}`.",
    responses={404: _ERREURS[404]},
)
def get_plan(
    restaurant_id: uuid.UUID,
    inclure_inactives: bool = Query(False),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(db, restaurant_id, current_user).plan(inclure_inactives)


# --------------------------------------------------------------------------- machines
@router.get(
    "/machines",
    dependencies=_READ,
    response_model=List[MachineOut],
    summary="Lister les machines",
    responses={404: _ERREURS[404]},
)
def list_machines(
    restaurant_id: uuid.UUID,
    categorie: Optional[MachineCategorie] = Query(None),
    etat: Optional[EtatOperationnel] = Query(None),
    actif: Optional[bool] = Query(None, description="Filtre actif/inactif (absent : toutes)"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _service(db, restaurant_id, current_user).list_machines(categorie, etat, actif)


@router.post(
    "/machines",
    dependencies=_WRITE,
    response_model=MachineOut,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une machine",
    description="La machine est créée `libre` et active. Un sèche-linge exige au moins un "
    "programme ; une intervention humaine exige une machine semi-automatique.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def create_machine(
    restaurant_id: uuid.UUID,
    body: MachineIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).create_machine(body)


@router.get(
    "/machines/{machine_id}",
    dependencies=_READ,
    response_model=MachineOut,
    summary="Fiche d'une machine",
    responses={404: _ERREURS[404]},
)
def get_machine(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).get_machine(machine_id)


@router.put(
    "/machines/{machine_id}",
    dependencies=_WRITE,
    response_model=MachineOut,
    summary="Modifier une machine (champs de saisie, jamais l'état)",
    description="Remplace les champs de saisie. L'état opérationnel se change par `POST /{id}/etat`.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def update_machine(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    body: MachineIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).update_machine(machine_id, body)


@router.delete(
    "/machines/{machine_id}",
    dependencies=_WRITE,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Désactiver une machine",
    description="Désactivation (`actif=false`), jamais une suppression. Refusée (409) si la "
    "machine est `en_cycle` ou `reservee`.",
    responses={404: _ERREURS[404], 409: _ERREURS[409]},
)
def deactivate_machine(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        _service(db, restaurant_id, current_user).deactivate_machine(machine_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/machines/{machine_id}/etat",
    dependencies=_WRITE,
    response_model=MachineOut,
    summary="Changer l'état opérationnel d'une machine",
    description="""
Transitions autorisées :

- `libre` → `reservee`, `en_cycle`, `maintenance`, `hors_service`
- `reservee` → `libre`, `en_cycle`
- `en_cycle` → `cycle_termine`
- `cycle_termine` → `attente_dechargement`, `libre`
- `attente_dechargement` → `libre`
- `maintenance` → `libre`, `hors_service`
- `hors_service` → `libre`, `maintenance`

Autre transition : 409. Un motif est obligatoire pour `maintenance` et `hors_service` (422).
Chaque changement écrit un événement d'historique et une ligne d'audit.
""",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def change_etat(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    body: ChangementEtat,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).changer_etat(
            machine_id, body.etat, body.motif
        )


# ------------------------------------------------------------------------ historique
@router.get(
    "/machines/{machine_id}/historique",
    dependencies=_READ,
    response_model=List[EvenementOut],
    summary="Historique d'une machine (plus récent d'abord)",
    responses={404: _ERREURS[404]},
)
def get_historique(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).historique(machine_id, skip, limit)


@router.post(
    "/machines/{machine_id}/historique",
    dependencies=_WRITE,
    response_model=EvenementOut,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter une note à l'historique d'une machine",
    responses={404: _ERREURS[404], 422: _ERREURS[422]},
)
def add_note(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    body: NoteIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return _service(db, restaurant_id, current_user).ajouter_note(machine_id, body.motif)


# ---------------------------------------------------------------------- maintenances
@router.get(
    "/machines/{machine_id}/maintenances",
    dependencies=_READ,
    response_model=List[MaintenanceOut],
    summary="Maintenances d'une machine (plus récentes d'abord)",
    responses={404: _ERREURS[404]},
)
def list_maintenances(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        rows = _service(db, restaurant_id, current_user).list_maintenances(
            machine_id, skip, limit
        )
    return [_maintenance_out(m) for m in rows]


@router.post(
    "/machines/{machine_id}/maintenances",
    dependencies=_WRITE,
    response_model=MaintenanceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Déclarer une maintenance (entretien, panne, réparation)",
    description="Sans `fin` : la maintenance est ouverte et, si la machine est `libre` ou "
    "`hors_service`, elle passe en `maintenance`. Avec `fin` : la maintenance est seulement "
    "historisée, l'état ne change pas. `indisponibilite_min` = fin - debut (null tant qu'ouverte).",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def declare_maintenance(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    body: MaintenanceIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        maintenance = _service(db, restaurant_id, current_user).declarer_maintenance(
            machine_id, body
        )
    return _maintenance_out(maintenance)


@router.post(
    "/machines/maintenances/{maintenance_id}/cloture",
    dependencies=_WRITE,
    response_model=MaintenanceOut,
    summary="Clôturer une maintenance",
    description="Si la machine est en `maintenance` pour cette intervention, elle repasse "
    "`libre`. 409 si la maintenance est déjà clôturée ou si la machine a un cycle en cours.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def close_maintenance(
    restaurant_id: uuid.UUID,
    maintenance_id: uuid.UUID,
    body: Optional[MaintenanceCloture] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        maintenance = _service(db, restaurant_id, current_user).cloturer_maintenance(
            maintenance_id, body.fin if body else None
        )
    return _maintenance_out(maintenance)


# ------------------------------------------------------------- conduite d'un cycle
_OPERATE = [Depends(perm.FRONT_OF_HOUSE)]


@router.post(
    "/machines/{machine_id}/demarrer",
    dependencies=_OPERATE,
    response_model=PressingMachineActionOut,
    summary="Démarrer un cycle pour une commande",
    description="Machine `reservee` pour cette commande -> `en_cycle`. Machine `libre` sans "
    "affectation (départ direct) : affectation implicite de min(charge restante, capacité), ou de "
    "`charge_kg` s'il est fourni (422 s'il dépasse la capacité ou la charge restante). "
    "`fin_estimee` = maintenant + durée du programme (+10 min si intervention humaine). La "
    "commande passe en `en_lavage` / `en_sechage` (`fin_estimee_source=cycle`). "
    "409 si la machine est réservée pour une autre commande ou occupée, ou si toute la charge "
    "est déjà affectée.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def demarrer_machine(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    body: DemarrageIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return PressingCommandeService(
            db, restaurant_id, getattr(current_user, "id", None)
        ).demarrer(machine_id, body.commande_id, body.programme, body.charge_kg)


@router.post(
    "/machines/{machine_id}/terminer",
    dependencies=_OPERATE,
    response_model=PressingMachineActionOut,
    summary="Terminer le cycle en cours",
    description="`en_cycle` -> `cycle_termine`. Durée MESURÉE = fin réelle - début réel. La commande "
    "passe `attente_sechage` (lave-linge, séchage demandé) ou `pret` seulement quand toutes les "
    "machines de l'étape sont terminées ET qu'il ne reste plus de charge à traiter ; sinon son "
    "statut reste et elle est « à réaffecter » (`a_reaffecter`).",
    responses={k: _ERREURS[k] for k in (404, 409)},
)
def terminer_machine(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return PressingCommandeService(
            db, restaurant_id, getattr(current_user, "id", None)
        ).terminer(machine_id)


@router.post(
    "/machines/{machine_id}/interrompre",
    dependencies=_OPERATE,
    response_model=PressingMachineActionOut,
    summary="Interrompre le cycle en cours (panne, coupure, erreur de programme)",
    description="`en_cycle` -> `cycle_termine` (motif obligatoire, journalisé). L'affectation reçoit "
    "`fin_reelle` = `interrompue_le` = maintenant et `motif_interruption`. `charge_traitee=false` "
    "(défaut) : l'affectation devient inactive et sa charge redevient à affecter (réaffectable "
    "sur une autre machine) ; `true` : la charge compte comme faite. L'étape avance comme pour "
    "`terminer`. La machine se libère au déchargement (`/decharger`, éventuellement vers la "
    "maintenance). 409 si la machine n'est pas en cycle.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def interrompre_machine(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    body: PressingInterruptionIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return PressingCommandeService(
            db, restaurant_id, getattr(current_user, "id", None)
        ).interrompre(machine_id, body.motif, body.charge_traitee)


@router.post(
    "/machines/{machine_id}/prolonger",
    dependencies=_OPERATE,
    response_model=PressingMachineActionOut,
    summary="Prolonger le cycle en cours",
    description="Machine `en_cycle` uniquement (409 sinon). Décale de `minutes` (1 à 240) la fin "
    "estimée de la machine et la fin prévue de l'affectation ; la fin estimée de la commande "
    "devient la plus tardive des affectations en cours. Note « Cycle prolongé de N min : motif » "
    "dans l'historique de la machine, et audit.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def prolonger_machine(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    body: PressingProlongationIn,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return PressingCommandeService(
            db, restaurant_id, getattr(current_user, "id", None)
        ).prolonger(machine_id, body.minutes, body.motif)


@router.post(
    "/machines/{machine_id}/decharger",
    dependencies=_OPERATE,
    response_model=PressingMachineActionOut,
    summary="Décharger la machine (un seul appel)",
    description="Depuis `cycle_termine` ou `attente_dechargement` -> `libre` (les transitions "
    "`cycle_termine` -> `attente_dechargement` -> `libre` sont journalisées dans l'ordre) ; "
    "`dechargee_le` horodaté. Corps facultatif : `apres` = `maintenance` ou `hors_service` laisse "
    "ensuite la machine dans cet état (motif obligatoire) ; `maintenance` {type, description} "
    "déclare en plus une maintenance ouverte (`maintenance_id` dans la réponse). 409 si la machine "
    "n'est pas à décharger.",
    responses={k: _ERREURS[k] for k in (404, 409, 422)},
)
def decharger_machine(
    restaurant_id: uuid.UUID,
    machine_id: uuid.UUID,
    body: Optional[PressingDechargementIn] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with _http_errors():
        return PressingCommandeService(
            db, restaurant_id, getattr(current_user, "id", None)
        ).decharger(machine_id, body)
