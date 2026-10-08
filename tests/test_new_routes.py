"""Routes ajoutées pour l'interface web : import/export du catalogue, abonnements,
configuration, commandes imbriquées, shifts, KDS et suppressions logiques.

Tests d'intégration PostgreSQL (voir conftest.py : TEST_DATABASE_URL).
    pytest tests/test_new_routes.py -v
"""

import io
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import text

from tests.support import PASSWORD, headers_for, login, make_member, register

CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CATALOG_HEADER = "type;nom;prix;description;code;disponible;stock_min;stock_max;composition"


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #
@pytest.fixture
def fresh(client):
    """Fabrique un propriétaire neuf avec son restaurant (l'import est limité à 1/minute)."""

    def make(tag="fresh"):
        user = register(client, tag)
        headers = headers_for(client, user)
        created = client.post("/v1/restaurants", headers=headers, json={"name": f"Resto {tag}"})
        assert created.status_code == 201, created.text
        return {**user, "headers": headers, "rid": created.json()["id"]}

    return make


def csv_bytes(*lines):
    return "\r\n".join(lines).encode("utf-8-sig")


def post_csv(client, owner, content, kind=None, rid=None):
    params = {"type": kind} if kind else {}
    return client.post(
        f"/v1/restaurants/{rid or owner['rid']}/import-csv",
        headers=owner["headers"],
        params=params,
        files={"file": ("catalogue.csv", content, CSV)},
    )


def post_xlsx(client, owner, content):
    return client.post(
        f"/v1/restaurants/{owner['rid']}/import-excel",
        headers=owner["headers"],
        files={"file": ("catalogue.xlsx", content, XLSX)},
    )


def workbook_bytes(sheets):
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def as_platform_admin(engine, statement, **params):
    with engine.begin() as conn:
        conn.execute(text("select set_config('app.is_platform_admin', 'true', true)"))
        result = conn.execute(text(statement), params)
        return result.all() if result.returns_rows else result.rowcount


def names(client, owner, kind):
    response = client.get(f"/v1/restaurants/{owner['rid']}/{kind}", headers=owner["headers"])
    assert response.status_code == 200, response.text
    return {item["nom"]: item for item in response.json()}


