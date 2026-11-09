"""Suppression d'une table : logique, réservée à la gestion, refusée si la table est en service."""

import pytest

from tests.support import headers_for, make_member, register


@pytest.fixture
def shop(client):
    user = register(client, "tbl")
    headers = headers_for(client, user)
    created = client.post("/v1/restaurants", headers=headers, json={"name": "Chez Tables"})
    assert created.status_code == 201, created.text
    return {**user, "headers": headers, "rid": created.json()["id"]}


def add(client, shop, numero, **extra):
    r = client.post(f"/v1/restaurants/{shop['rid']}/tables", headers=shop["headers"],
                    json={"numero": numero, "capacite": 4, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def listed(client, shop):
    return {t["numero"] for t in client.get(f"/v1/restaurants/{shop['rid']}/tables", headers=shop["headers"]).json()}


class TestDeleteTable:
    def test_a_deleted_table_leaves_the_plan_and_frees_its_number(self, client, shop):
        tid = add(client, shop, "T1")
        assert client.delete(f"/v1/restaurants/tables/{tid}", headers=shop["headers"]).status_code == 204
        assert "T1" not in listed(client, shop)
        assert client.get(f"/v1/restaurants/tables/{tid}", headers=shop["headers"]).status_code == 404
        assert client.put(f"/v1/restaurants/tables/{tid}", headers=shop["headers"], json={"capacite": 2}).status_code == 404
        assert client.delete(f"/v1/restaurants/tables/{tid}", headers=shop["headers"]).status_code == 404
        add(client, shop, "T1")  # le numéro est de nouveau disponible
        assert "T1" in listed(client, shop)

    def test_a_table_with_an_open_session_cannot_be_deleted(self, client, shop):
        tid = add(client, shop, "T2")
        opened = client.post(f"/v1/ros/restaurants/{shop['rid']}/sessions", headers=shop["headers"], json={"table_id": tid})
        assert opened.status_code == 201, opened.text
        assert client.delete(f"/v1/restaurants/tables/{tid}", headers=shop["headers"]).status_code == 409
        assert "T2" in listed(client, shop)

    def test_the_layout_attributes_are_kept_on_update(self, client, shop):
        plan = {"plan": {"niveau": "etage-1", "x": 12.5, "y": 40}}
        tid = add(client, shop, "T3", attributs_jsonb=plan)
        got = client.get(f"/v1/restaurants/tables/{tid}", headers=shop["headers"]).json()
        assert got["attributs_jsonb"] == plan

    def test_only_management_can_delete(self, client, engine, shop):
        tid = add(client, shop, "T4")
        waiter = make_member(client, engine, shop, "waiter")
        assert client.delete(f"/v1/restaurants/tables/{tid}", headers=waiter["headers"]).status_code == 403
        manager = make_member(client, engine, shop, "manager")
        assert client.delete(f"/v1/restaurants/tables/{tid}", headers=manager["headers"]).status_code == 204

    def test_another_restaurant_cannot_delete_it(self, client, shop):
        tid = add(client, shop, "T5")
        other = register(client, "tblother")
        h = headers_for(client, other)
        assert client.post("/v1/restaurants", headers=h, json={"name": "Voisin"}).status_code == 201
        assert client.delete(f"/v1/restaurants/tables/{tid}", headers=h).status_code in (403, 404)
        assert "T5" in listed(client, shop)
