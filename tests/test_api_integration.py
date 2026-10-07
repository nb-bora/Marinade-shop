"""Parcours réel de l'API sur PostgreSQL, avec le rôle applicatif sous RLS.

Ces tests attrapent ce que les tests unitaires ne voient pas : une route dont le
service a une autre signature, un schéma de réponse qui ne correspond pas au modèle,
un commit en milieu de requête qui fait perdre le contexte RLS, etc.

Ils s'exécutent uniquement si TEST_DATABASE_URL est défini. Cette URL doit viser une
base JETABLE (son nom contient « test »), migrée à la dernière révision, avec le
rôle APPLICATIF (ni superutilisateur ni propriétaire) : les requêtes sont validées
(`commit`) comme en production, donc les données restent dans cette base.

    TEST_DATABASE_URL=postgresql://marinade_app:...@localhost:5432/marinade_test
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.services.auth_service import _get_totp

PASSWORD = "MotDePasseFort123!"


# --------------------------------------------------------------------------- #
# Infrastructure
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def engine():
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run the PostgreSQL API integration tests.")
    from app.core.config import settings

    name = urlparse(url).path.lstrip("/")
    assert "test" in name, f"refus : la base '{name}' ne ressemble pas à une base de test"
    assert url != settings.DATABASE_URL, "TEST_DATABASE_URL must differ from DATABASE_URL"

    eng = create_engine(url, pool_pre_ping=True)
    with eng.connect() as conn:
        role = conn.execute(
            text("select rolsuper or rolbypassrls from pg_roles where rolname = current_user")
        ).scalar()
        assert not role, "utiliser le rôle applicatif : un superutilisateur ignore la RLS"
        head = conn.execute(text("select version_num from alembic_version")).scalar()
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    expected = ScriptDirectory.from_config(
        Config(os.path.join(root, "alembic.ini"))
    ).get_current_head()
    if head != expected:
        pytest.skip(f"Base de test non migrée : {head!r} au lieu de {expected!r}")
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def client(engine):
    from app.core import database
    from app.main import app

    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    mp = pytest.MonkeyPatch()
    mp.setattr(database, "get_engine", lambda: engine)
    mp.setattr(database, "get_session_local", lambda: session_factory)
    yield TestClient(app)
    mp.undo()


def sql_as_platform_admin(engine, statement, **params):
    """Écrit des données de test que l'API ne sait pas créer (membres, rôle admin)."""
    with engine.begin() as conn:
        conn.execute(text("select set_config('app.is_platform_admin', 'true', true)"))
        conn.execute(text(statement), params)


def register(client, tag):
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    phone = "+2376" + str(uuid.uuid4().int)[:8]
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": PASSWORD,
            "first_name": "Test",
            "last_name": tag,
            "role": "restaurant",
        },
    )
    assert response.status_code == 201, response.text
    return {"email": email, "id": response.json()["id"]}


def login(client, user, code=None):
    body = {"email": user["email"], "password": PASSWORD}
    if code:
        body["two_factor_code"] = code
    return client.post("/v1/auth/login", json=body)


def headers_for(client, user, tenant=None):
    response = login(client, user)
    assert response.status_code == 200, response.text
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    if tenant:
        headers["X-Tenant-ID"] = tenant
    return headers


@pytest.fixture(scope="module")
def owner(client):
    user = register(client, "owner")
    headers = headers_for(client, user)
    response = client.post(
        "/v1/restaurants",
        headers=headers,
        json={"name": "Chez Marinade", "currency": "XAF", "city": "Douala", "taux_service": 10},
    )
    assert response.status_code == 201, response.text
    return {**user, "headers": headers, "rid": response.json()["id"]}


@pytest.fixture(scope="module")
def stranger(client):
    user = register(client, "stranger")
    headers = headers_for(client, user)
    response = client.post("/v1/restaurants", headers=headers, json={"name": "Autre resto"})
    assert response.status_code == 201, response.text
    return {**user, "headers": headers, "rid": response.json()["id"]}


@pytest.fixture(scope="module")
def admin(client, engine):
    user = register(client, "admin")
    with engine.begin() as conn:
        conn.execute(text("update users set role = 'admin' where id = :id"), {"id": user["id"]})
    return {**user, "headers": headers_for(client, user)}


def make_member(client, engine, owner, staff_role):
    user = register(client, staff_role)
    sql_as_platform_admin(
        engine,
        "insert into restaurant_members (id, restaurant_id, user_id, role, staff_role, is_active)"
        " values (:id, :rid, :uid, :role, :role, true)",
        id=str(uuid.uuid4()),
        rid=owner["rid"],
        uid=user["id"],
        role=staff_role,
    )
    return {**user, "headers": headers_for(client, user, tenant=owner["rid"])}


# --------------------------------------------------------------------------- #
# Authentification
# --------------------------------------------------------------------------- #
class TestAuth:
    def test_refresh_rotates_the_token_and_revokes_the_old_one(self, client):
        user = register(client, "refresh")
        tokens = login(client, user).json()
        rotated = client.post("/v1/auth/refresh", params={"refresh_token": tokens["refresh_token"]})
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["refresh_token"] != tokens["refresh_token"]
        replay = client.post("/v1/auth/refresh", params={"refresh_token": tokens["refresh_token"]})
        assert replay.status_code == 401

    def test_two_factor_end_to_end(self, client):
        user = register(client, "twofa")
        headers = headers_for(client, user)
        setup = client.post("/v1/auth/2fa/setup", headers=headers)
        assert setup.status_code == 200, setup.text
        secret, codes = setup.json()["secret"], setup.json()["recovery_codes"]

        assert client.post("/v1/auth/2fa/confirm", headers=headers, json={"token": "000000"}).status_code == 400
        assert (
            client.post(
                "/v1/auth/2fa/confirm", headers=headers, json={"token": _get_totp(secret).now()}
            ).status_code
            == 200
        )

        missing = login(client, user)
        assert missing.status_code == 401
        assert missing.json()["details"] == {"two_factor_required": True}
        assert login(client, user, "000000").status_code == 401
        assert login(client, user, _get_totp(secret).now()).status_code == 200
        assert login(client, user, codes[0]).status_code == 200
        assert login(client, user, codes[0]).status_code == 401, "code de secours à usage unique"

    def test_forgot_password_reveals_nothing(self, client):
        user = register(client, "forgot")
        response = client.post("/v1/auth/forgot-password", json={"email": user["email"]})
        assert response.json() == {"message": "Reset email sent"}