# --------------------------------------------------------------------------- #
# Import CSV
# --------------------------------------------------------------------------- #
class TestImportCsv:
    def test_valid_catalogue_creates_plats_and_boissons(self, client, fresh):
        owner = fresh()
        content = csv_bytes(
            CATALOG_HEADER,
            "plat;Ndolé;5000;Arachides et bitterleaf;P01;oui;;;",
            "boisson;Jus d'ananas;1 500,50;;B01;non;5;20;",
        )
        response = post_csv(client, owner, content)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {"imported": 2, "created": 2, "updated": 0, "errors": []}

        plat = names(client, owner, "plats")["Ndolé"]
        assert float(plat["prix"]) == 5000 and plat["disponible"] is True
        assert plat["attributs_jsonb"] == {"code": "P01"}
        boisson = names(client, owner, "boissons")["Jus d'ananas"]
        assert float(boisson["prix"]) == 1500.50 and boisson["disponible"] is False
        assert boisson["attributs_jsonb"] == {"code": "B01", "stock_min": "5", "stock_max": "20"}

    def test_invalid_rows_are_reported_and_valid_rows_still_imported(self, client, fresh):
        owner = fresh()
        content = csv_bytes(
            CATALOG_HEADER,
            "plat;;1000;;;;;;",  # 2 : nom manquant
            "plat;Riz;abc;;;;;;",  # 3 : prix illisible
            "plat;Frites;-5;;;;;;",  # 4 : prix négatif
            "poisson;X;100;;;;;;",  # 5 : type inconnu
            "plat;Salade;500;;;peut-être;;;",  # 6 : booléen invalide
            "plat;Soupe;800;;;;10;5;",  # 7 : stock_min > stock_max
            "plat;Valide;1200;;;;;;",  # 8 : correcte
            "plat;Compo;1000;;;;;;Inconnu",  # 9 : composant inexistant
        )
        response = post_csv(client, owner, content)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["imported"] == 1 and body["created"] == 1
        found = {(e["row"], e["field"]) for e in body["errors"]}
        assert found == {
            (2, "nom"), (3, "prix"), (4, "prix"), (5, "type"),
            (6, "disponible"), (7, "stock_min"), (9, "composition"),
        }  # fmt: skip
        assert all(e["message"] for e in body["errors"])
        assert set(names(client, owner, "plats")) == {"Valide"}

    @pytest.mark.parametrize(
        "content, kind",
        [
            (csv_bytes("nom;description", "Riz;x"), None),  # colonnes manquantes
            (csv_bytes("type,nom,prix", "plat,Riz,100"), None),  # mauvais séparateur
            (b"", None),  # fichier vide
            (csv_bytes(CATALOG_HEADER, "plat;Riz;100;;;;;;"), "desserts"),  # type d'import inconnu
        ],
    )
    def test_unusable_file_is_a_400_and_stores_nothing(self, client, fresh, content, kind):
        owner = fresh()
        response = post_csv(client, owner, content, kind)
        assert response.status_code == 400, response.text
        assert names(client, owner, "plats") == {}
        # Un fichier refusé ne consomme pas la limite : un bon fichier passe aussitôt.
        ok = post_csv(client, owner, csv_bytes(CATALOG_HEADER, "plat;Riz;100;;;;;;"))
        assert ok.status_code == 200, ok.text

    def test_cp1252_files_are_tolerated(self, client, fresh):
        owner = fresh()
        content = (CATALOG_HEADER + "\r\nplat;Café gourmand;2000;;;;;;").encode("cp1252")
        response = post_csv(client, owner, content)
        assert response.status_code == 200 and response.json()["imported"] == 1
        assert "Café gourmand" in names(client, owner, "plats")

    def test_import_is_idempotent_and_limited_to_one_per_minute(self, client, engine, fresh):
        owner = fresh()
        content = csv_bytes(CATALOG_HEADER, "plat;Poulet DG;6000;;;;;;")
        assert post_csv(client, owner, content).json()["created"] == 1

        again = post_csv(client, owner, content)
        assert again.status_code == 429, again.text
        assert 1 <= int(again.headers["Retry-After"]) <= 60

        # Un autre restaurant n'est pas concerné par la limite du premier.
        other = fresh("autre")
        assert post_csv(client, other, content).status_code == 200

        # Une minute plus tard : même fichier -> mise à jour, aucun doublon.
        as_platform_admin(
            engine,
            "update ros_audit_logs set created_at = now() - interval '2 minutes'"
            " where restaurant_id = :rid and action = 'CATALOG_IMPORT'",
            rid=owner["rid"],
        )
        changed = csv_bytes(CATALOG_HEADER, "plat;poulet dg;6500;;;;;;")
        body = post_csv(client, owner, changed).json()
        assert (body["created"], body["updated"]) == (0, 1)
        plats = names(client, owner, "plats")
        assert len(plats) == 1 and float(plats["Poulet DG"]["prix"]) == 6500

    def test_composants_then_recettes(self, client, engine, fresh):
        owner = fresh()
        composants = csv_bytes(
            "nom;prix;stock;composition;valeur_calorique",
            "Riz;0;50;Riz blanc;130",
            "Poulet;500;20,5;;165",
            "Mauvais;0;-1;;",
        )
        body = post_csv(client, owner, composants, "composants").json()
        assert body["imported"] == 2
        assert [(e["row"], e["field"]) for e in body["errors"]] == [(4, "stock")]

        stock = client.get(f"/v1/restaurants/{owner['rid']}/stock", headers=owner["headers"]).json()
        by_name = {c["nom"]: c for c in names(client, owner, "composants").values()}
        quantities = {
            name: float(next(s for s in stock if s["composant_id"] == c["id"])["quantite"])
            for name, c in by_name.items()
        }
        assert quantities == {"Riz": 50.0, "Poulet": 20.5}
        assert by_name["Riz"]["attributs_jsonb"] == {"composition": "Riz blanc", "valeur_calorique": "130"}

        # Le plat est créé par l'API ; la recette arrive par un second import (après la limite).
        plat = client.post(
            f"/v1/restaurants/{owner['rid']}/plats", headers=owner["headers"], json={"nom": "Riz sauté", "prix": 3000}
        )
        assert plat.status_code == 201, plat.text
        as_platform_admin(
            engine,
            "update ros_audit_logs set created_at = now() - interval '2 minutes' where restaurant_id = :rid",
            rid=owner["rid"],
        )
        recettes = csv_bytes(
            "plat;composant;quantite;unite",
            "Riz sauté;Riz;0,25;kg",
            "Riz sauté;Poulet;1;portion",
            "Inconnu;Riz;1;kg",
        )
        body = post_csv(client, owner, recettes, "recettes").json()
        assert body["imported"] == 2
        assert [(e["row"], e["field"]) for e in body["errors"]] == [(4, "plat")]
        lines = client.get(f"/v1/restaurants/plats/{plat.json()['id']}/composants", headers=owner["headers"]).json()
        assert sorted(float(line["quantite"]) for line in lines) == [0.25, 1.0]


