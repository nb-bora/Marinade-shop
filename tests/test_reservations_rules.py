"""Règles des réservations et de la liste d'attente (intégrité, tables, fuseau, clients).

Chaque test crée son propre restaurant : les états ne se contaminent pas entre tests.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tests.support import headers_for, make_member, register


def _salle(client, tag="salle"):
    user = register(client, tag)
    h = headers_for(client, user)
    response = client.post(
        "/v1/restaurants",
        headers=h,
        json={"name": f"Resto {tag}", "currency": "XAF", "city": "Douala"},
    )
    assert response.status_code == 201, response.text
    return {**user, "headers": h, "rid": response.json()["id"]}


def _table(client, salle, numero, capacite=4, emplacement=None):
    body = {"numero": numero, "capacite": capacite}
    if emplacement:
        body["emplacement"] = emplacement
    response = client.post(
        f"/v1/restaurants/{salle['rid']}/tables", headers=salle["headers"], json=body
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _statut_table(client, salle, table_id):
    tables = client.get(f"/v1/restaurants/{salle['rid']}/tables", headers=salle["headers"]).json()
    return next(t["statut"] for t in tables if t["id"] == table_id)


def _a_partir_de(jours=3, heures=0):
    base = datetime.now(timezone.utc) + timedelta(days=jours, hours=heures)
    return base.replace(minute=0, second=0, microsecond=0).isoformat()


def _resa(client, salle, quand, table=None, party=2, name="Client", force=False, **extra):
    body = {
        "customer_name": name,
        "party_size": party,
        "reservation_date": quand,
        "duration_minutes": extra.pop("duration_minutes", 90),
        **extra,
    }
    if table:
        body["table_id"] = table
    url = f"/v1/reservations/restaurants/{salle['rid']}/reservations"
    return client.post(url, headers=salle["headers"], json=body, params={"force": force} if force else None)


def _action(client, salle, reservation_id, action, **kwargs):
    return client.post(
        f"/v1/reservations/{reservation_id}/{action}", headers=salle["headers"], **kwargs
    )


def _vers_etat(client, salle, cible, table=None):
    """Crée une réservation et la conduit jusqu'à l'état demandé."""
    created = _resa(client, salle, _a_partir_de(jours=5), table=table)
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    chemin = {
        "pending": [],
        "confirmed": ["confirm"],
        "checked_in": ["confirm", "check-in"],
        "completed": ["confirm", "check-in", "complete"],
        "cancelled": ["cancel"],
        "no_show": ["no-show"],
    }[cible]
    for etape in chemin:
        if etape == "cancel":
            response = _action(client, salle, rid, "cancel", json={"reason": "Test"})
        else:
            response = _action(client, salle, rid, etape)
        assert response.status_code == 200, (etape, response.text)
    return rid


# --------------------------------------------------------------------------- transitions


@pytest.mark.parametrize(
    ("etat", "action", "corps"),
    [
        ("cancelled", "check-in", None),
        ("cancelled", "confirm", None),
        ("no_show", "check-in", None),
        ("no_show", "confirm", None),
        ("completed", "cancel", {"reason": "Trop tard"}),
        ("completed", "no-show", None),
        ("pending", "complete", None),
        ("checked_in", "no-show", None),
        ("checked_in", "cancel", {"reason": "Imprévu"}),
        ("confirmed", "complete", None),
    ],
)
def test_transition_interdite_renvoie_409(client, etat, action, corps):
    salle = _salle(client, f"interdit-{etat}-{action.replace('-', '')}")
    rid = _vers_etat(client, salle, etat)
    response = _action(client, salle, rid, action, json=corps) if corps else _action(client, salle, rid, action)
    assert response.status_code == 409, response.text
    assert "impossible" in response.json()["detail"]


def test_confirmer_deux_fois_ne_change_rien(client):
    salle = _salle(client, "double-confirm")
    rid = _vers_etat(client, salle, "confirmed")
    again = _action(client, salle, rid, "confirm", json={})
    assert again.status_code == 200 and again.json()["status"] == "confirmed"


def test_no_show_et_terminer_horodatent(client):
    salle = _salle(client, "no-show")
    absent = _vers_etat(client, salle, "no_show")
    body = client.get(f"/v1/reservations/{absent}", headers=salle["headers"]).json()
    assert body["status"] == "no_show" and body["no_show_at"]

    arrivee = _vers_etat(client, salle, "completed")
    body = client.get(f"/v1/reservations/{arrivee}", headers=salle["headers"]).json()
    assert body["status"] == "completed" and body["completed_at"] and body["checked_in_at"]


def test_statut_dans_la_mise_a_jour_est_refuse(client):
    salle = _salle(client, "statut-put")
    rid = _vers_etat(client, salle, "pending")
    response = client.put(f"/v1/reservations/{rid}", headers=salle["headers"], json={"status": "confirmed"})
    assert response.status_code == 422


# --------------------------------------------------------------------------- chevauchement et tables


def test_chevauchement_sur_une_table_est_refuse(client):
    salle = _salle(client, "chevauche")
    table = _table(client, salle, "T1", capacite=4)
    debut = _a_partir_de(jours=4, heures=19)
    premiere = _resa(client, salle, debut, table=table, name="Premier")
    assert premiere.status_code == 201, premiere.text

    decale = (datetime.fromisoformat(debut) + timedelta(minutes=60)).isoformat()
    conflit = _resa(client, salle, decale, table=table, name="Second")
    assert conflit.status_code == 409
    assert conflit.json()["details"]["customer_name"] == "Premier"
    assert conflit.json()["details"]["heure"]

    adjacent = (datetime.fromisoformat(debut) + timedelta(minutes=90)).isoformat()
    assert _resa(client, salle, adjacent, table=table, name="Suivant").status_code == 201


def test_deplacer_une_reservation_sur_une_table_occupee_est_refuse(client):
    salle = _salle(client, "deplace")
    table = _table(client, salle, "D1", capacite=4)
    debut = _a_partir_de(jours=6, heures=19)
    _resa(client, salle, debut, table=table, name="Occupe")
    libre = _resa(client, salle, _a_partir_de(jours=6, heures=12), name="Libre")
    rid = libre.json()["id"]
    response = client.put(f"/v1/reservations/{rid}", headers=salle["headers"], json={"table_id": table, "reservation_date": debut})
    assert response.status_code == 409


def test_table_reservee_a_la_confirmation_puis_liberee_a_l_annulation(client):
    salle = _salle(client, "cycle-table")
    table = _table(client, salle, "C1", capacite=4)
    rid = _resa(client, salle, _a_partir_de(jours=7), table=table).json()["id"]
    assert _statut_table(client, salle, table) == "libre"
    _action(client, salle, rid, "confirm", json={})
    assert _statut_table(client, salle, table) == "reservee"
    annulee = _action(client, salle, rid, "cancel", json={"reason": "Changement"})
    assert annulee.status_code == 200
    assert _statut_table(client, salle, table) == "libre"


def test_arrivee_occupe_la_table_et_ouvre_une_session(client):
    salle = _salle(client, "arrivee")
    table = _table(client, salle, "A1", capacite=4, emplacement="Terrasse")
    rid = _resa(client, salle, _a_partir_de(jours=8), table=table, party=3).json()["id"]
    _action(client, salle, rid, "confirm", json={})
    arrivee = _action(client, salle, rid, "check-in")
    assert arrivee.status_code == 200, arrivee.text
    body = arrivee.json()
    assert body["status"] == "checked_in" and body["session_id"]
    assert _statut_table(client, salle, table) == "occupee"

    # Deux heures plus tard : hors chevauchement (le premier dure 90 min), la table reste le sujet.
    seconde = _resa(client, salle, _a_partir_de(jours=8, heures=2), table=table, name="Autre").json()["id"]
    _action(client, salle, seconde, "confirm", json={})
    refus = _action(client, salle, seconde, "check-in")
    assert refus.status_code == 409


# --------------------------------------------------------------------------- capacité, date, horaires


def test_capacite_depassee_refusee_sauf_gestion_forcee(client):
    salle = _salle(client, "capacite")
    table = _table(client, salle, "P1", capacite=2)
    quand = _a_partir_de(jours=9)
    assert _resa(client, salle, quand, table=table, party=3).status_code == 409
    forcee = _resa(client, salle, quand, table=table, party=3, force=True)
    assert forcee.status_code == 201, forcee.text


def test_force_refuse_au_personnel_sans_gestion(client, engine):
    salle = _salle(client, "force-serveur")
    table = _table(client, salle, "S1", capacite=2)
    serveur = make_member(client, engine, salle, "waiter")
    response = client.post(
        f"/v1/reservations/restaurants/{salle['rid']}/reservations",
        headers=serveur["headers"],
        json={
            "customer_name": "X",
            "party_size": 4,
            "reservation_date": _a_partir_de(jours=9),
            "table_id": table,
        },
        params={"force": True},
    )
    assert response.status_code == 403


def test_date_naive_refusee(client):
    salle = _salle(client, "naive")
    response = _resa(client, salle, "2030-03-12T19:00:00")
    assert response.status_code == 422


def test_date_passee_refusee_sauf_gestion(client):
    salle = _salle(client, "passee")
    passee = _a_partir_de(jours=-2)
    assert _resa(client, salle, passee).status_code == 422
    assert _resa(client, salle, passee, force=True).status_code == 201


def test_hors_horaires_refuse_sauf_gestion(client):
    salle = _salle(client, "horaires")
    fermé = {
        jour: {"actif": False, "ouverture": "08:00", "fermeture": "22:00", "plages": []}
        for jour in ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    }
    assert client.put(
        f"/v1/restaurants/{salle['rid']}", headers=salle["headers"], json={"horaires_ouverture": fermé}
    ).status_code == 200
    quand = _a_partir_de(jours=10, heures=19)
    assert _resa(client, salle, quand).status_code == 422
    assert _resa(client, salle, quand, force=True).status_code == 201


# --------------------------------------------------------------------------- liste d'attente


def _attente(client, salle, nom, couverts=2):
    response = client.post(
        f"/v1/reservations/restaurants/{salle['rid']}/waitlist",
        headers=salle["headers"],
        json={"customer_name": nom, "party_size": couverts},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_installer_sur_table_occupee_refuse(client):
    salle = _salle(client, "install-occupee")
    table = _table(client, salle, "O1", capacite=4)
    rid = _resa(client, salle, _a_partir_de(jours=11), table=table).json()["id"]
    _action(client, salle, rid, "confirm", json={})
    _action(client, salle, rid, "check-in")
    entree = _attente(client, salle, "Attente")
    response = client.post(
        f"/v1/reservations/waitlist/{entree['id']}/seat", headers=salle["headers"], params={"table_id": table}
    )
    assert response.status_code == 409


def test_installer_deux_fois_refuse(client):
    salle = _salle(client, "install-deux-fois")
    table = _table(client, salle, "I1", capacite=4)
    entree = _attente(client, salle, "Groupe")
    url = f"/v1/reservations/waitlist/{entree['id']}/seat"
    assert client.post(url, headers=salle["headers"], params={"table_id": table}).status_code == 200
    assert client.post(url, headers=salle["headers"], params={"table_id": table}).status_code == 409


def test_installer_une_entree_retiree_refuse(client):
    salle = _salle(client, "retire-installe")
    table = _table(client, salle, "R1", capacite=4)
    entree = _attente(client, salle, "Parti")
    assert client.delete(
        f"/v1/reservations/waitlist/{entree['id']}", headers=salle["headers"], params={"reason": "parti"}
    ).status_code == 204
    response = client.post(
        f"/v1/reservations/waitlist/{entree['id']}/seat", headers=salle["headers"], params={"table_id": table}
    )
    assert response.status_code == 409


def test_renumerotation_apres_installation_et_retrait(client):
    salle = _salle(client, "renumero")
    table = _table(client, salle, "N1", capacite=4)
    a, b, c = (_attente(client, salle, nom) for nom in ("A", "B", "C"))
    client.post(
        f"/v1/reservations/waitlist/{a['id']}/seat", headers=salle["headers"], params={"table_id": table}
    )
    liste = client.get(
        f"/v1/reservations/restaurants/{salle['rid']}/waitlist",
        headers=salle["headers"],
        params={"status": "WAITING"},
    ).json()
    assert [(e["customer_name"], e["position"]) for e in liste] == [("B", 1), ("C", 2)]

    client.delete(f"/v1/reservations/waitlist/{b['id']}", headers=salle["headers"], params={"reason": "parti"})
    liste = client.get(
        f"/v1/reservations/restaurants/{salle['rid']}/waitlist",
        headers=salle["headers"],
        params={"status": "WAITING"},
    ).json()
    assert [(e["customer_name"], e["position"]) for e in liste] == [("C", 1)]


def test_huit_ajouts_simultanes_gardent_des_positions_uniques(client):
    salle = _salle(client, "course")
    url = f"/v1/reservations/restaurants/{salle['rid']}/waitlist"

    def ajouter(indice):
        local = TestClient(client.app)
        return local.post(
            url, headers=salle["headers"], json={"customer_name": f"G{indice}", "party_size": 2}
        ).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuts = list(pool.map(ajouter, range(8)))
    assert statuts == [201] * 8
    liste = client.get(url, headers=salle["headers"], params={"status": "WAITING"}).json()
    assert sorted(e["position"] for e in liste) == list(range(1, 9))


def test_prevenir_exige_une_adresse(client):
    salle = _salle(client, "prevenir")
    sans = _attente(client, salle, "Sans mail")
    response = client.post(f"/v1/reservations/waitlist/{sans['id']}/notify", headers=salle["headers"])
    assert response.status_code == 422

    avec = client.post(
        f"/v1/reservations/restaurants/{salle['rid']}/waitlist",
        headers=salle["headers"],
        json={"customer_name": "Avec mail", "party_size": 2, "customer_email": "client@example.test"},
    ).json()
    ok = client.post(f"/v1/reservations/waitlist/{avec['id']}/notify", headers=salle["headers"])
    assert ok.status_code == 200 and ok.json()["destinataire"] == "client@example.test"


# --------------------------------------------------------------------------- isolation


def test_autre_restaurant_obtient_404(client, owner, stranger):
    salle = _salle(client, "isole")
    rid = _resa(client, salle, _a_partir_de(jours=12)).json()["id"]
    intrus = stranger["headers"]
    assert client.get(f"/v1/reservations/{rid}", headers=intrus).status_code == 404
    assert client.put(f"/v1/reservations/{rid}", headers=intrus, json={"party_size": 3}).status_code == 404
    assert client.post(f"/v1/reservations/{rid}/cancel", headers=intrus, json={"reason": "x"}).status_code == 404


def test_client_d_un_autre_restaurant_est_refuse(client, stranger):
    salle = _salle(client, "client-croise")
    etranger = client.post(
        f"/v1/ros/restaurants/{stranger['rid']}/customers",
        headers=stranger["headers"],
        json={"name": "Autre", "phone": "+237677000111"},
    )
    assert etranger.status_code == 201, etranger.text
    response = _resa(client, salle, _a_partir_de(jours=13), customer_id=etranger.json()["id"])
    assert response.status_code == 400


# --------------------------------------------------------------------------- clients


def test_recherche_et_historique_client(client):
    salle = _salle(client, "clients")
    cree = client.post(
        f"/v1/ros/restaurants/{salle['rid']}/customers",
        headers=salle["headers"],
        json={"name": "Mme Mbarga", "phone": "+237699123456"},
    )
    assert cree.status_code == 201, cree.text
    cid = cree.json()["id"]
    trouves = client.get(
        f"/v1/reservations/restaurants/{salle['rid']}/customers/search",
        headers=salle["headers"],
        params={"q": "Mbarga"},
    ).json()
    assert [c["id"] for c in trouves] == [cid]

    absente = _resa(client, salle, _a_partir_de(jours=14), customer_id=cid).json()["id"]
    _action(client, salle, absente, "no-show")
    resume = client.get(
        f"/v1/reservations/restaurants/{salle['rid']}/customers/{cid}/summary", headers=salle["headers"]
    ).json()
    assert resume["absences"] == 1 and resume["reservations"] == 1 and resume["visites"] == 0


# --------------------------------------------------------------------------- disponibilité et fuseau


def test_disponibilite_par_creneau(client):
    salle = _salle(client, "dispo")
    _table(client, salle, "D2", capacite=2)
    grande = _table(client, salle, "D6", capacite=6)
    jour = (datetime.now(timezone.utc) + timedelta(days=15)).date().isoformat()
    _resa(client, salle, f"{jour}T19:00:00+01:00", table=grande, party=4)

    response = client.get(
        f"/v1/reservations/restaurants/{salle['rid']}/availability",
        headers=salle["headers"],
        params={"date": jour, "party_size": 2, "duration": 90},
    )
    assert response.status_code == 200, response.text
    corps = response.json()
    assert corps["fuseau"] == "Africa/Douala"
    creneaux = {c["heure"]: c for c in corps["creneaux"]}
    assert creneaux["19:00"]["tables_libres"] == 1
    assert creneaux["21:00"]["tables_libres"] == 2
    assert creneaux["19:00"]["disponible"] is True


def test_disponibilite_sans_table_assez_grande(client):
    salle = _salle(client, "dispo-petite")
    _table(client, salle, "P2", capacite=2)
    jour = (datetime.now(timezone.utc) + timedelta(days=16)).date().isoformat()
    corps = client.get(
        f"/v1/reservations/restaurants/{salle['rid']}/availability",
        headers=salle["headers"],
        params={"date": jour, "party_size": 8},
    ).json()
    assert corps["creneaux"] and not any(c["disponible"] for c in corps["creneaux"])


def test_fuseau_expose_et_valide(client):
    salle = _salle(client, "fuseau")
    assert client.get(f"/v1/restaurants/{salle['rid']}", headers=salle["headers"]).json()["timezone"] == "Africa/Douala"
    maj = client.put(f"/v1/restaurants/{salle['rid']}", headers=salle["headers"], json={"timezone": "Asia/Tokyo"})
    assert maj.status_code == 200 and maj.json()["timezone"] == "Asia/Tokyo"
    assert client.put(
        f"/v1/restaurants/{salle['rid']}", headers=salle["headers"], json={"timezone": "Mars/Olympus"}
    ).status_code == 422
    assert client.put(
        f"/v1/restaurants/{salle['rid']}", headers=salle["headers"], json={"timezone": None}
    ).status_code == 422


def test_dates_de_reponse_avec_decalage(client):
    salle = _salle(client, "iso")
    created = _resa(client, salle, "2030-06-01T19:00:00+01:00")
    assert created.status_code == 201, created.text
    assert created.json()["reservation_date"].startswith("2030-06-01T18:00:00")
