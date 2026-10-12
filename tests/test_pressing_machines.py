"""Espace pressing : machines, zones, états, maintenances, plan (unitaire + intégration).

Les tests unitaires n'ont besoin d'aucune base. Les tests d'intégration exigent
TEST_DATABASE_URL (voir conftest.py) :

    pytest tests/test_pressing_machines.py -v
"""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.schemas.pressing_machines import MachineIn, MaintenanceIn, ZoneIn
from app.services import pressing_machine_etats as etats
from app.services.pressing_calcul import PressingRegleError
from tests.support import headers_for, make_member, register

# --------------------------------------------------------------------------- #
# Unitaires
# --------------------------------------------------------------------------- #
AUTORISEES = [
    ("libre", "reservee"),
    ("libre", "en_cycle"),
    ("libre", "maintenance"),
    ("libre", "hors_service"),
    ("reservee", "libre"),
    ("reservee", "en_cycle"),
    ("en_cycle", "cycle_termine"),
    ("cycle_termine", "attente_dechargement"),
    ("cycle_termine", "libre"),
    ("attente_dechargement", "libre"),
    ("maintenance", "libre"),
    ("maintenance", "hors_service"),
    ("hors_service", "libre"),
    ("hors_service", "maintenance"),
]


class TestTransitions:
    def test_table_complete(self):
        assert set(etats.TRANSITIONS) == set(etats.ETATS)
        assert sum(len(v) for v in etats.TRANSITIONS.values()) == len(AUTORISEES)

    @pytest.mark.parametrize("actuel, cible", AUTORISEES)
    def test_transitions_autorisees(self, actuel, cible):
        etats.verifier_transition(actuel, cible, motif="panne moteur")

    @pytest.mark.parametrize(
        "actuel, cible",
        [
            ("libre", "libre"),
            ("libre", "cycle_termine"),
            ("libre", "attente_dechargement"),
            ("reservee", "maintenance"),
            ("en_cycle", "libre"),
            ("en_cycle", "maintenance"),
            ("en_cycle", "hors_service"),
            ("cycle_termine", "en_cycle"),
            ("attente_dechargement", "en_cycle"),
            ("maintenance", "en_cycle"),
            ("maintenance", "reservee"),
            ("hors_service", "en_cycle"),
        ],
    )
    def test_transitions_interdites(self, actuel, cible):
        with pytest.raises(etats.TransitionInterdite, match="Transition interdite"):
            etats.verifier_transition(actuel, cible, motif="x")

    @pytest.mark.parametrize("cible", ["maintenance", "hors_service"])
    @pytest.mark.parametrize("motif", [None, "", "   "])
    def test_motif_obligatoire(self, cible, motif):
        with pytest.raises(PressingRegleError, match="motif est obligatoire"):
            etats.verifier_transition("libre", cible, motif)

    def test_motif_facultatif_ailleurs(self):
        etats.verifier_transition("libre", "reservee")
        etats.verifier_transition("maintenance", "libre")


def machine(**extra):
    base = {"nom": "Lave 1", "categorie": "lave_linge", "capacite_kg": "8"}
    base.update(extra)
    return base


PROGRAMME = {"nom": "Coton 60", "duree_min": 90, "types_linge": ["coton"]}