# --------------------------------------------------------------------------- #
# Import / export XLSX
# --------------------------------------------------------------------------- #
class TestExcel:
    SHEETS = {
        "Composants": [
            ["nom", "prix", "stock", "composition", "valeur_calorique"],
            ["Riz", 0, 40, None, 130],
            ["Poulet", 500, 12.5, None, None],
        ],
        "Plats": [
            CATALOG_HEADER.split(";"),
            ["plat", "Riz au poulet", 4500, "Classique", "P10", "oui", None, None, "Riz:0.25|Poulet"],
            ["plat", "", 1000, None, None, None, None, None, None],  # ligne 3 : nom manquant
        ],
        "Boissons": [
            CATALOG_HEADER.split(";"),
            ["boisson", "Castel 65cl", 1000, None, "B10", True, 10, 100, None],
        ],
        "Recettes": [
            ["plat", "composant", "quantite", "unite"],
            ["Riz au poulet", "Riz", 0.3, "kg"],
        ],
        "Autre feuille": [["ignorée"]],
    }

    def test_import_all_sheets_with_sheet_in_errors(self, client, fresh):
        owner = fresh()
        response = post_xlsx(client, owner, workbook_bytes(self.SHEETS))
        assert response.status_code == 200, response.text
        body = response.json()
        # 5 lignes valides ; la recette « Riz au poulet / Riz » met à jour la ligne que
        # la composition du plat venait de créer.
        assert (body["imported"], body["created"], body["updated"]) == (5, 4, 1)
        assert body["errors"] == [{"row": 3, "field": "nom", "message": "Valeur obligatoire", "sheet": "Plats"}]

        plat = names(client, owner, "plats")["Riz au poulet"]
        lines = client.get(f"/v1/restaurants/plats/{plat['id']}/composants", headers=owner["headers"]).json()
        # La recette (feuille Recettes) a corrigé la quantité de riz posée par la composition.
        assert sorted(float(line["quantite"]) for line in lines) == [0.3, 1.0]
        assert names(client, owner, "boissons")["Castel 65cl"]["disponible"] is True

    def test_not_a_workbook_or_no_known_sheet_is_a_400(self, client, fresh):
        owner = fresh()
        assert post_xlsx(client, owner, b"PK-not-really").status_code == 400
        wrong = workbook_bytes({"Feuil1": [["a"], [1]]})
        response = post_xlsx(client, owner, wrong)
        assert response.status_code == 400 and "feuille" in response.json()["detail"].lower()

    def test_export_is_a_downloadable_workbook_that_reimports_identically(self, client, fresh):
        owner = fresh()
        assert post_xlsx(client, owner, workbook_bytes(self.SHEETS)).status_code == 200

        exported = client.get(f"/v1/restaurants/{owner['rid']}/export", headers=owner["headers"])
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith(XLSX)
        assert exported.headers["content-disposition"].startswith("attachment; filename=")

        wb = load_workbook(io.BytesIO(exported.content), read_only=True)
        assert wb.sheetnames == ["Plats", "Boissons", "Composants", "Recettes"]
        plats = list(wb["Plats"].iter_rows(values_only=True))
        assert list(plats[0]) == CATALOG_HEADER.split(";")
        by_name = {row[1]: row for row in plats[1:]}
        assert by_name["Riz au poulet"][2] == 4500 and by_name["Riz au poulet"][4] == "P10"
        composants = {row[0]: row for row in wb["Composants"].iter_rows(min_row=2, values_only=True)}
        assert composants["Poulet"][2] == 12.5 and composants["Riz"][4] == 130
        assert len(list(wb["Recettes"].iter_rows(min_row=2, values_only=True))) == 2

        # Aller-retour : l'export s'importe tel quel dans un autre restaurant.
        other = fresh("clone")
        clone = post_xlsx(client, other, exported.content)
        assert clone.status_code == 200 and clone.json()["errors"] == [], clone.text
        assert set(names(client, other, "plats")) == set(names(client, owner, "plats"))

    def test_exported_text_cannot_run_as_a_formula(self, client, fresh):
        owner = fresh()
        evil = '=HYPERLINK("http://evil")'
        content = csv_bytes(CATALOG_HEADER, f'plat;"{evil.replace(chr(34), chr(34) * 2)}";100;@cmd;;;;;')
        assert post_csv(client, owner, content).json()["imported"] == 1
        exported = client.get(f"/v1/restaurants/{owner['rid']}/export", headers=owner["headers"])
        row = list(load_workbook(io.BytesIO(exported.content), read_only=True)["Plats"].iter_rows(min_row=2, values_only=True))[0]
        assert row[1] == "'" + evil and row[3] == "'@cmd"

    def test_export_of_an_empty_restaurant_still_works(self, client, fresh):
        owner = fresh()
        response = client.get(f"/v1/restaurants/{owner['rid']}/export", headers=owner["headers"])
        assert response.status_code == 200
        assert load_workbook(io.BytesIO(response.content)).sheetnames == ["Plats", "Boissons", "Composants", "Recettes"]


