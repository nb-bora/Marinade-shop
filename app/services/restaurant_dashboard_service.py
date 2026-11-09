"""Tableau de bord du restaurant : indicateurs du jour, comparaison à la semaine précédente,
salle, cuisine, réservations, stock, caisse et alertes. Une dizaine de requêtes d'agrégat,
toutes bornées au restaurant et au « jour local » de l'établissement."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models.reservation import Reservation
from app.models.restaurant import Composant, Restaurant, StockComposant, Table
from app.models.ros import (
    ProductionTicket,
    RosCashShift,
    RosInvoice,
    RosOrder,
    RosOrderItem,
    RosPaymentTransaction,
    ServiceSession,
)
from app.models.user import User
from app.schemas.restaurant_dashboard import (
    RestoDashAlerte,
    RestoDashboardResponse,
    RestoDashCaisse,
    RestoDashCuisine,
    RestoDashHeure,
    RestoDashJour,
    RestoDashKpi,
    RestoDashMoyen,
    RestoDashPoste,
    RestoDashProduit,
    RestoDashReservation,
    RestoDashReservations,
    RestoDashSalle,
    RestoDashStock,
    RestoDashStockBas,
)
from app.utils.exceptions import NotFoundError

FUSEAU_DEFAUT = "Africa/Douala"
COMMANDES_NON_VALIDES = ("DRAFT", "CANCELLED", "REFUNDED")
COMMANDES_EN_COURS = ("PENDING_PAYMENT", "CONFIRMED", "SENT_TO_PRODUCTION", "READY", "SERVED")
SESSIONS_OUVERTES = ("OPEN", "ACTIVE", "PAYMENT_PENDING", "PARTIALLY_PAID")
RESERVATIONS_ACTIVES = ("pending", "confirmed", "checked_in")
SEUIL_TICKET_ATTENTE_MIN = 15
SEUIL_TICKET_CRITIQUE_MIN = 30
SEUIL_SESSION_LONGUE_H = 4
# Un ticket plus vieux n'appartient plus au service en cours (oublié, jamais soldé) : il ne doit
# ni gonfler les compteurs ni déclencher « attente de 29 jours ».
FENETRE_TICKETS_H = 12


def _duree(minutes: int) -> str:
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"


def _f(value: Any) -> float:
    return float(value) if value is not None else 0.0


def _zone(restaurant: Restaurant):
    nom = getattr(restaurant, "timezone", None) or FUSEAU_DEFAUT
    try:
        from zoneinfo import ZoneInfo

        return nom, ZoneInfo(nom)
    except Exception:
        return FUSEAU_DEFAUT, timezone(timedelta(hours=1))


def _minuit(local_dt: datetime) -> datetime:
    return local_dt.replace(hour=0, minute=0, second=0, microsecond=0)


class RestaurantDashboardService:
    def __init__(self, db: Session):
        self.db = db

    def build(self, restaurant_id: uuid.UUID, now: Optional[datetime] = None) -> RestoDashboardResponse:
        restaurant = self.db.get(Restaurant, restaurant_id)
        if restaurant is None:
            raise NotFoundError("Restaurant introuvable")
        nom_fuseau, zone = _zone(restaurant)
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        now_local = now.astimezone(zone)
        debut_local = _minuit(now_local)
        debut = debut_local.astimezone(timezone.utc)
        ref_debut = (debut_local - timedelta(days=7)).astimezone(timezone.utc)
        ref_fin = (debut_local - timedelta(days=7) + timedelta(days=1)).astimezone(timezone.utc)
        ref_now = (now_local - timedelta(days=7)).astimezone(timezone.utc)
        debut_semaine = (debut_local - timedelta(days=6)).astimezone(timezone.utc)
        fin_jour = (debut_local + timedelta(days=1)).astimezone(timezone.utc)

        ctx = dict(rid=restaurant_id, tz=nom_fuseau, now=now, debut=debut, fin_jour=fin_jour,
                   ref_debut=ref_debut, ref_fin=ref_fin, ref_now=ref_now,
                   debut_semaine=debut_semaine, now_local=now_local)
        ca, heures, moyens = self._paiements(ctx)
        commandes = self._commandes(ctx)
        reservations = self._reservations(ctx, zone)
        stock = self._stock(restaurant_id)
        cuisine = self._cuisine(restaurant_id, now)
        salle = self._salle(restaurant_id)
        caisse = self._caisse(restaurant_id)

        kpi = RestoDashKpi(
            ca_jour=ca["jour"], ca_reference=ca["reference"],
            variation_pct=(
                round(100 * (ca["jour"] - ca["reference"]) / ca["reference"], 1)
                if ca["reference"] > 0 else None
            ),
            commandes=commandes["jour"], commandes_reference=commandes["reference"],
            panier_moyen=commandes["panier"], tables_servies=commandes["tables"],
            en_cours=commandes["en_cours"], reste_a_encaisser=self._reste_a_encaisser(restaurant_id),
        )
        # Courbe horaire : les 24 heures, avec la référence de la semaine précédente.
        par_heure = {h: (ca_h, n) for h, ca_h, n in heures["jour"]}
        ref_heure = {h: ca_h for h, ca_h in heures["reference"]}
        cmd_heure = commandes["par_heure"]
        courbe = [
            RestoDashHeure(
                heure=h, ca=par_heure.get(h, (0.0, 0))[0], commandes=cmd_heure.get(h, 0),
                ca_reference=ref_heure.get(h, 0.0),
            )
            for h in range(24)
        ]
        jours = []
        for i in range(7):
            d = (debut_local - timedelta(days=6 - i)).date()
            jours.append(RestoDashJour(
                jour=d.isoformat(), ca=ca["semaine"].get(d, 0.0),
                commandes=commandes["semaine"].get(d, 0),
            ))
        return RestoDashboardResponse(
            genere_le=now, fuseau=nom_fuseau, devise=restaurant.currency or "XAF",
            kpi=kpi, heures=courbe, semaine=jours,
            top_produits=self._top_produits(ctx), moyens_paiement=moyens, salle=salle,
            cuisine=cuisine, reservations=reservations, stock=stock, caisse=caisse,
            alertes=self._alertes(kpi, cuisine, stock, reservations, caisse, ctx),
        )

    # ------------------------------------------------------------------ paiements

    def _paiements(self, c: Dict[str, Any]):
        P = RosPaymentTransaction
        base = [P.restaurant_id == c["rid"], P.status == "SUCCEEDED"]
        local = func.timezone(c["tz"], P.created_at)
        heure = func.date_part("hour", local)

        def somme(debut, fin):
            return _f(self.db.execute(
                select(func.coalesce(func.sum(P.amount), 0)).where(*base, P.created_at >= debut, P.created_at < fin)
            ).scalar())

        jour = somme(c["debut"], c["fin_jour"])
        reference = somme(c["ref_debut"], c["ref_now"])

        def par_heure(debut, fin):
            rows = self.db.execute(
                select(heure, func.coalesce(func.sum(P.amount), 0), func.count())
                .where(*base, P.created_at >= debut, P.created_at < fin)
                .group_by(heure)
            ).all()
            return [(int(h), _f(m), int(n)) for h, m, n in rows]

        h_jour = par_heure(c["debut"], c["fin_jour"])
        h_ref = [(h, m) for h, m, _ in par_heure(c["ref_debut"], c["ref_fin"])]

        rows = self.db.execute(
            select(func.date(local), func.coalesce(func.sum(P.amount), 0))
            .where(*base, P.created_at >= c["debut_semaine"], P.created_at < c["fin_jour"])
            .group_by(func.date(local))
        ).all()
        semaine = {d: _f(m) for d, m in rows}

        moyens = self.db.execute(
            select(P.payment_method, func.coalesce(func.sum(P.amount), 0), func.count())
            .where(*base, P.created_at >= c["debut"], P.created_at < c["fin_jour"])
            .group_by(P.payment_method)
            .order_by(func.sum(P.amount).desc())
        ).all()
        return (
            {"jour": jour, "reference": reference, "semaine": semaine},
            {"jour": h_jour, "reference": h_ref},
            [RestoDashMoyen(moyen=m, montant=_f(a), paiements=int(n)) for m, a, n in moyens],
        )

    # ------------------------------------------------------------------ commandes

    def _commandes(self, c: Dict[str, Any]) -> Dict[str, Any]:
        O = RosOrder
        valides = [O.restaurant_id == c["rid"], O.status.notin_(COMMANDES_NON_VALIDES)]
        local = func.timezone(c["tz"], O.created_at)

        n_jour, total_jour, tables = self.db.execute(
            select(func.count(), func.coalesce(func.sum(O.total_amount), 0), func.count(func.distinct(O.session_id)))
            .where(*valides, O.created_at >= c["debut"], O.created_at < c["fin_jour"])
        ).one()
        n_ref = self.db.execute(
            select(func.count()).where(*valides, O.created_at >= c["ref_debut"], O.created_at < c["ref_now"])
        ).scalar()
        par_heure = dict(
            (int(h), int(n))
            for h, n in self.db.execute(
                select(func.date_part("hour", local), func.count())
                .where(*valides, O.created_at >= c["debut"], O.created_at < c["fin_jour"])
                .group_by(func.date_part("hour", local))
            ).all()
        )
        semaine = {
            d: int(n)
            for d, n in self.db.execute(
                select(func.date(local), func.count())
                .where(*valides, O.created_at >= c["debut_semaine"], O.created_at < c["fin_jour"])
                .group_by(func.date(local))
            ).all()
        }
        en_cours = self.db.execute(
            select(func.count()).where(O.restaurant_id == c["rid"], O.status.in_(COMMANDES_EN_COURS))
        ).scalar()
        return {
            "jour": int(n_jour), "reference": int(n_ref or 0),
            "panier": round(_f(total_jour) / n_jour, 2) if n_jour else 0.0,
            "tables": int(tables), "en_cours": int(en_cours or 0),
            "par_heure": par_heure, "semaine": semaine,
        }

    def _reste_a_encaisser(self, rid: uuid.UUID) -> float:
        I = RosInvoice
        return _f(self.db.execute(
            select(func.coalesce(func.sum(I.total_amount - I.amount_paid), 0))
            .where(I.restaurant_id == rid, I.status.in_(("ISSUED", "PARTIALLY_PAID")))
        ).scalar())

    def _top_produits(self, c: Dict[str, Any]) -> List[RestoDashProduit]:
        I, O = RosOrderItem, RosOrder
        rows = self.db.execute(
            select(I.product_name, func.sum(I.quantity), func.sum(I.quantity * I.unit_price))
            .join(O, O.id == I.order_id)
            .where(O.restaurant_id == c["rid"], O.status.notin_(COMMANDES_NON_VALIDES),
                   O.created_at >= c["debut_semaine"], O.created_at < c["fin_jour"])
            .group_by(I.product_name)
            .order_by(func.sum(I.quantity).desc(), I.product_name)
            .limit(6)
        ).all()
        return [RestoDashProduit(nom=n, quantite=int(q), montant=_f(m)) for n, q, m in rows]

    # ------------------------------------------------------------------ salle, cuisine

    def _salle(self, rid: uuid.UUID) -> RestoDashSalle:
        rows = dict(self.db.execute(
            select(Table.statut, func.count())
            .where(Table.restaurant_id == rid, Table.deleted_at.is_(None))
            .group_by(Table.statut)
        ).all())
        sessions = self.db.execute(
            select(func.count()).where(
                ServiceSession.restaurant_id == rid, ServiceSession.status.in_(SESSIONS_OUVERTES)
            )
        ).scalar()
        return RestoDashSalle(
            total=sum(rows.values()), libres=rows.get("libre", 0), occupees=rows.get("occupee", 0),
            reservees=rows.get("reservee", 0), maintenance=rows.get("maintenance", 0),
            sessions_ouvertes=int(sessions or 0),
        )

    def _cuisine(self, rid: uuid.UUID, now: datetime) -> RestoDashCuisine:
        T = ProductionTicket
        rows = self.db.execute(
            select(T.station, T.status, func.count(), func.min(T.created_at))
            .where(T.restaurant_id == rid, T.status.in_(("QUEUED", "IN_PREPARATION", "READY")),
                   T.created_at >= now - timedelta(hours=FENETRE_TICKETS_H))
            .group_by(T.station, T.status)
        ).all()
        postes: Dict[str, Dict[str, int]] = {}
        plus_ancien: Optional[datetime] = None
        for station, statut, n, premier in rows:
            p = postes.setdefault(station, {"QUEUED": 0, "IN_PREPARATION": 0, "READY": 0})
            p[statut] = int(n)
            if statut == "QUEUED" and premier and (plus_ancien is None or premier < plus_ancien):
                plus_ancien = premier
        attente = 0
        if plus_ancien is not None:
            if plus_ancien.tzinfo is None:
                plus_ancien = plus_ancien.replace(tzinfo=timezone.utc)
            attente = max(0, int((now - plus_ancien).total_seconds() // 60))
        return RestoDashCuisine(
            en_attente=sum(p["QUEUED"] for p in postes.values()),
            en_preparation=sum(p["IN_PREPARATION"] for p in postes.values()),
            pretes=sum(p["READY"] for p in postes.values()),
            attente_max_min=attente,
            postes=[
                RestoDashPoste(poste=k, en_attente=v["QUEUED"], en_preparation=v["IN_PREPARATION"], pretes=v["READY"])
                for k, v in sorted(postes.items())
            ],
        )

    # ------------------------------------------------------------------ réservations, stock, caisse

    def _reservations(self, c: Dict[str, Any], zone) -> RestoDashReservations:
        R = Reservation
        jour = [R.restaurant_id == c["rid"], R.deleted_at.is_(None), R.status.in_(RESERVATIONS_ACTIVES),
                R.reservation_date >= c["debut"], R.reservation_date < c["fin_jour"]]
        total, couverts = self.db.execute(
            select(func.count(), func.coalesce(func.sum(R.party_size), 0)).where(*jour)
        ).one()
        a_confirmer = self.db.execute(
            select(func.count()).where(*jour, R.status == "pending", R.reservation_date >= c["now"])
        ).scalar()
        rows = self.db.execute(
            select(R, Table.numero)
            .outerjoin(Table, Table.id == R.table_id)
            .where(*jour, R.reservation_date >= c["now"] - timedelta(minutes=30))
            .order_by(R.reservation_date)
            .limit(6)
        ).all()
        return RestoDashReservations(
            total_jour=int(total), couverts_jour=int(couverts), a_confirmer=int(a_confirmer or 0),
            prochaines=[
                RestoDashReservation(
                    id=str(r.id), heure=r.reservation_date, nom=r.customer_name,
                    couverts=r.party_size, statut=r.status, table=numero,
                )
                for r, numero in rows
            ],
        )

    def _stock(self, rid: uuid.UUID) -> RestoDashStock:
        S = StockComposant
        bas = and_(S.seuil_alerte > 0, S.quantite <= S.seuil_alerte)
        base = [Composant.restaurant_id == rid, Composant.deleted_at.is_(None)]
        sous_seuil = self.db.execute(
            select(func.count()).select_from(S).join(Composant, Composant.id == S.composant_id).where(*base, bas)
        ).scalar()
        ruptures = self.db.execute(
            select(func.count()).select_from(S).join(Composant, Composant.id == S.composant_id)
            .where(*base, bas, S.quantite <= 0)
        ).scalar()
        ratio = case((S.seuil_alerte > 0, S.quantite / S.seuil_alerte), else_=1)
        rows = self.db.execute(
            select(Composant.nom, S.quantite, S.seuil_alerte, Composant.stock_unite)
            .join(Composant, Composant.id == S.composant_id)
            .where(*base, bas)
            .order_by(ratio, Composant.nom)
            .limit(6)
        ).all()
        return RestoDashStock(
            sous_seuil=int(sous_seuil or 0), ruptures=int(ruptures or 0),
            articles=[RestoDashStockBas(nom=n, quantite=_f(q), seuil=_f(s), unite=u) for n, q, s, u in rows],
        )

    def _caisse(self, rid: uuid.UUID) -> RestoDashCaisse:
        rows = self.db.execute(
            select(User.first_name, User.last_name)
            .select_from(RosCashShift)
            .join(User, User.id == RosCashShift.operator_user_id)
            .where(RosCashShift.restaurant_id == rid, RosCashShift.status == "OPEN")
        ).all()
        return RestoDashCaisse(ouvertes=len(rows), caissiers=[f"{p} {n}".strip() for p, n in rows])

    # ------------------------------------------------------------------ alertes

    def _alertes(self, kpi, cuisine, stock, reservations, caisse, c) -> List[RestoDashAlerte]:
        a: List[RestoDashAlerte] = []
        if cuisine.en_attente and cuisine.attente_max_min > SEUIL_TICKET_ATTENTE_MIN:
            a.append(RestoDashAlerte(
                niveau="critique" if cuisine.attente_max_min > SEUIL_TICKET_CRITIQUE_MIN else "avertissement",
                type="cuisine_attente",
                message=f"{cuisine.en_attente} ticket{'s' if cuisine.en_attente > 1 else ''} en attente en production, le plus ancien depuis {_duree(cuisine.attente_max_min)}",
                lien="/cuisine",
            ))
        if stock.ruptures:
            a.append(RestoDashAlerte(niveau="critique", type="stock_rupture",
                                     message=f"{stock.ruptures} ingrédient{'s' if stock.ruptures > 1 else ''} en rupture de stock", lien="/stock"))
        if stock.sous_seuil > stock.ruptures:
            a.append(RestoDashAlerte(niveau="avertissement", type="stock_bas",
                                     message=f"{stock.sous_seuil - stock.ruptures} ingrédient{'s' if stock.sous_seuil - stock.ruptures > 1 else ''} sous le seuil d'alerte", lien="/stock"))
        if reservations.a_confirmer:
            a.append(RestoDashAlerte(niveau="avertissement", type="reservation_a_confirmer",
                                     message=f"{reservations.a_confirmer} réservation{'s' if reservations.a_confirmer > 1 else ''} à confirmer aujourd'hui", lien="/reservations"))
        longue = self.db.execute(
            select(func.count()).where(
                ServiceSession.restaurant_id == c["rid"], ServiceSession.status.in_(SESSIONS_OUVERTES),
                ServiceSession.opened_at < c["now"] - timedelta(hours=SEUIL_SESSION_LONGUE_H),
            )
        ).scalar()
        if longue:
            a.append(RestoDashAlerte(niveau="info", type="session_longue",
                                     message=f"{longue} addition{'s' if longue > 1 else ''} ouverte{'s' if longue > 1 else ''} depuis plus de {SEUIL_SESSION_LONGUE_H} h", lien="/salle"))
        if kpi.ca_jour > 0 and caisse.ouvertes == 0:
            a.append(RestoDashAlerte(niveau="info", type="caisse_fermee",
                                     message="Des encaissements ont eu lieu mais aucune caisse n'est ouverte", lien="/caisse"))
        if (kpi.variation_pct is not None and kpi.variation_pct <= -30 and c["now_local"].hour >= 14):
            a.append(RestoDashAlerte(niveau="info", type="ca_en_baisse",
                                     message=f"Chiffre d'affaires en retrait de {abs(kpi.variation_pct):.0f} % sur la semaine dernière à cette heure"))
        ordre = {"critique": 0, "avertissement": 1, "info": 2}
        a.sort(key=lambda x: ordre[x.niveau])
        return a
