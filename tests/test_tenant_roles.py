"""Décision d'accès par rôle, sans base de données.

La décision est une fonction pure de ``TenantAccess`` (qui est l'utilisateur DANS ce
restaurant) : on teste la règle, pas les requêtes SQL. La résolution de l'accès
elle-même est vérifiée contre PostgreSQL par tests/test_api_integration.py.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.api.dependencies import (
    TenantAccess,
    _effective_roles,
    _tenant_access,
    ensure_tenant_role,
)

TENANT = uuid.uuid4()


def _access(**kwargs) -> TenantAccess:
    return TenantAccess(TENANT, **kwargs)


def test_owner_passes_any_role_requirement():
    assert _access(is_owner=True).allows({"manager"})


def test_platform_admin_passes():
    assert _access(is_admin=True).allows({"manager"})


def test_manager_member_passes_roles_they_are_not_listed_for():
    assert _access(is_member=True, roles=frozenset({"manager"})).allows({"cashier"})


def test_waiter_is_refused_a_management_action():
    assert not _access(is_member=True, roles=frozenset({"waiter"})).allows({"manager"})


def test_cashier_passes_cash_desk_but_not_management():
    cashier = _access(is_member=True, roles=frozenset({"cashier"}))
    assert cashier.allows({"manager", "cashier"})
    assert not cashier.allows({"manager"})


def test_a_stranger_has_no_access_at_all():
    assert not _access().has_access
    assert not _access().allows({"manager"})


class TestEffectiveRoles:
    def test_legacy_member_role_is_still_honoured(self):
        """Les lignes antérieures à staff_role portent le rôle dans la colonne `role`."""
        assert _effective_roles(None, "cashier") == frozenset({"cashier"})

    def test_legacy_kitchen_role_counts_as_chef(self):
        assert _effective_roles(None, "kitchen") == frozenset({"chef"})

    def test_generic_staff_role_grants_nothing(self):
        assert _effective_roles(None, "staff") == frozenset()

    def test_both_columns_are_combined(self):
        assert _effective_roles("waiter", "staff") == frozenset({"waiter"})


class _Row:
    def __init__(self, **values):
        self.__dict__.update(values)


class _Result:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row

    def first(self):
        return self._row


class _CountingDB:
    """Session factice : renvoie une ligne d'accès et compte les requêtes."""

    def __init__(self, row):
        self.row = row
        self.info = {}
        self.queries = 0

    def execute(self, *args, **kwargs):
        self.queries += 1
        return _Result(self.row)


class _User:
    def __init__(self, role="restaurant"):
        self.id = uuid.uuid4()
        self.role = role


def test_access_is_resolved_with_one_query_then_remembered():
    db = _CountingDB(_Row(is_owner=False, is_member=True, role="staff", staff_role="waiter"))
    user = _User()
    first = _tenant_access(db, user, TENANT)
    again = _tenant_access(db, user, TENANT)
    assert first is again
    assert db.queries == 1, "plusieurs gardes sur la même requête ne doivent interroger qu'une fois"
    assert first.roles == frozenset({"waiter"})


def test_the_cache_is_per_user_and_per_restaurant():
    db = _CountingDB(_Row(is_owner=True, is_member=False, role=None, staff_role=None))
    _tenant_access(db, _User(), TENANT)
    _tenant_access(db, _User(), TENANT)
    _tenant_access(db, _User(), uuid.uuid4())
    assert db.queries == 3


def test_unlinked_user_gets_404_not_403_and_the_refusal_is_remembered():
    """404 : on ne confirme pas l'existence du restaurant d'un autre."""
    db = _CountingDB(_Row(is_owner=False, is_member=False, role=None, staff_role=None))
    user = _User()
    for _ in range(2):
        with pytest.raises(HTTPException) as exc:
            _tenant_access(db, user, TENANT)
        assert exc.value.status_code == 404
    assert db.queries == 1


def test_ensure_tenant_role_refuses_with_403_when_the_role_is_missing():
    db = _CountingDB(_Row(is_owner=False, is_member=True, role="staff", staff_role="waiter"))
    db.info["rls_context"] = {"app.current_tenant_id": str(TENANT)}
    with pytest.raises(HTTPException) as exc:
        ensure_tenant_role(db, _User(), TENANT, {"manager"})
    assert exc.value.status_code == 403


def test_ensure_tenant_role_returns_the_access_when_allowed():
    db = _CountingDB(_Row(is_owner=True, is_member=False, role=None, staff_role=None))
    db.info["rls_context"] = {"app.current_tenant_id": str(TENANT)}
    assert ensure_tenant_role(db, _User(), TENANT, {"manager"}).is_owner
