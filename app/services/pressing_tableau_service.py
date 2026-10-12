"""Tableau de bord et rapports d'un pressing (lecture seule, aucune écriture).

Les montants sont ceux des tables de commandes et de paiements du pressing
(``source = "transactions_pressing"``) : jamais la table ``transactions`` des abonnements.

* chiffre d'affaires = montant total (remise déduite) des commandes NON annulées, daté de
  leur création ; ce n'est PAS l'encaissé (``encaisse_jour`` vient des paiements) ;
* durées MESURÉES = fin réelle - début réel de cycles terminés ; durées ESTIMÉES = durée
  prévue du programme au moment de l'affectation. Les deux ne sont jamais mélangées ;
* utilisation = minutes en cycle / cycle terminé / attente de déchargement rapportées aux
  minutes où la machine n'est ni en maintenance ni hors service, reconstituées depuis le
  journal ``pressing_machine_evenements`` (état au début de journée + changements).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import Date, cast, func, or_
from sqlalchemy.orm import Session

from app.models.pressing import (
    PressingCloture,
    PressingCommande,
    PressingCommandeLigne,
    PressingCommandeMachine,
    PressingMachine,
    PressingMachineEvenement,
    PressingMaintenance,
    PressingPaiement,
)
from app.services import pressing_tableau_calcul as calc
from app.services import pressing_temps as temps
from app.services.pressing_calcul import PressingRegleError
from app.services.pressing_commande_service import PressingCommandeService
from app.services.pressing_commande_statuts import (
    STATUTS,
    STATUTS_EN_COURS,
    STATUTS_REAFFECTABLES,
)
from app.services.pressing_machine_etats import ETATS

PERIODE_MAX_JOURS = 366
FENETRE_DUREES_JOURS = 30


def _sec_vers_min(expr):
    return func.extract("epoch", expr) / 60.0


def _arrondi(valeur, chiffres=1) -> Optional[float]:
    return None if valeur is None else round(float(valeur), chiffres)


class PressingTableauService:
    def __init__(self, db: Session, restaurant_id: uuid.UUID, now=None):
        self.db = db
        self.restaurant_id = restaurant_id
        self._now = now or temps.maintenant

    # ----------------------------------------------------------- tableau de bord
    def _commandes(self):
        return self.db.query(PressingCommande).filter(
            PressingCommande.restaurant_id == self.restaurant_id
        )

    def _somme_commandes(self, colonne, *filtres) -> int:
        valeur = (
            self.db.query(func.coalesce(func.sum(colonne), 0))
            .select_from(PressingCommande)
            .filter(
                PressingCommande.restaurant_id == self.restaurant_id,
                PressingCommande.statut != "annulee",
                *filtres,
            )
            .scalar()
        )
        return int(valeur or 0)

    def tableau_de_bord(self) -> dict:
        maintenant = self._now()
        jour = temps.jour_local(maintenant)
        debut_jour = temps.debut_du_jour(jour)
        debut_semaine = temps.debut_du_jour(jour - timedelta(days=jour.weekday()))
        debut_mois = temps.debut_du_jour(jour.replace(day=1))
        fenetre = maintenant - timedelta(days=FENETRE_DUREES_JOURS)

        machines = (
            self.db.query(PressingMachine)
            .filter(
                PressingMachine.restaurant_id == self.restaurant_id,
                PressingMachine.actif.is_(True),
            )
            .order_by(PressingMachine.nom, PressingMachine.id)
            .all()
        )
        par_etat = {etat: 0 for etat in ETATS}
        for m in machines:
            par_etat[m.etat_operationnel] += 1

        # --- commandes
        par_statut = {statut: 0 for statut in STATUTS}
        for statut, nombre in (
            self.db.query(PressingCommande.statut, func.count(PressingCommande.id))
            .filter(PressingCommande.restaurant_id == self.restaurant_id)
            .group_by(PressingCommande.statut)
            .all()
        ):
            par_statut[statut] = nombre
        terminees_jour = (
            self._commandes()
            .filter(
                PressingCommande.statut != "annulee",
                PressingCommande.pret_le >= debut_jour,
            )
            .count()
        )

        # --- finance
        encaisse_jour = int(
            self.db.query(func.coalesce(func.sum(PressingPaiement.montant), 0))
            .filter(
                PressingPaiement.restaurant_id == self.restaurant_id,
                PressingPaiement.cree_le >= debut_jour,
            )
            .scalar()
            or 0
        )
        total = PressingCommande.montant_total
        finance = {
            "ca_jour": self._somme_commandes(total, PressingCommande.cree_le >= debut_jour),
            "ca_semaine": self._somme_commandes(total, PressingCommande.cree_le >= debut_semaine),
            "ca_mois": self._somme_commandes(total, PressingCommande.cree_le >= debut_mois),
            "encaisse_jour": encaisse_jour,
            "reste_a_payer_total": self._somme_commandes(
                PressingCommande.montant_total - PressingCommande.montant_paye
            ),
            "source": "transactions_pressing",
        }

        # --- activité
        activite = {
            "poids_traite_kg_jour": self._poids_kg(PressingCommande.pret_le >= debut_jour),
            "poids_traite_kg_semaine": self._poids_kg(PressingCommande.pret_le >= debut_semaine),
            "nb_commandes_jour": (
                self._commandes()
                .filter(
                    PressingCommande.statut != "annulee", PressingCommande.cree_le >= debut_jour
                )
                .count()
            ),
            "duree_moyenne_traitement_min_mesuree": _arrondi(
                self.db.query(
                    func.avg(
                        _sec_vers_min(
                            PressingCommandeMachine.fin_reelle - PressingCommandeMachine.debut_reel
                        )
                    )
                )
                .filter(
                    PressingCommandeMachine.restaurant_id == self.restaurant_id,
                    PressingCommandeMachine.debut_reel.isnot(None),
                    PressingCommandeMachine.fin_reelle.isnot(None),
                    PressingCommandeMachine.fin_reelle >= fenetre,
                )
                .scalar()
            ),
            "duree_estimee_moyenne_min": _arrondi(
                self.db.query(func.avg(PressingCommandeMachine.duree_min))
                .filter(
                    PressingCommandeMachine.restaurant_id == self.restaurant_id,
                    PressingCommandeMachine.duree_min.isnot(None),
                    PressingCommandeMachine.cree_le >= fenetre,
                )
                .scalar()
            ),
        }

        # --- lignes d'affectation vivantes : réservations, cycles en cours, cycles à décharger
        # (un cycle interrompu dont la charge n'est pas traitée est inactif mais reste à
        # décharger : sa fin réelle alimente l'alerte d'attente de déchargement).
        reservations = {}
        cycles = {}
        derniers_termines = {}
        if machines:
            lignes = (
                self.db.query(PressingCommandeMachine, PressingCommande.numero)
                .join(PressingCommande, PressingCommande.id == PressingCommandeMachine.commande_id)
                .filter(
                    PressingCommandeMachine.restaurant_id == self.restaurant_id,
                    PressingCommandeMachine.dechargee_le.is_(None),
                    or_(
                        PressingCommandeMachine.actif.is_(True),
                        PressingCommandeMachine.interrompue_le.isnot(None),
                    ),
                )
                .order_by(
                    PressingCommandeMachine.debut_reel.nullsfirst(),
                    PressingCommandeMachine.fin_reelle.nullsfirst(),
                    PressingCommandeMachine.cree_le,
                )
                .all()
            )
            for ligne, numero in lignes:
                if ligne.debut_reel is None:
                    if ligne.actif and ligne.fin_reelle is None:
                        reservations[ligne.machine_id] = (ligne, numero)
                elif ligne.fin_reelle is None:
                    cycles[ligne.machine_id] = (ligne, numero)
                else:
                    derniers_termines[ligne.machine_id] = (ligne, numero)

        occupations: List[dict] = []
        liberations: List[dict] = []
        snapshots: List[calc.MachineSnapshot] = []
        for m in machines:
            ligne, numero = cycles.get(m.id, (None, None))
            if m.etat_operationnel == "en_cycle":
                debut = ligne.debut_reel if ligne else None
                fin = m.fin_estimee
                occupations.append(
                    {
                        "machine_id": m.id,
                        "nom": m.nom,
                        "categorie": m.categorie,
                        "commande_numero": numero,
                        "debut_reel": debut,
                        "fin_estimee": fin,
                        "ecoule_min": int((maintenant - debut).total_seconds() // 60)
                        if debut
                        else None,
                        "restant_min": max(0, int((fin - maintenant).total_seconds() // 60))
                        if fin
                        else None,
                        "en_retard": bool(fin and maintenant > fin),
                    }
                )
                if fin is not None:
                    liberations.append({"machine_id": m.id, "nom": m.nom, "fin_estimee": fin})
                snapshots.append(
                    calc.MachineSnapshot(
                        m.id, m.nom, m.etat_operationnel, m.fin_estimee, m.commande_courante_id,
                        numero, bool(ligne.intervention_humaine) if ligne else False,
                        ligne.programme if ligne else None,
                    )
                )
            elif m.etat_operationnel in ("cycle_termine", "attente_dechargement"):
                fini, numero = derniers_termines.get(m.id, (None, None))
                snapshots.append(
                    calc.MachineSnapshot(
                        m.id, m.nom, m.etat_operationnel, m.fin_estimee, m.commande_courante_id,
                        numero, False, fini.programme if fini else None,
                        fini.fin_reelle if fini else None,
                    )
                )
            elif m.etat_operationnel == "reservee":
                reservee, numero = reservations.get(m.id, (None, None))
                snapshots.append(
                    calc.MachineSnapshot(
                        m.id, m.nom, m.etat_operationnel, m.fin_estimee, m.commande_courante_id,
                        numero, False, reservee.programme if reservee else None,
                        debut_prevu=reservee.debut_prevu if reservee else None,
                    )
                )
        liberations.sort(key=lambda x: x["fin_estimee"])

        pannes = [
            calc.PanneOuverte(machine_id, nom, description)
            for machine_id, nom, description in self.db.query(
                PressingMaintenance.machine_id, PressingMachine.nom, PressingMaintenance.description
            )
            .join(PressingMachine, PressingMachine.id == PressingMaintenance.machine_id)
            .filter(
                PressingMaintenance.restaurant_id == self.restaurant_id,
                PressingMaintenance.type == "panne",
                PressingMaintenance.fin.is_(None),
                PressingMachine.actif.is_(True),
            )
            .order_by(PressingMaintenance.debut)
            .all()
        ]
        pretes = [
            calc.CommandePrete(c.id, c.numero, c.pret_le)
            for c in self._commandes()
            .filter(PressingCommande.statut == "pret", PressingCommande.pret_le.isnot(None))
            .order_by(PressingCommande.pret_le)
            .all()
        ]

        occupees, disponibles = self._utilisation(machines, debut_jour, maintenant)
        return {
            "genere_a": maintenant,
            "fuseau": temps.FUSEAU_NOM,
            "machines": {
                "total_lave_linge": sum(1 for m in machines if m.categorie == "lave_linge"),
                "total_seche_linge": sum(1 for m in machines if m.categorie == "seche_linge"),
                "par_etat": par_etat,
            },
            "commandes": {
                "par_statut": par_statut,
                "en_attente_prise_en_charge": par_statut["recue"],
                "en_cours": sum(par_statut[s] for s in STATUTS_EN_COURS),
                "terminees_jour": terminees_jour,
            },
            "finance": finance,
            "activite": activite,
            "utilisation": {
                "taux_pct_aujourdhui": calc.taux_pct(occupees, disponibles),
                "minutes_occupees": round(occupees, 2),
                "minutes_disponibles": round(disponibles, 2),
            },
            "occupations": occupations,
            "prochaines_liberations": liberations[:5],
            "alertes": calc.calculer_alertes(
                snapshots, pannes, pretes, maintenant,
                **self._donnees_alertes_commandes(jour),
            ),
        }

    def _donnees_alertes_commandes(self, jour: date) -> dict:
        """Entrées des alertes de commandes (prise en charge, charge restante, séchage en
        attente) et de caisse (paiements après la clôture du jour)."""
        recues = [
            calc.CommandeRecue(c.id, c.numero, c.cree_le)
            for c in self._commandes()
            .filter(PressingCommande.statut == "recue", PressingCommande.etape.isnot(None))
            .order_by(PressingCommande.cree_le)
            .all()
        ]
        engagees = (
            self._commandes()
            .filter(
                PressingCommande.statut.in_(STATUTS_REAFFECTABLES),
                PressingCommande.etape.isnot(None),
            )
            .order_by(PressingCommande.cree_le)
            .all()
        )
        charges = PressingCommandeService(self.db, self.restaurant_id).etats_charge(engagees)
        a_reaffecter = [
            calc.CommandeAReaffecter(
                c.id, c.numero, c.etape, round(charges[c.id]["charge_restante_kg"] * 1000)
            )
            for c in engagees
            if charges[c.id]["a_reaffecter"]
        ]
        sechages = [
            calc.CommandeAttenteSechage(commande_id, numero, fin_lavage)
            for commande_id, numero, fin_lavage in self.db.query(
                PressingCommande.id, PressingCommande.numero,
                func.max(PressingCommandeMachine.fin_reelle),
            )
            .join(
                PressingCommandeMachine,
                PressingCommandeMachine.commande_id == PressingCommande.id,
            )
            .filter(
                PressingCommande.restaurant_id == self.restaurant_id,
                PressingCommande.statut == "attente_sechage",
                PressingCommandeMachine.etape == "lavage",
                PressingCommandeMachine.actif.is_(True),
                PressingCommandeMachine.fin_reelle.isnot(None),
            )
            .group_by(PressingCommande.id, PressingCommande.numero)
            .order_by(func.max(PressingCommandeMachine.fin_reelle))
            .all()
        ]
        apres_cloture = None
        cloture = (
            self.db.query(PressingCloture)
            .filter(
                PressingCloture.restaurant_id == self.restaurant_id, PressingCloture.date == jour
            )
            .first()
        )
        if cloture is not None:
            _, fin_jour = temps.bornes_jour(jour)
            nombre, montant = (
                self.db.query(
                    func.count(PressingPaiement.id),
                    func.coalesce(func.sum(PressingPaiement.montant), 0),
                )
                .filter(
                    PressingPaiement.restaurant_id == self.restaurant_id,
                    PressingPaiement.cree_le > cloture.cree_le,
                    PressingPaiement.cree_le < fin_jour,
                )
                .one()
            )
            if nombre:
                apres_cloture = int(montant)
        return {
            "recues": recues,
            "a_reaffecter": a_reaffecter,
            "sechages": sechages,
            "encaisse_apres_cloture": apres_cloture,
        }

    def _poids_kg(self, *filtres) -> float:
        grammes = self._somme_commandes(PressingCommande.poids_grams, *filtres)
        return round(grammes / 1000, 3)

    def _utilisation(self, machines, debut: datetime, fin: datetime):
        """(minutes occupées, minutes disponibles) du jour, toutes machines actives."""
        if not machines:
            return 0.0, 0.0
        ids = [m.id for m in machines]
        avant = {
            machine_id: etat
            for machine_id, etat in self.db.query(
                PressingMachineEvenement.machine_id, PressingMachineEvenement.nouvel_etat
            )
            .filter(
                PressingMachineEvenement.restaurant_id == self.restaurant_id,
                PressingMachineEvenement.machine_id.in_(ids),
                PressingMachineEvenement.nouvel_etat.isnot(None),
                PressingMachineEvenement.date_evenement <= debut,
            )
            .distinct(PressingMachineEvenement.machine_id)
            .order_by(
                PressingMachineEvenement.machine_id,
                PressingMachineEvenement.date_evenement.desc(),
                PressingMachineEvenement.id.desc(),
            )
            .all()
        }
        evenements: Dict[uuid.UUID, list] = {}
        for machine_id, date_evt, etat in (
            self.db.query(
                PressingMachineEvenement.machine_id,
                PressingMachineEvenement.date_evenement,
                PressingMachineEvenement.nouvel_etat,
            )
            .filter(
                PressingMachineEvenement.restaurant_id == self.restaurant_id,
                PressingMachineEvenement.machine_id.in_(ids),
                PressingMachineEvenement.nouvel_etat.isnot(None),
                PressingMachineEvenement.date_evenement > debut,
                PressingMachineEvenement.date_evenement <= fin,
            )
            .order_by(PressingMachineEvenement.date_evenement, PressingMachineEvenement.id)
            .all()
        ):
            evenements.setdefault(machine_id, []).append((date_evt, etat))
        total_occupees = total_disponibles = 0.0
        for m in machines:
            depart = max(debut, m.created_at) if m.created_at else debut
            par_etat = calc.minutes_par_etat(
                evenements.get(m.id, []), avant.get(m.id, "libre"), depart, fin
            )
            occupees, disponibles = calc.utilisation(par_etat)
            total_occupees += occupees
            total_disponibles += disponibles
        return total_occupees, total_disponibles

    # ----------------------------------------------------------------- rapports
    def rapports(self, du: date, au: date) -> dict:
        if au < du:
            raise PressingRegleError("La date de fin précède la date de début")
        jours = (au - du).days + 1
        if jours > PERIODE_MAX_JOURS:
            raise PressingRegleError(
                f"La période ne peut pas dépasser {PERIODE_MAX_JOURS} jours ({jours} demandés)"
            )
        debut = temps.debut_du_jour(du)
        fin = temps.debut_du_jour(au + timedelta(days=1))
        maintenant = self._now()
        hors_annulees = (
            PressingCommande.restaurant_id == self.restaurant_id,
            PressingCommande.statut != "annulee",
            PressingCommande.cree_le >= debut,
            PressingCommande.cree_le < fin,
        )

        jour_local = cast(func.timezone(temps.FUSEAU_NOM, PressingCommande.cree_le), Date)
        par_jour = {
            d: int(montant or 0)
            for d, montant in self.db.query(jour_local, func.sum(PressingCommande.montant_total))
            .filter(*hors_annulees)
            .group_by(jour_local)
            .all()
        }
        ca_par_jour = [
            {"date": du + timedelta(days=i), "montant": par_jour.get(du + timedelta(days=i), 0)}
            for i in range(jours)
        ]

        par_type = {
            type_: int(montant or 0)
            for type_, montant in self.db.query(
                PressingCommandeLigne.type, func.sum(PressingCommandeLigne.montant)
            )
            .join(PressingCommande, PressingCommande.id == PressingCommandeLigne.commande_id)
            .filter(*hors_annulees)
            .group_by(PressingCommandeLigne.type)
            .all()
        }
        nb, poids = self.db.query(
            func.count(PressingCommande.id),
            func.coalesce(func.sum(PressingCommande.poids_grams), 0),
        ).filter(*hors_annulees).one()

        cycle_filtre = (
            PressingCommandeMachine.restaurant_id == self.restaurant_id,
            PressingCommandeMachine.debut_reel.isnot(None),
            PressingCommandeMachine.fin_reelle.isnot(None),
            PressingCommandeMachine.fin_reelle >= debut,
            PressingCommandeMachine.fin_reelle < fin,
        )
        duree_min = _sec_vers_min(
            PressingCommandeMachine.fin_reelle - PressingCommandeMachine.debut_reel
        )
        stats = {
            machine_id: (cycles, minutes)
            for machine_id, cycles, minutes in self.db.query(
                PressingCommandeMachine.machine_id,
                func.count(PressingCommandeMachine.id),
                func.coalesce(func.sum(duree_min), 0.0),
            )
            .filter(*cycle_filtre)
            .group_by(PressingCommandeMachine.machine_id)
            .all()
        }
        machines = [
            {
                "machine_id": m.id,
                "nom": m.nom,
                "cycles": stats.get(m.id, (0, 0))[0],
                "heures_utilisation": round(float(stats.get(m.id, (0, 0))[1]) / 60, 2),
            }
            for m in self.db.query(PressingMachine)
            .filter(
                PressingMachine.restaurant_id == self.restaurant_id,
                PressingMachine.actif.is_(True),
            )
            .order_by(PressingMachine.nom, PressingMachine.id)
            .all()
        ]
        moyenne = self.db.query(func.avg(duree_min)).filter(*cycle_filtre).scalar()

        pannes = (
            self.db.query(PressingMaintenance)
            .filter(
                PressingMaintenance.restaurant_id == self.restaurant_id,
                PressingMaintenance.type == "panne",
                PressingMaintenance.debut >= debut,
                PressingMaintenance.debut < fin,
            )
            .all()
        )
        indisponibilite = 0
        for p in pannes:
            fin_panne = min(p.fin or maintenant, fin)
            indisponibilite += max(0, int((fin_panne - p.debut).total_seconds() // 60))

        return {
            "periode": {"du": du, "au": au, "jours": jours, "granularite": "jour"},
            "ca_par_jour": ca_par_jour,
            "ca_par_service": {
                "lavage": par_type.get("lavage", 0),
                "sechage": par_type.get("sechage", 0),
                "articles": par_type.get("article", 0),
                "combinaisons": par_type.get("combinaison", 0),
            },
            "nb_commandes": nb,
            "poids_kg": round(int(poids) / 1000, 3),
            "machines": machines,
            "pannes": {"nombre": len(pannes), "indisponibilite_min": indisponibilite},
            "duree_moyenne_cycle_min_mesuree": _arrondi(moyenne),
        }