# --------------------------------------------------------------------------- #
# Catalogue : menus, catégories, composants, plats, nomenclature, boissons, tables
# --------------------------------------------------------------------------- #
class TestCatalogue:
    def test_category_is_created_from_the_url_alone(self, client, owner):
        rid, h = owner["rid"], owner["headers"]
        menu = client.post(f"/v1/restaurants/{rid}/menus", headers=h, json={"name": "Menu du midi"})
        assert menu.status_code == 201, menu.text
        menu_id = menu.json()["id"]

        created = client.post(
            f"/v1/restaurants/menus/{menu_id}/categories",
            headers=h,
            json={"name": "Entrées", "ordre": 1},
        )
        assert created.status_code == 201, created.text
        assert created.json()["menu_id"] == menu_id
        assert created.json()["restaurant_id"] == rid

        duplicate_order = client.post(
            f"/v1/restaurants/menus/{menu_id}/categories", headers=h, json={"name": "Autre", "ordre": 1}
        )
        assert duplicate_order.status_code == 400

        wrong_menu = client.post(
            f"/v1/restaurants/menus/{menu_id}/categories",
            headers=h,
            json={"name": "Plats", "ordre": 2, "menu_id": str(uuid.uuid4())},
        )
        assert wrong_menu.status_code == 400

        listed = client.get(f"/v1/restaurants/menus/{menu_id}/categories", headers=h)
        assert [c["name"] for c in listed.json()] == ["Entrées"]

    def test_unknown_menu_is_404(self, client, owner):
        response = client.post(
            f"/v1/restaurants/menus/{uuid.uuid4()}/categories",
            headers=owner["headers"],
            json={"name": "X"},
        )
        assert response.status_code == 404

    def test_plat_with_a_bill_of_materials(self, client, owner):
        rid, h = owner["rid"], owner["headers"]

        def composant(nom):
            r = client.post(
                f"/v1/restaurants/{rid}/composants",
                headers=h,
                json={"nom": nom, "type": "base", "prix_supplement": 0},
            )
            assert r.status_code == 201, r.text
            return r.json()["id"]

        riz, poulet, sauce = composant("Riz"), composant("Poulet"), composant("Sauce tomate")

        plat = client.post(
            f"/v1/restaurants/{rid}/plats",
            headers=h,
            json={"nom": "Riz sauce", "prix": 2500, "composant_ids": [riz]},
        )
        assert plat.status_code == 201, plat.text
        plat_id = plat.json()["id"]

        lines = client.get(f"/v1/restaurants/plats/{plat_id}/composants", headers=h)
        assert lines.status_code == 200, lines.text
        assert [(ln["composant_id"], float(ln["quantite"])) for ln in lines.json()] == [(riz, 1.0)]

        added = client.post(
            f"/v1/restaurants/plats/{plat_id}/composants",
            headers=h,
            json={"composant_id": poulet, "quantite": 2},
        )
        assert added.status_code == 201, added.text
        assert added.json()["plat_id"] == plat_id
        assert float(added.json()["quantite"]) == 2.0

        duplicate = client.post(
            f"/v1/restaurants/plats/{plat_id}/composants", headers=h, json={"composant_id": poulet}
        )
        assert duplicate.status_code == 409

        updated = client.put(
            f"/v1/restaurants/plats/{plat_id}/composants/{poulet}", headers=h, json={"quantite": 3}
        )
        assert updated.status_code == 200, updated.text
        assert float(updated.json()["quantite"]) == 3.0

        replaced = client.put(
            f"/v1/restaurants/plats/{plat_id}/composants",
            headers=h,
            json=[{"composant_id": sauce, "quantite": 1}, {"composant_id": riz, "quantite": 4}],
        )
        assert replaced.status_code == 200, replaced.text
        assert [ln["composant_id"] for ln in replaced.json()] == [sauce, riz]

        twice = client.put(
            f"/v1/restaurants/plats/{plat_id}/composants",
            headers=h,
            json=[{"composant_id": riz}, {"composant_id": riz}],
        )
        assert twice.status_code in (400, 422)

        assert client.delete(f"/v1/restaurants/plats/{plat_id}/composants/{riz}", headers=h).status_code == 204
        assert client.delete(f"/v1/restaurants/plats/{plat_id}/composants/{riz}", headers=h).status_code == 404

        cleared = client.put(f"/v1/restaurants/plats/{plat_id}", headers=h, json={"composant_ids": []})
        assert cleared.status_code == 200, cleared.text
        assert client.get(f"/v1/restaurants/plats/{plat_id}/composants", headers=h).json() == []

    def test_plat_cannot_use_another_restaurants_composant(self, client, owner, stranger):
        foreign = client.post(
            f"/v1/restaurants/{stranger['rid']}/composants",
            headers=stranger["headers"],
            json={"nom": "Secret", "type": "base"},
        ).json()["id"]
        response = client.post(
            f"/v1/restaurants/{owner['rid']}/plats",
            headers=owner["headers"],
            json={"nom": "Piégé", "prix": 1000, "composant_ids": [foreign]},
        )
        assert response.status_code == 400

    def test_boisson_and_tables(self, client, owner):
        rid, h = owner["rid"], owner["headers"]
        assert (
            client.post(
                f"/v1/restaurants/{rid}/boissons", headers=h, json={"nom": "Bière", "prix": 1000}
            ).status_code
            == 201
        )
        table = client.post(
            f"/v1/restaurants/{rid}/tables", headers=h, json={"numero": "T1", "capacite": 4}
        )
        assert table.status_code == 201, table.text
        table_id = table.json()["id"]
        assert any(t["id"] == table_id for t in client.get(f"/v1/restaurants/{rid}/tables/free", headers=h).json())
        updated = client.put(f"/v1/restaurants/tables/{table_id}", headers=h, json={"capacite": 6})
        assert updated.status_code == 200 and updated.json()["capacite"] == 6
        assert client.put(f"/v1/restaurants/tables/{uuid.uuid4()}", headers=h, json={"capacite": 2}).status_code == 404


