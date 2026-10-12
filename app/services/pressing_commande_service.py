"""Cœur opérationnel d'un pressing : commandes, affectation des machines, cycles, caisse, clients.

Couche service (accès base + journal d'audit ``ros_audit_logs``). Le service ne valide jamais
de commit : la requête s'en charge (``get_db``) et annule tout si une erreur est levée.

Règles transverses :

* TOUT changement d'état de machine passe par ``PressingMachineService.changer_etat`` (table
  des transitions respectée, événement et audit écrits) ;
* tout changement de statut de commande passe par ``_set_statut`` (tableau pur
  ``pressing_commande_statuts``) et est audité ;
* ordre des verrous : commande d'abord, puis machines triées par identifiant (pas d'interblocage) ;
* le prix vient exclusivement de ``pressing_calcul`` (via ``PressingService.calculer``).

Charges successives : l'affectation travaille sur la charge RESTANTE de l'étape (poids moins
la charge des affectations actives de l'étape, réservées, en cycle ou terminées). Une étape
n'avance (séchage ou « prête ») que lorsqu'aucune machine n'y travaille plus ET qu'il ne reste
plus de charge ; sinon la commande garde son statut et reste « à réaffecter ».

Erreurs : ``NotFoundError`` (404), ``ConflictError`` / ``TransitionInterdite`` (409),
``PressingRegleError`` (422).
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Integer, cast, func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.pressing import (
    PressingCloture,
    PressingCommande,
    PressingCommandeLigne,
    PressingCommandeMachine,
    PressingMachine,
    PressingPaiement,
)
from app.repositories.ros_repository import RosAuditLogRepository
from app.schemas.pressing_commandes import (
    PressingAffectationIn,
    PressingCommandeBase,
    PressingDechargementIn,
    PressingPaiementIn,
)
from app.schemas.pressing_machines import MaintenanceIn
from app.services import pressing_affectation as aff
from app.services import pressing_commande_statuts as statuts
from app.services import pressing_temps as temps
from app.services.pressing_calcul import DemandeCalcul, PressingRegleError
from app.services.pressing_machine_service import PressingMachineService
from app.services.pressing_service import PressingService
from app.utils.exceptions import ConflictError, NotFoundError

MODES = ("especes", "mobile_money", "carte", "autre")


class PressingCommandeService:
    def __init__(self, db: Session, restaurant_id: uuid.UUID, actor_id=None, now=None):
        self.db = db
        self.restaurant_id = restaurant_id
        self.actor_id = actor_id
        self._now = now or temps.maintenant
        self._audit = RosAuditLogRepository(db)
        self.machines = PressingMachineService(db, restaurant_id, actor_id)
        self.tarifs = PressingService(db, restaurant_id, actor_id)

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

    @staticmethod
    def commande_state(c: PressingCommande) -> dict:
        return {
            "numero": c.numero,
            "client_nom": c.client_nom,
            "client_telephone": c.client_telephone,
            "poids_grams": c.poids_grams,
            "lavage": c.lavage,
            "sechage": c.sechage,
            "types_linge": list(c.types_linge or []),
            "instructions": c.instructions,
            "statut": c.statut,
            "etape": c.etape,
            "sous_total": c.sous_total,
            "remise_fcfa": c.remise_fcfa,
            "montant_total": c.montant_total,
            "montant_paye": c.montant_paye,
        }

    # -------------------------------------------------------------- lecture
    def get_commande(self, commande_id: uuid.UUID, for_update: bool = False) -> PressingCommande:
        query = self.db.query(PressingCommande).filter(
            PressingCommande.id == commande_id,
            PressingCommande.restaurant_id == self.restaurant_id,
        )
        if for_update:
            query = query.with_for_update()
        commande = query.first()
        if commande is None:
            raise NotFoundError("Commande introuvable")
        return commande

    @staticmethod
    def etat_charge(commande: PressingCommande, affectations) -> dict:
        """Charge de l'étape courante d'après les affectations de la commande (pur).

        ``a_reaffecter`` : étape entamée (en attente de machine, en lavage, en séchage), charge
        restante > 0 et aucune affectation active non terminée sur l'étape.
        """
        if commande.etape is None:
            return {"charge_engagee_kg": 0.0, "charge_restante_kg": None, "a_reaffecter": False}
        actives = [a for a in affectations if a.etape == commande.etape and a.actif]
        engagee = sum(a.charge_g for a in actives)
        restante = aff.charge_restante(commande.poids_grams, engagee)
        en_cours = any(a.fin_reelle is None for a in actives)
        return {
            "charge_engagee_kg": engagee / 1000,
            "charge_restante_kg": restante / 1000,
            "a_reaffecter": (
                commande.statut in statuts.STATUTS_REAFFECTABLES and restante > 0 and not en_cours
            ),
        }

    def etats_charge(self, commandes: List[PressingCommande]) -> Dict[uuid.UUID, dict]:
        """``etat_charge`` de plusieurs commandes, en une requête."""
        if not commandes:
            return {}
        par_commande: Dict[uuid.UUID, list] = {}
        for ligne in (
            self.db.query(PressingCommandeMachine)
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.commande_id.in_([c.id for c in commandes]),
                PressingCommandeMachine.actif.is_(True),
            )
            .all()
        ):
            par_commande.setdefault(ligne.commande_id, []).append(ligne)
        return {c.id: self.etat_charge(c, par_commande.get(c.id, [])) for c in commandes}

    def sorties(self, commandes: List[PressingCommande]) -> List[dict]:
        """Commandes avec lignes et machines, en 2 requêtes quel que soit le nombre."""
        if not commandes:
            return []
        ids = [c.id for c in commandes]
        lignes: Dict[uuid.UUID, list] = {}
        for ligne in (
            self.db.query(PressingCommandeLigne)
            .filter(
                PressingCommandeLigne.restaurant_id == self.restaurant_id,
                PressingCommandeLigne.commande_id.in_(ids),
            )
            .order_by(PressingCommandeLigne.position)
            .all()
        ):
            lignes.setdefault(ligne.commande_id, []).append(ligne)
        machines: Dict[uuid.UUID, list] = {}
        affectations: Dict[uuid.UUID, list] = {}
        for ligne, nom in (
            self.db.query(PressingCommandeMachine, PressingMachine.nom)
            .join(PressingMachine, PressingMachine.id == PressingCommandeMachine.machine_id)
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.commande_id.in_(ids),
            )
            .order_by(PressingCommandeMachine.cree_le, PressingCommandeMachine.id)
            .all()
        ):
            affectations.setdefault(ligne.commande_id, []).append(ligne)
            machines.setdefault(ligne.commande_id, []).append(
                {
                    "id": ligne.id,
                    "machine_id": ligne.machine_id,
                    "machine_nom": nom,
                    "etape": ligne.etape,
                    "charge_kg": ligne.charge_g / 1000,
                    "programme": ligne.programme,
                    "duree_min": ligne.duree_min,
                    "intervention_humaine": ligne.intervention_humaine,
                    "debut_prevu": ligne.debut_prevu,
                    "fin_prevue": ligne.fin_prevue,
                    "debut_reel": ligne.debut_reel,
                    "fin_reelle": ligne.fin_reelle,
                    "dechargee_le": ligne.dechargee_le,
                    "interrompue_le": ligne.interrompue_le,
                    "motif_interruption": ligne.motif_interruption,
                    "actif": ligne.actif,
                }
            )
        return [
            {
                "id": c.id,
                "restaurant_id": c.restaurant_id,
                "numero": c.numero,
                "client_nom": c.client_nom,
                "client_telephone": c.client_telephone,
                "poids_grams": c.poids_grams,
                "poids_facturable_grams": c.poids_facturable_grams,
                "lavage": c.lavage,
                "sechage": c.sechage,
                "instructions": c.instructions,
                "types_linge": list(c.types_linge or []),
                "statut": c.statut,
                "etape": c.etape,
                "sous_total": c.sous_total,
                "remise_fcfa": c.remise_fcfa,
                "montant_total": c.montant_total,
                "montant_paye": c.montant_paye,
                "reste_a_payer": c.montant_total - c.montant_paye,
                "cree_le": c.cree_le,
                "pris_en_charge_le": c.pris_en_charge_le,
                "pret_le": c.pret_le,
                "livre_le": c.livre_le,
                "debut_prevu": c.debut_prevu,
                "fin_estimee": c.fin_estimee,
                "fin_estimee_source": c.fin_estimee_source,
                "fin_reelle": c.fin_reelle,
                "annule_le": c.annule_le,
                "motif_annulation": c.motif_annulation,
                **self.etat_charge(c, affectations.get(c.id, [])),
                "lignes": lignes.get(c.id, []),
                "machines": machines.get(c.id, []),
            }
            for c in commandes
        ]

    def sortie(self, commande: PressingCommande) -> dict:
        return self.sorties([commande])[0]

    def list_commandes(
        self,
        statut: Optional[str] = None,
        q: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[List[PressingCommande], int]:
        query = self.db.query(PressingCommande).filter(
            PressingCommande.restaurant_id == self.restaurant_id
        )
        if statut:
            query = query.filter(PressingCommande.statut == statut)
        if q and q.strip():
            motif = f"%{_echapper_like(q.strip())}%"
            query = query.filter(
                or_(
                    PressingCommande.numero.ilike(motif, escape="\\"),
                    PressingCommande.client_nom.ilike(motif, escape="\\"),
                    PressingCommande.client_telephone.ilike(motif, escape="\\"),
                )
            )
        total = query.count()
        items = (
            query.order_by(PressingCommande.cree_le.desc(), PressingCommande.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    # ----------------------------------------------------- création / édition
    def _prochain_numero(self) -> str:
        """PR-AAAAMMJJ-NNN, séquence du jour (fuseau du pressing) sous verrou transactionnel."""
        jour = temps.jour_local(self._now())
        prefixe = f"PR-{jour:%Y%m%d}-"
        self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:cle))"),
            {"cle": f"pressing-numero:{self.restaurant_id}:{prefixe}"},
        )
        dernier = (
            self.db.query(
                func.max(cast(func.substr(PressingCommande.numero, len(prefixe) + 1), Integer))
            )
            .filter(
                PressingCommande.restaurant_id == self.restaurant_id,
                PressingCommande.numero.like(prefixe + "%"),
            )
            .scalar()
        )
        return f"{prefixe}{(dernier or 0) + 1:03d}"

    def _calculer(self, data: PressingCommandeBase) -> dict:
        return self.tarifs.calculer(
            DemandeCalcul(
                poids_grams=data.poids_grams,
                lavage=data.lavage,
                sechage=data.sechage,
                articles=[(a.article_id, a.quantite) for a in data.articles],
                combinaisons=[(c.combinaison_id, c.quantite) for c in data.combinaisons],
                remise_fcfa=data.remise_fcfa,
            )
        )

    def _ecrire_lignes(self, commande: PressingCommande, calcul: dict) -> None:
        self.db.query(PressingCommandeLigne).filter(
            PressingCommandeLigne.commande_id == commande.id
        ).delete(synchronize_session=False)
        for position, ligne in enumerate(calcul["lignes"]):
            self.db.add(
                PressingCommandeLigne(
                    restaurant_id=self.restaurant_id,
                    commande_id=commande.id,
                    position=position,
                    type=ligne["type"],
                    libelle=ligne["libelle"][:160],
                    quantite=ligne["quantite"],
                    prix_unitaire=ligne["prix_unitaire"],
                    montant=ligne["montant"],
                )
            )
        self.db.flush()

    def create_commande(self, data: PressingCommandeBase) -> PressingCommande:
        calcul = self._calculer(data)
        commande = PressingCommande(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            numero=self._prochain_numero(),
            client_nom=data.client_nom,
            client_telephone=data.client_telephone,
            poids_grams=data.poids_grams,
            poids_facturable_grams=calcul["poids_facturable_grams"],
            lavage=data.lavage,
            sechage=data.sechage,
            instructions=data.instructions,
            types_linge=list(data.types_linge),
            statut="recue",
            etape=statuts.etape_initiale(data.lavage, data.sechage),
            sous_total=calcul["sous_total"],
            remise_fcfa=calcul["remise_fcfa"],
            montant_total=calcul["total"],
            montant_paye=0,
            cree_le=self._now(),
            auteur_id=self.actor_id,
        )
        try:
            with self.db.begin_nested():
                self.db.add(commande)
                self.db.flush()
        except IntegrityError as exc:  # numéro concurrent : le verrou l'évite, filet de sécurité
            raise ConflictError("Numéro de commande déjà pris, réessayez") from exc
        self._ecrire_lignes(commande, calcul)
        self._poser_estimation_initiale(commande)
        self._log(
            "PRESSING_COMMANDE_CREATE", "PressingCommande", commande.id, None,
            self.commande_state(commande),
        )
        paiement = getattr(data, "paiement", None)
        if paiement is not None:
            # Même transaction : un paiement refusé (montant > total...) annule la création.
            self.payer(commande.id, paiement)
        return commande

    def _estimation_initiale(self, commande: PressingCommande) -> Optional[datetime]:
        """Promesse client : fin de la meilleure option pour la première étape (charge totale,
        cycles successifs compris) + le programme de séchage compatible le plus court si un
        séchage suit le lavage (sèche-linge supposé libre). ``None`` si rien n'est faisable."""
        etape = commande.etape
        if etape is None or commande.poids_grams is None:
            return None
        maintenant = self._now()
        types = aff.normaliser_types(commande.types_linge)
        reco = aff.recommander(
            self._infos_machines(aff.CATEGORIE_PAR_ETAPE[etape]),
            aff.Demande(commande.poids_grams, etape, types, maintenant),
        )
        if not reco.faisable or not reco.options:
            return None
        fin = reco.options[0].fin_totale
        if etape == "lavage" and commande.sechage:
            sechoirs, _ = aff.evaluer_candidats(
                self._infos_machines(aff.CATEGORIE_PAR_ETAPE["sechage"]),
                aff.Demande(commande.poids_grams, "sechage", types, maintenant),
            )
            if not sechoirs:
                return None
            fin += timedelta(minutes=min(c.duree_min for c in sechoirs))
        return fin

    def _poser_estimation_initiale(self, commande: PressingCommande) -> None:
        fin = self._estimation_initiale(commande)
        commande.fin_estimee = fin
        commande.fin_estimee_source = "estimation_initiale" if fin is not None else None
        self.db.flush()

    def update_commande(self, commande_id: uuid.UUID, data: PressingCommandeBase) -> PressingCommande:
        commande = self.get_commande(commande_id, for_update=True)
        if commande.statut != "recue":
            raise ConflictError(
                "Seule une commande « reçue » peut être modifiée "
                f"(statut actuel : {statuts.LIBELLES[commande.statut]})"
            )
        calcul = self._calculer(data)
        if calcul["total"] < commande.montant_paye:
            raise PressingRegleError(
                f"Le nouveau total ({calcul['total']} FCFA) est inférieur au montant déjà payé "
                f"({commande.montant_paye} FCFA)"
            )
        before = self.commande_state(commande)
        commande.client_nom = data.client_nom
        commande.client_telephone = data.client_telephone
        commande.poids_grams = data.poids_grams
        commande.poids_facturable_grams = calcul["poids_facturable_grams"]
        commande.lavage = data.lavage
        commande.sechage = data.sechage
        commande.instructions = data.instructions
        commande.types_linge = list(data.types_linge)
        commande.etape = statuts.etape_initiale(data.lavage, data.sechage)
        commande.sous_total = calcul["sous_total"]
        commande.remise_fcfa = calcul["remise_fcfa"]
        commande.montant_total = calcul["total"]
        self.db.flush()
        self._ecrire_lignes(commande, calcul)
        self._poser_estimation_initiale(commande)  # poids ou services changés : promesse revue
        self._log(
            "PRESSING_COMMANDE_UPDATE", "PressingCommande", commande.id, before,
            self.commande_state(commande),
        )
        return commande

    # ----------------------------------------------------------------- statuts
    def _set_statut(self, commande: PressingCommande, cible: str, reason=None, **champs) -> None:
        statuts.verifier_transition(commande.statut, cible)
        before = self.commande_state(commande)
        commande.statut = cible
        for nom, valeur in champs.items():
            setattr(commande, nom, valeur)
        self.db.flush()
        self._log(
            "PRESSING_COMMANDE_STATUT", "PressingCommande", commande.id, before,
            self.commande_state(commande), reason=reason,
        )

    def marquer_pret(self, commande_id: uuid.UUID) -> PressingCommande:
        """Commande sans machine (articles seuls) : recue -> pret."""
        commande = self.get_commande(commande_id, for_update=True)
        if commande.lavage or commande.sechage:
            raise PressingRegleError(
                "Cette commande demande un lavage ou un séchage : elle passe par les machines"
            )
        self._set_statut(commande, "pret", pret_le=self._now(), etape=None)
        return commande

    def annuler(self, commande_id: uuid.UUID, motif: str) -> PressingCommande:
        motif = (motif or "").strip()
        if not motif:
            raise PressingRegleError("Un motif d'annulation est obligatoire")
        commande = self.get_commande(commande_id, for_update=True)
        statuts.verifier_transition(commande.statut, "annulee")
        affectations = (
            self.db.query(PressingCommandeMachine)
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.commande_id == commande.id,
                PressingCommandeMachine.actif.is_(True),
                PressingCommandeMachine.fin_reelle.is_(None),
            )
            .order_by(PressingCommandeMachine.machine_id)
            .all()
        )
        for ligne in affectations:
            machine = self.machines.get_machine(ligne.machine_id, for_update=True)
            if machine.etat_operationnel == "reservee" and machine.commande_courante_id == commande.id:
                self.machines.changer_etat(
                    machine.id, "libre", f"Commande {commande.numero} annulée",
                    _machine=machine, verifier_actif=False,
                )
            ligne.actif = False
        self.db.flush()
        avant = self.commande_state(commande)
        self._set_statut(
            commande, "annulee", reason=motif, etape=None, annule_le=self._now(),
            motif_annulation=motif, fin_estimee=None, fin_estimee_source=None, debut_prevu=None,
        )
        self._log(
            "PRESSING_COMMANDE_ANNULATION", "PressingCommande", commande.id, avant,
            self.commande_state(commande), reason=motif,
        )
        return commande

    # ------------------------------------------------------------ affectation
    def charge_engagee_g(self, commande: PressingCommande, etape: str) -> int:
        """Charge des affectations ACTIVES de l'étape (réservées, en cycle ou terminées)."""
        return int(
            self.db.query(func.coalesce(func.sum(PressingCommandeMachine.charge_g), 0))
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.commande_id == commande.id,
                PressingCommandeMachine.etape == etape,
                PressingCommandeMachine.actif.is_(True),
            )
            .scalar()
            or 0
        )

    def charge_restante_g(self, commande: PressingCommande, etape: str) -> int:
        return aff.charge_restante(commande.poids_grams, self.charge_engagee_g(commande, etape))

    def _etape_a_affecter(self, commande: PressingCommande) -> Tuple[str, int]:
        """(étape, charge restante) ; 409 si la commande n'a rien à affecter."""
        if commande.etape is None:
            raise ConflictError("Cette commande n'a besoin d'aucune machine")
        if commande.statut not in statuts.STATUTS_AFFECTABLES | statuts.STATUTS_REAFFECTABLES:
            raise ConflictError(
                f"Affectation impossible : la commande est {statuts.LIBELLES[commande.statut]}"
            )
        if commande.poids_grams is None:
            raise PressingRegleError("Le poids de la commande est obligatoire pour affecter")
        restante = self.charge_restante_g(commande, commande.etape)
        if restante <= 0:
            raise ConflictError(
                f"Affectation impossible : toute la charge de l'étape « {commande.etape} » est "
                f"déjà affectée (commande {statuts.LIBELLES[commande.statut]})"
            )
        return commande.etape, restante

    def _infos_machines(self, categorie: str, for_update: bool = False) -> List[aff.MachineInfo]:
        query = self.db.query(PressingMachine).filter(
            PressingMachine.restaurant_id == self.restaurant_id,
            PressingMachine.categorie == categorie,
        )
        if for_update:
            query = query.order_by(PressingMachine.id).with_for_update()
        machines = query.all()
        charges = dict(
            self.db.query(
                PressingCommandeMachine.machine_id, func.sum(PressingCommandeMachine.charge_g)
            )
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.actif.is_(True),
                PressingCommandeMachine.dechargee_le.is_(None),
            )
            .group_by(PressingCommandeMachine.machine_id)
            .all()
        )
        return [
            aff.MachineInfo(
                id=m.id,
                nom=m.nom,
                categorie=m.categorie,
                capacite_g=aff.grammes(m.capacite_kg),
                etat=m.etat_operationnel,
                actif=m.actif,
                programmes=tuple(m.programmes or []),
                fin_estimee=m.fin_estimee,
                charge_cumulee_kg=float(charges.get(m.id, 0) or 0) / 1000,
                type_fonctionnement=m.type_fonctionnement,
            )
            for m in machines
        ]

    def _demande(self, commande: PressingCommande, etape: str, charge_g: int) -> aff.Demande:
        return aff.Demande(
            charge_g=charge_g,
            etape=etape,
            types_linge=aff.normaliser_types(commande.types_linge),
            maintenant=self._now(),
        )

    def recommandation(self, commande_id: uuid.UUID) -> dict:
        commande = self.get_commande(commande_id)
        etape, restante = self._etape_a_affecter(commande)
        infos = self._infos_machines(aff.CATEGORIE_PAR_ETAPE[etape])
        return aff.recommander(infos, self._demande(commande, etape, restante)).to_dict()

    def _lignes_en_cours(self, commande_id) -> List[PressingCommandeMachine]:
        """Affectations actives non terminées de la commande (réservées ou en cycle)."""
        return (
            self.db.query(PressingCommandeMachine)
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.commande_id == commande_id,
                PressingCommandeMachine.actif.is_(True),
                PressingCommandeMachine.fin_reelle.is_(None),
            )
            .all()
        )

    def _maj_fin_estimee(self, commande: PressingCommande, source: str) -> None:
        """fin_estimee = la plus tardive des fins prévues des affectations en cours (inchangée
        s'il n'y en a aucune)."""
        fins = [a.fin_prevue for a in self._lignes_en_cours(commande.id) if a.fin_prevue]
        if fins:
            commande.fin_estimee = max(fins)
            commande.fin_estimee_source = source
            self.db.flush()

    def _creer_affectation(
        self,
        commande: PressingCommande,
        etape: str,
        plan: List[Tuple[aff.Candidat, int]],
    ) -> None:
        """Écrit les affectations et réserve les machines. Depuis « reçue » ou « en attente de
        séchage », la commande passe en attente de machine ; sinon (charges successives) son
        statut ne change pas."""
        demandee = sum(charge for _, charge in plan)
        restante = self.charge_restante_g(commande, etape)
        if restante <= 0:
            raise ConflictError(f"Toute la charge de l'étape « {etape} » est déjà affectée")
        if demandee > restante:
            raise ConflictError(
                f"La charge demandée ({aff._fmt_kg(demandee)} kg) dépasse la charge restante "
                f"à affecter ({aff._fmt_kg(restante)} kg)"
            )
        aff.verifier_capacites(plan, demandee, restante)
        for candidat, charge in sorted(plan, key=lambda p: str(p[0].machine.id)):
            machine = self.machines.get_machine(candidat.machine.id, for_update=True)
            if machine.etat_operationnel != "libre" or machine.commande_courante_id is not None:
                raise ConflictError(
                    f"La machine « {machine.nom} » n'est plus libre "
                    f"({_etat_libelle(machine.etat_operationnel)}) : elle est occupée par une "
                    "autre commande"
                )
            ligne = PressingCommandeMachine(
                id=uuid.uuid4(),
                restaurant_id=self.restaurant_id,
                commande_id=commande.id,
                machine_id=machine.id,
                etape=etape,
                charge_g=charge,
                programme=candidat.programme,
                duree_min=candidat.duree_min,
                intervention_humaine=candidat.intervention,
                debut_prevu=candidat.debut,
                fin_prevue=candidat.fin,
                actif=True,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(ligne)
                    self.db.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    f"La machine « {machine.nom} » vient d'être affectée à une autre commande"
                ) from exc
            self.machines.changer_etat(
                machine.id, "reservee", f"Commande {commande.numero} ({etape})",
                commande_courante_id=commande.id, fin_estimee=candidat.fin,
                _machine=machine,
            )
            self._log(
                "PRESSING_AFFECTATION", "PressingCommande", commande.id, None,
                {
                    "machine_id": str(machine.id), "machine": machine.nom, "etape": etape,
                    "charge_g": charge, "programme": candidat.programme,
                    "debut_prevu": candidat.debut.isoformat(), "fin_prevue": candidat.fin.isoformat(),
                },
            )
        if commande.statut in statuts.STATUTS_AFFECTABLES:
            debuts = [c.debut for c, _ in plan]
            fins = [c.fin for c, _ in plan]
            self._set_statut(
                commande, "en_attente_machine",
                pris_en_charge_le=commande.pris_en_charge_le or self._now(),
                debut_prevu=min(debuts), fin_estimee=max(fins), fin_estimee_source="affectation",
            )
        else:
            self._maj_fin_estimee(commande, "affectation")

    def affecter(self, commande_id: uuid.UUID, data: PressingAffectationIn) -> PressingCommande:
        commande = self.get_commande(commande_id, for_update=True)
        etape, restante = self._etape_a_affecter(commande)
        infos = self._infos_machines(aff.CATEGORIE_PAR_ETAPE[etape], for_update=True)
        demande = self._demande(commande, etape, restante)
        candidats, exclues = aff.evaluer_candidats(infos, demande)
        par_id = {c.machine.id: c for c in candidats}
        raisons_exclusion = {e.machine_id: e.raison for e in exclues}
        noms = {m.id: m.nom for m in infos}

        def _avec_programme(candidat: aff.Candidat) -> aff.Candidat:
            demande_prog = data.programmes.get(candidat.machine.id)
            if demande_prog is None:
                return candidat
            programme = aff.programme_de(candidat.machine, demande_prog, demande.types_linge)
            if programme is None:
                raise PressingRegleError(
                    f"Programme « {demande_prog} » introuvable ou incompatible sur "
                    f"« {candidat.machine.nom} »"
                )
            nom, duree, intervention = programme
            return dataclasses.replace(
                candidat, programme=nom, duree_min=duree, intervention=intervention
            )

        if data.options_choisie is not None:
            options = aff.recommander(infos, demande).options
            if data.options_choisie >= len(options):
                raise PressingRegleError(
                    f"Option {data.options_choisie} inexistante ({len(options)} option(s) proposée(s))"
                )
            plan = [
                (_avec_programme(par_id[m.machine_id]), m.charge_g)
                for m in options[data.options_choisie].machines
            ]
        else:
            choisis = []
            for mid in data.machine_ids:
                if mid in par_id:
                    choisis.append(_avec_programme(par_id[mid]))
                elif mid in raisons_exclusion:
                    raise PressingRegleError(
                        f"Machine « {noms[mid]} » inutilisable : {raisons_exclusion[mid]}"
                    )
                else:
                    raise PressingRegleError(
                        f"Machine introuvable ou d'une autre catégorie que l'étape « {etape} » : {mid}"
                    )
            if len({c.machine.id for c in choisis}) != len(choisis):
                raise PressingRegleError("Une machine ne peut apparaître qu'une fois")
            plan = aff.repartir(choisis, demande.charge_g)
            if plan is None:
                total = sum(c.machine.capacite_g for c in choisis)
                if not data.accepter_partiel:
                    raise PressingRegleError(
                        f"Capacité insuffisante : {aff._fmt_kg(demande.charge_g)} kg à traiter "
                        f"pour {aff._fmt_kg(total)} kg de capacité cumulée. Envoyez "
                        "« accepter_partiel: true » pour remplir ces machines à leur capacité "
                        f"(il restera {aff._fmt_kg(demande.charge_g - total)} kg à affecter)"
                    )
                # Charges successives : chaque machine est remplie, le reste attend une machine.
                plan = [(c, c.machine.capacite_g) for c in choisis]
        for candidat, _ in plan:
            if not candidat.libre:
                raise ConflictError(
                    f"La machine « {candidat.machine.nom} » est occupée (réservée ou en cycle) : "
                    f"attendez sa libération vers {temps.heure_locale(candidat.debut)}"
                )
        self._creer_affectation(commande, etape, plan)
        return commande

    # ------------------------------------------------------- cycle des machines
    def _ligne_active(
        self, commande_id, machine_id, etape=None, demarree: Optional[bool] = None
    ) -> Optional[PressingCommandeMachine]:
        query = self.db.query(PressingCommandeMachine).filter(
            PressingCommandeMachine.restaurant_id == self.restaurant_id,
            PressingCommandeMachine.commande_id == commande_id,
            PressingCommandeMachine.machine_id == machine_id,
            PressingCommandeMachine.actif.is_(True),
            PressingCommandeMachine.fin_reelle.is_(None),
        )
        if etape:
            query = query.filter(PressingCommandeMachine.etape == etape)
        if demarree is True:
            query = query.filter(PressingCommandeMachine.debut_reel.isnot(None))
        elif demarree is False:
            query = query.filter(PressingCommandeMachine.debut_reel.is_(None))
        return query.first()

    def demarrer(
        self,
        machine_id: uuid.UUID,
        commande_id: uuid.UUID,
        programme: str,
        charge_kg=None,
    ) -> dict:
        commande = self.get_commande(commande_id, for_update=True)
        if commande.etape is None:
            raise ConflictError("Cette commande n'a besoin d'aucune machine")
        etape = commande.etape
        statut_cycle = "en_lavage" if etape == "lavage" else "en_sechage"
        if commande.statut not in (
            statuts.STATUTS_AFFECTABLES | {"en_attente_machine", statut_cycle}
        ):
            raise ConflictError(
                f"Démarrage impossible : la commande est {statuts.LIBELLES[commande.statut]}"
            )
        machine = self.machines.get_machine(machine_id, for_update=True)
        if machine.categorie != aff.CATEGORIE_PAR_ETAPE[etape]:
            raise PressingRegleError(
                f"La machine « {machine.nom} » ne convient pas à l'étape « {etape} »"
            )
        ligne = self._ligne_active(commande.id, machine.id, etape, demarree=False)
        info = next(i for i in self._infos_machines(machine.categorie) if i.id == machine.id)
        types = aff.normaliser_types(commande.types_linge)
        choisi = aff.programme_de(info, programme, types)
        if choisi is None:
            raise PressingRegleError(
                f"Programme « {programme} » introuvable ou incompatible avec le linge sur "
                f"« {machine.nom} »"
            )
        nom_prog, duree, intervention = choisi

        if machine.etat_operationnel == "reservee":
            if machine.commande_courante_id != commande.id or ligne is None:
                raise ConflictError(
                    f"La machine « {machine.nom} » est réservée pour une autre commande"
                )
            if charge_kg is not None:
                raise PressingRegleError(
                    "charge_kg ne s'utilise que pour un départ direct sur une machine libre : "
                    "la charge de cette réservation est déjà fixée"
                )
        elif machine.etat_operationnel == "libre":
            if ligne is None:
                # Départ direct sur une machine libre : affectation implicite de cette machine
                # pour tout ou partie de la charge restante (charges successives).
                charge = self._charge_depart_direct(commande, etape, info, charge_kg)
                maintenant = self._now()
                candidat = aff.Candidat(info, nom_prog, duree, intervention, maintenant, True)
                self._creer_affectation(commande, etape, [(candidat, charge)])
                ligne = self._ligne_active(commande.id, machine.id, etape, demarree=False)
                machine = self.machines.get_machine(machine.id, for_update=True)
        else:
            raise ConflictError(
                f"La machine « {machine.nom} » ne peut pas démarrer : "
                f"{_etat_libelle(machine.etat_operationnel)}"
            )

        maintenant = self._now()
        fin = maintenant + timedelta(minutes=duree)
        self.machines.changer_etat(
            machine.id, "en_cycle", f"Commande {commande.numero} : {nom_prog}",
            commande_courante_id=commande.id, fin_estimee=fin, _machine=machine,
        )
        ligne.debut_reel = maintenant
        ligne.programme = nom_prog
        ligne.duree_min = duree
        ligne.intervention_humaine = intervention
        ligne.fin_prevue = fin
        if ligne.debut_prevu is None:
            ligne.debut_prevu = maintenant
        self.db.flush()
        if commande.statut != statut_cycle:
            self._set_statut(commande, statut_cycle)
        self._maj_fin_estimee(commande, "cycle")
        return self._action_out(machine, commande, ligne)

    def _charge_depart_direct(
        self, commande: PressingCommande, etape: str, info: aff.MachineInfo, charge_kg
    ) -> int:
        """Charge d'un départ direct : ``charge_kg`` si fourni (≤ capacité et ≤ restante),
        sinon le minimum de la charge restante et de la capacité de la machine."""
        if commande.poids_grams is None:
            raise PressingRegleError("Le poids de la commande est obligatoire")
        restante = self.charge_restante_g(commande, etape)
        if restante <= 0:
            raise ConflictError(
                f"Toute la charge de l'étape « {etape} » est déjà affectée : démarrez l'une "
                "des machines réservées"
            )
        if charge_kg is None:
            return min(restante, info.capacite_g)
        charge = aff.grammes(charge_kg)
        if charge > info.capacite_g:
            raise PressingRegleError(
                f"Capacité dépassée : {aff._fmt_kg(charge)} kg pour « {info.nom} » "
                f"({aff._fmt_kg(info.capacite_g)} kg)"
            )
        if charge > restante:
            raise PressingRegleError(
                f"La charge indiquée ({aff._fmt_kg(charge)} kg) dépasse la charge restante "
                f"de l'étape ({aff._fmt_kg(restante)} kg)"
            )
        return charge

    def _avancer_si_etape_finie(
        self, commande: PressingCommande, etape: str, maintenant: datetime
    ) -> None:
        """Fait avancer l'étape quand plus aucune machine n'y travaille ET que toute sa charge
        est traitée ; sinon le statut reste (la commande est « à réaffecter »)."""
        if commande.statut not in statuts.STATUTS_CYCLE:
            return
        encore = (
            self.db.query(func.count(PressingCommandeMachine.id))
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.commande_id == commande.id,
                PressingCommandeMachine.etape == etape,
                PressingCommandeMachine.actif.is_(True),
                PressingCommandeMachine.fin_reelle.is_(None),
            )
            .scalar()
        )
        if encore or self.charge_restante_g(commande, etape) > 0:
            return
        if etape == "lavage" and commande.sechage:
            self._set_statut(
                commande, "attente_sechage", etape="sechage", debut_prevu=None,
                fin_estimee=None, fin_estimee_source=None,
            )
        else:
            self._set_statut(commande, "pret", pret_le=maintenant, etape=None)

    def _cycle_en_cours(self, machine_id: uuid.UUID, action: str):
        """(commande, machine, ligne) verrouillées dans l'ordre commande puis machine, pour une
        machine en cycle ; 409 sinon."""
        provisoire = self.machines.get_machine(machine_id)
        if provisoire.etat_operationnel != "en_cycle":
            raise ConflictError(
                f"{action} impossible : la machine « {provisoire.nom} » n'a pas de cycle en cours "
                f"({_etat_libelle(provisoire.etat_operationnel)})"
            )
        if provisoire.commande_courante_id is None:
            raise ConflictError(f"La machine « {provisoire.nom} » n'est liée à aucune commande")
        commande = self.get_commande(provisoire.commande_courante_id, for_update=True)
        machine = self.machines.get_machine(machine_id, for_update=True)
        if machine.etat_operationnel != "en_cycle":
            raise ConflictError(f"La machine « {machine.nom} » n'a plus de cycle en cours")
        ligne = self._ligne_active(commande.id, machine.id, demarree=True)
        if ligne is None:
            raise ConflictError(
                f"Aucun cycle démarré trouvé pour « {machine.nom} » sur la commande {commande.numero}"
            )
        return commande, machine, ligne

    def interrompre(self, machine_id: uuid.UUID, motif: str, charge_traitee: bool = False) -> dict:
        """Cycle arrêté avant son terme (panne, coupure de courant, erreur de programme).

        La machine passe ``cycle_termine`` (à décharger). ``charge_traitee=False`` : l'affectation
        devient inactive et sa charge redevient à affecter ; ``True`` : elle compte comme faite.
        """
        motif = (motif or "").strip()
        if not motif:
            raise PressingRegleError("Un motif d'interruption est obligatoire")
        commande, machine, ligne = self._cycle_en_cours(machine_id, "Interruption")
        maintenant = self._now()
        self.machines.changer_etat(
            machine.id, "cycle_termine",
            f"Cycle interrompu (commande {commande.numero}) : {motif}", _machine=machine,
        )
        ligne.fin_reelle = maintenant
        ligne.interrompue_le = maintenant
        ligne.motif_interruption = motif[:500]
        if not charge_traitee:
            ligne.actif = False
        self.db.flush()
        self._log(
            "PRESSING_CYCLE_INTERROMPU", "PressingCommande", commande.id,
            {"machine_id": str(machine.id), "machine": machine.nom, "etape": ligne.etape},
            {
                "machine": machine.nom, "charge_g": ligne.charge_g, "charge_traitee": charge_traitee,
                "interrompue_le": maintenant.isoformat(), "numero": commande.numero,
            },
            reason=motif,
        )
        self._avancer_si_etape_finie(commande, ligne.etape, maintenant)
        return self._action_out(machine, commande, ligne)

    def prolonger(self, machine_id: uuid.UUID, minutes: int, motif: str) -> dict:
        """Décale la fin estimée du cycle en cours (machine, affectation, commande)."""
        motif = (motif or "").strip()
        if not motif:
            raise PressingRegleError("Un motif de prolongation est obligatoire")
        if not 1 <= minutes <= 240:
            raise PressingRegleError("La prolongation va de 1 à 240 minutes")
        commande, machine, ligne = self._cycle_en_cours(machine_id, "Prolongation")
        delta = timedelta(minutes=minutes)
        maintenant = self._now()
        avant = machine.fin_estimee
        machine.fin_estimee = (machine.fin_estimee or ligne.fin_prevue or maintenant) + delta
        ligne.fin_prevue = (ligne.fin_prevue or avant or maintenant) + delta
        self.db.flush()
        self._maj_fin_estimee(commande, "cycle")
        texte = f"Cycle prolongé de {minutes} min : {motif}"
        self.machines._evenement(machine, "note", motif=texte)
        self._log(
            "PRESSING_CYCLE_PROLONGE", "PressingMachine", machine.id,
            {"fin_estimee": avant.isoformat() if avant else None},
            {
                "fin_estimee": machine.fin_estimee.isoformat(), "minutes": minutes,
                "commande": commande.numero,
            },
            reason=motif,
        )
        return self._action_out(machine, commande, ligne)

    def liberer(
        self,
        commande_id: uuid.UUID,
        ligne_ids: Optional[List[uuid.UUID]] = None,
        motif: Optional[str] = None,
    ) -> PressingCommande:
        """Libère des affectations NON DÉMARRÉES de l'étape courante (toutes par défaut) : la
        machine réservée redevient libre et la charge redevient à affecter. Sans affectation
        active restante sur l'étape, la commande revient à « reçue » (lavage, ou séchage seul)
        ou à « en attente de séchage » (séchage après lavage)."""
        motif = (motif or "").strip() or None
        commande = self.get_commande(commande_id, for_update=True)
        if commande.etape is None:
            raise ConflictError("Cette commande n'a aucune affectation de machine à libérer")
        liberables = (
            self.db.query(PressingCommandeMachine)
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.commande_id == commande.id,
                PressingCommandeMachine.etape == commande.etape,
                PressingCommandeMachine.actif.is_(True),
                PressingCommandeMachine.fin_reelle.is_(None),
                PressingCommandeMachine.debut_reel.is_(None),
            )
            .all()
        )
        a_liberer = self._lignes_a_liberer(commande, liberables, ligne_ids)
        raison = motif or f"Affectation libérée (commande {commande.numero})"
        for ligne in sorted(a_liberer, key=lambda l_: str(l_.machine_id)):
            machine = self.machines.get_machine(ligne.machine_id, for_update=True)
            if machine.etat_operationnel == "reservee" and machine.commande_courante_id == commande.id:
                self.machines.changer_etat(
                    machine.id, "libre", raison, _machine=machine, verifier_actif=False
                )
            ligne.actif = False
            self.db.flush()
            self._log(
                "PRESSING_AFFECTATION_LIBEREE", "PressingCommande", commande.id,
                {
                    "machine_id": str(machine.id), "machine": machine.nom, "etape": ligne.etape,
                    "charge_g": ligne.charge_g, "actif": True,
                },
                {"machine_id": str(machine.id), "actif": False, "numero": commande.numero},
                reason=motif,
            )
        actives = (
            self.db.query(func.count(PressingCommandeMachine.id))
            .filter(
                PressingCommandeMachine.restaurant_id == self.restaurant_id,
                PressingCommandeMachine.commande_id == commande.id,
                PressingCommandeMachine.etape == commande.etape,
                PressingCommandeMachine.actif.is_(True),
            )
            .scalar()
        )
        if not actives and commande.statut == "en_attente_machine":
            if commande.etape == "sechage" and commande.lavage:
                self._set_statut(
                    commande, "attente_sechage", reason=motif, debut_prevu=None,
                    fin_estimee=None, fin_estimee_source=None,
                )
            else:
                self._set_statut(commande, "recue", reason=motif, debut_prevu=None)
                self._poser_estimation_initiale(commande)
        else:
            self._maj_fin_estimee(commande, "affectation")
        return commande

    def _lignes_a_liberer(self, commande, liberables, ligne_ids) -> List[PressingCommandeMachine]:
        if not ligne_ids:
            if not liberables:
                raise ConflictError(
                    "Aucune affectation à libérer : aucune machine n'est réservée pour l'étape "
                    f"« {commande.etape} » sans avoir démarré"
                )
            return liberables
        par_id = {l_.id: l_ for l_ in liberables}
        choisies = []
        for ligne_id in dict.fromkeys(ligne_ids):
            if ligne_id in par_id:
                choisies.append(par_id[ligne_id])
                continue
            existe = (
                self.db.query(PressingCommandeMachine.id)
                .filter(
                    PressingCommandeMachine.restaurant_id == self.restaurant_id,
                    PressingCommandeMachine.commande_id == commande.id,
                    PressingCommandeMachine.id == ligne_id,
                )
                .first()
            )
            if existe is None:
                raise NotFoundError(f"Affectation introuvable pour cette commande : {ligne_id}")
            raise ConflictError(
                "Affectation non libérable (déjà démarrée, terminée, inactive ou d'une autre "
                f"étape) : {ligne_id}"
            )
        return choisies

    def terminer(self, machine_id: uuid.UUID) -> dict:
        commande, machine, ligne = self._cycle_en_cours(machine_id, "Fin de cycle")
        maintenant = self._now()
        self.machines.changer_etat(
            machine.id, "cycle_termine", f"Commande {commande.numero} : cycle terminé",
            _machine=machine,
        )
        ligne.fin_reelle = maintenant
        self.db.flush()
        self._avancer_si_etape_finie(commande, ligne.etape, maintenant)
        return self._action_out(machine, commande, ligne)

    def decharger(
        self, machine_id: uuid.UUID, data: Optional[PressingDechargementIn] = None
    ) -> dict:
        """Déchargement en un geste : ``cycle_termine`` ou ``attente_dechargement`` -> ``libre``
        (les deux transitions sont journalisées dans l'ordre). Avec ``apres`` = maintenance ou
        hors_service, la machine y passe ensuite (motif obligatoire) ; ``maintenance`` déclare
        une maintenance ouverte par le service des machines."""
        data = data or PressingDechargementIn()
        machine = self.machines.get_machine(machine_id, for_update=True)
        commande_id = machine.commande_courante_id
        etat = machine.etat_operationnel
        if etat not in ("cycle_termine", "attente_dechargement"):
            raise ConflictError(
                f"La machine « {machine.nom} » n'est pas à décharger "
                f"({_etat_libelle(etat)})"
            )
        ligne = None
        if commande_id is not None:
            ligne = (
                self.db.query(PressingCommandeMachine)
                .filter(
                    PressingCommandeMachine.restaurant_id == self.restaurant_id,
                    PressingCommandeMachine.commande_id == commande_id,
                    PressingCommandeMachine.machine_id == machine.id,
                    PressingCommandeMachine.fin_reelle.isnot(None),
                    PressingCommandeMachine.dechargee_le.is_(None),
                )
                .order_by(PressingCommandeMachine.fin_reelle.desc())
                .first()
            )
        if etat == "cycle_termine":
            self.machines.changer_etat(
                machine.id, "attente_dechargement", "Déchargement commencé", _machine=machine
            )
        maintenant = self._now()
        self.machines.changer_etat(machine.id, "libre", "Déchargement terminé", _machine=machine)
        if ligne is not None:
            ligne.dechargee_le = maintenant
            self.db.flush()
        maintenance_id = self._apres_dechargement(machine, data)
        commande = self.get_commande(commande_id) if commande_id else None
        return self._action_out(machine, commande, ligne, maintenance_id=maintenance_id)

    def _apres_dechargement(
        self, machine: PressingMachine, data: PressingDechargementIn
    ) -> Optional[uuid.UUID]:
        """Machine déchargée (libre) -> maintenance / hors service, maintenance déclarée."""
        if data.apres == "libre":
            return None
        maintenance_id = None
        if data.maintenance is not None:
            # declarer_maintenance fait passer la machine libre en « maintenance » et lie
            # l'événement à la maintenance (clôture -> libre).
            maintenance = self.machines.declarer_maintenance(
                machine.id,
                MaintenanceIn(type=data.maintenance.type, description=data.maintenance.description),
            )
            maintenance_id = maintenance.id
        if machine.etat_operationnel != data.apres:
            self.machines.changer_etat(machine.id, data.apres, data.motif, _machine=machine)
        self._log(
            "PRESSING_DECHARGEMENT", "PressingMachine", machine.id, {"etat": "libre"},
            {
                "etat": machine.etat_operationnel,
                "maintenance_id": str(maintenance_id) if maintenance_id else None,
            },
            reason=data.motif,
        )
        return maintenance_id

    @staticmethod
    def _action_out(machine, commande, ligne, maintenance_id=None) -> dict:
        duree = None
        if ligne is not None and ligne.debut_reel and ligne.fin_reelle:
            duree = round((ligne.fin_reelle - ligne.debut_reel).total_seconds() / 60, 2)
        return {
            "machine_id": machine.id,
            "etat": machine.etat_operationnel,
            "commande_id": commande.id if commande is not None else None,
            "commande_statut": commande.statut if commande is not None else None,
            "fin_estimee": machine.fin_estimee,
            "debut_reel": ligne.debut_reel if ligne is not None else None,
            "fin_reelle": ligne.fin_reelle if ligne is not None else None,
            "duree_mesuree_min": duree,
            "dechargee_le": ligne.dechargee_le if ligne is not None else None,
            "interrompue_le": ligne.interrompue_le if ligne is not None else None,
            "maintenance_id": maintenance_id,
        }

    # --------------------------------------------------------------- paiements
    def payer(self, commande_id: uuid.UUID, data: PressingPaiementIn) -> PressingPaiement:
        commande = self.get_commande(commande_id, for_update=True)
        if commande.statut == "annulee":
            raise ConflictError("Cette commande est annulée : aucun paiement n'est accepté")
        reste = commande.montant_total - commande.montant_paye
        if data.montant > reste:
            raise PressingRegleError(f"Le montant dépasse le reste à payer de {reste} FCFA")
        before = {"montant_paye": commande.montant_paye, "reste_a_payer": reste}
        paiement = PressingPaiement(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            commande_id=commande.id,
            montant=data.montant,
            mode=data.mode,
            reference=data.reference,
            cree_le=self._now(),
            auteur_id=self.actor_id,
        )
        self.db.add(paiement)
        commande.montant_paye += data.montant
        self.db.flush()
        self._log(
            "PRESSING_PAIEMENT", "PressingPaiement", paiement.id, before,
            {
                "commande": commande.numero, "montant": data.montant, "mode": data.mode,
                "reference": data.reference, "montant_paye": commande.montant_paye,
                "reste_a_payer": commande.montant_total - commande.montant_paye,
            },
        )
        return paiement

    def annuler_paiement(
        self, commande_id: uuid.UUID, paiement_id: uuid.UUID, motif: str
    ) -> PressingPaiement:
        """Annule un paiement par une écriture de contre-passation (montant opposé, même mode),
        jamais par suppression. Possible sur une commande annulée (remboursement)."""
        motif = (motif or "").strip()
        if not motif:
            raise PressingRegleError("Un motif d'annulation est obligatoire")
        commande = self.get_commande(commande_id, for_update=True)
        original = (
            self.db.query(PressingPaiement)
            .filter(
                PressingPaiement.id == paiement_id,
                PressingPaiement.restaurant_id == self.restaurant_id,
                PressingPaiement.commande_id == commande.id,
            )
            .with_for_update()
            .first()
        )
        if original is None:
            raise NotFoundError("Paiement introuvable")
        if original.annule_paiement_id is not None:
            raise ConflictError("Une contre-passation ne peut pas être annulée")
        if original.annule_le is not None:
            raise ConflictError("Ce paiement est déjà annulé")
        maintenant = self._now()
        if original.reference:
            reference = f"Annulation de {original.reference}"
        else:
            reference = (
                f"Annulation de {original.montant} FCFA ({original.mode}) du "
                f"{temps.jour_local(original.cree_le):%d/%m/%Y} à "
                f"{temps.heure_locale(original.cree_le)}"
            )
        contre = PressingPaiement(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            commande_id=commande.id,
            montant=-original.montant,
            mode=original.mode,
            reference=reference[:80],
            cree_le=maintenant,
            auteur_id=self.actor_id,
            annule_paiement_id=original.id,
        )
        try:
            with self.db.begin_nested():
                self.db.add(contre)
                self.db.flush()
        except IntegrityError as exc:  # contre-passation concurrente
            raise ConflictError("Ce paiement est déjà annulé") from exc
        before = {
            "montant_paye": commande.montant_paye,
            "reste_a_payer": commande.montant_total - commande.montant_paye,
        }
        original.annule_le = maintenant
        original.annule_par = self.actor_id
        original.motif_annulation = motif[:500]
        commande.montant_paye -= original.montant
        self.db.flush()
        self._log(
            "PRESSING_PAIEMENT_ANNULATION", "PressingPaiement", original.id, before,
            {
                "commande": commande.numero, "montant": original.montant, "mode": original.mode,
                "contre_passation_id": str(contre.id), "montant_paye": commande.montant_paye,
                "reste_a_payer": commande.montant_total - commande.montant_paye,
            },
            reason=motif,
        )
        return contre

    def list_paiements(self, commande_id: uuid.UUID) -> List[PressingPaiement]:
        commande = self.get_commande(commande_id)
        return (
            self.db.query(PressingPaiement)
            .filter(
                PressingPaiement.restaurant_id == self.restaurant_id,
                PressingPaiement.commande_id == commande.id,
            )
            .order_by(PressingPaiement.cree_le, PressingPaiement.id)
            .all()
        )

    def livrer(self, commande_id: uuid.UUID, forcer: bool = False) -> PressingCommande:
        commande = self.get_commande(commande_id, for_update=True)
        if commande.statut != "pret":
            raise ConflictError(
                f"Livraison impossible : la commande est {statuts.LIBELLES[commande.statut]} "
                "(statut « prête » requis)"
            )
        reste = commande.montant_total - commande.montant_paye
        if reste > 0 and not forcer:
            raise ConflictError(
                f"Reste à payer de {reste} FCFA : encaissez-le ou forcez la livraison (forcer=true)"
            )
        if reste > 0:
            self._log(
                "PRESSING_LIVRAISON_FORCEE", "PressingCommande", commande.id,
                {"reste_a_payer": reste}, {"reste_a_payer": reste, "numero": commande.numero},
                reason=f"Livraison forcée avec {reste} FCFA impayés",
            )
        maintenant = self._now()
        self._set_statut(commande, "livre", livre_le=maintenant, fin_reelle=maintenant)
        return commande

    # ------------------------------------------------------------------- caisse
    def _paiements_du_jour(self, jour: date):
        debut, fin = temps.bornes_jour(jour)
        return (
            self.db.query(PressingPaiement, PressingCommande.numero, PressingCommande.client_nom)
            .join(PressingCommande, PressingCommande.id == PressingPaiement.commande_id)
            .filter(
                PressingPaiement.restaurant_id == self.restaurant_id,
                PressingPaiement.cree_le >= debut,
                PressingPaiement.cree_le < fin,
            )
            .order_by(PressingPaiement.cree_le, PressingPaiement.id)
            .all()
        )

    def get_cloture(self, jour: date) -> Optional[PressingCloture]:
        return (
            self.db.query(PressingCloture)
            .filter(
                PressingCloture.restaurant_id == self.restaurant_id, PressingCloture.date == jour
            )
            .first()
        )

    def journal(self, jour: Optional[date] = None) -> dict:
        """Journal NET du jour : une contre-passation compte en négatif dans son mode, le jour
        où elle est écrite. Les paiements postérieurs à la clôture sont acceptés et totalisés
        dans ``encaisse_apres_cloture``."""
        jour = jour or temps.jour_local(self._now())
        par_mode = {mode: 0 for mode in MODES}
        paiements = []
        cloture = self.get_cloture(jour)
        apres_cloture = 0
        for paiement, numero, nom in self._paiements_du_jour(jour):
            par_mode[paiement.mode] += paiement.montant
            if cloture is not None and paiement.cree_le > cloture.cree_le:
                apres_cloture += paiement.montant
            paiements.append(
                {
                    "id": paiement.id,
                    "commande_id": paiement.commande_id,
                    "montant": paiement.montant,
                    "mode": paiement.mode,
                    "reference": paiement.reference,
                    "cree_le": paiement.cree_le,
                    "auteur_id": paiement.auteur_id,
                    "annule_paiement_id": paiement.annule_paiement_id,
                    "annule_le": paiement.annule_le,
                    "annule_par": paiement.annule_par,
                    "motif_annulation": paiement.motif_annulation,
                    "commande_numero": numero,
                    "client_nom": nom,
                }
            )
        return {
            "date": jour,
            "fuseau": temps.FUSEAU_NOM,
            "total_encaisse": sum(par_mode.values()),
            "par_mode": par_mode,
            "paiements": paiements,
            "cloture": cloture,
            "encaisse_apres_cloture": apres_cloture,
        }

    def cloturer(self, jour: date, montant_compte: int) -> PressingCloture:
        if jour > temps.jour_local(self._now()):
            raise PressingRegleError("On ne peut pas clôturer un jour futur")
        if self.get_cloture(jour) is not None:
            raise ConflictError(f"La caisse du {jour.isoformat()} est déjà clôturée")
        journal = self.journal(jour)
        attendues = journal["par_mode"]["especes"]
        cloture = PressingCloture(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant_id,
            date=jour,
            total_encaisse=journal["total_encaisse"],
            especes_attendues=attendues,
            montant_compte=montant_compte,
            ecart=montant_compte - attendues,
            auteur_id=self.actor_id,
            cree_le=self._now(),
        )
        try:
            with self.db.begin_nested():
                self.db.add(cloture)
                self.db.flush()
        except IntegrityError as exc:
            raise ConflictError(f"La caisse du {jour.isoformat()} est déjà clôturée") from exc
        self._log(
            "PRESSING_CLOTURE_CAISSE", "PressingCloture", cloture.id, None,
            {
                "date": jour.isoformat(), "total_encaisse": cloture.total_encaisse,
                "especes_attendues": attendues, "montant_compte": montant_compte,
                "ecart": cloture.ecart, "par_mode": journal["par_mode"],
            },
        )
        return cloture

    # ------------------------------------------------------------------ clients
    def clients(self, q: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[dict]:
        """Clients dérivés des commandes : regroupés par téléphone, sinon par nom normalisé.

        Les commandes annulées ne comptent pas.
        """
        cle = func.coalesce(
            PressingCommande.client_telephone, func.lower(func.trim(PressingCommande.client_nom))
        )
        derniere = func.max(PressingCommande.cree_le)
        query = self.db.query(
            func.max(PressingCommande.client_telephone).label("telephone"),
            # Nom de la commande la plus récente du groupe.
            func.max(PressingCommande.client_nom).label("nom_max"),
            func.count(PressingCommande.id).label("nb"),
            func.sum(PressingCommande.montant_total).label("total"),
            func.sum(PressingCommande.montant_total - PressingCommande.montant_paye).label("reste"),
            derniere.label("derniere"),
            cle.label("cle"),
        ).filter(
            PressingCommande.restaurant_id == self.restaurant_id,
            PressingCommande.statut != "annulee",
        )
        if q and q.strip():
            motif = f"%{_echapper_like(q.strip())}%"
            query = query.filter(
                or_(
                    PressingCommande.client_nom.ilike(motif, escape="\\"),
                    PressingCommande.client_telephone.ilike(motif, escape="\\"),
                )
            )
        lignes = (
            query.group_by(cle)
            .order_by(derniere.desc(), cle)
            .offset(skip)
            .limit(limit)
            .all()
        )
        if not lignes:
            return []
        # Nom affiché = celui de la dernière commande du groupe (une requête pour la page).
        cles = [ligne.cle for ligne in lignes]
        recents = (
            self.db.query(cle.label("cle"), PressingCommande.client_nom, PressingCommande.cree_le)
            .filter(
                PressingCommande.restaurant_id == self.restaurant_id,
                PressingCommande.statut != "annulee",
                cle.in_(cles),
            )
            .order_by(PressingCommande.cree_le.asc())
            .all()
        )
        nom_recent = {r.cle: r.client_nom for r in recents}  # le dernier écrase les précédents
        return [
            {
                "nom": nom_recent.get(ligne.cle, ligne.nom_max),
                "telephone": ligne.telephone,
                "nb_commandes": ligne.nb,
                "total_depense": int(ligne.total or 0),
                "reste_a_payer": int(ligne.reste or 0),
                "derniere_commande": ligne.derniere,
            }
            for ligne in lignes
        ]


def _echapper_like(valeur: str) -> str:
    return valeur.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _etat_libelle(etat: str) -> str:
    from app.services.pressing_machine_etats import LIBELLES

    return LIBELLES.get(etat, etat)
