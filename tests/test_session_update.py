"""Modifier les couverts d'une session ouverte : seulement tant qu'elle est ouverte, dans son restaurant."""

import pytest

from tests.support import headers_for, make_member, register


@pytest.fixture
def shop(client):
    user = register(client, "sess")
    headers = headers_for(client, user)
    created = client.post("/v1/restaurants", headers=headers, json={"name": "Chez Sessions"})
    assert created.status_code == 201, created.text
    return {**user, "headers": headers, "rid": created.json()["id"]}


def open_session(client, shop, context="2 couverts · Salle"):
    r = client.post(f"/v1/ros/restaurants/{shop['rid']}/sessions", headers=shop["headers"], json={"table_context": context})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def url(shop, sid):
    return f"/v1/ros/restaurants/{shop['rid']}/sessions/{sid}"


class TestUpdateSession:
    def test_the_context_can_be_updated_while_the_session_is_open(self, client, shop):
        sid = open_session(client, shop)
        r = client.put(url(shop, sid), headers=shop["headers"], json={"table_context": "4 couverts · Salle"})
        assert r.status_code == 200, r.text
        assert r.json()["table_context"] == "4 couverts · Salle"
        listed = client.get(f"/v1/ros/restaurants/{shop['rid']}/sessions", headers=shop["headers"]).json()
        assert [s["table_context"] for s in listed if s["id"] == sid] == ["4 couverts · Salle"]

    def test_an_empty_update_changes_nothing(self, client, shop):
        sid = open_session(client, shop)
        assert client.put(url(shop, sid), headers=shop["headers"], json={}).json()["table_context"] == "2 couverts · Salle"

    def test_a_closed_session_cannot_be_modified(self, client, shop):
        sid = open_session(client, shop)
        assert client.post(url(shop, sid) + "/close", headers=shop["headers"]).status_code == 200
        assert client.put(url(shop, sid), headers=shop["headers"], json={"table_context": "9 couverts"}).status_code == 409

    def test_unknown_session_and_overlong_context(self, client, shop):
        sid = open_session(client, shop)
        assert client.put(url(shop, "00000000-0000-0000-0000-000000000000"), headers=shop["headers"], json={}).status_code == 404
        assert client.put(url(shop, sid), headers=shop["headers"], json={"table_context": "x" * 101}).status_code == 422

    def test_another_restaurant_cannot_touch_it(self, client, shop):
        sid = open_session(client, shop)
        other = register(client, "sessother")
        h = headers_for(client, other)
        orid = client.post("/v1/restaurants", headers=h, json={"name": "Voisin"}).json()["id"]
        r = client.put(f"/v1/ros/restaurants/{orid}/sessions/{sid}", headers=h, json={"table_context": "hack"})
        assert r.status_code in (403, 404)
        r = client.put(url(shop, sid), headers=h, json={"table_context": "hack"})
        assert r.status_code in (403, 404)

    def test_waiters_may_update_the_covers(self, client, engine, shop):
        waiter = make_member(client, engine, shop, "waiter")
        sid = open_session(client, shop)
        assert client.put(url(shop, sid), headers=waiter["headers"], json={"table_context": "3 couverts · Salle"}).status_code == 200