# --------------------------------------------------------------------------- #
# ROS : de la commande à l'encaissement, par l'API seule
# --------------------------------------------------------------------------- #
ITEMS = [
    {"product_name": "Poulet braisé", "quantity": 1, "unit_price": 4000, "tax_rate": 19.25, "destination_station": "KITCHEN"},
    {"product_name": "Jus d'ananas", "quantity": 2, "unit_price": 1500, "destination_station": "BAR"},
]


class TestRos:
    def test_dine_in_order_is_payable_with_the_returned_invoice(self, client, owner):
        rid, h = owner["rid"], owner["headers"]
        session = client.post(f"/v1/ros/restaurants/{rid}/sessions", headers=h, json={"table_context": "Terrasse"})
        assert session.status_code == 201, session.text
        session_id = session.json()["id"]

        order = client.post(
            f"/v1/ros/restaurants/{rid}/orders",
            headers=h,
            json={"session_id": session_id, "fulfillment_type": "DINE_IN", "items": ITEMS},
        )
        assert order.status_code == 201, order.text
        body = order.json()
        assert body["status"] == "CONFIRMED"
        assert float(body["total_amount"]) == 8347.50
        assert body["invoice_id"] and body["invoice_number"].startswith("INV-")

        invoice = client.get(f"/v1/ros/restaurants/{rid}/invoices/{body['invoice_id']}", headers=h)
        assert invoice.status_code == 200, invoice.text
        assert float(invoice.json()["amount_due"]) == 8347.50

        by_session = client.get(f"/v1/ros/restaurants/{rid}/sessions/{session_id}/invoice", headers=h)
        assert by_session.status_code == 200 and by_session.json()["id"] == body["invoice_id"]

        # La session ne peut pas être fermée tant qu'il reste un solde dû.
        assert client.post(f"/v1/ros/restaurants/{rid}/sessions/{session_id}/close", headers=h).status_code in (400, 409, 422)

        payment = client.post(
            f"/v1/ros/restaurants/{rid}/payments",
            headers=h,
            json={"invoice_id": body["invoice_id"], "payment_method": "CASH", "amount": 8347.50},
        )
        assert payment.status_code == 201, payment.text
        assert payment.json()["status"] == "SUCCEEDED"

        settled = client.get(f"/v1/ros/restaurants/{rid}/invoices/{body['invoice_id']}", headers=h).json()
        assert settled["status"] == "PAID" and float(settled["amount_due"]) == 0.0

        closed = client.post(f"/v1/ros/restaurants/{rid}/sessions/{session_id}/close", headers=h)
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "CLOSED"

    def test_replaying_an_order_returns_the_same_invoice(self, client, owner):
        rid, h = owner["rid"], owner["headers"]
        key = str(uuid.uuid4())
        payload = {"fulfillment_type": "COUNTER", "items": [ITEMS[1]]}
        first = client.post(f"/v1/ros/restaurants/{rid}/orders", headers={**h, "X-Idempotency-Key": key}, json=payload)
        again = client.post(f"/v1/ros/restaurants/{rid}/orders", headers={**h, "X-Idempotency-Key": key}, json=payload)
        assert first.status_code == again.status_code == 201
        assert first.json()["id"] == again.json()["id"]
        assert first.json()["invoice_id"] == again.json()["invoice_id"]

    def test_cash_shift_variance_and_group_reporting(self, client, owner):
        rid, h = owner["rid"], owner["headers"]
        assert client.post(f"/v1/ros/restaurants/{rid}/shifts/open", headers=h, json={"opening_balance": 15000}).status_code == 201
        assert client.post(f"/v1/ros/restaurants/{rid}/shifts/open", headers=h, json={"opening_balance": 1}).status_code == 409
        closed = client.post(f"/v1/ros/restaurants/{rid}/shifts/close", headers=h, json={"closing_balance_counted": 14500})
        assert closed.status_code == 200, closed.text
        assert float(closed.json()["variance"]) == -500.0
        report = client.get("/v1/ros/group/reporting", headers=h)
        assert report.status_code == 200, report.text
        assert report.json()["total_restaurants"] == 1
        assert report.json()["total_orders"] >= 1

    def test_foreign_invoice_is_not_found(self, client, owner, stranger):
        rid, h = owner["rid"], owner["headers"]
        order = client.post(
            f"/v1/ros/restaurants/{rid}/orders", headers=h, json={"fulfillment_type": "COUNTER", "items": [ITEMS[1]]}
        ).json()
        mine = client.get(f"/v1/ros/restaurants/{rid}/invoices/{order['invoice_id']}", headers=h)
        assert mine.status_code == 200
        # Même identifiant, interrogé depuis le restaurant d'un autre : introuvable.
        other = client.get(
            f"/v1/ros/restaurants/{stranger['rid']}/invoices/{order['invoice_id']}", headers=stranger["headers"]
        )
        assert other.status_code == 404


