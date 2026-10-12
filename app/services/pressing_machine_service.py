"""Espace pressing : zones, machines, états opérationnels, maintenances, historique, plan.

Couche service (accès base + journal d'audit ``ros_audit_logs``). Le service ne valide jamais
de commit : la requête s'en charge. Toute méthode est limitée au restaurant du service.

Erreurs : ``NotFoundError`` (404), ``ConflictError`` / ``TransitionInterdite`` (409),
``PressingRegleError`` (422).

Pour le lot « commandes » : ``changer_etat`` est la seule porte d'entrée pour modifier
``etat_operationnel`` (transition vérifiée, événement écrit, audit écrit). Il accepte
``commande_courante_id`` / ``fin_estimee`` pour poser ou libérer la commande en cours.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.pressing import (
    PressingMachine,
    PressingMachineEvenement,
    PressingMaintenance,
    PressingZone,
)
from app.repositories.ros_repository import RosAuditLogRepository
from app.schemas.pressing_machines import MachineIn, MaintenanceIn, ZoneIn
from app.services import pressing_machine_etats as etats
from app.services.pressing_calcul import PressingRegleError
from app.utils.exceptions import ConflictError, NotFoundError

_UNSET = object()
# Cycle en cours : la machine travaille, on ne clôt pas une maintenance dessus.
_ETATS_CYCLE_EN_COURS = frozenset({"en_cycle"})


def _num(value):
    return None if value is None else str(value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PressingMachineService:
    def __init__(self, db: Session, restaurant_id: uuid.UUID, actor_id=None):
        self.db = db
        self.restaurant_id = restaurant_id
        self.actor_id = actor_id
        self._audit = RosAuditLogRepository(db)

    # ------------------------------------------------------------------ audit
    def _log(self, action, entity_name, entity_id, before, after, reason=None):
        self._audit.log_action(
            restaurant_id=self.restaurant_id,
            action=action,
            entity_name=entity_name,
            entity_id=entity_id,
            actor_id=self.actor_id,
            before_state=before,
            after_state=after,
            reason=reason,
        )

    def _flush_unique(self, obj, message_par_contrainte: dict, defaut: str) -> None:
        """Flush dans un point de sauvegarde : un doublon concurrent devient un 409 propre."""
        try:
            with self.db.begin_nested():
                self.db.add(obj)
                self.db.flush()
        except IntegrityError as exc:
            texte = str(exc.orig)
            for contrainte, message in message_par_contrainte.items():
                if contrainte in texte:
                    raise ConflictError(message) from exc
            raise ConflictError(defaut) from exc

    # ------------------------------------------------------------------ zones
    @staticmethod
    def zone_state(zone: PressingZone) -> dict:
        return {
            "nom": zone.nom,
            "type": zone.type,
            "couleur": zone.couleur,
            "x": _num(zone.x),
            "y": _num(zone.y),
            "w": _num(zone.w),
            "h": _num(zone.h),
        }

    def list_zones(self) -> List[PressingZone]:
        return (
            self.db.query(PressingZone)
            .filter(PressingZone.restaurant_id == self.restaurant_id)
            .order_by(func.lower(PressingZone.nom), PressingZone.id)
            .all()
        )

    def get_zone(self, zone_id: uuid.UUID) -> PressingZone:
        zone = (
            self.db.query(PressingZone)
            .filter(
                PressingZone.id == zone_id, PressingZone.restaurant_id == self.restaurant_id
            )
            .first()
        )
        if zone is None:
            raise NotFoundError("Zone introuvable")
        return zone

    def _zone_by_name(self, nom: str) -> Optional[PressingZone]:
        return (
            self.db.query(PressingZone)
            .filter(
                PressingZone.restaurant_id == self.restaurant_id,
                func.lower(PressingZone.nom) == nom.lower(),
            )
            .first()
        )

    def create_zone(self, data: ZoneIn) -> PressingZone:
        message = f"Une zone nommée « {data.nom} » existe déjà"
        if self._zone_by_name(data.nom) is not None:
            raise ConflictError(message)
        zone = PressingZone(restaurant_id=self.restaurant_id, **data.model_dump())
        self._flush_unique(zone, {}, message)
        self.db.refresh(zone)
        self._log("PRESSING_ZONE_CREATE", "PressingZone", zone.id, None, self.zone_state(zone))
        return zone

    def update_zone(self, zone_id: uuid.UUID, data: ZoneIn) -> PressingZone:
        zone = self.get_zone(zone_id)
        message = f"Une zone nommée « {data.nom} » existe déjà"
        other = self._zone_by_name(data.nom)
        if other is not None and other.id != zone.id:
            raise ConflictError(message)
        before = self.zone_state(zone)
        for champ, valeur in data.model_dump().items():
            setattr(zone, champ, valeur)
        self._flush_unique(zone, {}, message)
        self.db.refresh(zone)
        self._log("PRESSING_ZONE_UPDATE", "PressingZone", zone.id, before, self.zone_state(zone))
        return zone

    def delete_zone(self, zone_id: uuid.UUID) -> None:
        zone = self.get_zone(zone_id)
        rattachees = (
            self.db.query(func.count(PressingMachine.id))
            .filter(
                PressingMachine.restaurant_id == self.restaurant_id,
                PressingMachine.zone_id == zone.id,
            )
            .scalar()
        )
        if rattachees:
            raise ConflictError(
                f"Impossible de supprimer la zone « {zone.nom} » : "
                f"{rattachees} machine(s) y sont rattachée(s)"
            )
        before = self.zone_state(zone)
        try:
            with self.db.begin_nested():
                self.db.delete(zone)
                self.db.flush()
        except IntegrityError as exc:  # machine rattachée entre-temps
            raise ConflictError(
                f"Impossible de supprimer la zone « {zone.nom} » : des machines y sont rattachées"
            ) from exc
        self._log("PRESSING_ZONE_DELETE", "PressingZone", zone_id, before, None)

    # --------------------------------------------------------------- machines
    @staticmethod
    def machine_state(machine: PressingMachine) -> dict:
        return {
            "nom": machine.nom,
            "categorie": machine.categorie,
            "marque": machine.marque,
            "modele": machine.modele,
            "numero_serie": machine.numero_serie,
            "type_fonctionnement": machine.type_fonctionnement,
            "capacite_kg": _num(machine.capacite_kg),
            "programmes": machine.programmes,
            "zone_id": str(machine.zone_id) if machine.zone_id else None,
            "position_x": _num(machine.position_x),
            "position_y": _num(machine.position_y),
            "conso_electrique_kwh_cycle": _num(machine.conso_electrique_kwh_cycle),
            "conso_eau_litres_cycle": _num(machine.conso_eau_litres_cycle),
            "date_mise_en_service": (
                machine.date_mise_en_service.isoformat() if machine.date_mise_en_service else None
            ),
            "remarques": machine.remarques,
            "contraintes": machine.contraintes,
            "etat_operationnel": machine.etat_operationnel,
            "actif": machine.actif,
        }

    def list_machines(
        self,
        categorie: Optional[str] = None,
        etat: Optional[str] = None,
        actif: Optional[bool] = None,
    ) -> List[PressingMachine]:
        query = self.db.query(PressingMachine).filter(
            PressingMachine.restaurant_id == self.restaurant_id
        )
        if categorie is not None:
            query = query.filter(PressingMachine.categorie == categorie)
        if etat is not None:
            query = query.filter(PressingMachine.etat_operationnel == etat)
        if actif is not None:
            query = query.filter(PressingMachine.actif.is_(actif))
        return query.order_by(func.lower(PressingMachine.nom), PressingMachine.id).all()

    def get_machine(self, machine_id: uuid.UUID, for_update: bool = False) -> PressingMachine:
        query = self.db.query(PressingMachine).filter(
            PressingMachine.id == machine_id,
            PressingMachine.restaurant_id == self.restaurant_id,
        )
        if for_update:
            query = query.with_for_update()
        machine = query.first()
        if machine is None:
            raise NotFoundError("Machine introuvable")
        return machine

    def _machine_conflicts(self, data: MachineIn, exclude_id: Optional[uuid.UUID]) -> None:
        base = self.db.query(PressingMachine.id).filter(
            PressingMachine.restaurant_id == self.restaurant_id
        )
        if exclude_id is not None:
            base = base.filter(PressingMachine.id != exclude_id)
        if base.filter(func.lower(PressingMachine.nom) == data.nom.lower()).first():
            raise ConflictError(f"Une machine nommée « {data.nom} » existe déjà")
        if (
            data.numero_serie
            and base.filter(
                func.lower(PressingMachine.numero_serie) == data.numero_serie.lower()
            ).first()
        ):
            raise ConflictError(
                f"Une machine avec le numéro de série « {data.numero_serie} » existe déjà"
            )

    def _check_zone(self, zone_id: Optional[uuid.UUID]) -> None:
        if zone_id is None:
            return
        existe = (
            self.db.query(PressingZone.id)
            .filter(
                PressingZone.id == zone_id, PressingZone.restaurant_id == self.restaurant_id
            )
            .first()
        )
        if existe is None:
            raise PressingRegleError(f"Zone introuvable pour ce restaurant : {zone_id}")

    @staticmethod
    def _valeurs(data: MachineIn) -> dict:
        valeurs = data.model_dump(exclude={"programmes"})
        valeurs["programmes"] = [
            p.model_dump(mode="json", exclude_none=True) for p in data.programmes
        ]
        return valeurs

    _CONTRAINTES = {
        "uq_pressing_machine_serie": "Une machine avec ce numéro de série existe déjà",
        "uq_pressing_machine_nom": "Une machine avec ce nom existe déjà",
    }

    def create_machine(self, data: MachineIn) -> PressingMachine:
        self._check_zone(data.zone_id)
        self._machine_conflicts(data, None)
        machine = PressingMachine(
            restaurant_id=self.restaurant_id,
            etat_operationnel="libre",
            actif=True,
            **self._valeurs(data),
        )
        self._flush_unique(machine, self._CONTRAINTES, "Cette machine existe déjà")
        self.db.refresh(machine)
        self._log(
            "PRESSING_MACHINE_CREATE", "PressingMachine", machine.id, None,
            self.machine_state(machine),
        )
        return machine

    def update_machine(self, machine_id: uuid.UUID, data: MachineIn) -> PressingMachine:
        machine = self.get_machine(machine_id, for_update=True)
        self._check_zone(data.zone_id)
        self._machine_conflicts(data, machine.id)
        before = self.machine_state(machine)
        for champ, valeur in self._valeurs(data).items():
            setattr(machine, champ, valeur)
        self._flush_unique(machine, self._CONTRAINTES, "Cette machine existe déjà")
        self.db.refresh(machine)
        self._log(
            "PRESSING_MACHINE_UPDATE", "PressingMachine", machine.id, before,
            self.machine_state(machine),
        )
        return machine

    def deactivate_machine(self, machine_id: uuid.UUID) -> None:
        machine = self.get_machine(machine_id, for_update=True)
        if not machine.actif:
            return
        if machine.etat_operationnel in etats.ETATS_OCCUPES:
            raise ConflictError(
                f"Impossible de désactiver la machine « {machine.nom} » : elle est "
                f"{etats.LIBELLES[machine.etat_operationnel]}"
            )
        before = self.machine_state(machine)
        machine.actif = False
        self.db.flush()
        self._log(
            "PRESSING_MACHINE_DEACTIVATE", "PressingMachine", machine.id, before,
            self.machine_state(machine),
        )

    # ------------------------------------------------------------------ états
    def _evenement(
        self, machine, type_, ancien=None, nouveau=None, motif=None, maintenance_id=None
    ) -> PressingMachineEvenement:
        evenement = PressingMachineEvenement(
            restaurant_id=self.restaurant_id,
            machine_id=machine.id,
            type=type_,
            ancien_etat=ancien,
            nouvel_etat=nouveau,
            motif=motif,
            maintenance_id=maintenance_id,
            auteur_id=self.actor_id,
            date_evenement=_now(),
        )
        self.db.add(evenement)
        self.db.flush()
        return evenement

    def changer_etat(
        self,
        machine_id: uuid.UUID,
        etat: str,
        motif: Optional[str] = None,
        *,
        maintenance_id: Optional[uuid.UUID] = None,
        commande_courante_id=_UNSET,
        fin_estimee=_UNSET,
        _machine: Optional[PressingMachine] = None,
        _type: str = "etat_change",
        verifier_actif: bool = True,
    ) -> PressingMachine:
        """Applique une transition autorisée, écrit l'événement et l'audit."""
        machine = _machine or self.get_machine(machine_id, for_update=True)
        if verifier_actif and not machine.actif:
            raise ConflictError(f"La machine « {machine.nom} » est désactivée")
        ancien = machine.etat_operationnel
        etats.verifier_transition(ancien, etat, motif)
        before = self.machine_state(machine)
        machine.etat_operationnel = etat
        if commande_courante_id is not _UNSET:
            machine.commande_courante_id = commande_courante_id
        if fin_estimee is not _UNSET:
            machine.fin_estimee = fin_estimee
        if etat == "libre":
            machine.commande_courante_id = None
            machine.fin_estimee = None
        self.db.flush()
        self._evenement(
            machine, _type, ancien, etat, motif, maintenance_id=maintenance_id
        )
        self._log(
            "PRESSING_MACHINE_ETAT", "PressingMachine", machine.id, before,
            self.machine_state(machine), reason=motif,
        )
        self.db.refresh(machine)
        return machine

    def ajouter_note(self, machine_id: uuid.UUID, texte: str) -> PressingMachineEvenement:
        machine = self.get_machine(machine_id)
        evenement = self._evenement(machine, "note", motif=texte)
        self._log(
            "PRESSING_MACHINE_NOTE", "PressingMachine", machine.id, None,
            {"motif": texte}, reason=texte,
        )
        return evenement

    def historique(
        self, machine_id: uuid.UUID, skip: int = 0, limit: int = 50
    ) -> List[PressingMachineEvenement]:
        machine = self.get_machine(machine_id)
        return (
            self.db.query(PressingMachineEvenement)
            .filter(
                PressingMachineEvenement.restaurant_id == self.restaurant_id,
                PressingMachineEvenement.machine_id == machine.id,
            )
            .order_by(
                PressingMachineEvenement.date_evenement.desc(), PressingMachineEvenement.id.desc()
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

    # ----------------------------------------------------------- maintenances
    @staticmethod
    def maintenance_state(m: PressingMaintenance) -> dict:
        return {
            "machine_id": str(m.machine_id),
            "type": m.type,
            "description": m.description,
            "debut": m.debut.isoformat() if m.debut else None,
            "fin": m.fin.isoformat() if m.fin else None,
            "duree_estimee_min": m.duree_estimee_min,
        }

    @staticmethod
    def indisponibilite_min(m: PressingMaintenance) -> Optional[int]:
        if m.fin is None or m.debut is None:
            return None
        return max(0, round((m.fin - m.debut).total_seconds() / 60))

    def list_maintenances(
        self, machine_id: uuid.UUID, skip: int = 0, limit: int = 50
    ) -> List[PressingMaintenance]:
        machine = self.get_machine(machine_id)
        return (
            self.db.query(PressingMaintenance)
            .filter(
                PressingMaintenance.restaurant_id == self.restaurant_id,
                PressingMaintenance.machine_id == machine.id,
            )
            .order_by(PressingMaintenance.debut.desc(), PressingMaintenance.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def declarer_maintenance(
        self, machine_id: uuid.UUID, data: MaintenanceIn
    ) -> PressingMaintenance:
        machine = self.get_machine(machine_id, for_update=True)
        if not machine.actif:
            raise ConflictError(f"La machine « {machine.nom} » est désactivée")
        maintenance = PressingMaintenance(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            machine_id=machine.id,
            type=data.type,
            description=data.description,
            debut=data.debut or _now(),
            fin=data.fin,
            duree_estimee_min=data.duree_estimee_min,
            auteur_id=self.actor_id,
        )
        self.db.add(maintenance)
        self.db.flush()
        self._log(
            "PRESSING_MAINTENANCE_CREATE", "PressingMaintenance", maintenance.id, None,
            self.maintenance_state(maintenance),
        )
        if data.fin is None and machine.etat_operationnel in ("libre", "hors_service"):
            # La machine passe en maintenance ; l'événement porte la maintenance.
            self.changer_etat(
                machine.id, "maintenance", data.description,
                maintenance_id=maintenance.id, _machine=machine, _type="maintenance",
            )
        else:
            # Historisée sans changer l'état (clôturée d'emblée, ou machine déjà occupée).
            self._evenement(
                machine, "maintenance", motif=f"{data.type} : {data.description}",
                maintenance_id=maintenance.id,
            )
        return maintenance

    def cloturer_maintenance(
        self, maintenance_id: uuid.UUID, fin: Optional[datetime] = None
    ) -> PressingMaintenance:
        maintenance = (
            self.db.query(PressingMaintenance)
            .filter(
                PressingMaintenance.id == maintenance_id,
                PressingMaintenance.restaurant_id == self.restaurant_id,
            )
            .with_for_update()
            .first()
        )
        if maintenance is None:
            raise NotFoundError("Maintenance introuvable")
        if maintenance.fin is not None:
            raise ConflictError("Cette maintenance est déjà clôturée")
        machine = self.get_machine(maintenance.machine_id, for_update=True)
        if machine.etat_operationnel in _ETATS_CYCLE_EN_COURS:
            raise ConflictError(
                f"Impossible de clôturer : la machine « {machine.nom} » a un cycle en cours"
            )
        fin = fin or _now()
        if fin < maintenance.debut:
            raise PressingRegleError("La fin de la maintenance précède son début")
        before = self.maintenance_state(maintenance)
        maintenance.fin = fin
        self.db.flush()
        self._log(
            "PRESSING_MAINTENANCE_CLOSE", "PressingMaintenance", maintenance.id, before,
            self.maintenance_state(maintenance),
        )
        if machine.etat_operationnel == "maintenance" and self._maintenance_courante(
            machine.id
        ) == maintenance.id:
            self.changer_etat(
                machine.id, "libre", "Fin de maintenance",
                maintenance_id=maintenance.id, _machine=machine, _type="maintenance",
                verifier_actif=False,
            )
        else:
            self._evenement(
                machine, "maintenance", motif="Maintenance clôturée",
                maintenance_id=maintenance.id,
            )
        return maintenance

    def _maintenance_courante(self, machine_id: uuid.UUID) -> Optional[uuid.UUID]:
        """Maintenance qui a placé la machine dans son état « maintenance » actuel."""
        return (
            self.db.query(PressingMachineEvenement.maintenance_id)
            .filter(
                PressingMachineEvenement.restaurant_id == self.restaurant_id,
                PressingMachineEvenement.machine_id == machine_id,
                PressingMachineEvenement.nouvel_etat == "maintenance",
            )
            .order_by(
                PressingMachineEvenement.date_evenement.desc(), PressingMachineEvenement.id.desc()
            )
            .limit(1)
            .scalar()
        )

    # ------------------------------------------------------------------- plan
    def plan(self, inclure_inactives: bool = False) -> dict:
        machines = self.list_machines(actif=None if inclure_inactives else True)
        return {"zones": self.list_zones(), "machines": machines}
