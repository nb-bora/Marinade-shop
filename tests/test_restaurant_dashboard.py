"""Tableau de bord du restaurant : chiffres, accès réservé à la gestion, isolation."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.support import headers_for, make_member, register
from tests.test_stock_and_payment_consistency import composant


@pytest.fixture
def shop(client):
    user = register(client, "dash")
    headers = headers_for(client, user)
    created = client.post("/v1/restaurants", headers=headers, json={"name": "Chez Dash", "taux_service": 0})
    assert created.status_code == 201, created.text
    return {**user, "headers": headers, "rid": created.json()["id"]}


def order(client, shop, price, qty=1, name="Ndolé", **extra):
    r = client.post(
        f"/v1/ros/restaurants/{shop['rid']}/orders", headers=shop["headers"],
        json={"fulfillment_type": "COUNTER",
              "items": [{"product_name": name, "quantity": qty, "unit_price": price, "tax_rate": 0}], **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


def pay(client, shop, invoice_id, amount, method="CASH"):
    r = client.post(
        f"/v1/ros/restaurants/{shop['rid']}/payments", headers=shop["headers"],
        json={"invoice_id": invoice_id, "payment_method": method, "amount": amount},
    )
    assert r.status_code == 201, r.text


def dashboard(client, shop, headers=None):
    return client.get(f"/v1/ros/restaurants/{shop['rid']}/dashboard", headers=headers or shop["headers"])


class TestDashboard:
    def test_an_empty_restaurant_gets_a_complete_zeroed_dashboard(self, client, shop):
        r = dashboard(client, shop)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["devise"] == "XAF" and d["fuseau"]
        assert d["kpi"]["ca_jour"] == 0 and d["kpi"]["variation_pct"] is None
        assert len(d["heures"]) == 24 and len(d["semaine"]) == 7
        assert d["top_produits"] == [] and d["alertes"] == []
        assert d["salle"]["total"] == 0 and d["cuisine"]["en_attente"] == 0

    def test_revenue_orders_and_average_basket_of_the_day(self, client, shop):
        a = order(client, shop, 3000)
        b = order(client, shop, 5000, qty=2, name="Poulet DG")
        pay(client, shop, a["invoice_id"], 3000, "CASH")
        pay(client, shop, b["invoice_id"], 4000, "ORANGE_MONEY")  # acompte : 6 000 restent dus
        d = dashboard(client, shop).json()
        k = d["kpi"]
        assert k["ca_jour"] == 7000 and k["commandes"] == 2 and k["panier_moyen"] == 6500
        assert k["reste_a_encaisser"] == 6000
        assert sum(h["ca"] for h in d["heures"]) == 7000
        assert d["semaine"][-1]["ca"] == 7000 and d["semaine"][-1]["commandes"] == 2
        assert {m["moyen"]: m["montant"] for m in d["moyens_paiement"]} == {"CASH": 3000, "ORANGE_MONEY": 4000}
        assert d["top_produits"][0] == {"nom": "Poulet DG", "quantite": 2, "montant": 10000.0}

    def test_hall_kitchen_reservations_stock_and_cash(self, client, shop):
        rid, h = shop["rid"], shop["headers"]
        for numero in ("T1", "T2", "T3"):
            assert client.post(f"/v1/restaurants/{rid}/tables", headers=h, json={"numero": numero, "capacite": 4}).status_code == 201
        when = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert client.post(
            f"/v1/reservations/restaurants/{rid}/reservations", headers=h,
            json={"customer_name": "Mme Ngo", "party_size": 4, "reservation_date": when},
        ).status_code == 201
        riz = composant(client, shop, "Riz", stock=2)
        assert client.put(f"/v1/restaurants/composants/{riz}/stock/seuil", headers=h, json={"seuil_alerte": 5}).status_code == 200
        assert client.post(f"/v1/ros/restaurants/{rid}/shifts/open", headers=h, json={"opening_balance": 1000}).status_code == 201
        order(client, shop, 2000, name="Brochettes")

        d = dashboard(client, shop).json()
        assert d["salle"]["total"] == 3 and d["salle"]["libres"] == 3
        assert d["reservations"]["total_jour"] in (0, 1)  # 1 sauf si l'heure tombe après minuit local
        if d["reservations"]["total_jour"]:
            assert d["reservations"]["prochaines"][0]["nom"] == "Mme Ngo"
            assert d["reservations"]["a_confirmer"] == 1
        assert d["stock"]["sous_seuil"] == 1 and d["stock"]["articles"][0]["nom"] == "Riz"
        assert d["caisse"]["ouvertes"] == 1
        types = {a["type"] for a in d["alertes"]}
        assert "stock_bas" in types
        assert d["kpi"]["en_cours"] >= 1

    def test_only_management_sees_it(self, client, engine, shop):
        waiter = make_member(client, engine, shop, "waiter")
        assert dashboard(client, shop, waiter["headers"]).status_code == 403
        manager = make_member(client, engine, shop, "manager")
        assert dashboard(client, shop, manager["headers"]).status_code == 200

    def test_another_restaurant_owner_is_refused(self, client, shop):
        other = register(client, "dashother")
        h = headers_for(client, other)
        assert client.post("/v1/restaurants", headers=h, json={"name": "Autre"}).status_code == 201
        assert dashboard(client, shop, h).status_code in (403, 404)

    def test_figures_never_leak_between_restaurants(self, client, shop):
        other = register(client, "dashleak")
        h = headers_for(client, other)
        rid = client.post("/v1/restaurants", headers=h, json={"name": "Voisin"}).json()["id"]
        voisin = {"headers": h, "rid": rid}
        pay(client, voisin, order(client, voisin, 9000)["invoice_id"], 9000)
        assert dashboard(client, shop).json()["kpi"]["ca_jour"] == 0

    def test_forgotten_old_tickets_do_not_pollute_the_kitchen_figures(self, client, engine, shop):
        from tests.support import sql_as_platform_admin

        o = order(client, shop, 2500, name="Soupe")
        pay(client, shop, o["invoice_id"], 2500)  # un comptoir part en production une fois payé
        d = dashboard(client, shop).json()
        assert d["cuisine"]["en_attente"] + d["cuisine"]["en_preparation"] >= 1, "le ticket du jour compte"

        sql_as_platform_admin(
            engine,
            "update production_tickets set created_at = now() - interval '30 days' where restaurant_id = :rid",
            rid=shop["rid"],
        )
        d = dashboard(client, shop).json()
        assert d["cuisine"]["en_attente"] == d["cuisine"]["en_preparation"] == d["cuisine"]["pretes"] == 0
        assert d["cuisine"]["attente_max_min"] == 0
        assert "cuisine_attente" not in {a["type"] for a in d["alertes"]}
