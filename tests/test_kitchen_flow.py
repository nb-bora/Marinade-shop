"""Cuisine et bar : machine d'états des tickets, fenêtre, rappel, urgence, routage,
résumé, expiration, clôtures et flux WebSocket.

Chaque test vit sur son propre restaurant (fixture ``kitchen`` ou ``fresh_kitchen``) pour
ne pas dépendre des tickets créés par les autres tests.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.services.ros_service import RosService
from tests.support import headers_for, make_member, register, sql_as_platform_admin

STATES = ["QUEUED", "IN_PREPARATION", "READY", "SERVED", "CANCELLED"]

# Transitions du service normal (table de référence, écrite en dur).
ALLOWED = {
    ("QUEUED", "IN_PREPARATION"),
    ("QUEUED", "CANCELLED"),
    ("IN_PREPARATION", "READY"),
    ("IN_PREPARATION", "CANCELLED"),
    ("READY", "SERVED"),
}
# Retours arrière : gestion seulement.
REVERSE = {("IN_PREPARATION", "QUEUED"), ("READY", "IN_PREPARATION")}

# Chemin depuis « À préparer » jusqu'à chaque état.
PATH_TO = {
    "QUEUED": [],
    "IN_PREPARATION": ["IN_PREPARATION"],
    "READY": ["IN_PREPARATION", "READY"],
    "SERVED": ["IN_PREPARATION", "READY", "SERVED"],
    "CANCELLED": ["CANCELLED"],
}


# --------------------------------------------------------------------------- #
# Fabrique de données
# --------------------------------------------------------------------------- #
def _restaurant(client, tag):
    user = register(client, tag)
    headers = headers_for(client, user)
    created = client.post("/v1/restaurants", headers=headers, json={"name": f"Cuisine {tag}"})
    assert created.status_code == 201, created.text
    return {**user, "headers": headers, "rid": created.json()["id"]}


def _kitchen(client, engine, tag):
    owner = _restaurant(client, f"{tag}-owner")
    return {
        "owner": owner,
        "chef": make_member(client, engine, owner, "chef"),
        "waiter": make_member(client, engine, owner, "waiter"),
        "rid": owner["rid"],
    }


@pytest.fixture(scope="module")
def kitchen(client, engine):
    """Un restaurant partagé par les tests de transitions (chaque test crée ses propres commandes)."""
    return _kitchen(client, engine, "module")


@pytest.fixture
def fresh_kitchen(client, engine):
    """Un restaurant neuf, pour les tests qui touchent à tout le restaurant (expiration, clôtures)."""
    return _kitchen(client, engine, "fresh")


def _plat(client, k, nom="Poulet braisé", station=None):
    body = {"nom": nom, "prix": 3000}
    if station:
        body["station"] = station
    created = client.post(f"/v1/restaurants/{k['rid']}/plats", headers=k["owner"]["headers"], json=body)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _boisson(client, k, nom="Jus d'ananas"):
    created = client.post(
        f"/v1/restaurants/{k['rid']}/boissons", headers=k["owner"]["headers"], json={"nom": nom, "prix": 1500}
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _order(client, k, items, **extra):
    response = client.post(
        f"/v1/ros/restaurants/{k['rid']}/orders",
        headers=k["owner"]["headers"],
        json={"fulfillment_type": "DINE_IN", "items": items, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _board(client, k, station="KITCHEN", headers=None):
    response = client.get(
        f"/v1/ros/restaurants/{k['rid']}/tickets/{station}", headers=headers or k["owner"]["headers"]
    )
    assert response.status_code == 200, response.text
    return response.json()


def _ticket_of(client, k, order_id, station="KITCHEN"):
    matches = [t for t in _board(client, k, station) if t["order_id"] == order_id]
    assert len(matches) == 1, f"un ticket attendu pour la commande {order_id} en {station}"
    return matches[0]


def _move(client, k, ticket_id, target, headers=None):
    return client.put(
        f"/v1/ros/restaurants/{k['rid']}/tickets/{ticket_id}/status",
        headers=headers or k["owner"]["headers"],
        json={"status": target},
    )


def _ticket_in_state(client, k, state, items=None):
    plat = _plat(client, k, nom=f"Plat {uuid.uuid4().hex[:6]}")
    order = _order(client, k, items or [{"product_id": plat, "quantity": 1}])
    ticket = _ticket_of(client, k, order["id"])
    for step in PATH_TO[state]:
        moved = _move(client, k, ticket["id"], step)
        assert moved.status_code == 200, moved.text
    return ticket["id"]


def _at(monkeypatch, minutes):
    """Horloge du service avancée de `minutes` (les tests de fenêtre n'attendent pas)."""
    later = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    monkeypatch.setattr(RosService, "_now", staticmethod(lambda: later))


def _audit_statuses(engine, ticket_id):
    with engine.begin() as conn:
        conn.execute(text("select set_config('app.is_platform_admin', 'true', true)"))
        rows = conn.execute(
            text(
                "select before_state->>'status', after_state->>'status' from ros_audit_logs"
                " where entity_id = :id and action = 'TICKET_STATUS'"
            ),
            {"id": ticket_id},
        ).all()
    return {(before, after) for before, after in rows}


# --------------------------------------------------------------------------- #
# 1. Transitions de statut
# --------------------------------------------------------------------------- #
class TestTransitions:
    @pytest.mark.parametrize(
        "current,target",
        [(a, b) for a in STATES for b in STATES],
        ids=lambda pair: str(pair),
    )
    def test_matrice_des_transitions_pour_le_personnel(self, client, kitchen, current, target):
        """Le serveur n'accepte que les transitions prévues ; le retour arrière est
        refusé (403) au personnel sans droit de gestion, et tout le reste est un 409."""
        ticket_id = _ticket_in_state(client, kitchen, current)
        response = _move(client, kitchen, ticket_id, target, headers=kitchen["chef"]["headers"])
        if (current, target) in ALLOWED:
            assert response.status_code == 200, response.text
            assert response.json()["status"] == target
        elif (current, target) in REVERSE:
            assert response.status_code == 403, response.text
            assert _board_status(client, kitchen, ticket_id) == current, "rien ne doit changer"
        else:
            assert response.status_code == 409, response.text

    @pytest.mark.parametrize("current,target", sorted(REVERSE))
    def test_le_management_peut_revenir_en_arriere(self, client, kitchen, current, target):
        ticket_id = _ticket_in_state(client, kitchen, current)
        response = _move(client, kitchen, ticket_id, target)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == target

    def test_un_ticket_servi_ne_repasse_pas_a_prêt_par_simple_changement(self, client, kitchen):
        ticket_id = _ticket_in_state(client, kitchen, "SERVED")
        response = _move(client, kitchen, ticket_id, "READY")
        assert response.status_code == 409
        assert "rappel" in response.json()["detail"].lower()

    def test_une_transition_refusee_ne_modifie_pas_la_base(self, client, kitchen, engine):
        ticket_id = _ticket_in_state(client, kitchen, "QUEUED")
        assert _move(client, kitchen, ticket_id, "SERVED").status_code == 409
        assert _board_status(client, kitchen, ticket_id) == "QUEUED"
        assert _audit_statuses(engine, ticket_id) == set(), "aucun audit pour une transition refusée"


def _board_status(client, k, ticket_id):
    for station in ("KITCHEN", "BAR", "DESSERT"):
        for ticket in _board(client, k, station):
            if ticket["id"] == ticket_id:
                return ticket["status"]
    return None


# --------------------------------------------------------------------------- #
# 2. Horodatages et audit
# --------------------------------------------------------------------------- #
class TestHorodatages:
    def test_chaque_etape_pose_son_horodatage(self, client, kitchen):
        ticket_id = _ticket_in_state(client, kitchen, "QUEUED")
        started = _move(client, kitchen, ticket_id, "IN_PREPARATION").json()
        assert started["started_at"] and started["ready_at"] is None
        ready = _move(client, kitchen, ticket_id, "READY").json()
        assert ready["ready_at"] and ready["served_at"] is None
        served = _move(client, kitchen, ticket_id, "SERVED").json()
        assert served["served_at"]
        for stamp in (started["started_at"], ready["ready_at"], served["served_at"]):
            assert datetime.fromisoformat(stamp).tzinfo is not None, "horodatage timezone-aware"

    def test_un_retour_arriere_remet_a_null_l_etat_quitte(self, client, kitchen):
        ticket_id = _ticket_in_state(client, kitchen, "READY")
        back = _move(client, kitchen, ticket_id, "IN_PREPARATION").json()
        assert back["ready_at"] is None and back["started_at"] is not None
        queued = _move(client, kitchen, ticket_id, "QUEUED").json()
        assert queued["started_at"] is None

    def test_chaque_changement_est_journalise(self, client, kitchen, engine):
        ticket_id = _ticket_in_state(client, kitchen, "QUEUED")
        _move(client, kitchen, ticket_id, "IN_PREPARATION")
        _move(client, kitchen, ticket_id, "READY")
        _move(client, kitchen, ticket_id, "IN_PREPARATION")  # retour arrière (gestion)
        assert _audit_statuses(engine, ticket_id) == {
            ("QUEUED", "IN_PREPARATION"),
            ("IN_PREPARATION", "READY"),
            ("READY", "IN_PREPARATION"),
        }


# --------------------------------------------------------------------------- #
# 3. Rappel, urgence
# --------------------------------------------------------------------------- #
class TestRappel:
    def test_un_ticket_servi_se_rappelle_dans_les_deux_minutes(self, client, kitchen):
        ticket_id = _ticket_in_state(client, kitchen, "SERVED")
        response = client.post(
            f"/v1/ros/restaurants/{kitchen['rid']}/tickets/{ticket_id}/recall",
            headers=kitchen["waiter"]["headers"],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "READY" and body["served_at"] is None and body["ready_at"]

    def test_le_rappel_est_refuse_apres_deux_minutes(self, client, kitchen, monkeypatch):
        ticket_id = _ticket_in_state(client, kitchen, "SERVED")
        _at(monkeypatch, minutes=3)
        response = client.post(
            f"/v1/ros/restaurants/{kitchen['rid']}/tickets/{ticket_id}/recall",
            headers=kitchen["waiter"]["headers"],
        )
        assert response.status_code == 409, response.text

    def test_on_ne_rappelle_que_un_ticket_servi(self, client, kitchen):
        ticket_id = _ticket_in_state(client, kitchen, "READY")
        response = client.post(
            f"/v1/ros/restaurants/{kitchen['rid']}/tickets/{ticket_id}/recall",
            headers=kitchen["waiter"]["headers"],
        )
        assert response.status_code == 409


class TestUrgence:
    def test_un_ticket_urgent_passe_en_tete_de_file(self, client, kitchen):
        first = _order(client, kitchen, [{"product_id": _plat(client, kitchen, "Brochette"), "quantity": 1}])
        second = _order(client, kitchen, [{"product_id": _plat(client, kitchen, "Riz"), "quantity": 1}])
        t1 = _ticket_of(client, kitchen, first["id"])["id"]
        t2 = _ticket_of(client, kitchen, second["id"])["id"]
        marked = client.put(
            f"/v1/ros/restaurants/{kitchen['rid']}/tickets/{t2}/priority",
            headers=kitchen["waiter"]["headers"],
            json={"priority": 1},
        )
        assert marked.status_code == 200, marked.text
        assert marked.json()["priority"] == 1
        ids = [t["id"] for t in _board(client, kitchen)]
        assert ids.index(t2) < ids.index(t1)

    def test_la_priorite_n_accepte_que_0_ou_1(self, client, kitchen):
        ticket_id = _ticket_in_state(client, kitchen, "QUEUED")
        response = client.put(
            f"/v1/ros/restaurants/{kitchen['rid']}/tickets/{ticket_id}/priority",
            headers=kitchen["owner"]["headers"],
            json={"priority": 2},
        )
        assert response.status_code == 422

    def test_un_ticket_pret_ne_peut_plus_etre_marque_urgent(self, client, kitchen):
        ticket_id = _ticket_in_state(client, kitchen, "READY")
        response = client.put(
            f"/v1/ros/restaurants/{kitchen['rid']}/tickets/{ticket_id}/priority",
            headers=kitchen["owner"]["headers"],
            json={"priority": 1},
        )
        assert response.status_code == 409


# --------------------------------------------------------------------------- #
# 4. Lecture : fenêtre, résumé, routage
# --------------------------------------------------------------------------- #
class TestFenetreEtLecture:
    def test_un_ticket_de_treize_heures_n_est_plus_affiche(self, client, fresh_kitchen, monkeypatch):
        order = _order(client, fresh_kitchen, [{"product_id": _plat(client, fresh_kitchen), "quantity": 1}])
        ticket_id = _ticket_of(client, fresh_kitchen, order["id"])["id"]
        _at(monkeypatch, minutes=13 * 60)
        assert ticket_id not in [t["id"] for t in _board(client, fresh_kitchen)]

    def test_le_pret_disparait_apres_trente_minutes(self, client, fresh_kitchen, monkeypatch):
        ticket_id = _ticket_in_state(client, fresh_kitchen, "READY")
        assert ticket_id in [t["id"] for t in _board(client, fresh_kitchen)]
        _at(monkeypatch, minutes=31)
        assert ticket_id not in [t["id"] for t in _board(client, fresh_kitchen)]

    def test_un_pret_recent_reste_visible_aux_deux_ecrans(self, client, kitchen):
        ticket_id = _ticket_in_state(client, kitchen, "READY")
        # Deux lectures indépendantes (deux écrans) concordent : rien n'est gardé côté client.
        first = [t for t in _board(client, kitchen) if t["id"] == ticket_id]
        second = [t for t in _board(client, kitchen) if t["id"] == ticket_id]
        assert first == second and first[0]["status"] == "READY"

    def test_le_resume_additionne_par_article(self, client, fresh_kitchen):
        poulet = _plat(client, fresh_kitchen, "Poulet braisé")
        frites = _plat(client, fresh_kitchen, "Frites")
        _order(client, fresh_kitchen, [{"product_id": poulet, "quantity": 2}])
        _order(client, fresh_kitchen, [{"product_id": poulet, "quantity": 1}, {"product_id": frites, "quantity": 4}])
        summary = client.get(
            f"/v1/ros/restaurants/{fresh_kitchen['rid']}/tickets/KITCHEN/summary",
            headers=fresh_kitchen["owner"]["headers"],
        )
        assert summary.status_code == 200, summary.text
        body = summary.json()
        totals = {item["product_name"]: item["quantity"] for item in body["items"]}
        assert totals == {"Poulet braisé": 3, "Frites": 4}
        assert body["ticket_count"] == 2 and body["total_quantity"] == 7

    def test_le_catalogue_decide_du_poste_pas_le_client(self, client, fresh_kitchen):
        jus = _boisson(client, fresh_kitchen)
        dessert = _plat(client, fresh_kitchen, "Gâteau", station="DESSERT")
        order = _order(
            client,
            fresh_kitchen,
            [
                # La caisse demande la cuisine pour une boisson et le bar pour un plat : ignoré.
                {"product_id": jus, "quantity": 1, "destination_station": "KITCHEN"},
                {"product_id": dessert, "quantity": 1, "destination_station": "BAR"},
            ],
        )
        assert [t["order_id"] for t in _board(client, fresh_kitchen, "BAR")] == [order["id"]]
        assert [t["order_id"] for t in _board(client, fresh_kitchen, "DESSERT")] == [order["id"]]
        assert order["id"] not in [t["order_id"] for t in _board(client, fresh_kitchen, "KITCHEN")]

    def test_le_ticket_indique_table_et_zone(self, client, fresh_kitchen):
        k = fresh_kitchen
        table = client.post(
            f"/v1/restaurants/{k['rid']}/tables",
            headers=k["owner"]["headers"],
            json={"numero": "4", "emplacement": "Terrasse"},
        )
        assert table.status_code == 201, table.text
        session = client.post(
            f"/v1/ros/restaurants/{k['rid']}/sessions",
            headers=k["owner"]["headers"],
            json={"table_id": table.json()["id"]},
        )
        assert session.status_code == 201, session.text
        order = _order(client, k, [{"product_id": _plat(client, k), "quantity": 1}], session_id=session.json()["id"])
        ticket = _ticket_of(client, k, order["id"])
        assert ticket["table_label"] == "Table 4" and ticket["zone"] == "Terrasse"
        # Sans session (comptoir) : pas de table, donc pas de libellé.
        no_table = _order(client, k, [{"product_id": _plat(client, k), "quantity": 1}])
        assert _ticket_of(client, k, no_table["id"])["table_label"] is None

    def test_une_ligne_libre_garde_le_poste_demande(self, client, fresh_kitchen):
        order = _order(
            client,
            fresh_kitchen,
            [{"product_name": "Glace", "unit_price": 800, "quantity": 1, "destination_station": "BAR"}],
        )
        assert order["id"] in [t["order_id"] for t in _board(client, fresh_kitchen, "BAR")]


# --------------------------------------------------------------------------- #
# 5. Expiration, clôtures
# --------------------------------------------------------------------------- #
class TestExpirationEtClotures:
    def test_expiration_reservee_a_la_gestion(self, client, fresh_kitchen):
        response = client.post(
            f"/v1/ros/restaurants/{fresh_kitchen['rid']}/tickets/expire",
            headers=fresh_kitchen["waiter"]["headers"],
        )
        assert response.status_code == 403

    def test_expiration_annule_les_tickets_perimes(self, client, fresh_kitchen, monkeypatch):
        order = _order(client, fresh_kitchen, [{"product_id": _plat(client, fresh_kitchen), "quantity": 1}])
        ticket_id = _ticket_of(client, fresh_kitchen, order["id"])["id"]
        _at(monkeypatch, minutes=13 * 60)
        response = client.post(
            f"/v1/ros/restaurants/{fresh_kitchen['rid']}/tickets/expire",
            headers=fresh_kitchen["owner"]["headers"],
        )
        assert response.status_code == 200, response.text
        assert response.json()["cancelled"] >= 1
        monkeypatch.undo()
        assert ticket_id not in [t["id"] for t in _board(client, fresh_kitchen)]
        assert _move(client, fresh_kitchen, ticket_id, "IN_PREPARATION").status_code == 409

    def test_cloture_de_session_annule_les_tickets_ouverts(self, client, fresh_kitchen):
        k = fresh_kitchen
        session = client.post(
            f"/v1/ros/restaurants/{k['rid']}/sessions",
            headers=k["owner"]["headers"],
            json={"table_context": "Terrasse"},
        )
        assert session.status_code == 201, session.text
        plat = _plat(client, k)
        order = _order(client, k, [{"product_id": plat, "quantity": 1}], session_id=session.json()["id"])
        ticket_id = _ticket_of(client, k, order["id"])["id"]
        paid = client.post(
            f"/v1/ros/restaurants/{k['rid']}/payments",
            headers=k["owner"]["headers"],
            json={"invoice_id": order["invoice_id"], "payment_method": "CASH", "amount": order["total_amount"]},
        )
        assert paid.status_code == 201, paid.text
        closed = client.post(
            f"/v1/ros/restaurants/{k['rid']}/sessions/{session.json()['id']}/close",
            headers=k["owner"]["headers"],
        )
        assert closed.status_code == 200, closed.text
        assert ticket_id not in [t["id"] for t in _board(client, k)]
        assert _move(client, k, ticket_id, "IN_PREPARATION").status_code == 409

    def test_cloture_de_shift_balaie_les_tickets_perimes(self, client, fresh_kitchen, monkeypatch):
        k = fresh_kitchen
        order = _order(client, k, [{"product_id": _plat(client, k), "quantity": 1}])
        ticket_id = _ticket_of(client, k, order["id"])["id"]
        opened = client.post(
            f"/v1/ros/restaurants/{k['rid']}/shifts/open",
            headers=k["owner"]["headers"],
            json={"opening_balance": 0},
        )
        assert opened.status_code == 201, opened.text
        _at(monkeypatch, minutes=13 * 60)
        closed = client.post(
            f"/v1/ros/restaurants/{k['rid']}/shifts/close",
            headers=k["owner"]["headers"],
            json={"closing_balance_counted": 0},
        )
        assert closed.status_code == 200, closed.text
        monkeypatch.undo()
        assert ticket_id not in [t["id"] for t in _board(client, k)]


# --------------------------------------------------------------------------- #
# 6. Multi-tenant
# --------------------------------------------------------------------------- #
class TestCrossTenant:
    def test_un_autre_restaurant_ne_lit_ni_ne_modifie_les_tickets(self, client, kitchen, stranger):
        ticket_id = _ticket_in_state(client, kitchen, "QUEUED")
        read = client.get(f"/v1/ros/restaurants/{kitchen['rid']}/tickets/KITCHEN", headers=stranger["headers"])
        assert read.status_code in (403, 404)
        moved = _move(client, kitchen, ticket_id, "IN_PREPARATION", headers=stranger["headers"])
        assert moved.status_code in (403, 404)
        expired = client.post(
            f"/v1/ros/restaurants/{kitchen['rid']}/tickets/expire", headers=stranger["headers"]
        )
        assert expired.status_code in (403, 404)
        assert _board_status(client, kitchen, ticket_id) == "QUEUED"

    def test_un_ticket_ne_se_modifie_pas_via_un_autre_restaurant(self, client, kitchen, stranger):
        ticket_id = _ticket_in_state(client, kitchen, "QUEUED")
        response = client.put(
            f"/v1/ros/restaurants/{stranger['rid']}/tickets/{ticket_id}/status",
            headers=kitchen["owner"]["headers"],
            json={"status": "IN_PREPARATION"},
        )
        assert response.status_code in (403, 404)
        assert _board_status(client, kitchen, ticket_id) == "QUEUED"


# --------------------------------------------------------------------------- #
# 7. Flux WebSocket
# --------------------------------------------------------------------------- #
class TestFluxKds:
    def test_pas_de_fantome_apres_deconnexion_et_messages_non_json_tolerés(self, client, kitchen):
        from starlette.testclient import TestClient

        from app.main import app
        from app.utils.ws_manager import kds_manager

        rid = kitchen["rid"]
        key = f"{rid}:KITCHEN"
        token = kitchen["owner"]["headers"]["Authorization"].split()[1]
        with TestClient(app) as shared:
            with shared.websocket_connect(f"/v1/ros/ws/kds/{rid}/KITCHEN", subprotocols=["bearer", token]) as screen:
                guard = threading.Timer(20, screen.close)
                guard.daemon = True
                guard.start()
                screen.send_text("ping")
                assert screen.receive_text() == "pong"
                screen.send_text("ceci n'est pas du JSON {")
                screen.send_text("ping")
                assert screen.receive_text() == "pong", "un message non JSON ne ferme pas l'écran"
                assert key in kds_manager.active_connections
                guard.cancel()
        assert key not in kds_manager.active_connections, "écran désenregistré à la déconnexion"

    def test_un_membre_retire_perd_son_ecran(self, client, engine, fresh_kitchen, monkeypatch):
        from starlette.testclient import TestClient

        import app.api.v1.ros as ros_api
        from app.main import app

        monkeypatch.setattr(ros_api, "KDS_REVALIDATE_SECONDS", 0.2)
        rid = fresh_kitchen["rid"]
        waiter = fresh_kitchen["waiter"]
        token = waiter["headers"]["Authorization"].split()[1]
        with TestClient(app) as shared:
            with shared.websocket_connect(f"/v1/ros/ws/kds/{rid}/KITCHEN", subprotocols=["bearer", token]) as screen:
                guard = threading.Timer(20, screen.close)
                guard.daemon = True
                guard.start()
                sql_as_platform_admin(
                    engine,
                    "update restaurant_members set is_active = false where user_id = :uid",
                    uid=waiter["id"],
                )
                with pytest.raises(WebSocketDisconnect):
                    screen.receive_text()
                guard.cancel()