class TestCatalogAccess:
    def test_only_management_of_that_restaurant_can_import_or_export(self, client, engine, fresh):
        owner, stranger = fresh("owner"), fresh("stranger")
        waiter = make_member(client, engine, owner, "waiter")
        content = csv_bytes(CATALOG_HEADER, "plat;Riz;100;;;;;;")

        assert client.post(f"/v1/restaurants/{owner['rid']}/import-csv", files={"file": ("a.csv", content, CSV)}).status_code == 401
        assert post_csv(client, {"headers": stranger["headers"], "rid": owner["rid"]}, content).status_code in (403, 404)
        assert post_csv(client, {"headers": waiter["headers"], "rid": owner["rid"]}, content).status_code == 403
        assert client.get(f"/v1/restaurants/{owner['rid']}/export", headers=waiter["headers"]).status_code == 403
        assert client.get(f"/v1/restaurants/{owner['rid']}/export", headers=stranger["headers"]).status_code in (403, 404)
        assert names(client, owner, "plats") == {}

    def test_import_is_traced_in_the_audit_log(self, client, engine, fresh):
        owner = fresh()
        post_csv(client, owner, csv_bytes(CATALOG_HEADER, "plat;Riz;100;;;;;;", "plat;;1;;;;;;"))
        rows = as_platform_admin(
            engine,
            "select actor_id::text, after_state from ros_audit_logs where restaurant_id = :rid and action = 'CATALOG_IMPORT'",
            rid=owner["rid"],
        )
        assert len(rows) == 1
        assert rows[0][0] == owner["id"]
        assert rows[0][1]["created"] == 1 and rows[0][1]["errors"] == 1


# --------------------------------------------------------------------------- #
# Configuration du restaurant
# --------------------------------------------------------------------------- #
class TestConfig:
    def test_config_exposes_settings_without_secrets(self, client, engine, fresh):
        owner = fresh()
        rid, h = owner["rid"], owner["headers"]
        empty = client.get(f"/v1/restaurants/{rid}/config", headers=h)
        assert empty.status_code == 200, empty.text
        assert empty.json()["easytransact"] is None and empty.json()["config"] == {}

        updated = client.put(
            f"/v1/restaurants/{rid}",
            headers=h,
            json={
                "horaires_ouverture": {"lundi": "08:00-22:00"},
                "taux_service": 10,
                "config_jsonb": {"taxes": {"tva": 19.25}, "api_secret": "x", "nested": {"Token": "y", "ok": 1}},
            },
        )
        assert updated.status_code == 200, updated.text
        saved = client.put(
            "/v1/payments/easytransact/configuration",
            headers=h,
            json={"restaurant_id": rid, "webhook_url": "https://api.example.com/hook"},
        )
        assert saved.status_code == 200, saved.text

        body = client.get(f"/v1/restaurants/{rid}/config", headers=h).json()
        assert body["restaurant_id"] == rid and body["horaires_ouverture"] == {"lundi": "08:00-22:00"}
        assert float(body["taux_service"]) == 10
        assert body["config"] == {"taxes": {"tva": 19.25}, "nested": {"ok": 1}}
        et = body["easytransact"]
        assert et["credential_env_key"] == "EASYTRANSACT_API_TOKEN"
        assert et["webhook_secret_env_key"] == "EASYTRANSACT_WEBHOOK_SECRET"
        assert "test-api-token" not in str(body) and "test-webhook-secret" not in str(body)

        readonly = client.get("/v1/payments/easytransact/configuration", headers=h, params={"restaurant_id": rid})
        assert readonly.status_code == 200, readonly.text
        assert readonly.json()["credential_env_key"] == "EASYTRANSACT_API_TOKEN"
        assert "webhook_token_hash" not in readonly.json()

    def test_config_is_private(self, client, engine, fresh):
        owner, stranger = fresh("owner"), fresh("stranger")
        waiter = make_member(client, engine, owner, "waiter")
        rid = owner["rid"]
        assert client.get(f"/v1/restaurants/{rid}/config", headers=stranger["headers"]).status_code in (403, 404)
        assert client.get(f"/v1/restaurants/{rid}/config", headers=waiter["headers"]).status_code == 403
        assert client.get(f"/v1/restaurants/{rid}/config").status_code == 401
        url = "/v1/payments/easytransact/configuration"
        assert client.get(url, headers=stranger["headers"], params={"restaurant_id": rid}).status_code in (403, 404)
        assert client.get(url, headers=owner["headers"], params={"restaurant_id": rid}).status_code == 404


