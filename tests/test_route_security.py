"""Garde-fou structurel : aucune route ne doit pouvoir être ajoutée sans protection.

Le défaut d'origine (/v1/ros/* sans isolation tenant) venait d'une route écrite
sans contrôle et que personne n'a remarqué. Ces tests parcourent TOUTES les routes
de l'application et échouent dès qu'une route n'est ni protégée ni explicitement
déclarée publique ci-dessous. Ils n'ont besoin d'aucune base de données.
"""

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute

from app.api.dependencies import (
    get_current_user,
    require_restaurant_access,
    require_subscription_access,
    require_tenant_path,
    require_transaction_access,
)
from app.main import app

# (méthode, chemin) volontairement accessibles sans jeton d'accès.
PUBLIC_ROUTES = {
    ("POST", "/v1/auth/register"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/refresh"),
    ("POST", "/v1/auth/forgot-password"),
    ("POST", "/v1/auth/reset-password"),
    # Porte son propre secret : le jeton envoyé par email.
    ("POST", "/v1/auth/verify-email"),
    # Catalogue commercial des offres d'abonnement.
    ("GET", "/v1/subscriptions/tiers"),
    ("GET", "/v1/subscriptions/tiers/{tier_id}"),
    # Appelé par le fournisseur de paiement : authentifié par signature HMAC.
    ("POST", "/v1/payments/easytransact/webhook/{restaurant_id}"),
}

# Le WebSocket s'authentifie lui-même (voir tests/test_websocket_auth.py).
SELF_AUTHENTICATED_WEBSOCKETS = {"/v1/ros/ws/kds/{restaurant_id}/{station}"}

TENANT_GUARDS = {
    require_tenant_path,
    require_restaurant_access,
    require_subscription_access,
    require_transaction_access,
}


def _dependency_calls(dependant) -> list:
    calls = []
    for sub in dependant.dependencies:
        calls.append(sub.call)
        calls.extend(_dependency_calls(sub))
    return calls


def _is_staff_guard(call) -> bool:
    return hasattr(call, "required_roles")


def _v1_routes():
    for route in app.routes:
        if isinstance(route, (APIRoute, APIWebSocketRoute)) and route.path.startswith(
            "/v1"
        ):
            yield route


def _http_routes():
    for route in _v1_routes():
        if isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, route


def test_every_http_route_requires_authentication_or_is_declared_public():
    unprotected = []
    for method, route in _http_routes():
        if (method, route.path) in PUBLIC_ROUTES:
            continue
        if get_current_user not in _dependency_calls(route.dependant):
            unprotected.append(f"{method} {route.path}")
    assert not unprotected, (
        "Routes without authentication (add get_current_user, or list them in "
        f"PUBLIC_ROUTES if they are meant to be public): {unprotected}"
    )


def test_public_routes_list_has_no_stale_entries():
    existing = {(m, r.path) for m, r in _http_routes()}
    stale = PUBLIC_ROUTES - existing
    assert not stale, f"PUBLIC_ROUTES mentions routes that no longer exist: {stale}"


def test_every_route_naming_a_restaurant_is_tenant_guarded():
    """Une route qui reçoit un restaurant_id doit vérifier l'accès à CE restaurant."""
    unguarded = []
    for method, route in _http_routes():
        if (method, route.path) in PUBLIC_ROUTES:
            continue
        if "{restaurant_id}" not in route.path:
            continue
        calls = _dependency_calls(route.dependant)
        if not (TENANT_GUARDS & set(calls)) and not any(
            _is_staff_guard(c) for c in calls
        ):
            unguarded.append(f"{method} {route.path}")
    assert not unguarded, f"Routes with a restaurant_id but no tenant guard: {unguarded}"


def test_subscription_and_transaction_ids_are_ownership_checked():
    """Connaître un UUID d'abonnement ou de transaction ne doit rien ouvrir."""
    from app.api.dependencies import require_admin

    problems = []
    for method, route in _http_routes():
        if (method, route.path) in PUBLIC_ROUTES:
            continue
        calls = set(_dependency_calls(route.dependant))
        if "{subscription_id}" in route.path and not (
            {require_subscription_access, require_admin} & calls
        ):
            problems.append(f"{method} {route.path}")
        if "{transaction_id}" in route.path and require_transaction_access not in calls:
            problems.append(f"{method} {route.path}")
    assert not problems, f"ID-addressed routes without an ownership check: {problems}"


def test_ros_router_is_tenant_guarded_by_default():
    ros_routes = [r for _, r in _http_routes() if r.path.startswith("/v1/ros/")]
    assert ros_routes
    for route in ros_routes:
        assert require_tenant_path in _dependency_calls(route.dependant), route.path


def test_websockets_are_declared_and_not_silently_open():
    websockets = {r.path for r in _v1_routes() if isinstance(r, APIWebSocketRoute)}
    assert websockets == SELF_AUTHENTICATED_WEBSOCKETS


def _roles_for(method: str, path: str) -> set:
    for m, route in _http_routes():
        if m == method and route.path == path:
            guards = [c for c in _dependency_calls(route.dependant) if _is_staff_guard(c)]
            assert guards, f"{method} {path} has no staff-role guard"
            return set.intersection(*(set(g.required_roles) for g in guards))
    raise AssertionError(f"route not found: {method} {path}")


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/v1/restaurants/{restaurant_id}/plats"),
        ("PUT", "/v1/restaurants/plats/{plat_id}"),
        ("POST", "/v1/restaurants/{restaurant_id}/boissons"),
        ("PUT", "/v1/restaurants/boissons/{boisson_id}"),
        ("POST", "/v1/restaurants/{restaurant_id}/combinaisons"),
        ("POST", "/v1/restaurants/{restaurant_id}/composants"),
        ("POST", "/v1/restaurants/{restaurant_id}/menus"),
        ("POST", "/v1/restaurants/commandes/{commande_id}/refunds/{refund_id}/approve"),
        ("POST", "/v1/restaurants/commandes/{commande_id}/refunds/{refund_id}/reject"),
    ],
)
def test_prices_and_refund_decisions_are_management_only(method, path):
    """Un serveur ne change pas un prix et n'approuve pas un remboursement."""
    assert _roles_for(method, path) == {"manager"}


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/v1/ros/restaurants/{restaurant_id}/payments"),
        ("POST", "/v1/ros/restaurants/{restaurant_id}/payments/split"),
        ("POST", "/v1/ros/restaurants/{restaurant_id}/shifts/open"),
        ("POST", "/v1/ros/restaurants/{restaurant_id}/shifts/close"),
        ("POST", "/v1/restaurants/commandes/{commande_id}/refunds"),
    ],
)
def test_money_handling_is_cash_desk_only(method, path):
    roles = _roles_for(method, path)
    assert "cashier" in roles and "manager" in roles
    assert "waiter" not in roles and "chef" not in roles


def test_waiters_can_take_orders_but_chefs_cannot_cash():
    take_order = _roles_for("POST", "/v1/ros/restaurants/{restaurant_id}/orders")
    assert "waiter" in take_order
    pay = _roles_for("POST", "/v1/ros/restaurants/{restaurant_id}/payments")
    assert "chef" not in pay and "waiter" not in pay
