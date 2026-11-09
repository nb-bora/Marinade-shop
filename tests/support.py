"""Aides partagées par les tests d'intégration PostgreSQL (voir conftest.py)."""

import re
import uuid
from contextlib import contextmanager

from sqlalchemy import event, text

PASSWORD = "MotDePasseFort123!"


def activation_code_for(email):
    """Le dernier code d'activation « envoyé » à cette adresse (boîte mémoire des tests)."""
    from app.services import email_service

    for mail in reversed(email_service.OUTBOX):
        if mail.to == email:
            found = re.search(r"Code : (\d{6})", mail.text)
            if found:
                return found.group(1)
    raise AssertionError(f"aucun code d'activation envoyé à {email}")

ITEMS = [
    {
        "product_name": "Poulet braisé",
        "quantity": 1,
        "unit_price": 4000,
        "tax_rate": 19.25,
        "destination_station": "KITCHEN",
    },
    {
        "product_name": "Jus d'ananas",
        "quantity": 2,
        "unit_price": 1500,
        "destination_station": "BAR",
    },
]


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
    # Comme un vrai utilisateur : le compte n'est utilisable qu'après saisie du code reçu.
    activation = client.post(
        "/v1/auth/activate", json={"email": email, "code": activation_code_for(email)}
    )
    assert activation.status_code == 200, activation.text
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


def no_server_error(response, *expected):
    where = f"{response.request.method} {response.request.url.path}"
    detail = f"{where} -> {response.status_code} {response.text[:300]}"
    assert response.status_code < 500, detail
    if expected:
        assert response.status_code in expected, detail
    return response


@contextmanager
def count_queries(engine):
    """Compte les requêtes SQL émises pendant le bloc (``counter['n']``)."""
    counter = {"n": 0, "statements": []}

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1
        counter["statements"].append(" ".join(statement.split())[:140])

    event.listen(engine, "before_cursor_execute", _count)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _count)