# --------------------------------------------------------------------------- #
# Isolation et rôles d'équipe
# --------------------------------------------------------------------------- #
class TestIsolationAndRoles:
    @pytest.mark.parametrize(
        "path",
        [
            "/v1/ros/restaurants/{rid}/sessions",
            "/v1/ros/restaurants/{rid}/tickets/KITCHEN",
            "/v1/restaurants/{rid}",
            "/v1/restaurants/{rid}/plats",
            "/v1/restaurants/{rid}/stock",
            "/v1/reservations/restaurants/{rid}/reservations",
        ],
    )
    def test_another_owner_cannot_read_my_restaurant(self, client, owner, stranger, path):
        response = client.get(path.format(rid=owner["rid"]), headers=stranger["headers"])
        assert response.status_code == 404, f"{path} -> {response.status_code}"

    def test_another_owner_cannot_write_in_my_restaurant(self, client, owner, stranger):
        response = client.post(
            f"/v1/ros/restaurants/{owner['rid']}/orders",
            headers=stranger["headers"],
            json={"items": [ITEMS[1]]},
        )
        assert response.status_code == 404

    def test_group_reporting_only_counts_my_restaurants(self, client, stranger):
        assert client.get("/v1/ros/group/reporting", headers=stranger["headers"]).json()["total_restaurants"] == 1

    def test_waiter_takes_orders_but_cannot_cash_or_price(self, client, engine, owner):
        waiter = make_member(client, engine, owner, "waiter")
        rid = owner["rid"]
        order = client.post(
            f"/v1/ros/restaurants/{rid}/orders",
            headers=waiter["headers"],
            json={"fulfillment_type": "DINE_IN", "items": [ITEMS[1]]},
        )
        assert order.status_code == 201, order.text
        assert client.post(f"/v1/ros/restaurants/{rid}/shifts/open", headers=waiter["headers"], json={"opening_balance": 1}).status_code == 403
        assert (
            client.post(
                f"/v1/ros/restaurants/{rid}/payments",
                headers=waiter["headers"],
                json={"invoice_id": order.json()["invoice_id"], "payment_method": "CASH", "amount": 1},
            ).status_code
            == 403
        )
        assert client.post(f"/v1/restaurants/{rid}/boissons", headers=waiter["headers"], json={"nom": "X", "prix": 1}).status_code == 403
        assert client.get(f"/v1/ros/restaurants/{rid}/tickets/BAR", headers=waiter["headers"]).status_code == 200

    def test_cashier_cashes_but_cannot_decide_refunds(self, client, engine, owner):
        cashier = make_member(client, engine, owner, "cashier")
        rid = owner["rid"]
        order = client.post(
            f"/v1/ros/restaurants/{rid}/orders", headers=owner["headers"], json={"fulfillment_type": "COUNTER", "items": [ITEMS[1]]}
        ).json()
        paid = client.post(
            f"/v1/ros/restaurants/{rid}/payments",
            headers=cashier["headers"],
            json={"invoice_id": order["invoice_id"], "payment_method": "CASH", "amount": 3570},
        )
        assert paid.status_code == 201, paid.text
        refund_path = f"/v1/restaurants/commandes/{uuid.uuid4()}/refunds/{uuid.uuid4()}/approve"
        assert client.post(refund_path, headers=cashier["headers"]).status_code in (403, 404)


# --------------------------------------------------------------------------- #
# Réservations et liste d'attente
# --------------------------------------------------------------------------- #
class TestReservations:
    def test_reservation_lifecycle(self, client, owner, stranger):
        rid, h = owner["rid"], owner["headers"]
        table = client.post(f"/v1/restaurants/{rid}/tables", headers=h, json={"numero": "R1", "capacite": 4}).json()["id"]
        when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

        created = client.post(
            f"/v1/reservations/restaurants/{rid}/reservations",
            headers=h,
            json={
                "customer_name": "Mme Ngo",
                "customer_phone": "+237655000000",
                "party_size": 3,
                "reservation_date": when,
                "table_id": table,
                "invites": [{"name": "Paul", "is_vegetarian": True}],
            },
        )
        assert created.status_code == 201, created.text
        res = created.json()
        assert res["status"] == "pending"
        assert [g["name"] for g in res["invites"]] == ["Paul"]
        res_id = res["id"]

        assert client.get(f"/v1/reservations/{res_id}", headers=h).json()["id"] == res_id
        assert [r["id"] for r in client.get(f"/v1/reservations/restaurants/{rid}/reservations", headers=h).json()] == [res_id]
        updated = client.put(f"/v1/reservations/{res_id}", headers=h, json={"party_size": 5})
        assert updated.status_code == 200 and updated.json()["party_size"] == 5
        assert client.post(f"/v1/reservations/{res_id}/confirm", headers=h, json={"notes": "Confirmée"}).json()["status"] == "confirmed"
        assert client.post(f"/v1/reservations/{res_id}/check-in", headers=h).json()["status"] == "checked_in"
        cancelled = client.post(f"/v1/reservations/{res_id}/cancel", headers=h, json={"reason": "Imprévu"})
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert client.delete(f"/v1/reservations/{res_id}", headers=h).status_code == 204
        assert client.get(f"/v1/reservations/{res_id}", headers=h).status_code == 404

    def test_reservation_cannot_use_another_restaurants_table(self, client, owner, stranger):
        foreign_table = client.post(
            f"/v1/restaurants/{stranger['rid']}/tables", headers=stranger["headers"], json={"numero": "S1", "capacite": 2}
        ).json()["id"]
        response = client.post(
            f"/v1/reservations/restaurants/{owner['rid']}/reservations",
            headers=owner["headers"],
            json={
                "customer_name": "X",
                "party_size": 2,
                "reservation_date": datetime.now(timezone.utc).isoformat(),
                "table_id": foreign_table,
            },
        )
        assert response.status_code == 400

    def test_waitlist(self, client, owner):
        rid, h = owner["rid"], owner["headers"]
        first = client.post(f"/v1/reservations/restaurants/{rid}/waitlist", headers=h, json={"customer_name": "A", "party_size": 2})
        second = client.post(f"/v1/reservations/restaurants/{rid}/waitlist", headers=h, json={"customer_name": "B", "party_size": 4})
        assert first.status_code == second.status_code == 201, (first.text, second.text)
        assert (first.json()["position"], second.json()["position"]) == (1, 2)
        assert [e["customer_name"] for e in client.get(f"/v1/reservations/restaurants/{rid}/waitlist", headers=h).json()] == ["A", "B"]
        seated = client.post(f"/v1/reservations/waitlist/{first.json()['id']}/seat", headers=h)
        assert seated.status_code == 200 and seated.json()["status"] == "SEATED"
        assert client.delete(f"/v1/reservations/waitlist/{second.json()['id']}", headers=h, params={"reason": "parti"}).status_code == 204


