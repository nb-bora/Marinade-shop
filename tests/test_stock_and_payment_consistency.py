"""Stock, plats, boissons, combinaisons, factures et encaissements : les invariants.

Chaque test pose une situation sur la vraie base (rôle applicatif, RLS active) puis
vérifie ce que le restaurant verrait : le stock ne gonfle jamais, ne devient jamais
négatif, n'est jamais déduit deux fois, et l'argent encaissé ne dépasse jamais le dû.

Exige TEST_DATABASE_URL (voir tests/conftest.py).
"""

import hashlib
import hmac
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from tests.support import (
    headers_for,
    make_member,
    register,
    sql_as_platform_admin,
)


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #
@pytest.fixture
def shop(client):
    """Un restaurant neuf par test : aucun stock partagé entre deux tests."""
    user = register(client, "shop")
    headers = headers_for(client, user)
    response = client.post(
        "/v1/restaurants", headers=headers, json={"name": "Maquis", "taux_service": 10}
    )
    assert response.status_code == 201, response.text
    return {**user, "headers": headers, "rid": response.json()["id"]}


def composant(client, shop, nom, stock=0, **extra):
    h, rid = shop["headers"], shop["rid"]
    created = client.post(
        f"/v1/restaurants/{rid}/composants", headers=h, json={"nom": nom, "type": "base", **extra}
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    if stock:
        moved = client.post(
            f"/v1/restaurants/composants/{cid}/stock/mouvements",
            headers=h,
            json={"type": "entree", "quantite": stock},
        )
        assert moved.status_code == 200, moved.text
    return cid


def plat(client, shop, nom, prix, lines):
    """Plat dont la nomenclature est [(composant_id, quantité), ...]."""
    h, rid = shop["headers"], shop["rid"]
    created = client.post(f"/v1/restaurants/{rid}/plats", headers=h, json={"nom": nom, "prix": prix})
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    if lines:
        replaced = client.put(
            f"/v1/restaurants/plats/{pid}/composants",
            headers=h,
            json=[{"composant_id": c, "quantite": q} for c, q in lines],
        )
        assert replaced.status_code == 200, replaced.text
    return pid


def combinaison(client, shop, nom, prix, composants):
    created = client.post(
        f"/v1/restaurants/{shop['rid']}/combinaisons",
        headers=shop["headers"],
        json={"nom": nom, "prix": prix, "composant_ids": composants},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def boisson(client, shop, nom, prix, composant_id=None, par_vente=1):
    body = {"nom": nom, "prix": prix}
    if composant_id:
        body.update({"composant_id": composant_id, "stock_par_vente": par_vente})
    created = client.post(f"/v1/restaurants/{shop['rid']}/boissons", headers=shop["headers"], json=body)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def stock(client, shop, composant_id):
    listed = client.get(f"/v1/restaurants/{shop['rid']}/stock?limit=500", headers=shop["headers"]).json()
    row = next(s for s in listed if s["composant_id"] == composant_id)
    return {k: float(row[k]) for k in ("quantite", "reservee", "disponible")}


def movements(engine, composant_id):
    with engine.begin() as conn:
        conn.execute(text("select set_config('app.is_platform_admin', 'true', true)"))
        rows = conn.execute(
            text("select type, quantite from stock_mouvements where composant_id = :c order by created_at, id"),
            {"c": composant_id},
        ).all()
    return [(r.type, float(r.quantite)) for r in rows]


def new_commande(client, shop):
    created = client.post(f"/v1/restaurants/{shop['rid']}/commandes", headers=shop["headers"], json={})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def add_item(client, shop, commande_id, **item):
    return client.post(
        f"/v1/restaurants/commandes/{commande_id}/items", headers=shop["headers"], json={"quantite": 1, **item}
    )


def pay_by_webhook(client, engine, shop, commande_id):
    """Simule le fournisseur : un webhook signé « success » pour cette commande."""
    # Le webhook n'est accepté que pour un restaurant dont le paiement est configuré.
    configured = client.put(
        "/v1/payments/easytransact/configuration",
        headers=shop["headers"],
        json={"restaurant_id": shop["rid"]},
    )
    assert configured.status_code in (200, 201), configured.text
    commande = client.get(f"/v1/restaurants/commandes/{commande_id}", headers=shop["headers"]).json()
    vendor = f"MRD-{uuid.uuid4().hex[:12]}"
    sql_as_platform_admin(
        engine,
        "insert into payment_intents (id, restaurant_id, commande_id, provider, vendor_reference,"
        " idempotency_key, amount_fcfa, currency, status)"
        " values (:id, :rid, :cid, 'easytransact', :vendor, :idem, :amount, 'XAF', 'initiated')",
        id=str(uuid.uuid4()),
        rid=shop["rid"],
        cid=commande_id,
        vendor=vendor,
        idem=f"idem-{vendor}",
        amount=max(1, int(Decimal(str(commande["total"])))),
    )
    body = json.dumps({"vendor_reference": vendor, "event_id": f"evt-{vendor}", "status": "success"}).encode()
    signature = hmac.new(settings.EASYTRANSACT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        f"/v1/payments/easytransact/webhook/{shop['rid']}",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )


# --------------------------------------------------------------------------- #
# Commandes historiques : réserver -> consommer | libérer
# --------------------------------------------------------------------------- #
class TestLegacyStockLifecycle:
    def test_a_combination_is_deducted_once_when_paid(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=10)
        combo = combinaison(client, shop, "Riz seul", 1500, [riz])
        commande = new_commande(client, shop)
        assert add_item(client, shop, commande, combinaison_id=combo, quantite=2).status_code == 201

        assert stock(client, shop, riz) == {"quantite": 10, "reservee": 2, "disponible": 8}
        paid = pay_by_webhook(client, engine, shop, commande)
        assert paid.status_code == 200, paid.text

        # Régression : la combinaison était sortie DEUX fois (10 - 2 - 2 = 6).
        assert stock(client, shop, riz) == {"quantite": 8, "reservee": 0, "disponible": 8}
        assert [m for m in movements(engine, riz) if m[0] == "sortie"] == [("sortie", 2.0)]

    def test_a_dish_reserves_its_recipe_then_consumes_it(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=10)
        poulet = composant(client, shop, "Poulet", stock=10)
        ndole = plat(client, shop, "Poulet-riz", 2500, [(riz, 2), (poulet, 1)])
        commande = new_commande(client, shop)
        assert add_item(client, shop, commande, plat_id=ndole, quantite=3).status_code == 201

        # Avant : un plat ne réservait RIEN, le webhook pouvait échouer après le paiement.
        assert stock(client, shop, riz) == {"quantite": 10, "reservee": 6, "disponible": 4}
        assert stock(client, shop, poulet)["reservee"] == 3

        assert pay_by_webhook(client, engine, shop, commande).status_code == 200
        assert stock(client, shop, riz) == {"quantite": 4, "reservee": 0, "disponible": 4}
        assert stock(client, shop, poulet) == {"quantite": 7, "reservee": 0, "disponible": 7}

    def test_cancelling_releases_the_reservation_without_inflating_stock(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=10)
        combo = combinaison(client, shop, "Riz seul", 1500, [riz])
        plat_id = plat(client, shop, "Riz nature", 1000, [(riz, 1)])
        commande = new_commande(client, shop)
        add_item(client, shop, commande, combinaison_id=combo, quantite=2)
        add_item(client, shop, commande, plat_id=plat_id, quantite=1)
        assert stock(client, shop, riz)["reservee"] == 3

        cancelled = client.put(
            f"/v1/restaurants/commandes/{commande}", headers=shop["headers"], json={"statut": "annulee"}
        )
        assert cancelled.status_code == 200, cancelled.text
        # Régression : l'annulation « remettait » 3 unités jamais sorties (13).
        assert stock(client, shop, riz) == {"quantite": 10, "reservee": 0, "disponible": 10}
        assert movements(engine, riz) == [("entree", 10.0)]

    def test_insufficient_stock_is_refused_and_reserves_nothing(self, client, shop):
        riz = composant(client, shop, "Riz", stock=3)
        sauce = composant(client, shop, "Sauce", stock=100)
        plat_id = plat(client, shop, "Riz sauce", 1500, [(riz, 2), (sauce, 1)])
        commande = new_commande(client, shop)

        refused = add_item(client, shop, commande, plat_id=plat_id, quantite=2)  # il faut 4 riz
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"] == "InsufficientStockError"
        shortage = refused.json()["details"]
        assert [d["nom"] for d in shortage] == ["Riz"]
        assert (shortage[0]["requis"], shortage[0]["disponible"]) == ("4.000", "3.000")
        # Tout ou rien : la sauce, elle, était disponible mais n'a pas été réservée.
        assert stock(client, shop, riz)["reservee"] == 0
        assert stock(client, shop, sauce)["reservee"] == 0

    def test_the_last_unit_cannot_be_promised_twice(self, client, shop):
        riz = composant(client, shop, "Riz", stock=2)
        plat_id = plat(client, shop, "Riz", 1000, [(riz, 1)])
        first, second = new_commande(client, shop), new_commande(client, shop)
        assert add_item(client, shop, first, plat_id=plat_id, quantite=2).status_code == 201
        assert add_item(client, shop, second, plat_id=plat_id, quantite=1).status_code == 409

    def test_a_drink_linked_to_a_component_uses_its_stock(self, client, engine, shop):
        bouteilles = composant(client, shop, "Castel 65cl", stock=12)
        castel = boisson(client, shop, "Castel", 1000, composant_id=bouteilles)
        eau = boisson(client, shop, "Eau (sans stock suivi)", 300)
        commande = new_commande(client, shop)
        assert add_item(client, shop, commande, boisson_id=castel, quantite=5).status_code == 201
        assert add_item(client, shop, commande, boisson_id=eau, quantite=2).status_code == 201
        assert stock(client, shop, bouteilles) == {"quantite": 12, "reservee": 5, "disponible": 7}

        assert pay_by_webhook(client, engine, shop, commande).status_code == 200
        assert stock(client, shop, bouteilles) == {"quantite": 7, "reservee": 0, "disponible": 7}

    def test_a_drink_cannot_be_linked_to_another_restaurants_component(self, client, shop, stranger):
        foreign = composant(client, {**stranger}, "Secret", stock=1)
        refused = client.post(
            f"/v1/restaurants/{shop['rid']}/boissons",
            headers=shop["headers"],
            json={"nom": "Piégée", "prix": 500, "composant_id": foreign},
        )
        assert refused.status_code == 400

    def test_supplements_are_reserved_and_consumed(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=10)
        plantain = composant(client, shop, "Plantain", stock=5, prix_supplement=300)
        plat_id = plat(client, shop, "Riz", 1000, [(riz, 1)])
        commande = new_commande(client, shop)
        added = add_item(client, shop, commande, plat_id=plat_id, quantite=2, supplement_ids=[plantain])
        assert added.status_code == 201, added.text
        assert float(added.json()["prix_unitaire"]) == 1300.0
        assert stock(client, shop, plantain)["reservee"] == 2
        assert pay_by_webhook(client, engine, shop, commande).status_code == 200
        assert stock(client, shop, plantain) == {"quantite": 3, "reservee": 0, "disponible": 3}

    def test_an_unavailable_component_blocks_the_dish(self, client, shop):
        sauce = composant(client, shop, "Sauce", stock=10)
        plat_id = plat(client, shop, "Poulet sauce", 2000, [(sauce, 1)])
        client.put(f"/v1/restaurants/composants/{sauce}", headers=shop["headers"], json={"disponible": False})
        commande = new_commande(client, shop)
        refused = add_item(client, shop, commande, plat_id=plat_id)
        assert refused.status_code == 400
        assert stock(client, shop, sauce)["reservee"] == 0

    def test_items_cannot_be_added_to_a_paid_commande(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=10)
        plat_id = plat(client, shop, "Riz", 1000, [(riz, 1)])
        commande = new_commande(client, shop)
        add_item(client, shop, commande, plat_id=plat_id)
        assert pay_by_webhook(client, engine, shop, commande).status_code == 200
        late = add_item(client, shop, commande, plat_id=plat_id)
        assert late.status_code == 400
        assert stock(client, shop, riz) == {"quantite": 9, "reservee": 0, "disponible": 9}

    def test_paying_twice_never_deducts_twice(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=10)
        plat_id = plat(client, shop, "Riz", 1000, [(riz, 1)])
        commande = new_commande(client, shop)
        add_item(client, shop, commande, plat_id=plat_id, quantite=2)
        assert pay_by_webhook(client, engine, shop, commande).status_code == 200
        assert pay_by_webhook(client, engine, shop, commande).status_code == 200
        assert stock(client, shop, riz)["quantite"] == 8


# --------------------------------------------------------------------------- #
# Remboursements
# --------------------------------------------------------------------------- #
class TestRefundRules:
    def served(self, client, shop, prix=1000, quantite=2, lines=None):
        plat_id = plat(client, shop, f"Plat {uuid.uuid4().hex[:4]}", prix, lines or [])
        commande = new_commande(client, shop)
        item = add_item(client, shop, commande, plat_id=plat_id, quantite=quantite).json()
        client.put(f"/v1/restaurants/commandes/{commande}", headers=shop["headers"], json={"statut": "servie"})
        total = float(client.get(f"/v1/restaurants/commandes/{commande}", headers=shop["headers"]).json()["total"])
        return commande, item["id"], total

    def refund(self, client, shop, commande, montant, **extra):
        return client.post(
            f"/v1/restaurants/commandes/{commande}/refunds",
            headers=shop["headers"],
            json={"montant": montant, "raison": "test", **extra},
        )

    def test_pending_requests_count_against_the_cap(self, client, shop):
        commande, _item, total = self.served(client, shop)  # 2 x 1000 + 10 % de service
        assert total == 2200.0
        assert self.refund(client, shop, commande, 1500).status_code == 201
        # Régression : 1000 passait (la demande de 1500 n'était pas comptée).
        assert self.refund(client, shop, commande, 1000).status_code == 400
        assert self.refund(client, shop, commande, 700).status_code == 201
        assert self.refund(client, shop, commande, 1).status_code == 400

    def test_a_rejected_request_frees_its_share_of_the_cap(self, client, shop):
        commande, _item, _total = self.served(client, shop)
        first = self.refund(client, shop, commande, 2000).json()
        assert self.refund(client, shop, commande, 500).status_code == 400
        client.post(
            f"/v1/restaurants/commandes/{commande}/refunds/{first['id']}/reject",
            headers=shop["headers"],
            params={"reason": "non"},
        )
        assert self.refund(client, shop, commande, 500).status_code == 201

    def test_stock_returns_only_when_asked_and_only_for_the_listed_items(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=10)
        commande, item, _total = self.served(client, shop, quantite=2, lines=[(riz, 1)])
        assert pay_by_webhook(client, engine, shop, commande).status_code == 200
        assert stock(client, shop, riz)["quantite"] == 8

        # Sans demande explicite, un remboursement ne touche pas au stock.
        plain = self.refund(client, shop, commande, 500).json()
        client.post(f"/v1/restaurants/commandes/{commande}/refunds/{plain['id']}/approve", headers=shop["headers"])
        assert stock(client, shop, riz)["quantite"] == 8

        explicit = self.refund(client, shop, commande, 1000, item_ids=[item], remettre_en_stock=True)
        assert explicit.status_code == 201, explicit.text
        assert explicit.json()["remettre_en_stock"] is True
        client.post(
            f"/v1/restaurants/commandes/{commande}/refunds/{explicit.json()['id']}/approve", headers=shop["headers"]
        )
        assert stock(client, shop, riz)["quantite"] == 10
        assert ("retour", 2.0) in movements(engine, riz)

    def test_the_same_item_cannot_be_refunded_twice(self, client, shop):
        commande, item, _total = self.served(client, shop)
        first = self.refund(client, shop, commande, 100, item_ids=[item]).json()
        client.post(f"/v1/restaurants/commandes/{commande}/refunds/{first['id']}/approve", headers=shop["headers"])
        assert self.refund(client, shop, commande, 100, item_ids=[item]).status_code == 400

    def test_restock_requires_naming_the_items(self, client, shop):
        commande, _item, _total = self.served(client, shop)
        assert self.refund(client, shop, commande, 100, remettre_en_stock=True).status_code == 400

    def test_items_must_belong_to_the_commande(self, client, shop):
        commande, _item, _total = self.served(client, shop)
        other, other_item, _ = self.served(client, shop)
        assert self.refund(client, shop, commande, 100, item_ids=[other_item]).status_code == 400

    def test_refund_totals_reach_completed_status(self, client, shop):
        commande, _item, total = self.served(client, shop)
        request = self.refund(client, shop, commande, total).json()
        approved = client.post(
            f"/v1/restaurants/commandes/{commande}/refunds/{request['id']}/approve", headers=shop["headers"]
        )
        assert approved.status_code == 200, approved.text
        detail = client.get(f"/v1/restaurants/commandes/{commande}", headers=shop["headers"]).json()
        assert detail["remboursement_statut"] in ("completed", None)


# --------------------------------------------------------------------------- #
# Moteur ROS : prix serveur, stock atomique, encaissements
# --------------------------------------------------------------------------- #
def ros_order(client, shop, items, fulfillment="DINE_IN", headers=None, **extra):
    return client.post(
        f"/v1/ros/restaurants/{shop['rid']}/orders",
        headers=headers or shop["headers"],
        json={"fulfillment_type": fulfillment, "items": items, **extra},
    )


def reporting_orders(client, shop):
    return client.get("/v1/ros/group/reporting", headers=shop["headers"]).json()["total_orders"]


class TestRosPricing:
    def test_catalogue_items_are_priced_by_the_server(self, client, shop):
        plat_id = plat(client, shop, "Ndolé", 2500, [])
        order = ros_order(
            client,
            shop,
            [{"product_id": plat_id, "quantity": 2, "unit_price": 1, "product_name": "gratuit", "tax_rate": 0}],
        )
        assert order.status_code == 201, order.text
        # 2 x 2500 + TVA 19,25 % du restaurant, et NON ce que la caisse a envoyé.
        assert float(order.json()["total_amount"]) == 5962.5

    def test_the_vat_rate_comes_from_the_restaurant_configuration(self, client, shop):
        plat_id = plat(client, shop, "Ndolé", 2500, [])
        configured = client.put(
            f"/v1/restaurants/{shop['rid']}",
            headers=shop["headers"],
            json={"config_jsonb": {"taxes": {"tva": 10}}},
        )
        assert configured.status_code == 200, configured.text
        order = ros_order(client, shop, [{"product_id": plat_id, "quantity": 2}])
        assert float(order.json()["total_amount"]) == 5500.0

    def test_an_unavailable_article_cannot_be_sold(self, client, shop):
        plat_id = plat(client, shop, "Ndolé", 2500, [])
        client.put(f"/v1/restaurants/plats/{plat_id}", headers=shop["headers"], json={"disponible": False})
        assert ros_order(client, shop, [{"product_id": plat_id, "quantity": 1}]).status_code == 400

    def test_a_product_of_another_restaurant_is_refused(self, client, shop, stranger):
        foreign = plat(client, {**stranger}, "Secret", 100, [])
        assert ros_order(client, shop, [{"product_id": foreign, "quantity": 1}]).status_code == 400

    def test_only_management_may_type_a_free_price(self, client, engine, shop):
        waiter = make_member(client, engine, shop, "waiter")
        manager = make_member(client, engine, shop, "manager")
        free = [{"product_name": "Plat du jour", "quantity": 1, "unit_price": 3000}]
        assert ros_order(client, shop, free, headers=waiter["headers"]).status_code == 403
        assert ros_order(client, shop, free, headers=manager["headers"]).status_code == 201
        assert ros_order(client, shop, free).status_code == 201  # le propriétaire

    def test_a_free_article_needs_a_name_and_a_price(self, client, shop):
        assert ros_order(client, shop, [{"quantity": 1, "unit_price": 100}]).status_code == 400
        assert ros_order(client, shop, [{"product_name": "x", "quantity": 1}]).status_code == 400


class TestRosStock:
    def test_every_kind_of_article_consumes_its_components(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=20)
        poulet = composant(client, shop, "Poulet", stock=20)
        bouteilles = composant(client, shop, "Bouteilles", stock=20)
        direct = composant(client, shop, "Citron", stock=20)
        ndole = plat(client, shop, "Poulet riz", 2500, [(riz, 2), (poulet, 1)])
        combo = combinaison(client, shop, "Riz seul", 1500, [riz])
        castel = boisson(client, shop, "Castel", 1000, composant_id=bouteilles)

        order = ros_order(
            client,
            shop,
            [
                {"product_id": ndole, "quantity": 2},
                {"product_id": combo, "quantity": 3},
                {"product_id": castel, "quantity": 4},
                {"product_id": direct, "quantity": 5, "product_name": "Citron", "unit_price": 100},
            ],
        )
        assert order.status_code == 201, order.text
        assert stock(client, shop, riz)["quantite"] == 20 - 2 * 2 - 3
        assert stock(client, shop, poulet)["quantite"] == 20 - 2
        assert stock(client, shop, bouteilles)["quantite"] == 20 - 4
        assert stock(client, shop, direct)["quantite"] == 20 - 5
        assert ("sortie", 7.0) in movements(engine, riz), "une seule sortie agrégée par composant"

    def test_a_shortage_creates_no_order_and_takes_no_stock(self, client, shop):
        riz = composant(client, shop, "Riz", stock=5)
        poulet = composant(client, shop, "Poulet", stock=100)
        a = plat(client, shop, "A", 1000, [(poulet, 1)])
        b = plat(client, shop, "B", 1000, [(riz, 3)])
        before = reporting_orders(client, shop)

        refused = ros_order(client, shop, [{"product_id": a, "quantity": 2}, {"product_id": b, "quantity": 2}])
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"] == "InsufficientStockError"
        assert reporting_orders(client, shop) == before
        assert stock(client, shop, poulet)["quantite"] == 100, "le plat A était servable : rien n'est sorti"
        assert stock(client, shop, riz)["quantite"] == 5

    def test_reserved_stock_is_not_sellable_through_ros(self, client, shop):
        riz = composant(client, shop, "Riz", stock=3)
        plat_id = plat(client, shop, "Riz", 1000, [(riz, 1)])
        commande = new_commande(client, shop)
        add_item(client, shop, commande, plat_id=plat_id, quantite=2)  # réserve 2 sur 3
        assert ros_order(client, shop, [{"product_id": plat_id, "quantity": 2}]).status_code == 409
        assert ros_order(client, shop, [{"product_id": plat_id, "quantity": 1}]).status_code == 201

    def test_concurrent_orders_never_oversell(self, client, shop):
        riz = composant(client, shop, "Riz", stock=5)
        plat_id = plat(client, shop, "Riz", 1000, [(riz, 1)])
        from app.main import app

        def place(_):
            with TestClient(app) as c:
                return ros_order(c, shop, [{"product_id": plat_id, "quantity": 1}]).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(place, range(14)))

        assert outcomes.count(201) == 5, outcomes
        assert outcomes.count(409) == 9, outcomes
        assert stock(client, shop, riz) == {"quantite": 0, "reservee": 0, "disponible": 0}

    def test_low_stock_feeds_the_procurement_suggestions(self, client, shop):
        riz = composant(client, shop, "Riz", stock=10)
        plat_id = plat(client, shop, "Riz", 1000, [(riz, 1)])
        h, rid = shop["headers"], shop["rid"]
        suggestions = f"/v1/ros/restaurants/{rid}/procurement/suggestions"
        assert client.get(suggestions, headers=h).json()["items"] == []

        threshold = client.put(
            f"/v1/restaurants/composants/{riz}/stock/seuil", headers=h, json={"seuil_alerte": 5}
        )
        assert threshold.status_code == 200, threshold.text
        assert float(threshold.json()["seuil_alerte"]) == 5.0

        assert ros_order(client, shop, [{"product_id": plat_id, "quantity": 6}]).status_code == 201
        items = client.get(suggestions, headers=h).json()["items"]
        assert [i["composant_id"] for i in items] == [riz]
        # reste 4, seuil 5 : on propose de remonter à deux fois le seuil (10 - 4).
        assert float(items[0]["suggested_order_qty"]) == 6.0

    def test_the_threshold_cannot_be_negative_or_set_by_a_waiter(self, client, engine, shop):
        riz = composant(client, shop, "Riz", stock=1)
        url = f"/v1/restaurants/composants/{riz}/stock/seuil"
        assert client.put(url, headers=shop["headers"], json={"seuil_alerte": -1}).status_code == 422
        waiter = make_member(client, engine, shop, "waiter")
        assert client.put(url, headers=waiter["headers"], json={"seuil_alerte": 3}).status_code == 403

    def test_the_database_forbids_reserving_more_than_exists(self, engine, client, shop):
        riz = composant(client, shop, "Riz", stock=3)
        with pytest.raises(Exception) as caught:
            sql_as_platform_admin(engine, "update stock_composants set reservee = 99 where composant_id = :c", c=riz)
        assert "check_stock_reservee_within_quantite" in str(caught.value)


class TestRosPayments:
    def due_order(self, client, shop, fulfillment="COUNTER", price=3000, **extra):
        order = ros_order(
            client, shop, [{"product_name": "Plat", "quantity": 1, "unit_price": price, "tax_rate": 0}], fulfillment, **extra
        )
        assert order.status_code == 201, order.text
        return order.json()

    def pay(self, client, shop, invoice_id, amount, method="CASH", headers=None):
        return client.post(
            f"/v1/ros/restaurants/{shop['rid']}/payments",
            headers=headers or shop["headers"],
            json={"invoice_id": invoice_id, "payment_method": method, "amount": amount},
        )

    def test_an_invoice_cannot_be_overpaid(self, client, shop):
        order = self.due_order(client, shop)
        assert self.pay(client, shop, order["invoice_id"], 4000).status_code == 400
        assert self.pay(client, shop, order["invoice_id"], 3000).status_code == 201
        again = self.pay(client, shop, order["invoice_id"], 1)
        assert again.status_code == 400
        invoice = client.get(
            f"/v1/ros/restaurants/{shop['rid']}/invoices/{order['invoice_id']}", headers=shop["headers"]
        ).json()
        assert float(invoice["amount_paid"]) == 3000.0
        assert float(invoice["amount_due"]) == 0.0

    def test_a_split_that_exceeds_the_balance_is_cancelled_entirely(self, client, shop):
        order = self.due_order(client, shop)
        split = client.post(
            f"/v1/ros/restaurants/{shop['rid']}/payments/split",
            headers=shop["headers"],
            json={
                "invoice_id": order["invoice_id"],
                "payments": [{"payment_method": "CASH", "amount": 2000}, {"payment_method": "MTN_MOMO", "amount": 2000}],
            },
        )
        assert split.status_code == 400, split.text
        invoice = client.get(
            f"/v1/ros/restaurants/{shop['rid']}/invoices/{order['invoice_id']}", headers=shop["headers"]
        ).json()
        assert float(invoice["amount_paid"]) == 0.0, "les 2000 en espèces ne doivent pas rester"

    def test_concurrent_payments_cannot_exceed_the_due(self, client, shop):
        order = self.due_order(client, shop)
        from app.main import app

        def pay(_):
            with TestClient(app) as c:
                return self.pay(c, shop, order["invoice_id"], 2000).status_code

        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(pay, range(4)))
        # 3000 dus : un seul règlement de 2000 passe, les autres dépasseraient le reste.
        assert outcomes.count(201) == 1, outcomes
        invoice = client.get(
            f"/v1/ros/restaurants/{shop['rid']}/invoices/{order['invoice_id']}", headers=shop["headers"]
        ).json()
        assert float(invoice["amount_paid"]) == 2000.0

    def test_a_prepaid_order_reaches_the_kitchen_only_when_fully_paid(self, client, shop):
        order = self.due_order(client, shop, price=3000)

        def tickets():
            listed = client.get(f"/v1/ros/restaurants/{shop['rid']}/tickets/KITCHEN", headers=shop["headers"]).json()
            return [t for t in listed if t["order_id"] == order["id"]]

        assert tickets() == []
        assert self.pay(client, shop, order["invoice_id"], 1000).status_code == 201
        assert tickets() == [], "un acompte ne lance pas la cuisine"
        assert self.pay(client, shop, order["invoice_id"], 2000).status_code == 201
        assert len(tickets()) == 1

    def test_the_cash_shift_counts_only_the_operators_own_cash(self, client, engine, shop):
        alice = make_member(client, engine, shop, "cashier")
        bruno = make_member(client, engine, shop, "cashier")
        rid = shop["rid"]
        for member, opening in ((alice, 10000), (bruno, 5000)):
            opened = client.post(f"/v1/ros/restaurants/{rid}/shifts/open", headers=member["headers"], json={"opening_balance": opening})
            assert opened.status_code == 201, opened.text

        self.pay(client, shop, self.due_order(client, shop, price=1000)["invoice_id"], 1000, headers=alice["headers"])
        self.pay(client, shop, self.due_order(client, shop, price=2000)["invoice_id"], 2000, headers=bruno["headers"])
        self.pay(client, shop, self.due_order(client, shop, price=4000)["invoice_id"], 4000, "MTN_MOMO", headers=alice["headers"])

        closed = {}
        for name, member, counted in (("alice", alice, 11000), ("bruno", bruno, 7000)):
            closed[name] = client.post(
                f"/v1/ros/restaurants/{rid}/shifts/close", headers=member["headers"], json={"closing_balance_counted": counted}
            ).json()
        # Alice : 10 000 + 1 000 espèces (le Mobile Money n'entre pas en caisse).
        assert float(closed["alice"]["closing_balance_expected"]) == 11000.0
        assert float(closed["alice"]["variance"]) == 0.0
        # Bruno : 5 000 + 2 000, sans les espèces d'Alice (avant : 8 000 pour les deux).
        assert float(closed["bruno"]["closing_balance_expected"]) == 7000.0
        assert float(closed["bruno"]["variance"]) == 0.0

    def test_a_new_order_reopens_a_settled_session(self, client, shop):
        rid, h = shop["rid"], shop["headers"]
        session = client.post(f"/v1/ros/restaurants/{rid}/sessions", headers=h, json={"table_context": "T1"}).json()["id"]
        first = ros_order(client, shop, [{"product_name": "Bière", "quantity": 1, "unit_price": 1000, "tax_rate": 0}], session_id=session).json()
        assert self.pay(client, shop, first["invoice_id"], 1000).status_code == 201

        second = ros_order(client, shop, [{"product_name": "Brochettes", "quantity": 1, "unit_price": 2000, "tax_rate": 0}], session_id=session)
        assert second.status_code == 201, second.text
        assert second.json()["invoice_id"] == first["invoice_id"], "même addition pour la table"
        invoice = client.get(f"/v1/ros/restaurants/{rid}/invoices/{first['invoice_id']}", headers=h).json()
        assert invoice["status"] == "PARTIALLY_PAID"
        assert float(invoice["amount_due"]) == 2000.0
        active = [s["id"] for s in client.get(f"/v1/ros/restaurants/{rid}/sessions", headers=h).json()]
        assert session in active, "la table doit de nouveau apparaître comme ouverte"
        assert client.post(f"/v1/ros/restaurants/{rid}/sessions/{session}/close", headers=h).status_code == 400


