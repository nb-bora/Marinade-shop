"""Décision d'accès par rôle (ensure_tenant_role), sans base de données.

Une fausse session renvoie des résultats préparés par modèle : on teste la règle de
décision (qui passe, qui est refusé, avec quel code), pas les requêtes SQL.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.dependencies import ensure_tenant_role
from app.models.restaurant import Restaurant
from app.models.tenant import RestaurantMember


class _Query:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    def __init__(self, restaurant=None, member=None):
        self._results = {Restaurant: restaurant, RestaurantMember: member}

    def query(self, model):
        return _Query(self._results.get(model))

    def execute(self, *args, **kwargs):  # set_db_context
        return None


TENANT = uuid.uuid4()
OWNER_ID = uuid.uuid4()


def _restaurant():
    return SimpleNamespace(id=TENANT, user_id=OWNER_ID)


def _user(role="restaurant", user_id=None):
    return SimpleNamespace(id=user_id or uuid.uuid4(), role=role)


def _member(staff_role=None, role="staff", active=True):
    return SimpleNamespace(staff_role=staff_role, role=role, is_active=active)


def test_owner_passes_any_role_requirement():
    owner = _user(user_id=OWNER_ID)
    db = _FakeDB(restaurant=_restaurant(), member=None)
    assert ensure_tenant_role(db, owner, TENANT, {"manager"}) is not None


def test_platform_admin_passes():
    db = _FakeDB(restaurant=_restaurant(), member=None)
    assert ensure_tenant_role(db, _user(role="admin"), TENANT, {"manager"})


def test_manager_member_passes_roles_they_are_not_listed_for():
    db = _FakeDB(restaurant=_restaurant(), member=_member(staff_role="manager"))
    assert ensure_tenant_role(db, _user(), TENANT, {"cashier"})


def test_waiter_is_refused_a_management_action_with_403():
    db = _FakeDB(restaurant=_restaurant(), member=_member(staff_role="waiter"))
    with pytest.raises(HTTPException) as exc:
        ensure_tenant_role(db, _user(), TENANT, {"manager"})
    assert exc.value.status_code == 403


def test_cashier_passes_cash_desk_but_not_management():
    db = _FakeDB(restaurant=_restaurant(), member=_member(staff_role="cashier"))
    assert ensure_tenant_role(db, _user(), TENANT, {"manager", "cashier"})
    with pytest.raises(HTTPException) as exc:
        ensure_tenant_role(db, _user(), TENANT, {"manager"})
    assert exc.value.status_code == 403


def test_legacy_member_role_is_still_honoured():
    """Les lignes antérieures à staff_role portent le rôle dans la colonne `role`."""
    db = _FakeDB(
        restaurant=_restaurant(), member=_member(staff_role=None, role="cashier")
    )
    assert ensure_tenant_role(db, _user(), TENANT, {"cashier"})


def test_legacy_kitchen_role_counts_as_chef():
    db = _FakeDB(
        restaurant=_restaurant(), member=_member(staff_role=None, role="kitchen")
    )
    assert ensure_tenant_role(db, _user(), TENANT, {"chef"})


def test_generic_staff_member_without_staff_role_gets_no_privilege():
    db = _FakeDB(restaurant=_restaurant(), member=_member(staff_role=None, role="staff"))
    with pytest.raises(HTTPException) as exc:
        ensure_tenant_role(db, _user(), TENANT, {"cashier", "waiter"})
    assert exc.value.status_code == 403


def test_user_with_no_link_to_the_restaurant_gets_404_not_403():
    """404 : on ne confirme pas l'existence du restaurant d'un autre."""
    db = _FakeDB(restaurant=None, member=None)
    with pytest.raises(HTTPException) as exc:
        ensure_tenant_role(db, _user(), TENANT, {"manager"})
    assert exc.value.status_code == 404