# --------------------------------------------------------------------------- #
# Commandes historiques et remboursements
# --------------------------------------------------------------------------- #
class TestRefunds:
    @pytest.fixture(scope="class")
    def served_commande(self, client, owner):
        rid, h = owner["rid"], owner["headers"]
        plat = client.post(f"/v1/restaurants/{rid}/plats", headers=h, json={"nom": "Ndolé", "prix": 5000}).json()["id"]
        commande = client.post(f"/v1/restaurants/{rid}/commandes", headers=h, json={})
        assert commande.status_code == 201, commande.text
        commande_id = commande.json()["id"]
        item = client.post(f"/v1/restaurants/commandes/{commande_id}/items", headers=h, json={"plat_id": plat, "quantite": 2})
        assert item.status_code == 201, item.text
        served = client.put(f"/v1/restaurants/commandes/{commande_id}", headers=h, json={"statut": "servie"})
        assert served.status_code == 200, served.text
        assert client.get(f"/v1/restaurants/commandes/{commande_id}", headers=h).status_code == 200
        assert client.get(f"/v1/restaurants/{rid}/commandes/active", headers=h).status_code == 200
        return commande_id

    def test_commande_unknown_returns_404_not_a_crash(self, client, owner):
        response = client.put(
            f"/v1/restaurants/commandes/{uuid.uuid4()}", headers=owner["headers"], json={"statut": "servie"}
        )
        assert response.status_code == 404

    def test_request_list_approve_and_reject(self, client, owner, served_commande):
        h, cid = owner["headers"], served_commande
        request = client.post(
            f"/v1/restaurants/commandes/{cid}/refunds", headers=h, json={"montant": 1000, "raison": "Plat froid"}
        )
        assert request.status_code == 201, request.text
        refund = request.json()
        assert refund["statut"] == "requested"
        assert float(refund["montant"]) == 1000.0
        assert refund["restaurant_id"] == owner["rid"]
        assert refund["effectue_par_id"] == owner["id"]

        listed = client.get(f"/v1/restaurants/commandes/{cid}/refunds", headers=h)
        assert listed.status_code == 200 and [r["id"] for r in listed.json()] == [refund["id"]]

        approved = client.post(f"/v1/restaurants/commandes/{cid}/refunds/{refund['id']}/approve", headers=h)
        assert approved.status_code == 200, approved.text
        assert approved.json()["statut"] == "approved"
        assert approved.json()["traite_par_id"] == owner["id"]

        again = client.post(f"/v1/restaurants/commandes/{cid}/refunds/{refund['id']}/approve", headers=h)
        assert again.status_code in (400, 409, 422), "une demande déjà traitée ne se retraite pas"

        second = client.post(
            f"/v1/restaurants/commandes/{cid}/refunds", headers=h, json={"montant": 500, "raison": "Erreur"}
        ).json()
        rejected = client.post(
            f"/v1/restaurants/commandes/{cid}/refunds/{second['id']}/reject", headers=h, params={"reason": "Non justifié"}
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["statut"] == "rejected"

    def test_refund_rules(self, client, owner, served_commande):
        h, cid = owner["headers"], served_commande
        too_much = client.post(
            f"/v1/restaurants/commandes/{cid}/refunds", headers=h, json={"montant": 99999999, "raison": "x"}
        )
        assert too_much.status_code in (400, 422)
        mismatch = client.post(
            f"/v1/restaurants/commandes/{cid}/refunds",
            headers=h,
            json={"commande_id": str(uuid.uuid4()), "montant": 10, "raison": "x"},
        )
        assert mismatch.status_code == 400

    def test_a_refund_cannot_be_processed_through_another_commande(self, client, owner, served_commande):
        h = owner["headers"]
        refund = client.post(
            f"/v1/restaurants/commandes/{served_commande}/refunds", headers=h, json={"montant": 10, "raison": "x"}
        ).json()
        other = client.post(f"/v1/restaurants/{owner['rid']}/commandes", headers=h, json={}).json()["id"]
        wrong = client.post(f"/v1/restaurants/commandes/{other}/refunds/{refund['id']}/approve", headers=h)
        assert wrong.status_code == 404


# --------------------------------------------------------------------------- #
# Abonnements et transactions
# --------------------------------------------------------------------------- #
class TestSubscriptionsAndTransactions:
    @pytest.fixture(scope="class")
    def subscription(self, client, admin, owner):
        tier = client.post(
            "/v1/subscriptions/tiers",
            headers=admin["headers"],
            json={"name": f"Starter-{uuid.uuid4().hex[:6]}", "daily_limit_fcfa": 50000, "monthly_price_fcfa": 10000, "annual_price_fcfa": 100000},
        )
        assert tier.status_code == 201, tier.text
        created = client.post(
            "/v1/subscriptions",
            headers=admin["headers"],
            json={
                "user_id": owner["id"],
                "restaurant_id": owner["rid"],
                "tier_id": tier.json()["id"],
                "status": "active",
                "start_date": date.today().isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        sub_id = created.json()["id"]
        balance = client.post(
            f"/v1/subscriptions/{sub_id}/balances",
            headers=admin["headers"],
            json={"subscription_id": sub_id, "balance_date": date.today().isoformat(), "initial_balance_fcfa": 50000, "used_balance_fcfa": 0},
        )
        assert balance.status_code == 201, balance.text
        return sub_id

    def test_status_update(self, client, admin, subscription):
        h = admin["headers"]
        assert client.put(f"/v1/subscriptions/{subscription}/status", headers=h, params={"status": "suspended"}).json()["status"] == "suspended"
        assert client.put(f"/v1/subscriptions/{subscription}/status", headers=h, params={"status": "active"}).json()["status"] == "active"
        assert client.put(f"/v1/subscriptions/{subscription}/status", headers=h, params={"status": "bogus"}).status_code == 422
        assert client.put(f"/v1/subscriptions/{uuid.uuid4()}/status", headers=h, params={"status": "active"}).status_code == 404

    def test_transaction_lifecycle(self, client, owner, subscription):
        h, rid = owner["headers"], owner["rid"]
        key = f"tx-{uuid.uuid4().hex}"
        payload = {
            "subscription_id": subscription,
            "restaurant_id": rid,
            "amount_fcfa": 1500,
            "idempotency_key": key,
            "pos_transaction_id": f"pos-{uuid.uuid4().hex[:10]}",
        }
        created = client.post("/v1/transactions", headers=h, json=payload)
        assert created.status_code == 201, created.text
        replay = client.post("/v1/transactions", headers=h, json=payload)
        assert replay.json()["id"] == created.json()["id"], "idempotence"
        tx_id = created.json()["id"]

        assert client.get(f"/v1/transactions/{tx_id}", headers=h).json()["id"] == tx_id
        assert [t["id"] for t in client.get(f"/v1/transactions/subscription/{subscription}", headers=h).json()] == [tx_id]
        assert tx_id in [t["id"] for t in client.get("/v1/transactions/my", headers=h).json()]
        by_pos = client.get(f"/v1/transactions/pos/{payload['pos_transaction_id']}", headers=h)
        assert by_pos.status_code == 200 and by_pos.json()["id"] == tx_id

        too_big = client.post("/v1/transactions", headers=h, json={**payload, "amount_fcfa": 10_000_000, "idempotency_key": key + "-big", "pos_transaction_id": None})
        assert too_big.status_code == 400

    def test_balances_and_transactions_are_private(self, client, owner, stranger, subscription):
        sh = stranger["headers"]
        assert client.get(f"/v1/subscriptions/{subscription}/balances", headers=sh).status_code in (403, 404)
        assert client.get(f"/v1/transactions/subscription/{subscription}", headers=sh).status_code in (403, 404)
        tx = client.post(
            "/v1/transactions",
            headers=owner["headers"],
            json={"subscription_id": subscription, "restaurant_id": owner["rid"], "amount_fcfa": 100, "idempotency_key": f"p-{uuid.uuid4().hex}"},
        ).json()["id"]
        assert client.get(f"/v1/transactions/{tx}", headers=sh).status_code in (403, 404)
        forged = client.post(
            "/v1/transactions",
            headers=sh,
            json={"subscription_id": subscription, "restaurant_id": owner["rid"], "amount_fcfa": 100, "idempotency_key": f"f-{uuid.uuid4().hex}"},
        )
        assert forged.status_code in (403, 404)


# --------------------------------------------------------------------------- #
# Toutes les autres routes : aucune ne doit répondre 500
# --------------------------------------------------------------------------- #
def no_server_error(response, *expected):
    where = f"{response.request.method} {response.request.url.path}"
    detail = f"{where} -> {response.status_code} {response.text[:300]}"
    assert response.status_code < 500, detail
    if expected:
        assert response.status_code in expected, detail
    return response


class TestRestaurantRoutes:
    def test_restaurant_profile(self, client, owner):
        h, rid = owner["headers"], owner["rid"]
        assert no_server_error(client.get("/v1/restaurants/me", headers=h), 200).json()["id"] == rid
        no_server_error(client.get(f"/v1/restaurants/{rid}", headers=h), 200)
        renamed = no_server_error(
            client.put(f"/v1/restaurants/{rid}", headers=h, json={"name": "Chez Marinade 2"}), 200
        )
        assert renamed.json()["name"] == "Chez Marinade 2"

    def test_menu_category_composant_boisson_updates(self, client, owner):
        h, rid = owner["headers"], owner["rid"]
        menu = client.post(f"/v1/restaurants/{rid}/menus", headers=h, json={"name": "Soir"}).json()["id"]
        no_server_error(client.get(f"/v1/restaurants/{rid}/menus", headers=h), 200)
        no_server_error(client.get(f"/v1/restaurants/menus/{menu}", headers=h), 200)
        no_server_error(client.put(f"/v1/restaurants/menus/{menu}", headers=h, json={"actif": False}), 200)
        category = client.post(
            f"/v1/restaurants/menus/{menu}/categories", headers=h, json={"name": "Desserts", "ordre": 3}
        ).json()["id"]
        no_server_error(
            client.put(f"/v1/restaurants/categories/{category}", headers=h, json={"name": "Douceurs"}), 200
        )

        composant = client.post(
            f"/v1/restaurants/{rid}/composants", headers=h, json={"nom": "Plantain", "type": "accompagnement"}
        ).json()["id"]
        no_server_error(client.get(f"/v1/restaurants/{rid}/composants", headers=h), 200)
        no_server_error(
            client.put(f"/v1/restaurants/composants/{composant}", headers=h, json={"prix_supplement": 300}), 200
        )

        boisson = client.post(
            f"/v1/restaurants/{rid}/boissons", headers=h, json={"nom": "Bissap", "prix": 500}
        ).json()["id"]
        no_server_error(client.get(f"/v1/restaurants/{rid}/boissons", headers=h), 200)
        no_server_error(client.get(f"/v1/restaurants/boissons/{boisson}", headers=h), 200)
        no_server_error(client.put(f"/v1/restaurants/boissons/{boisson}", headers=h, json={"prix": 600}), 200)

        table = client.post(
            f"/v1/restaurants/{rid}/tables", headers=h, json={"numero": "Z9", "capacite": 2}
        ).json()["id"]
        no_server_error(client.get(f"/v1/restaurants/{rid}/tables", headers=h), 200)
        no_server_error(client.get(f"/v1/restaurants/tables/{table}", headers=h), 200)

        plat = client.post(f"/v1/restaurants/{rid}/plats", headers=h, json={"nom": "Eru", "prix": 3000}).json()["id"]
        no_server_error(client.get(f"/v1/restaurants/{rid}/plats", headers=h), 200)
        no_server_error(client.get(f"/v1/restaurants/plats/{plat}", headers=h), 200)
        no_server_error(client.put(f"/v1/restaurants/plats/{plat}", headers=h, json={"prix": 3500}), 200)
        no_server_error(client.get(f"/v1/restaurants/plats/{uuid.uuid4()}", headers=h), 404)

    def test_stock_and_combinations(self, client, owner):
        h, rid = owner["headers"], owner["rid"]
        riz = client.post(f"/v1/restaurants/{rid}/composants", headers=h, json={"nom": "Riz S", "type": "base"}).json()["id"]
        sauce = client.post(
            f"/v1/restaurants/{rid}/composants", headers=h, json={"nom": "Sauce S", "type": "sauce", "prix_supplement": 200}
        ).json()["id"]
        for kind, qty in (("entree", 50), ("perte", 2), ("ajustement", 40)):
            no_server_error(
                client.post(
                    f"/v1/restaurants/composants/{riz}/stock/mouvements", headers=h, json={"type": kind, "quantite": qty}
                ),
                200,
                201,
            )
        stock = no_server_error(client.get(f"/v1/restaurants/{rid}/stock", headers=h), 200).json()
        riz_stock = next(s for s in stock if s["composant_id"] == riz)
        assert float(riz_stock["quantite"]) == 40.0
        no_server_error(
            client.post(
                f"/v1/restaurants/composants/{sauce}/stock/mouvements", headers=h, json={"type": "entree", "quantite": 20}
            ),
            200,
            201,
        )

        combo = no_server_error(
            client.post(
                f"/v1/restaurants/{rid}/combinaisons",
                headers=h,
                json={"nom": "Riz sauce", "prix": 3500, "composant_ids": [riz, sauce]},
            ),
            201,
        ).json()["id"]
        no_server_error(client.get(f"/v1/restaurants/{rid}/combinaisons", headers=h), 200)
        recommended = no_server_error(
            client.get(f"/v1/restaurants/{rid}/combinaisons/recommandations", headers=h), 200
        ).json()
        assert combo in [c["id"] for c in recommended]
        no_server_error(client.put(f"/v1/restaurants/combinaisons/{combo}", headers=h, json={"prix": 3800}), 200)

    def test_legacy_commande_with_combination_and_cancellation(self, client, owner):
        h, rid = owner["headers"], owner["rid"]
        riz = client.post(f"/v1/restaurants/{rid}/composants", headers=h, json={"nom": "Riz L", "type": "base"}).json()["id"]
        client.post(f"/v1/restaurants/composants/{riz}/stock/mouvements", headers=h, json={"type": "entree", "quantite": 10})
        combo = client.post(
            f"/v1/restaurants/{rid}/combinaisons", headers=h, json={"nom": "Riz seul", "prix": 1500, "composant_ids": [riz]}
        ).json()["id"]
        boisson = client.post(f"/v1/restaurants/{rid}/boissons", headers=h, json={"nom": "Eau", "prix": 300}).json()["id"]

        commande = client.post(f"/v1/restaurants/{rid}/commandes", headers=h, json={}).json()["id"]
        no_server_error(
            client.post(f"/v1/restaurants/commandes/{commande}/items", headers=h, json={"combinaison_id": combo, "quantite": 2}),
            201,
        )
        no_server_error(
            client.post(f"/v1/restaurants/commandes/{commande}/items", headers=h, json={"boisson_id": boisson, "quantite": 1}),
            201,
        )
        items = no_server_error(client.get(f"/v1/restaurants/commandes/{commande}/items", headers=h), 200).json()
        assert len(items) == 2
        assert no_server_error(client.get(f"/v1/restaurants/{rid}/commandes", headers=h), 200).json()
        # Le client ne peut pas marquer une commande payée : seul le webhook signé le fait.
        no_server_error(
            client.put(f"/v1/restaurants/commandes/{commande}", headers=h, json={"statut": "payee"}), 400, 403, 409, 422
        )
        no_server_error(
            client.put(f"/v1/restaurants/commandes/{commande}", headers=h, json={"statut": "annulee"}), 200
        )


class TestRosOtherRoutes:
    def test_customers_tickets_split_sync_and_procurement(self, client, owner):
        h, rid = owner["headers"], owner["rid"]
        customer = no_server_error(
            client.post(
                f"/v1/ros/restaurants/{rid}/customers",
                headers=h,
                json={"customer_type": "VIP", "name": "M. Eto'o", "phone": "+237677000000"},
            ),
            201,
        )
        assert customer.json()["customer_type"] == "VIP"

        order = client.post(
            f"/v1/ros/restaurants/{rid}/orders", headers=h, json={"fulfillment_type": "DINE_IN", "items": [ITEMS[0]]}
        ).json()
        tickets = no_server_error(client.get(f"/v1/ros/restaurants/{rid}/tickets/KITCHEN", headers=h), 200).json()
        ticket = next(t for t in tickets if t["order_id"] == order["id"])
        for new_status in ("IN_PREPARATION", "READY", "SERVED"):
            moved = no_server_error(
                client.put(
                    f"/v1/ros/restaurants/{rid}/tickets/{ticket['id']}/status", headers=h, json={"status": new_status}
                ),
                200,
            )
            assert moved.json()["status"] == new_status
        no_server_error(client.get(f"/v1/ros/restaurants/{rid}/sessions", headers=h), 200)

        total = float(order["total_amount"])
        split = no_server_error(
            client.post(
                f"/v1/ros/restaurants/{rid}/payments/split",
                headers=h,
                json={
                    "invoice_id": order["invoice_id"],
                    "payments": [
                        {"payment_method": "CASH", "amount": 3000},
                        {"payment_method": "MTN_MOMO", "amount": round(total - 3000, 2), "external_reference": "MOMO-1"},
                    ],
                },
            ),
            201,
        )
        assert len(split.json()) == 2
        invoice = client.get(f"/v1/ros/restaurants/{rid}/invoices/{order['invoice_id']}", headers=h).json()
        assert invoice["status"] == "PAID"

        batch = no_server_error(
            client.post(
                f"/v1/ros/restaurants/{rid}/sync",
                headers=h,
                json={
                    "orders": [
                        {"fulfillment_type": "DINE_IN", "items": [ITEMS[1]], "idempotency_key": str(uuid.uuid4())}
                    ],
                    "payments": [],
                },
            ),
            200,
        )
        assert batch.json()["processed_orders"] == 1
        assert batch.json()["errors"] == []
        no_server_error(client.get(f"/v1/ros/restaurants/{rid}/procurement/suggestions", headers=h), 200)

    def test_paying_more_than_due_does_not_crash(self, client, owner):
        h, rid = owner["headers"], owner["rid"]
        order = client.post(
            f"/v1/ros/restaurants/{rid}/orders", headers=h, json={"fulfillment_type": "COUNTER", "items": [ITEMS[1]]}
        ).json()
        response = client.post(
            f"/v1/ros/restaurants/{rid}/payments",
            headers=h,
            json={"invoice_id": order["invoice_id"], "payment_method": "CASH", "amount": 99999999},
        )
        no_server_error(response)


class TestPlatformRoutes:
    def test_admin_users(self, client, admin):
        h = admin["headers"]
        me = no_server_error(client.get("/v1/users/me", headers=h), 200)
        assert me.json()["id"] == admin["id"]
        new_user = {
            "email": f"u-{uuid.uuid4().hex[:8]}@example.com",
            "phone": "+2376" + str(uuid.uuid4().int)[:8],
            "password": PASSWORD,
            "first_name": "A",
            "last_name": "B",
            "role": "restaurant",
        }
        created = no_server_error(client.post("/v1/users", headers=h, json=new_user), 201).json()["id"]
        assert no_server_error(client.get("/v1/users", headers=h), 200).json()
        no_server_error(client.get(f"/v1/users/{created}", headers=h), 200)
        no_server_error(client.put(f"/v1/users/{created}", headers=h, json={"first_name": "Zoé"}), 200)
        no_server_error(client.delete(f"/v1/users/{created}", headers=h), 204)
        no_server_error(client.get(f"/v1/users/{created}", headers=h), 404)

    def test_regular_user_cannot_use_admin_routes(self, client, owner):
        h = owner["headers"]
        assert client.get("/v1/users", headers=h).status_code == 403
        assert client.get("/v1/admin/mobile-operator-prefixes", headers=h).status_code == 403
        tier = {"name": "x", "daily_limit_fcfa": 1, "monthly_price_fcfa": 1, "annual_price_fcfa": 1}
        assert client.post("/v1/subscriptions/tiers", headers=h, json=tier).status_code == 403

    def test_mobile_operator_prefixes(self, client, admin):
        h = admin["headers"]
        listed = no_server_error(client.get("/v1/admin/mobile-operator-prefixes", headers=h), 200).json()
        assert {p["operator_code"] for p in listed} >= {"MTN_CM", "ORANGE_CM"}
        created = no_server_error(
            client.post(
                "/v1/admin/mobile-operator-prefixes",
                headers=h,
                json={"operator_code": "MTN_CM", "operator_name": "MTN Cameroun", "national_prefix": "682"},
            ),
            201,
        ).json()
        no_server_error(
            client.patch(f"/v1/admin/mobile-operator-prefixes/{created['id']}", headers=h, json={"is_active": False}),
            200,
        )

    def test_subscription_tiers(self, client, admin):
        h = admin["headers"]
        tiers = no_server_error(client.get("/v1/subscriptions/tiers"), 200).json()
        if tiers:
            tier_id = tiers[0]["id"]
            no_server_error(client.get(f"/v1/subscriptions/tiers/{tier_id}"), 200)
            no_server_error(
                client.put(f"/v1/subscriptions/tiers/{tier_id}", headers=h, json={"monthly_price_fcfa": 12000}), 200
            )
        no_server_error(client.get("/v1/subscriptions/tiers/999999"), 404)


class TestPayments:
    def test_configuration_and_unknown_intent(self, client, owner, stranger):
        h, rid = owner["headers"], owner["rid"]
        saved = no_server_error(
            client.put(
                "/v1/payments/easytransact/configuration",
                headers=h,
                json={"restaurant_id": rid, "webhook_url": "https://api.example.com/hook"},
            ),
            200,
            201,
        )
        assert saved.json()["restaurant_id"] == rid
        no_server_error(client.get(f"/v1/payments/easytransact/{uuid.uuid4()}/status", headers=h), 404)
        foreign = client.put(
            "/v1/payments/easytransact/configuration", headers=stranger["headers"], json={"restaurant_id": rid}
        )
        assert foreign.status_code in (403, 404), "un autre propriétaire ne configure pas mes paiements"

    def test_owner_cannot_choose_a_custom_secret_reference(self, client, owner):
        response = client.put(
            "/v1/payments/easytransact/configuration",
            headers=owner["headers"],
            json={"restaurant_id": owner["rid"], "webhook_secret_env_key": "EASYTRANSACT_WEBHOOK_SECRET_MINE"},
        )
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "body",
        [
            b'{"vendor_reference":"MRD-1","event_id":"e1","status":"success"}',
            b"not json at all",
            b"{}",
        ],
    )
    def test_unsigned_webhook_always_gets_the_same_answer(self, client, owner, body):
        """Même réponse quelle que soit la charge : rien n'est révélé sans signature."""
        response = client.post(
            f"/v1/payments/easytransact/webhook/{owner['rid']}",
            content=body,
            headers={"Content-Type": "application/json", "X-Signature": "deadbeef"},
        )
        assert response.status_code in (401, 503), response.text
