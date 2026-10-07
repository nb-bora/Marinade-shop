"""Budget de requêtes SQL et pagination, mesurés sur la vraie base.

Le coût d'une requête HTTP ne doit dépendre ni du nombre de lignes renvoyées ni de la
taille des tables : on compte les instructions SQL émises et on vérifie qu'elles ne
croissent pas quand les données grossissent (pas de N+1), puis que chaque liste est
bornée par une page.

Ces tests exigent TEST_DATABASE_URL (voir tests/conftest.py).
"""

import uuid
from datetime import datetime, timezone

import pytest

from tests.support import ITEMS, count_queries, headers_for, register

# Authentification (utilisateur + contexte RLS + restaurant + contexte restaurant) puis
# la requête métier : au-delà, la route fait du travail inutile.
READ_BUDGET = 6


@pytest.fixture(scope="module")
def shop(client):
    user = register(client, "budget")
    headers = headers_for(client, user)
    rid = client.post("/v1/restaurants", headers=headers, json={"name": "Budget"}).json()["id"]
    return {"headers": headers, "rid": rid, "composants": []}


def grow(client, shop, count):
    h, rid = shop["headers"], shop["rid"]
    for _ in range(count):
        tag = uuid.uuid4().hex[:6]
        c = client.post(f"/v1/restaurants/{rid}/composants", headers=h, json={"nom": f"c{tag}", "type": "base"}).json()["id"]
        client.post(f"/v1/restaurants/composants/{c}/stock/mouvements", headers=h, json={"type": "entree", "quantite": 100})
        shop["composants"].append(c)
        client.post(f"/v1/restaurants/{rid}/plats", headers=h, json={"nom": f"p{tag}", "prix": 1000, "composant_ids": [c]})
        client.post(f"/v1/restaurants/{rid}/combinaisons", headers=h, json={"nom": f"k{tag}", "prix": 2000, "composant_ids": [c]})
        client.post(f"/v1/restaurants/{rid}/boissons", headers=h, json={"nom": f"b{tag}", "prix": 500})
        client.post(f"/v1/restaurants/{rid}/tables", headers=h, json={"numero": f"T{tag}", "capacite": 4})
        client.post(f"/v1/restaurants/{rid}/menus", headers=h, json={"name": f"m{tag}"})
        client.post(
            f"/v1/reservations/restaurants/{rid}/reservations",
            headers=h,
            json={
                "customer_name": "X",
                "party_size": 2,
                "reservation_date": datetime.now(timezone.utc).isoformat(),
                "invites": [{"name": "a"}, {"name": "b"}],
            },
        )
        client.post(f"/v1/reservations/restaurants/{rid}/waitlist", headers=h, json={"customer_name": "W", "party_size": 2})
        client.post(f"/v1/ros/restaurants/{rid}/orders", headers=h, json={"fulfillment_type": "DINE_IN", "items": [ITEMS[1]]})
        client.post(f"/v1/restaurants/{rid}/commandes", headers=h, json={})


def endpoints(client, shop):
    h, rid = shop["headers"], shop["rid"]
    r, ros, res = f"/v1/restaurants/{rid}", f"/v1/ros/restaurants/{rid}", f"/v1/reservations/restaurants/{rid}"
    return {
        "plats": lambda: client.get(f"{r}/plats", headers=h),
        "boissons": lambda: client.get(f"{r}/boissons", headers=h),
        "tables": lambda: client.get(f"{r}/tables", headers=h),
        "tables libres": lambda: client.get(f"{r}/tables/free", headers=h),
        "menus": lambda: client.get(f"{r}/menus", headers=h),
        "composants": lambda: client.get(f"{r}/composants", headers=h),
        "stock": lambda: client.get(f"{r}/stock", headers=h),
        "combinaisons": lambda: client.get(f"{r}/combinaisons", headers=h),
        "recommandations": lambda: client.get(f"{r}/combinaisons/recommandations", headers=h),
        "commandes": lambda: client.get(f"{r}/commandes", headers=h),
        "commandes actives": lambda: client.get(f"{r}/commandes/active", headers=h),
        "reservations": lambda: client.get(f"{res}/reservations", headers=h),
        "liste d'attente": lambda: client.get(f"{res}/waitlist", headers=h),
        "sessions ROS": lambda: client.get(f"{ros}/sessions", headers=h),
        "tickets ROS": lambda: client.get(f"{ros}/tickets/KITCHEN", headers=h),
        "approvisionnement": lambda: client.get(f"{ros}/procurement/suggestions", headers=h),
    }


def measure(engine, call):
    with count_queries(engine) as counter:
        response = call()
    assert response.status_code == 200, response.text
    return counter["n"]