class TestValidation:
    def test_machine_minimale(self):
        m = MachineIn(**machine())
        assert m.type_fonctionnement == "automatique" and m.programmes == []
        assert m.capacite_kg == Decimal("8")

    @pytest.mark.parametrize("capacite", ["0", "-1", "200.01", "201", "8.123"])
    def test_capacite_refusee(self, capacite):
        with pytest.raises(ValidationError):
            MachineIn(**machine(capacite_kg=capacite))

    @pytest.mark.parametrize("capacite", ["0.01", "8.5", "200"])
    def test_capacite_acceptee(self, capacite):
        assert MachineIn(**machine(capacite_kg=capacite)).capacite_kg == Decimal(capacite)

    def test_nom_vide_refuse(self):
        with pytest.raises(ValidationError):
            MachineIn(**machine(nom="   "))

    def test_programmes_30_maximum(self):
        MachineIn(**machine(programmes=[PROGRAMME] * 30))
        with pytest.raises(ValidationError):
            MachineIn(**machine(programmes=[PROGRAMME] * 31))

    @pytest.mark.parametrize(
        "programme",
        [
            {**PROGRAMME, "duree_min": 0},
            {**PROGRAMME, "duree_min": 721},
            {**PROGRAMME, "nom": ""},
            {**PROGRAMME, "nom": "x" * 81},
            {**PROGRAMME, "etapes": [{"nom": "Rinçage", "duree_min": 0}]},
        ],
    )
    def test_programme_invalide(self, programme):
        with pytest.raises(ValidationError):
            MachineIn(**machine(programmes=[programme]))

    def test_etapes_et_types_linge(self):
        m = MachineIn(
            **machine(
                programmes=[
                    {
                        **PROGRAMME,
                        "types_linge": ["coton", "coton", " drap "],
                        "etapes": [{"nom": "Lavage", "duree_min": 60}],
                    }
                ]
            )
        )
        assert m.programmes[0].types_linge == ["coton", "drap"]
        assert m.programmes[0].etapes[0].duree_min == 60

    def test_seche_linge_exige_un_programme(self):
        with pytest.raises(ValidationError, match="au moins un programme"):
            MachineIn(**machine(categorie="seche_linge"))
        MachineIn(**machine(categorie="seche_linge", programmes=[PROGRAMME]))

    def test_intervention_humaine_exige_semi_automatique(self):
        humain = {**PROGRAMME, "intervention_humaine": True}
        with pytest.raises(ValidationError, match="semi-automatique"):
            MachineIn(**machine(programmes=[humain]))
        with pytest.raises(ValidationError, match="semi-automatique"):
            MachineIn(**machine(programmes=[humain], type_fonctionnement="automatique"))
        MachineIn(**machine(programmes=[humain], type_fonctionnement="semi_automatique"))

    def test_positions_et_consommations(self):
        with pytest.raises(ValidationError):
            MachineIn(**machine(position_x=100.5))
        with pytest.raises(ValidationError):
            MachineIn(**machine(conso_eau_litres_cycle="-1"))
        MachineIn(**machine(position_x=0, position_y=100, conso_eau_litres_cycle="0"))

    def test_zone_geometrie(self):
        base = {"nom": "Lavage", "type": "lavage", "couleur": "#aabbcc", "x": 10, "y": 10, "w": 40, "h": 40}
        assert ZoneIn(**base).couleur == "#AABBCC"
        for faux in (
            {"w": 0},
            {"h": 0},
            {"x": 61},  # x + w > 100
            {"y": 61},
            {"couleur": "rouge"},
            {"couleur": "#abc"},
            {"type": "cuisine"},
        ):
            with pytest.raises(ValidationError):
                ZoneIn(**{**base, **faux})

    def test_maintenance_fin_avant_debut(self):
        with pytest.raises(ValidationError, match="précède"):
            MaintenanceIn(
                type="panne", description="x", debut="2026-10-09T10:00:00Z", fin="2026-10-09T09:00:00Z"
            )


# --------------------------------------------------------------------------- #
# Intégration : API
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def pressing(client):
    """Propriétaire d'un établissement de type pressing."""

    def make(tag="pressing"):
        user = register(client, tag)
        headers = headers_for(client, user)
        created = client.post(
            "/v1/restaurants",
            headers=headers,
            json={"name": f"ZZ {tag}", "type_etablissement": "pressing"},
        )
        assert created.status_code == 201, created.text
        return {**user, "headers": headers, "rid": created.json()["id"]}

    return make


@pytest.fixture(scope="module")
def p1(pressing):
    return pressing("pressing-a")


@pytest.fixture(scope="module")
def p2(pressing):
    return pressing("pressing-b")


def u(owner, path=""):
    return f"/v1/restaurants/{owner['rid']}/pressing{path}"


ZONE = {"nom": "Lavage", "type": "lavage", "couleur": "#3B82F6", "x": 5, "y": 5, "w": 40, "h": 50}


