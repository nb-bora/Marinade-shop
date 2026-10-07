"""GET /users/me/access : où travaille l'utilisateur et ce qu'il y peut faire.

Contre PostgreSQL avec le rôle applicatif, donc sous RLS réelle (voir conftest.py).
"""

import pytest

from tests.support import headers_for, make_member, register

pytestmark = pytest.mark.usefixtures("engine")

URL = "/v1/users/me/access"


def ids(response):
    assert response.status_code == 200, response.text
    return {item["restaurant_id"] for item in response.json()}


def entry(response, rid):
    return next(i for i in response.json() if i["restaurant_id"] == rid)


def test_the_owner_sees_their_restaurant_with_every_capability(client, owner):
    response = client.get(URL, headers=owner["headers"])
    assert ids(response) == {owner["rid"]}
    item = entry(response, owner["rid"])
    assert item["relation"] == "owner" and item["roles"] == ["owner"]
    assert set(item["capabilities"]) == {
        "management", "stock", "front_of_house", "cash_desk", "production", "reservations",
    }


def test_a_cashier_sees_the_restaurant_but_only_the_capabilities_of_their_role(client, engine, owner):
    cashier = make_member(client, engine, owner, "cashier")
    # Sans X-Tenant-ID : c'est justement la route qui permet de le découvrir.
    response = client.get(URL, headers=headers_for(client, cashier))
    assert ids(response) == {owner["rid"]}
    item = entry(response, owner["rid"])
    assert item["relation"] == "member" and item["roles"] == ["cashier"]
    assert "cash_desk" in item["capabilities"]
    assert "management" not in item["capabilities"]
    assert "stock" not in item["capabilities"]


def test_a_chef_is_not_offered_the_cash_desk(client, engine, owner):
    chef = make_member(client, engine, owner, "chef")
    item = entry(client.get(URL, headers=headers_for(client, chef)), owner["rid"])
    assert "production" in item["capabilities"] and "stock" in item["capabilities"]
    assert "cash_desk" not in item["capabilities"]


def test_a_manager_is_offered_everything(client, engine, owner):
    manager = make_member(client, engine, owner, "manager")
    item = entry(client.get(URL, headers=headers_for(client, manager)), owner["rid"])
    assert "management" in item["capabilities"] and "cash_desk" in item["capabilities"]


def test_one_restaurant_never_lists_another(client, owner, stranger):
    assert owner["rid"] not in ids(client.get(URL, headers=stranger["headers"]))
    assert stranger["rid"] not in ids(client.get(URL, headers=owner["headers"]))


def test_a_user_without_any_restaurant_gets_an_empty_list(client):
    nobody = register(client, "nobody")
    response = client.get(URL, headers=headers_for(client, nobody))
    assert response.status_code == 200 and response.json() == []


def test_a_deactivated_membership_disappears(client, engine, owner):
    from tests.support import sql_as_platform_admin

    waiter = make_member(client, engine, owner, "waiter")
    sql_as_platform_admin(
        engine, "update restaurant_members set is_active = false where user_id = :uid",
        uid=waiter["id"],
    )
    assert client.get(URL, headers=headers_for(client, waiter)).json() == []


def test_a_platform_admin_sees_every_restaurant(client, admin, owner, stranger):
    response = client.get(URL + "?limit=100", headers=admin["headers"])
    assert {owner["rid"], stranger["rid"]} <= ids(response)
    assert entry(response, owner["rid"])["relation"] == "platform_admin"
    assert "management" in entry(response, owner["rid"])["capabilities"]


def test_the_name_filter_narrows_the_list_and_treats_wildcards_literally(client, admin, owner, stranger):
    found = ids(client.get(URL + "?q=chez marinade&limit=100", headers=admin["headers"]))
    assert owner["rid"] in found and stranger["rid"] not in found
    # « % » ne doit pas devenir un joker.
    assert ids(client.get(URL + "?q=%25", headers=admin["headers"])) == set()


def test_the_list_is_bounded(client, admin):
    assert client.get(URL + "?limit=0", headers=admin["headers"]).status_code == 422
    assert client.get(URL + "?limit=101", headers=admin["headers"]).status_code == 422


def test_it_requires_authentication(client):
    assert client.get(URL).status_code in (401, 403)


class TestPlatformAdminTenantHeader:
    """L'administrateur désigne le restaurant par X-Tenant-ID, comme tout autre utilisateur."""

    PAYMENTS = "/v1/payments/easytransact/transactions"

    def test_the_header_scopes_a_restaurant_route_to_the_chosen_restaurant(self, client, admin, owner):
        response = client.get(self.PAYMENTS, headers={**admin["headers"], "X-Tenant-ID": owner["rid"]})
        assert response.status_code == 200, response.text
        assert response.json() == {"items": [], "next_cursor": None}

    def test_without_the_header_there_is_no_default_restaurant(self, client, admin):
        # Un administrateur n'a pas de restaurant « par défaut » : il doit en désigner un.
        assert client.get(self.PAYMENTS, headers=admin["headers"]).status_code == 400

    def test_an_unknown_restaurant_is_refused_as_not_found(self, client, admin):
        import uuid

        headers = {**admin["headers"], "X-Tenant-ID": str(uuid.uuid4())}
        assert client.get(self.PAYMENTS, headers=headers).status_code == 404

    def test_a_malformed_header_is_refused(self, client, admin):
        headers = {**admin["headers"], "X-Tenant-ID": "pas-un-uuid"}
        assert client.get(self.PAYMENTS, headers=headers).status_code == 400

    def test_the_header_gives_an_ordinary_user_nothing_more_than_before(self, client, owner, stranger):
        headers = {**stranger["headers"], "X-Tenant-ID": owner["rid"]}
        assert client.get(self.PAYMENTS, headers=headers).status_code == 404


def test_a_member_cannot_write_to_the_restaurants_table_through_the_read_policy(client, engine, owner):
    """La politique ajoutée est en lecture seule : un employé ne modifie pas le restaurant."""
    from sqlalchemy import text

    waiter = make_member(client, engine, owner, "waiter")
    with engine.begin() as conn:
        conn.execute(
            text("select set_config('app.current_user_id', :uid, true)"), {"uid": waiter["id"]}
        )
        changed = conn.execute(
            text("update restaurants set name = 'pirate' where id = :rid"), {"rid": owner["rid"]}
        ).rowcount
    assert changed == 0