class TestRosOfflineSync:
    def test_one_bad_item_does_not_take_the_rest_with_it(self, client, shop):
        riz = composant(client, shop, "Riz", stock=2)
        ok = lambda n: {  # noqa: E731
            "fulfillment_type": "DINE_IN",
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"product_name": n, "quantity": 1, "unit_price": 500, "tax_rate": 0}],
        }
        too_big = {
            "fulfillment_type": "DINE_IN",
            "idempotency_key": str(uuid.uuid4()),
            "items": [{"product_id": riz, "quantity": 9, "product_name": "Riz", "unit_price": 100}],
        }
        before = reporting_orders(client, shop)
        synced = client.post(
            f"/v1/ros/restaurants/{shop['rid']}/sync",
            headers=shop["headers"],
            json={"orders": [ok("A"), too_big, ok("C")], "payments": []},
        )
        assert synced.status_code == 200, synced.text
        body = synced.json()
        assert body["processed_orders"] == 2
        assert len(body["errors"]) == 1 and "Stock insuffisant" in body["errors"][0]["error"]
        assert reporting_orders(client, shop) == before + 2
        assert stock(client, shop, riz)["quantite"] == 2, "la commande refusée n'a rien sorti"

    def test_replaying_the_same_batch_creates_nothing_twice(self, client, shop):
        batch = {
            "orders": [
                {
                    "fulfillment_type": "DINE_IN",
                    "idempotency_key": str(uuid.uuid4()),
                    "items": [{"product_name": "Eau", "quantity": 1, "unit_price": 500, "tax_rate": 0}],
                }
            ],
            "payments": [],
        }
        client.post(f"/v1/ros/restaurants/{shop['rid']}/sync", headers=shop["headers"], json=batch)
        after_first = reporting_orders(client, shop)
        client.post(f"/v1/ros/restaurants/{shop['rid']}/sync", headers=shop["headers"], json=batch)
        assert reporting_orders(client, shop) == after_first

    def test_a_waiter_cannot_slip_a_free_price_through_the_sync(self, client, engine, shop):
        waiter = make_member(client, engine, shop, "waiter")
        synced = client.post(
            f"/v1/ros/restaurants/{shop['rid']}/sync",
            headers=waiter["headers"],
            json={
                "orders": [
                    {
                        "fulfillment_type": "DINE_IN",
                        "idempotency_key": str(uuid.uuid4()),
                        "items": [{"product_name": "Offert", "quantity": 1, "unit_price": 1, "tax_rate": 0}],
                    }
                ],
                "payments": [],
            },
        )
        assert synced.status_code == 200
        assert synced.json()["processed_orders"] == 0
        assert "management" in synced.json()["errors"][0]["error"].lower()