def make_zone(client, owner, **extra):
    r = client.post(u(owner, "/zones"), headers=owner["headers"], json={**ZONE, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def make_machine(client, owner, **extra):
    body = {"nom": f"M-{uuid.uuid4().hex[:6]}", "categorie": "lave_linge", "capacite_kg": "8", **extra}
    r = client.post(u(owner, "/machines"), headers=owner["headers"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def set_etat(client, owner, machine, etat, motif=None):
    return client.post(
        u(owner, f"/machines/{machine['id']}/etat"),
        headers=owner["headers"],
        json={"etat": etat, "motif": motif},
    )


def audit(engine, owner, action):
    with engine.begin() as conn:
        conn.execute(text("select set_config('app.is_platform_admin', 'true', true)"))
        return conn.execute(
            text(
                "select before_state, after_state, actor_id from ros_audit_logs"
                " where restaurant_id = :rid and action = :action order by created_at, id"
            ),
            {"rid": owner["rid"], "action": action},
        ).all()


class TestTypeEtablissement:
    def test_defaut_restaurant_et_exposition(self, client, owner):
        r = client.get(f"/v1/restaurants/{owner['rid']}", headers=owner["headers"])
        assert r.json()["type_etablissement"] == "restaurant"

    def test_creation_pressing(self, client, p1):
        r = client.get(f"/v1/restaurants/{p1['rid']}", headers=p1["headers"])
        assert r.status_code == 200
        assert r.json()["type_etablissement"] == "pressing"
        me = client.get("/v1/restaurants/me", headers=p1["headers"])
        assert me.json()["type_etablissement"] == "pressing"

    def test_type_inconnu_refuse(self, client):
        user = register(client, "typeko")
        r = client.post(
            "/v1/restaurants",
            headers=headers_for(client, user),
            json={"name": "X", "type_etablissement": "boulangerie"},
        )
        assert r.status_code == 422

    def test_modification_refusee_409(self, client, p1):
        r = client.put(
            f"/v1/restaurants/{p1['rid']}", headers=p1["headers"], json={"type_etablissement": "restaurant"}
        )
        assert r.status_code == 409
        assert r.json()["detail"] == "Le type d'établissement ne se change pas après la création"

    def test_meme_valeur_toleree_et_autres_champs_modifiables(self, client, p1):
        r = client.put(
            f"/v1/restaurants/{p1['rid']}",
            headers=p1["headers"],
            json={"type_etablissement": "pressing", "city": "Douala"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["city"] == "Douala" and r.json()["type_etablissement"] == "pressing"

    def test_acces_utilisateur_expose_le_type(self, client, p1):
        r = client.get("/v1/users/me/access", headers=p1["headers"])
        assert r.status_code == 200, r.text
        assert [a["type_etablissement"] for a in r.json()] == ["pressing"]


class TestZones:
    def test_crud_et_unicite(self, client, p1):
        zone = make_zone(client, p1)
        assert set(zone) == {"id", "nom", "type", "couleur", "x", "y", "w", "h"}
        assert zone["couleur"] == "#3B82F6" and zone["w"] == 40
        # Nom en double, sans tenir compte de la casse.
        r = client.post(u(p1, "/zones"), headers=p1["headers"], json={**ZONE, "nom": "LAVAGE"})
        assert r.status_code == 409
        # Mise en page par PUT.
        r = client.put(
            u(p1, f"/zones/{zone['id']}"), headers=p1["headers"], json={**ZONE, "x": 20, "w": 30}
        )
        assert r.status_code == 200 and r.json()["x"] == 20 and r.json()["w"] == 30
        listed = client.get(u(p1, "/zones"), headers=p1["headers"]).json()
        assert [z["id"] for z in listed] == [zone["id"]]
        assert client.delete(u(p1, f"/zones/{zone['id']}"), headers=p1["headers"]).status_code == 204
        assert client.get(u(p1, "/zones"), headers=p1["headers"]).json() == []

    @pytest.mark.parametrize(
        "faux",
        [{"w": 0}, {"x": 70}, {"y": 60, "h": 50}, {"couleur": "bleu"}, {"type": "cuisine"}, {"nom": " "}],
    )
    def test_zone_invalide_422(self, client, p1, faux):
        r = client.post(u(p1, "/zones"), headers=p1["headers"], json={**ZONE, "nom": "Zone invalide", **faux})
        assert r.status_code == 422

    def test_suppression_refusee_avec_machine(self, client, p1):
        zone = make_zone(client, p1, nom="Séchage", type="sechage", x=50, y=5)
        make_machine(client, p1, zone_id=zone["id"])
        r = client.delete(u(p1, f"/zones/{zone['id']}"), headers=p1["headers"])
        assert r.status_code == 409
        assert "rattachée" in r.json()["detail"]

    def test_zone_inconnue_404(self, client, p1):
        r = client.put(u(p1, f"/zones/{uuid.uuid4()}"), headers=p1["headers"], json=ZONE)
        assert r.status_code == 404


class TestMachines:
    def test_machines_completes_et_plan(self, client, engine, p1):
        zone = make_zone(client, p1, nom="Atelier plan", x=0, y=60, w=100, h=40)
        lave = make_machine(
            client,
            p1,
            nom="Lave-linge 8 kg",
            marque="LG",
            modele="F4",
            numero_serie="SN-LAVE-1",
            type_fonctionnement="semi_automatique",
            capacite_kg="8",
            programmes=[
                {"nom": "Coton 60", "duree_min": 90, "types_linge": ["coton", "drap"]},
                {
                    "nom": "Délicat",
                    "duree_min": 45,
                    "types_linge": ["delicat"],
                    "intervention_humaine": True,
                    "etapes": [{"nom": "Lavage", "duree_min": 30}, {"nom": "Rinçage", "duree_min": 15}],
                },
                {"nom": "Rapide", "duree_min": 20, "types_linge": ["tout"]},
            ],
            zone_id=zone["id"],
            position_x=10.5,
            position_y=70,
            conso_electrique_kwh_cycle="1.2",
            conso_eau_litres_cycle="55.5",
            date_mise_en_service="2025-03-01",
            remarques="Porte lourde",
            contraintes="Pas de couette",
        )
        assert lave["etat_operationnel"] == "libre" and lave["actif"] is True
        assert lave["commande_courante_id"] is None and lave["fin_estimee"] is None
        assert len(lave["programmes"]) == 3 and lave["programmes"][1]["intervention_humaine"] is True
        assert lave["programmes"][1]["etapes"][1] == {"nom": "Rinçage", "duree_min": 15}
        assert lave["programmes"][0]["intervention_humaine"] is False
        assert lave["capacite_kg"] == "8.00" and lave["position_x"] == 10.5
        assert lave["cree_le"] and lave["modifie_le"]

        seche = make_machine(
            client,
            p1,
            nom="Sèche-linge 10 kg",
            categorie="seche_linge",
            capacite_kg="10",
            programmes=[{"nom": "Standard", "duree_min": 60, "types_linge": ["tout"]}],
            zone_id=zone["id"],
            position_x=60,
            position_y=70,
        )
        # Sèche-linge sans programme : 422.
        r = client.post(
            u(p1, "/machines"),
            headers=p1["headers"],
            json={"nom": "Sèche vide", "categorie": "seche_linge", "capacite_kg": "9"},
        )
        assert r.status_code == 422

        plan = client.get(u(p1, "/plan"), headers=p1["headers"]).json()
        assert zone["id"] in [z["id"] for z in plan["zones"]]
        by_id = {m["id"]: m for m in plan["machines"]}
        assert set(by_id[lave["id"]]) == {
            "id", "nom", "categorie", "type_fonctionnement", "etat_operationnel",
            "zone_id", "position_x", "position_y", "capacite_kg", "actif",
        }
        assert by_id[seche["id"]]["categorie"] == "seche_linge"

        # Filtres de liste.
        assert {m["id"] for m in client.get(u(p1, "/machines?categorie=seche_linge"), headers=p1["headers"]).json()} == {seche["id"]}
        assert lave["id"] in {m["id"] for m in client.get(u(p1, "/machines?etat=libre&actif=true"), headers=p1["headers"]).json()}
        assert client.get(u(p1, "/machines?etat=nimporte"), headers=p1["headers"]).status_code == 422

        # PUT : champs de saisie, jamais l'état.
        body = {
            "nom": "Lave-linge 8 kg", "categorie": "lave_linge", "capacite_kg": "9.5",
            "type_fonctionnement": "semi_automatique", "numero_serie": "SN-LAVE-1",
            "programmes": [{"nom": "Coton 40", "duree_min": 80, "types_linge": ["coton"]}],
            "etat_operationnel": "hors_service",
        }
        r = client.put(u(p1, f"/machines/{lave['id']}"), headers=p1["headers"], json=body)
        assert r.status_code == 200, r.text
        assert r.json()["capacite_kg"] == "9.50" and r.json()["etat_operationnel"] == "libre"
        assert len(r.json()["programmes"]) == 1
        assert audit(engine, p1, "PRESSING_MACHINE_UPDATE")

        # Doublons : nom (casse) et numéro de série.
        r = client.post(u(p1, "/machines"), headers=p1["headers"], json={**body, "nom": "LAVE-LINGE 8 KG", "numero_serie": "autre"})
        assert r.status_code == 409
        r = client.post(u(p1, "/machines"), headers=p1["headers"], json={**body, "nom": "Autre nom", "numero_serie": "sn-lave-1"})
        assert r.status_code == 409
        assert "série" in r.json()["detail"]

    def test_zone_d_un_autre_restaurant_refusee(self, client, p1, p2):
        zone_p2 = make_zone(client, p2, nom="Chez B")
        r = client.post(
            u(p1, "/machines"),
            headers=p1["headers"],
            json={"nom": "Intruse", "categorie": "lave_linge", "capacite_kg": "5", "zone_id": zone_p2["id"]},
        )
        assert r.status_code == 422

    def test_machine_inconnue_404(self, client, p1):
        assert client.get(u(p1, f"/machines/{uuid.uuid4()}"), headers=p1["headers"]).status_code == 404


class TestEtatsHistoriqueMaintenance:
    def test_transitions_valides_invalides_et_historique(self, client, engine, p1):
        m = make_machine(client, p1)
        assert set_etat(client, p1, m, "en_cycle").json()["etat_operationnel"] == "en_cycle"
        # Interdit : en_cycle -> libre
        r = set_etat(client, p1, m, "libre")
        assert r.status_code == 409 and "Transition interdite" in r.json()["detail"]
        assert set_etat(client, p1, m, "cycle_termine").status_code == 200
        assert set_etat(client, p1, m, "attente_dechargement").status_code == 200
        assert set_etat(client, p1, m, "libre").json()["etat_operationnel"] == "libre"
        # Motif obligatoire.
        assert set_etat(client, p1, m, "hors_service").status_code == 422
        assert set_etat(client, p1, m, "hors_service", "Moteur HS").status_code == 200
        assert set_etat(client, p1, m, "en_cycle").status_code == 409

        histo = client.get(u(p1, f"/machines/{m['id']}/historique"), headers=p1["headers"]).json()
        assert [(e["ancien_etat"], e["nouvel_etat"]) for e in histo] == [
            ("libre", "hors_service"),
            ("attente_dechargement", "libre"),
            ("cycle_termine", "attente_dechargement"),
            ("en_cycle", "cycle_termine"),
            ("libre", "en_cycle"),
        ]
        assert histo[0]["type"] == "etat_change" and histo[0]["motif"] == "Moteur HS"
        assert histo[0]["auteur_id"] == p1["id"]
        assert set(histo[0]) >= {"id", "date", "type", "ancien_etat", "nouvel_etat", "motif", "auteur_id"}
        page = client.get(u(p1, f"/machines/{m['id']}/historique?skip=1&limit=2"), headers=p1["headers"]).json()
        assert [e["id"] for e in page] == [e["id"] for e in histo[1:3]]

        # Note.
        r = client.post(u(p1, f"/machines/{m['id']}/historique"), headers=p1["headers"], json={"motif": "Visite du technicien"})
        assert r.status_code == 201 and r.json()["type"] == "note"

        logs = audit(engine, p1, "PRESSING_MACHINE_ETAT")
        assert len(logs) >= 5
        assert logs[0].before_state["etat_operationnel"] == "libre"
        assert logs[0].after_state["etat_operationnel"] == "en_cycle"
        assert str(logs[0].actor_id) == p1["id"]

    def test_maintenance_ouverte_puis_cloturee(self, client, engine, p1):
        m = make_machine(client, p1)
        r = client.post(
            u(p1, f"/machines/{m['id']}/maintenances"),
            headers=p1["headers"],
            json={"type": "panne", "description": "Ne vidange plus", "duree_estimee_min": 120},
        )
        assert r.status_code == 201, r.text
        maint = r.json()
        assert maint["fin"] is None and maint["indisponibilite_min"] is None
        assert maint["duree_estimee_min"] == 120
        current = client.get(u(p1, f"/machines/{m['id']}"), headers=p1["headers"]).json()
        assert current["etat_operationnel"] == "maintenance"

        r = client.post(
            u(p1, f"/machines/maintenances/{maint['id']}/cloture"),
            headers=p1["headers"],
            json={"fin": "2999-01-01T00:00:00Z"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["fin"] is not None and r.json()["indisponibilite_min"] > 0
        current = client.get(u(p1, f"/machines/{m['id']}"), headers=p1["headers"]).json()
        assert current["etat_operationnel"] == "libre"
        # Déjà clôturée.
        r = client.post(u(p1, f"/machines/maintenances/{maint['id']}/cloture"), headers=p1["headers"], json={})
        assert r.status_code == 409

        listed = client.get(u(p1, f"/machines/{m['id']}/maintenances"), headers=p1["headers"]).json()
        assert [x["id"] for x in listed] == [maint["id"]]
        histo = client.get(u(p1, f"/machines/{m['id']}/historique"), headers=p1["headers"]).json()
        assert [e["nouvel_etat"] for e in histo] == ["libre", "maintenance"]
        assert all(e["type"] == "maintenance" and e["maintenance_id"] == maint["id"] for e in histo)
        assert audit(engine, p1, "PRESSING_MAINTENANCE_CREATE") and audit(engine, p1, "PRESSING_MAINTENANCE_CLOSE")

    def test_maintenance_deja_terminee_sans_changer_l_etat(self, client, p1):
        m = make_machine(client, p1)
        r = client.post(
            u(p1, f"/machines/{m['id']}/maintenances"),
            headers=p1["headers"],
            json={
                "type": "entretien", "description": "Détartrage",
                "debut": "2026-10-01T08:00:00Z", "fin": "2026-10-01T09:30:00Z",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["indisponibilite_min"] == 90
        current = client.get(u(p1, f"/machines/{m['id']}"), headers=p1["headers"]).json()
        assert current["etat_operationnel"] == "libre"
        bad = client.post(
            u(p1, f"/machines/{m['id']}/maintenances"),
            headers=p1["headers"],
            json={"type": "panne", "description": "x", "debut": "2026-10-02T08:00:00Z", "fin": "2026-10-01T08:00:00Z"},
        )
        assert bad.status_code == 422

    def test_cloture_refusee_si_cycle_en_cours(self, client, p1):
        m = make_machine(client, p1)
        # Machine en cycle : la maintenance est seulement historisée (pas de changement d'état).
        set_etat(client, p1, m, "en_cycle")
        r = client.post(
            u(p1, f"/machines/{m['id']}/maintenances"),
            headers=p1["headers"],
            json={"type": "entretien", "description": "Contrôle"},
        )
        assert r.status_code == 201
        assert client.get(u(p1, f"/machines/{m['id']}"), headers=p1["headers"]).json()["etat_operationnel"] == "en_cycle"
        r = client.post(u(p1, f"/machines/maintenances/{r.json()['id']}/cloture"), headers=p1["headers"], json={})
        assert r.status_code == 409 and "cycle en cours" in r.json()["detail"]

    def test_desactivation(self, client, engine, p1):
        m = make_machine(client, p1)
        set_etat(client, p1, m, "reservee")
        r = client.delete(u(p1, f"/machines/{m['id']}"), headers=p1["headers"])
        assert r.status_code == 409
        assert client.get(u(p1, f"/machines/{m['id']}"), headers=p1["headers"]).json()["actif"] is True
        set_etat(client, p1, m, "libre")
        assert client.delete(u(p1, f"/machines/{m['id']}"), headers=p1["headers"]).status_code == 204
        assert client.get(u(p1, f"/machines/{m['id']}"), headers=p1["headers"]).json()["actif"] is False
        # Absente du plan, présente avec inclure_inactives.
        ids = [x["id"] for x in client.get(u(p1, "/plan"), headers=p1["headers"]).json()["machines"]]
        assert m["id"] not in ids
        ids = [x["id"] for x in client.get(u(p1, "/plan?inclure_inactives=true"), headers=p1["headers"]).json()["machines"]]
        assert m["id"] in ids
        assert client.get(u(p1, "/machines?actif=false"), headers=p1["headers"]).json()[0]["actif"] is False
        # Plus de changement d'état sur une machine désactivée.
        assert set_etat(client, p1, m, "en_cycle").status_code == 409
        assert audit(engine, p1, "PRESSING_MACHINE_DEACTIVATE")


class TestAccesEtIsolation:
    def test_restaurant_non_pressing_recoit_404(self, client, owner):
        mid = str(uuid.uuid4())
        for method, path in [
            ("get", "/zones"),
            ("post", "/zones"),
            ("get", "/plan"),
            ("get", "/machines"),
            ("post", "/machines"),
            ("get", f"/machines/{mid}"),
            ("get", f"/machines/{mid}/historique"),
            ("post", f"/machines/{mid}/etat"),
        ]:
            r = getattr(client, method)(u(owner, path), headers=owner["headers"], **({"json": {}} if method == "post" else {}))
            assert r.status_code == 404, (method, path, r.text)
            assert r.json()["detail"] == "Cet établissement n'est pas un pressing"

    def test_isolation_entre_deux_pressings(self, client, p1, p2):
        m1 = make_machine(client, p1, nom="Isolée A")
        z1 = make_zone(client, p1, nom="Zone isolée A", x=0, y=0, w=10, h=10)
        # Même nom dans l'autre pressing : autorisé.
        make_machine(client, p2, nom="Isolée A")
        make_zone(client, p2, nom="Zone isolée A", x=0, y=0, w=10, h=10)
        # B ne voit ni ne touche les ressources de A, ni par son propre préfixe, ni par celui de A.
        assert m1["id"] not in [m["id"] for m in client.get(u(p2, "/machines"), headers=p2["headers"]).json()]
        assert client.get(u(p2, f"/machines/{m1['id']}"), headers=p2["headers"]).status_code == 404
        assert set_etat(client, p2, m1, "en_cycle").status_code == 404
        assert client.delete(u(p2, f"/zones/{z1['id']}"), headers=p2["headers"]).status_code == 404
        assert client.get(u(p1, "/machines"), headers=p2["headers"]).status_code in (403, 404)
        assert client.get(u(p1, f"/machines/{m1['id']}"), headers=p2["headers"]).status_code in (403, 404)
        plan_b = client.get(u(p2, "/plan"), headers=p2["headers"]).json()
        assert m1["id"] not in [m["id"] for m in plan_b["machines"]]
        assert z1["id"] not in [z["id"] for z in plan_b["zones"]]

    def test_droits_lecture_et_ecriture(self, client, engine, p1):
        waiter = make_member(client, engine, p1, "waiter")
        cook = make_member(client, engine, p1, "chef")
        m = make_machine(client, p1)
        # Le serveur lit mais n'écrit pas.
        assert client.get(u(p1, "/plan"), headers=waiter["headers"]).status_code == 200
        assert client.get(u(p1, f"/machines/{m['id']}/historique"), headers=waiter["headers"]).status_code == 200
        r = client.post(u(p1, f"/machines/{m['id']}/etat"), headers=waiter["headers"], json={"etat": "en_cycle"})
        assert r.status_code == 403
        r = client.post(u(p1, "/zones"), headers=waiter["headers"], json=ZONE)
        assert r.status_code == 403
        assert client.delete(u(p1, f"/machines/{m['id']}"), headers=waiter["headers"]).status_code == 403
        # Un cuisinier n'a pas la lecture du service en salle.
        assert client.get(u(p1, "/machines"), headers=cook["headers"]).status_code == 403
        # Sans jeton : 401.
        assert client.get(u(p1, "/machines")).status_code in (401, 403)