class TestQueryBudget:
    def test_no_route_issues_more_queries_when_data_grows(self, client, engine, shop):
        grow(client, shop, 2)
        small = {name: measure(engine, call) for name, call in endpoints(client, shop).items()}
        grow(client, shop, 10)
        large = {name: measure(engine, call) for name, call in endpoints(client, shop).items()}

        growing = {n: (small[n], large[n]) for n in small if large[n] > small[n]}
        assert not growing, f"N+1 : requêtes (2 lignes, 12 lignes) par route : {growing}"
        over_budget = {n: c for n, c in large.items() if c > READ_BUDGET + 2}
        assert not over_budget, f"routes au-dessus du budget de requêtes : {over_budget}"

    def test_authentication_overhead_is_constant(self, client, engine, shop):
        grow(client, shop, 1)
        with count_queries(engine) as counter:
            client.get(f"/v1/restaurants/{shop['rid']}/plats", headers=shop["headers"])
        assert counter["n"] <= READ_BUDGET, "\n".join(counter["statements"])

    def test_extra_role_guards_do_not_requery_access(self, client, engine, shop):
        """Un garde de rôle réutilise l'accès déjà résolu : aucune requête de plus."""
        h, rid = shop["headers"], shop["rid"]
        with count_queries(engine) as plain:
            client.get(f"/v1/ros/restaurants/{rid}/sessions", headers=h)
        with count_queries(engine) as guarded:
            client.get(f"/v1/ros/restaurants/{rid}/tickets/KITCHEN", headers=h)
        assert abs(plain["n"] - guarded["n"]) <= 1


class TestPagination:
    @pytest.mark.parametrize("query", ["limit=0", "limit=501", "skip=-1", "limit=abc"])
    def test_invalid_page_parameters_are_rejected(self, client, shop, query):
        response = client.get(f"/v1/restaurants/{shop['rid']}/plats?{query}", headers=shop["headers"])
        assert response.status_code == 422

    def test_pages_partition_the_collection_without_overlap(self, client, shop):
        h, rid = shop["headers"], shop["rid"]
        full = client.get(f"/v1/restaurants/{rid}/plats?limit=500", headers=h).json()
        assert len(full) >= 7
        pages = []
        for skip in range(0, len(full), 3):
            page = client.get(f"/v1/restaurants/{rid}/plats?skip={skip}&limit=3", headers=h).json()
            assert len(page) <= 3
            pages.extend(item["id"] for item in page)
        assert pages == [item["id"] for item in full], "pages = collection, dans le même ordre"
        assert len(set(pages)) == len(pages)

    def test_default_page_is_bounded(self, client, shop):
        listed = client.get(f"/v1/restaurants/{shop['rid']}/plats", headers=shop["headers"]).json()
        assert len(listed) <= 100


class TestSellableCombinations:
    """Recommandations évaluées par la base : composant dispo ET stock libre suffisant."""

    def make(self, client, shop, stock, quantity_hint=None):
        h, rid = shop["headers"], shop["rid"]
        tag = uuid.uuid4().hex[:6]
        composant = client.post(f"/v1/restaurants/{rid}/composants", headers=h, json={"nom": f"s{tag}", "type": "base"}).json()["id"]
        if stock:
            client.post(f"/v1/restaurants/composants/{composant}/stock/mouvements", headers=h, json={"type": "entree", "quantite": stock})
        combo = client.post(
            f"/v1/restaurants/{rid}/combinaisons", headers=h, json={"nom": f"k{tag}", "prix": 1000, "composant_ids": [composant]}
        ).json()["id"]
        return composant, combo

    def recommended(self, client, shop):
        listed = client.get(f"/v1/restaurants/{shop['rid']}/combinaisons/recommandations?limit=500", headers=shop["headers"]).json()
        return {c["id"] for c in listed}

    def test_a_combination_without_stock_is_not_offered(self, client, shop):
        _, empty = self.make(client, shop, stock=0)
        _, stocked = self.make(client, shop, stock=5)
        offered = self.recommended(client, shop)
        assert stocked in offered
        assert empty not in offered

    def test_an_unavailable_component_removes_the_combination(self, client, shop):
        composant, combo = self.make(client, shop, stock=5)
        assert combo in self.recommended(client, shop)
        client.put(f"/v1/restaurants/composants/{composant}", headers=shop["headers"], json={"disponible": False})
        assert combo not in self.recommended(client, shop)

    def test_reserved_stock_is_not_offered_again(self, client, shop):
        h, rid = shop["headers"], shop["rid"]
        composant, combo = self.make(client, shop, stock=2)
        commande = client.post(f"/v1/restaurants/{rid}/commandes", headers=h, json={}).json()["id"]
        added = client.post(f"/v1/restaurants/commandes/{commande}/items", headers=h, json={"combinaison_id": combo, "quantite": 2})
        assert added.status_code == 201, added.text
        assert combo not in self.recommended(client, shop), "le stock est réservé : plus rien à vendre"