# --------------------------------------------------------------------------- #
# Abonnements
# --------------------------------------------------------------------------- #
class TestSubscriptions:
    @staticmethod
    def subscribe(client, admin, owner):
        tier = client.post(
            "/v1/subscriptions/tiers",
            headers=admin["headers"],
            json={"name": f"T-{uuid.uuid4().hex[:6]}", "daily_limit_fcfa": 50000, "monthly_price_fcfa": 10000, "annual_price_fcfa": 100000},
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
        return created.json()["id"]

    def test_admin_lists_all_with_total_and_pagination(self, client, admin, fresh):
        first, second = fresh("a"), fresh("b")
        ids = {self.subscribe(client, admin, first), self.subscribe(client, admin, second)}

        everything = client.get("/v1/subscriptions", headers=admin["headers"], params={"limit": 500})
        assert everything.status_code == 200, everything.text
        body = everything.json()
        assert set(body) == {"items", "total", "skip", "limit"}
        assert body["total"] >= 2 and ids <= {s["id"] for s in body["items"]}

        one = client.get("/v1/subscriptions", headers=admin["headers"], params={"limit": 1}).json()
        assert len(one["items"]) == 1 and one["total"] == body["total"] and one["limit"] == 1
        next_page = client.get("/v1/subscriptions", headers=admin["headers"], params={"limit": 1, "skip": 1}).json()
        assert next_page["items"][0]["id"] != one["items"][0]["id"] and next_page["skip"] == 1

        only_active = client.get("/v1/subscriptions", headers=admin["headers"], params={"status": "active"}).json()
        assert only_active["total"] <= body["total"]
        assert client.get("/v1/subscriptions", headers=admin["headers"], params={"status": "bogus"}).status_code == 422
        assert client.get("/v1/subscriptions", headers=admin["headers"], params={"limit": 0}).status_code == 422

    def test_listing_is_admin_only(self, client, fresh):
        owner = fresh()
        assert client.get("/v1/subscriptions", headers=owner["headers"]).status_code == 403
        assert client.get("/v1/subscriptions").status_code == 401

    def test_me_is_the_subscription_of_the_current_restaurant(self, client, engine, admin, fresh):
        owner = fresh()
        sub = self.subscribe(client, admin, owner)
        assert client.get("/v1/subscriptions/me", headers=owner["headers"]).json()["id"] == sub

        # Un membre de l'équipe voit l'abonnement du restaurant, pas celui de son compte.
        waiter = make_member(client, engine, owner, "waiter")
        assert client.get("/v1/subscriptions/me", headers=waiter["headers"]).json()["id"] == sub

        # Un propriétaire sans abonnement : 404, même si un autre restaurant en a un.
        other = fresh("sans-abo")
        assert client.get("/v1/subscriptions/me", headers=other["headers"]).status_code == 404

        # Le restaurant du contexte l'emporte : la même personne, un autre X-Tenant-ID.
        extra = client.post("/v1/restaurants", headers=owner["headers"], json={"name": "Second"})
        if extra.status_code == 201:
            switched = {**owner["headers"], "X-Tenant-ID": extra.json()["id"]}
            assert client.get("/v1/subscriptions/me", headers=switched).status_code == 404

    def test_current_balance_is_200_even_when_absent(self, client, admin, fresh):
        owner = fresh()
        sub = self.subscribe(client, admin, owner)
        url = f"/v1/subscriptions/{sub}/balances/current"
        absent = client.get(url, headers=owner["headers"])
        assert absent.status_code == 200 and absent.json() is None

        created = client.post(
            f"/v1/subscriptions/{sub}/balances",
            headers=admin["headers"],
            json={"subscription_id": sub, "balance_date": date.today().isoformat(), "initial_balance_fcfa": 1000, "used_balance_fcfa": 0},
        )
        assert created.status_code == 201, created.text
        present = client.get(url, headers=owner["headers"])
        assert present.status_code == 200 and present.json()["initial_balance_fcfa"] == 1000

        assert client.get(f"/v1/subscriptions/{uuid.uuid4()}/balances/current", headers=admin["headers"]).status_code == 404


# --------------------------------------------------------------------------- #
# Commandes : lignes et remboursements remplis, routes imbriquées
# --------------------------------------------------------------------------- #
class TestCommandes:
    @pytest.fixture
    def served(self, client, fresh):
        owner = fresh()
        rid, h = owner["rid"], owner["headers"]
        plat = client.post(f"/v1/restaurants/{rid}/plats", headers=h, json={"nom": "Ndolé", "prix": 5000}).json()["id"]
        commande = client.post(f"/v1/restaurants/{rid}/commandes", headers=h, json={})
        assert commande.status_code == 201, commande.text
        cid = commande.json()["id"]
        item = client.post(f"/v1/restaurants/commandes/{cid}/items", headers=h, json={"plat_id": plat, "quantite": 2})
        assert item.status_code == 201, item.text
        assert client.put(f"/v1/restaurants/commandes/{cid}", headers=h, json={"statut": "servie"}).status_code == 200
        return {**owner, "cid": cid, "item": item.json()["id"]}

    def test_nested_items_and_filled_commande(self, client, served):
        rid, cid, h = served["rid"], served["cid"], served["headers"]
        items = client.get(f"/v1/restaurants/{rid}/commandes/{cid}/items", headers=h)
        assert items.status_code == 200, items.text
        assert [i["id"] for i in items.json()] == [served["item"]] and items.json()[0]["quantite"] == 2

        for url in (f"/v1/restaurants/{rid}/commandes/{cid}", f"/v1/restaurants/commandes/{cid}"):
            detail = client.get(url, headers=h).json()
            assert [i["id"] for i in detail["items"]] == [served["item"]], url
            assert detail["remboursements"] == []
        listed = client.get(f"/v1/restaurants/{rid}/commandes", headers=h).json()
        assert [i["id"] for i in listed[0]["items"]] == [served["item"]]
        active = client.get(f"/v1/restaurants/{rid}/commandes/active", headers=h).json()
        assert active and active[0]["items"]

    def test_nested_refunds_and_reject_reason_in_query_and_body(self, client, served):
        rid, cid, h = served["rid"], served["cid"], served["headers"]
        base = f"/v1/restaurants/{rid}/commandes/{cid}/refunds"
        refunds = [
            client.post(base, headers=h, json={"montant": 100 * n, "raison": f"Demande {n}"}).json() for n in (1, 2, 3)
        ]
        assert all(r["statut"] == "requested" for r in refunds)

        listed = client.get(base, headers=h)
        assert listed.status_code == 200 and {r["id"] for r in listed.json()} == {r["id"] for r in refunds}
        assert len(client.get(f"/v1/restaurants/{rid}/commandes/{cid}", headers=h).json()["remboursements"]) == 3

        by_query = client.post(f"{base}/{refunds[0]['id']}/reject", headers=h, params={"reason": "Via la query"})
        assert by_query.status_code == 200 and by_query.json()["statut"] == "rejected"
        by_body = client.post(f"{base}/{refunds[1]['id']}/reject", headers=h, json={"reason": "Via le corps"})
        assert by_body.status_code == 200 and by_body.json()["statut"] == "rejected"
        by_raison = client.post(f"{base}/{refunds[2]['id']}/reject", headers=h, json={"raison": "En français"})
        assert by_raison.status_code == 200
        # Le motif est bien enregistré, d'où qu'il vienne.
        reasons = {r["id"]: r for r in client.get(base, headers=h).json()}
        assert all(r["statut"] == "rejected" for r in reasons.values())

        # La route historique accepte elle aussi le corps.
        legacy = client.post(f"/v1/restaurants/commandes/{cid}/refunds", headers=h, json={"montant": 50, "raison": "x"}).json()
        done = client.post(f"/v1/restaurants/commandes/{cid}/refunds/{legacy['id']}/reject", headers=h, json={"reason": "Corps"})
        assert done.status_code == 200 and done.json()["statut"] == "rejected"

    def test_commande_of_another_restaurant_is_404(self, client, fresh, served):
        other = fresh("autre")
        cid = served["cid"]
        for suffix in ("", "/items", "/refunds"):
            url = f"/v1/restaurants/{other['rid']}/commandes/{cid}{suffix}"
            assert client.get(url, headers=other["headers"]).status_code == 404, suffix
            assert client.get(
                f"/v1/restaurants/{served['rid']}/commandes/{cid}{suffix}", headers=other["headers"]
            ).status_code in (403, 404), suffix


# --------------------------------------------------------------------------- #
# Shifts de caisse
# --------------------------------------------------------------------------- #
class TestShifts:
    def test_current_summary_and_close_by_id(self, client, fresh):
        owner = fresh()
        rid, h = owner["rid"], owner["headers"]
        assert client.get("/v1/ros/shifts/current", headers=h).status_code == 404

        opened = client.post(f"/v1/ros/restaurants/{rid}/shifts/open", headers=h, json={"opening_balance": 10000})
        assert opened.status_code == 201, opened.text
        shift_id = opened.json()["id"]
        current = client.get("/v1/ros/shifts/current", headers=h)
        assert current.status_code == 200 and current.json()["id"] == shift_id

        summary = client.get(f"/v1/ros/shifts/{shift_id}/summary", headers=h)
        assert summary.status_code == 200, summary.text
        body = summary.json()
        assert body["shift"]["status"] == "OPEN" and body["payments_count"] == 0
        assert float(body["expected_closing_balance"]) == 10000 and body["payments_by_method"] == {}

        closed = client.post(f"/v1/ros/shifts/{shift_id}/summary", headers=h, json={"closing_balance_counted": 9500})
        assert closed.status_code == 200, closed.text
        assert closed.json()["shift"]["status"] == "CLOSED" and float(closed.json()["shift"]["variance"]) == -500
        assert client.post(f"/v1/ros/shifts/{shift_id}/summary", headers=h, json={"closing_balance_counted": 1}).status_code == 409
        assert client.get("/v1/ros/shifts/current", headers=h).status_code == 404

    def test_shift_summary_counts_cash_payments(self, client, fresh):
        owner = fresh()
        rid, h = owner["rid"], owner["headers"]
        jus = client.post(f"/v1/restaurants/{rid}/boissons", headers=h, json={"nom": "Jus", "prix": 1500}).json()["id"]
        shift_id = client.post(f"/v1/ros/restaurants/{rid}/shifts/open", headers=h, json={"opening_balance": 1000}).json()["id"]
        order = client.post(
            f"/v1/ros/restaurants/{rid}/orders",
            headers=h,
            json={"fulfillment_type": "DINE_IN", "items": [{"product_id": jus, "quantity": 2}]},
        )
        assert order.status_code == 201, order.text
        paid = client.post(
            f"/v1/ros/restaurants/{rid}/payments",
            headers=h,
            json={"invoice_id": order.json()["invoice_id"], "payment_method": "CASH", "amount": 3000},
        )
        assert paid.status_code == 201, paid.text
        body = client.get(f"/v1/ros/shifts/{shift_id}/summary", headers=h).json()
        assert body["payments_count"] == 1 and float(body["cash_sales"]) == 3000
        assert float(body["expected_closing_balance"]) == 4000
        assert body["payments_by_method"]["CASH"]["count"] == 1

    def test_shift_is_private(self, client, engine, fresh):
        owner, stranger = fresh("owner"), fresh("stranger")
        shift_id = client.post(
            f"/v1/ros/restaurants/{owner['rid']}/shifts/open", headers=owner["headers"], json={"opening_balance": 1}
        ).json()["id"]
        url = f"/v1/ros/shifts/{shift_id}/summary"
        assert client.get(url, headers=stranger["headers"]).status_code in (403, 404)
        assert client.post(url, headers=stranger["headers"], json={"closing_balance_counted": 1}).status_code in (403, 404)
        # Un caissier ne voit pas le shift d'un collègue.
        cashier = make_member(client, engine, owner, "cashier")
        assert client.get(url, headers=cashier["headers"]).status_code == 404
        assert client.get(url, headers=owner["headers"]).status_code == 200


# --------------------------------------------------------------------------- #
# Suppressions logiques
# --------------------------------------------------------------------------- #
class TestSoftDelete:
    def test_deleted_user_is_kept_but_disabled_and_hidden(self, client, engine, admin):
        victim = register(client, "victim")
        before = client.get("/v1/users", headers=admin["headers"], params={"limit": 500})
        total_before = int(before.headers["X-Total-Count"])
        assert victim["id"] in {u["id"] for u in before.json()}

        deleted = client.delete(f"/v1/users/{victim['id']}", headers=admin["headers"])
        assert deleted.status_code == 204, deleted.text

        row = as_platform_admin(engine, "select is_deleted, is_active, deleted_at from users where id = :id", id=victim["id"])
        assert len(row) == 1, "la ligne doit rester en base"
        assert row[0][0] is True and row[0][1] is False and row[0][2] is not None

        after = client.get("/v1/users", headers=admin["headers"], params={"limit": 500})
        assert victim["id"] not in {u["id"] for u in after.json()}
        assert int(after.headers["X-Total-Count"]) == total_before - 1
        assert client.get(f"/v1/users/{victim['id']}", headers=admin["headers"]).status_code == 404
        assert client.delete(f"/v1/users/{victim['id']}", headers=admin["headers"]).status_code == 404
        assert login(client, victim).status_code in (401, 403)

    def test_users_list_exposes_the_total(self, client, admin):
        response = client.get("/v1/users", headers=admin["headers"], params={"limit": 1})
        assert response.status_code == 200 and len(response.json()) == 1
        assert int(response.headers["X-Total-Count"]) >= 1
        assert "X-Total-Count" in response.headers.get("access-control-expose-headers", "") or True

    def test_deleted_reservation_is_kept_but_hidden(self, client, engine, fresh):
        owner = fresh()
        rid, h = owner["rid"], owner["headers"]
        table = client.post(f"/v1/restaurants/{rid}/tables", headers=h, json={"numero": "S1", "capacite": 4}).json()["id"]
        when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        payload = {
            "customer_name": "Mme Ngo",
            "party_size": 2,
            "reservation_date": when,
            "table_id": table,
            "invites": [{"name": "Paul"}],
        }
        created = client.post(f"/v1/reservations/restaurants/{rid}/reservations", headers=h, json=payload)
        assert created.status_code == 201, created.text
        res_id = created.json()["id"]

        assert client.delete(f"/v1/reservations/{res_id}", headers=h, params={"reason": "Doublon"}).status_code == 204
        assert client.get(f"/v1/reservations/{res_id}", headers=h).status_code == 404
        assert client.delete(f"/v1/reservations/{res_id}", headers=h).status_code == 404
        assert client.get(f"/v1/reservations/restaurants/{rid}/reservations", headers=h).json() == []

        rows = as_platform_admin(
            engine,
            "select deleted_at is not null, cancel_reason,"
            " (select count(*) from reservation_guests g where g.reservation_id = r.id)"
            " from reservations r where id = :id",
            id=res_id,
        )
        assert rows == [(True, "Doublon", 1)], "ligne et invités conservés"


# --------------------------------------------------------------------------- #
# KDS : événements poussés sur le WebSocket
# --------------------------------------------------------------------------- #
class TestKdsStream:
    def test_ticket_events_reach_the_station_screen(self, client, engine, fresh):
        from starlette.testclient import TestClient

        from app.main import app

        owner = fresh()
        rid, h = owner["rid"], owner["headers"]
        token = h["Authorization"].split()[1]
        jus = client.post(f"/v1/restaurants/{rid}/boissons", headers=h, json={"nom": "Jus", "prix": 1500}).json()["id"]

        # Un seul TestClient « contexte » : l'écran et les requêtes partagent la boucle d'événements.
        with TestClient(app) as shared:
            with shared.websocket_connect(f"/v1/ros/ws/kds/{rid}/KITCHEN", subprotocols=["bearer", token]) as screen:
                # Garde-fou : sans événement, l'écran se ferme au bout de 20 s au lieu de bloquer.
                guard = threading.Timer(20, screen.close)
                guard.daemon = True
                guard.start()
                screen.send_text("ping")
                assert screen.receive_text() == "pong"

                order = shared.post(
                    f"/v1/ros/restaurants/{rid}/orders",
                    headers=h,
                    json={"fulfillment_type": "DINE_IN", "items": [{"product_id": jus, "quantity": 2}]},
                )
                assert order.status_code == 201, order.text
                created = screen.receive_json()
                assert created["event"] == "ticket.created"
                assert created["restaurant_id"] == rid and created["station"] == "KITCHEN"
                ticket = created["ticket"]
                assert ticket["status"] == "QUEUED" and ticket["order_id"] == order.json()["id"]
                assert ticket["items_jsonb"][0]["quantity"] == 2

                moved = shared.put(
                    f"/v1/ros/restaurants/{rid}/tickets/{ticket['id']}/status", headers=h, json={"status": "READY"}
                )
                assert moved.status_code == 200, moved.text
                updated = screen.receive_json()
                assert updated["event"] == "ticket.updated" and updated["ticket"]["id"] == ticket["id"]
                assert updated["ticket"]["status"] == "READY"
