"""Affectation intelligente, transitions de commande, alertes et utilisation (SANS base).

    pytest tests/test_pressing_affectation.py -v
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import pressing_affectation as aff
from app.services import pressing_commande_statuts as st
from app.services import pressing_tableau_calcul as tc
from app.services.pressing_calcul import PressingRegleError

T0 = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
COTON = {"nom": "Coton 60", "duree_min": 60, "types_linge": ["coton"]}


def machine(nom, kg, etat="libre", categorie="lave_linge", programmes=None, **extra):
    return aff.MachineInfo(
        id=uuid.uuid4(),
        nom=nom,
        categorie=categorie,
        capacite_g=int(kg * 1000),
        etat=etat,
        programmes=tuple(programmes if programmes is not None else [COTON]),
        **extra,
    )


def demande(kg, etape="lavage", types=(), maintenant=T0):
    return aff.Demande(int(kg * 1000), etape, tuple(types), maintenant)


# ----------------------------------------------------------------------- best-fit
class TestBestFit:
    def test_plus_petite_capacite_suffisante(self):
        petite, moyenne, grande = machine("P", 8), machine("M", 12), machine("G", 20)
        reco = aff.recommander([grande, moyenne, petite], demande(7))
        assert reco.faisable and reco.etape == "lavage"
        assert reco.options[0].machines[0].nom == "P"
        assert [o.machines[0].nom for o in reco.options] == ["P", "M", "G"]

    def test_grande_machine_preservee_pour_petite_charge(self):
        petite, grande = machine("P", 8), machine("G", 30)
        reco = aff.recommander([grande, petite], demande(3))
        assert reco.options[0].machines[0].nom == "P"
        option_grande = reco.options[1]
        assert option_grande.machines[0].nom == "G"
        assert any("Grande machine" in a for a in option_grande.avertissements)
        assert option_grande.score > reco.options[0].score

    def test_grande_machine_choisie_si_necessaire(self):
        petite, grande = machine("P", 8), machine("G", 30)
        reco = aff.recommander([petite, grande], demande(20))
        assert [o.machines[0].nom for o in reco.options] == ["G"]
        assert not any("Grande machine" in a for a in reco.options[0].avertissements)

    def test_penalite_proportionnelle_au_sous_remplissage(self):
        petite, grande = machine("P", 8), machine("G", 30)
        peu = aff.recommander([petite, grande], demande(2)).options[1].score
        beaucoup = aff.recommander([petite, grande], demande(8)).options[1].score
        assert peu > beaucoup


# --------------------------------------------------------------------- équilibrage
class TestEquilibrage:
    def test_a_capacite_egale_la_moins_chargee_gagne(self):
        chargee = machine("A", 10, charge_cumulee_kg=9)
        libre = machine("B", 10, charge_cumulee_kg=0)
        reco = aff.recommander([chargee, libre], demande(5))
        assert reco.options[0].machines[0].nom == "B"
        assert reco.options[0].score < reco.options[1].score

    def test_libres_toujours_avant_occupees(self):
        occupee = machine("A", 8, etat="en_cycle", fin_estimee=T0 + timedelta(minutes=5))
        libre_grande = machine("B", 30)
        reco = aff.recommander([occupee, libre_grande], demande(4))
        assert [o.machines[0].nom for o in reco.options] == ["B", "A"]


# ------------------------------------------------------------ machines occupées
class TestOccupees:
    @pytest.mark.parametrize("etat", ["reservee", "en_cycle", "cycle_termine", "attente_dechargement"])
    def test_option_attendre_avec_fin_estimee(self, etat):
        fin = T0 + timedelta(minutes=25)
        reco = aff.recommander([machine("A", 8, etat=etat, fin_estimee=fin)], demande(5))
        m = reco.options[0].machines[0]
        assert reco.faisable
        assert m.debut_prevu == fin and m.attente_min == 25
        assert m.fin_prevue == fin + timedelta(minutes=60)
        assert any("occupée" in a for a in reco.options[0].avertissements)

    def test_fin_dans_le_passe_ou_inconnue(self):
        passe = machine("A", 8, etat="en_cycle", fin_estimee=T0 - timedelta(minutes=10))
        inconnue = machine("B", 8, etat="en_cycle")
        reco = aff.recommander([passe, inconnue], demande(5))
        par_nom = {o.machines[0].nom: o.machines[0] for o in reco.options}
        assert par_nom["A"].attente_min == 0
        assert par_nom["B"].attente_min == aff.ATTENTE_PAR_DEFAUT_MIN


# ---------------------------------------------------------------------- exclusions
class TestExclusions:
    def test_etats_et_activite_exclus(self):
        machines = [
            machine("maint", 8, etat="maintenance"),
            machine("hs", 8, etat="hors_service"),
            machine("off", 8, actif=False),
            machine("ok", 8),
        ]
        reco = aff.recommander(machines, demande(5))
        assert [o.machines[0].nom for o in reco.options] == ["ok"]
        assert {e.nom for e in reco.exclues} == {"maint", "hs", "off"}

    def test_categorie_incompatible_avec_l_etape(self):
        seche = machine("S", 10, categorie="seche_linge")
        lave = machine("L", 10)
        assert aff.recommander([seche, lave], demande(5, "lavage")).options[0].machines[0].nom == "L"
        reco = aff.recommander([seche, lave], demande(5, "sechage"))
        assert reco.options[0].machines[0].nom == "S"

    def test_programme_incompatible_exclut_avec_raison(self):
        delicat = machine("D", 8, programmes=[{"nom": "Laine", "duree_min": 40, "types_linge": ["laine"]}])
        reco = aff.recommander([delicat], demande(5, types=["coton"]))
        assert not reco.faisable
        assert "programme compatible" in reco.exclues[0].raison
        assert reco.action_conseillee == "decision_responsable"

    def test_tout_et_sans_type(self):
        tout = machine("T", 8, programmes=[{"nom": "Tout", "duree_min": 50, "types_linge": ["tout"]}])
        laine = machine("L", 8, programmes=[{"nom": "Laine", "duree_min": 40, "types_linge": ["laine"]}])
        assert aff.recommander([tout, laine], demande(5, types=["drap"])).options[0].machines[0].nom == "T"
        # Commande sans type de linge : tout programme convient, même sans types déclarés.
        vide = machine("V", 8, programmes=[{"nom": "X", "duree_min": 30, "types_linge": []}])
        assert aff.recommander([vide], demande(5)).faisable
        # Types demandés + programme sans types : incompatible.
        assert not aff.recommander([vide], demande(5, types=["coton"])).faisable

    def test_machine_sans_programme(self):
        reco = aff.recommander([machine("N", 8, programmes=[])], demande(5))
        assert not reco.faisable and "Aucun programme" in reco.exclues[0].raison

    def test_programme_le_plus_court_compatible(self):
        m = machine("M", 8, programmes=[
            {"nom": "Long", "duree_min": 120, "types_linge": ["coton"]},
            {"nom": "Rapide", "duree_min": 30, "types_linge": ["coton"]},
            {"nom": "Laine", "duree_min": 10, "types_linge": ["laine"]},
        ])
        option = aff.recommander([m], demande(5, types=["coton"])).options[0]
        assert option.machines[0].programme == "Rapide" and option.machines[0].duree_min == 30


# ------------------------------------------------------------------- semi-automatique
class TestSemiAuto:
    def test_intervention_ajoute_du_temps_et_une_raison(self):
        semi = machine(
            "S", 8, type_fonctionnement="semi_automatique",
            programmes=[{**COTON, "intervention_humaine": True}],
        )
        option = aff.recommander([semi], demande(5, types=["coton"])).options[0]
        m = option.machines[0]
        assert m.intervention_humaine and m.duree_min == 60 + aff.INTERVENTION_MIN
        assert m.fin_prevue - m.debut_prevu == timedelta(minutes=70)
        assert any("intervention requise" in r.lower() for r in option.raisons)

    def test_programme_sans_intervention_prefere_si_plus_court(self):
        m = machine("M", 8, programmes=[
            {"nom": "Manuel", "duree_min": 55, "types_linge": ["coton"], "intervention_humaine": True},
            {"nom": "Auto", "duree_min": 62, "types_linge": ["coton"]},
        ])
        # 55 + 10 = 65 > 62 : le programme automatique est plus court au total.
        assert aff.recommander([m], demande(5, types=["coton"])).options[0].machines[0].programme == "Auto"


# --------------------------------------------------------------------- répartition
class TestRepartition:
    def test_repartition_quand_la_charge_depasse_la_plus_grande(self):
        machines = [machine("A", 10), machine("B", 8), machine("C", 6)]
        reco = aff.recommander(machines, demande(22))
        assert reco.faisable
        rep = reco.options[0]
        assert rep.type == "repartition"
        charges = {m.nom: m.charge_kg for m in rep.machines}
        assert sum(charges.values()) == pytest.approx(22)
        assert charges == {"A": 10, "B": 8, "C": 4}  # la dernière : plus petite capable (C, 6 kg)
        assert any("dépasse la plus grande machine" in r for r in rep.raisons)

    def test_derniere_machine_best_fit(self):
        machines = [machine("A", 10), machine("B", 8), machine("C", 3)]
        rep = aff.recommander(machines, demande(12)).options[0]
        charges = {m.nom: m.charge_kg for m in rep.machines}
        assert charges == {"A": 10, "C": 2}  # le reste (2 kg) va dans la plus petite machine capable

    def test_capacite_cumulee_insuffisante_charges_successives(self):
        # Autrefois « décision du responsable » : désormais la plus grande machine libre est
        # remplie et le reste sera traité aux cycles suivants.
        reco = aff.recommander([machine("A", 10), machine("B", 5)], demande(40))
        assert reco.faisable and reco.action_conseillee is None
        assert [o.type for o in reco.options] == ["partielle"]
        option = reco.options[0]
        assert option.machines[0].nom == "A" and option.machines[0].charge_kg == 10
        assert "Il restera 30 kg à traiter après ce cycle (environ 4 cycles au total)" in option.avertissements

    def test_non_faisable_sans_aucune_machine_compatible(self):
        reco = aff.recommander([machine("S", 10, categorie="seche_linge")], demande(5))
        assert not reco.faisable and reco.options == []
        assert "Aucune machine de lavage utilisable" in reco.motif_si_non_faisable
        assert reco.action_conseillee == "decision_responsable"

    def test_attendre_si_une_machine_en_maintenance_suffirait(self):
        reco = aff.recommander([machine("G", 40, etat="maintenance")], demande(30))
        assert not reco.faisable and reco.action_conseillee == "attendre"
        # Avec une petite machine libre : charges successives, et la grande machine est signalée.
        reco = aff.recommander([machine("A", 10), machine("G", 40, etat="maintenance")], demande(30))
        assert reco.faisable and reco.options[0].type == "partielle"
        assert any("« G » (40 kg), en maintenance" in a for a in reco.options[0].avertissements)

    def test_machines_occupees_comptent_dans_la_repartition(self):
        occupee = machine("A", 10, etat="en_cycle", fin_estimee=T0 + timedelta(minutes=40))
        libre = machine("B", 10)
        reco = aff.recommander([occupee, libre], demande(18))
        rep = [o for o in reco.options if o.type == "repartition"][0]
        assert max(m.attente_min for m in rep.machines) == 40
        # Libres d'abord : la charge partielle sur B (libre) passe avant la répartition qui attend A.
        assert reco.options[0].type == "partielle" and reco.options[0].machines[0].nom == "B"
        assert reco.options.index(rep) > 0

    def test_repartition_sur_libres_si_aucune_grande_libre(self):
        grande_occupee = machine("G", 30, etat="en_cycle", fin_estimee=T0 + timedelta(minutes=90))
        libres = [machine("A", 10), machine("B", 10)]
        reco = aff.recommander([grande_occupee, *libres], demande(18))
        types = [o.type for o in reco.options]
        assert types[0] == "repartition" and "machine_unique" in types
        assert reco.options[0].machines[0].attente_min == 0

    def test_une_machine_une_seule_fois_par_option(self):
        machines = [machine(f"M{i}", 6) for i in range(6)]
        for option in aff.recommander(machines, demande(30)).options:
            ids = [m.machine_id for m in option.machines]
            assert len(ids) == len(set(ids))

    def test_au_plus_trois_options(self):
        machines = [machine(f"M{i}", 8 + i) for i in range(7)]
        assert len(aff.recommander(machines, demande(5)).options) == 3

    def test_options_triees_par_score_libres_d_abord(self):
        machines = [machine("A", 8), machine("B", 12), machine("C", 8, etat="en_cycle", fin_estimee=T0 + timedelta(minutes=1))]
        options = aff.recommander(machines, demande(5)).options
        libres = [o for o in options if not o.attend]
        assert [o.score for o in libres] == sorted(o.score for o in libres)
        assert options.index(libres[-1]) < [i for i, o in enumerate(options) if o.attend][0]


class TestProprieteCapacite:
    def test_capacite_jamais_depassee_sur_200_charges_aleatoires(self):
        rng = random.Random(20261010)
        for _ in range(200):
            machines = [
                machine(
                    f"M{i}",
                    rng.choice([3, 5, 6.5, 8, 10, 12, 16, 25]),
                    etat=rng.choice(["libre", "libre", "en_cycle", "reservee", "maintenance"]),
                    fin_estimee=T0 + timedelta(minutes=rng.randint(0, 120)),
                    charge_cumulee_kg=rng.choice([0, 0, 4, 10]),
                )
                for i in range(rng.randint(1, 7))
            ]
            charge_g = rng.randint(100, 70_000)
            reco = aff.recommander(machines, aff.Demande(charge_g, "lavage", (), T0))
            capacites = {m.id: m.capacite_g for m in machines}
            utilisables = [
                m for m in machines if m.etat not in aff.ETATS_INDISPONIBLES and m.actif
            ]
            assert len(reco.options) <= 3
            assert reco.faisable == bool(utilisables)
            for option in reco.options:
                ids = [m.machine_id for m in option.machines]
                assert len(ids) == len(set(ids))
                total = 0
                for m in option.machines:
                    charge = round(m.charge_kg * 1000)
                    assert 0 < charge <= capacites[m.machine_id], (charge, capacites[m.machine_id])
                    total += charge
                if option.type == "partielle":
                    # Une seule machine, remplie à sa capacité, et il reste de la charge.
                    assert len(option.machines) == 1
                    assert total == capacites[option.machines[0].machine_id] < charge_g
                    assert option.cycles == -(-charge_g // total) >= 2
                    # Vérifiée comme à l'affectation : demandée = capacité, jamais > restante.
                    candidat = aff.Candidat(
                        next(x for x in machines if x.id == option.machines[0].machine_id),
                        option.machines[0].programme, option.machines[0].duree_min, False, T0, True,
                    )
                    aff.verifier_capacites([(candidat, total)], total, charge_g)
                else:
                    assert total == charge_g
            if not reco.faisable:
                assert reco.motif_si_non_faisable and reco.action_conseillee in ("attendre", "decision_responsable")

    def test_verifier_capacites_refuse_un_depassement(self):
        m = machine("A", 5)
        c = aff.Candidat(m, "Coton 60", 60, False, T0, True)
        with pytest.raises(ValueError, match="Capacité dépassée"):
            aff.verifier_capacites([(c, 6000)], 6000)
        with pytest.raises(ValueError, match="entièrement"):
            aff.verifier_capacites([(c, 4000)], 6000)
        aff.verifier_capacites([(c, 5000)], 5000)

    def test_verifier_capacites_charge_demandee_et_restante(self):
        c = aff.Candidat(machine("A", 8), "Coton 60", 60, False, T0, True)
        aff.verifier_capacites([(c, 8000)], 8000, 14_000)  # partielle : 8 kg sur 14 restants
        aff.verifier_capacites([(c, 6000)], 6000, 6000)  # dernier cycle : tout le reste
        with pytest.raises(ValueError, match="charge restante"):
            aff.verifier_capacites([(c, 8000)], 8000, 6000)
        with pytest.raises(ValueError, match="nulle"):
            aff.verifier_capacites([(c, 0)], 0, 6000)

    def test_charge_restante_jamais_negative(self):
        assert aff.charge_restante(14_000, 8000) == 6000
        assert aff.charge_restante(14_000, 14_000) == 0
        assert aff.charge_restante(5000, 8000) == 0
        assert aff.charge_restante(None, 0) == 0


# ------------------------------------------------------------------ charges successives
class TestPartielle:
    def test_14_kg_pour_une_seule_machine_de_8_kg(self):
        reco = aff.recommander([machine("Lave 8", 8)], demande(14))
        assert reco.faisable and reco.motif_si_non_faisable is None
        option = reco.options[0]
        assert option.type == "partielle" and len(reco.options) == 1
        m = option.machines[0]
        assert m.nom == "Lave 8" and m.charge_kg == 8 and m.attente_min == 0
        assert option.avertissements[0] == "Il restera 6 kg à traiter après ce cycle (environ 2 cycles au total)"
        assert option.score == 2 * 60 and option.cycles == 2
        assert option.fin_totale == T0 + timedelta(minutes=120)
        assert option.to_dict()["type"] == "partielle"

    def test_plus_grande_machine_libre_preferee(self):
        reco = aff.recommander([machine("P", 8), machine("G", 10), machine("X", 5)], demande(30))
        partielle = [o for o in reco.options if o.type == "partielle"][0]
        assert partielle.machines[0].nom == "G" and partielle.machines[0].charge_kg == 10
        assert "Il restera 20 kg" in partielle.avertissements[0] and partielle.cycles == 3

    def test_machine_capable_occupee_petite_machine_libre(self):
        grande = machine("G", 20, etat="en_cycle", fin_estimee=T0 + timedelta(minutes=30))
        reco = aff.recommander([grande, machine("P", 8)], demande(14))
        assert [(o.type, o.machines[0].nom) for o in reco.options] == [
            ("partielle", "P"), ("machine_unique", "G")
        ]
        assert reco.options[0].attend is False and reco.options[1].attend is True

    def test_sans_machine_libre_option_attente(self):
        occupee = machine("A", 10, etat="en_cycle", fin_estimee=T0 + timedelta(minutes=40))
        reco = aff.recommander([occupee], demande(25))
        assert reco.faisable and [o.type for o in reco.options] == ["partielle"]
        option = reco.options[0]
        assert option.attend and option.machines[0].attente_min == 40
        assert option.score == 40 + 3 * 60

    def test_pas_de_partielle_si_une_machine_libre_suffit(self):
        reco = aff.recommander([machine("P", 8), machine("G", 20)], demande(14))
        assert "partielle" not in [o.type for o in reco.options]

    def test_pas_de_partielle_si_une_machine_capable_est_seulement_occupee(self):
        grande = machine("G", 20, etat="reservee", fin_estimee=T0 + timedelta(minutes=30))
        reco = aff.recommander([grande], demande(14))
        assert [o.type for o in reco.options] == ["machine_unique"]


# ------------------------------------------------------------------------ heure locale
class TestHeureLocale:
    def test_heure_affichee_a_douala_et_non_en_utc(self):
        # T0 = 08:00 UTC = 09:00 à Douala (UTC+1). La machine se libère à 08:25 UTC.
        occupee = machine("A", 8, etat="en_cycle", fin_estimee=T0 + timedelta(minutes=25))
        option = aff.recommander([occupee], demande(5)).options[0]
        message = [a for a in option.avertissements if "occupée" in a][0]
        assert "libre vers 09:25" in message and "08:25" not in message

    def test_heure_locale_option_partielle_en_attente(self):
        occupee = machine("A", 10, etat="en_cycle", fin_estimee=T0 + timedelta(minutes=40))
        option = aff.recommander([occupee], demande(25)).options[0]
        assert any("libre vers 09:40" in a for a in option.avertissements)

    def test_helper(self):
        from app.services import pressing_temps as temps

        assert temps.heure_locale(datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc)) == "00:30"


# --------------------------------------------------------------- transitions commande
AUTORISEES = [
    ("recue", "en_attente_machine"),
    ("recue", "pret"),
    ("recue", "annulee"),
    ("en_attente_machine", "en_lavage"),
    ("en_attente_machine", "en_sechage"),
    ("en_attente_machine", "annulee"),
    ("en_attente_machine", "recue"),  # affectations libérées (étape lavage, séchage seul)
    ("en_attente_machine", "attente_sechage"),  # affectations de séchage libérées
    ("en_lavage", "attente_sechage"),
    ("en_lavage", "pret"),
    ("attente_sechage", "en_attente_machine"),
    ("attente_sechage", "en_sechage"),
    ("attente_sechage", "annulee"),
    ("en_sechage", "pret"),
    ("pret", "livre"),
]


class TestTransitionsCommande:
    def test_table_complete(self):
        assert set(st.TRANSITIONS) == set(st.STATUTS)
        assert sum(len(v) for v in st.TRANSITIONS.values()) == len(AUTORISEES)

    @pytest.mark.parametrize("actuel, cible", AUTORISEES)
    def test_autorisees(self, actuel, cible):
        st.verifier_transition(actuel, cible)

    def test_toutes_les_autres_sont_interdites(self):
        autorisees = set(AUTORISEES)
        for actuel in st.STATUTS:
            for cible in st.STATUTS:
                if (actuel, cible) in autorisees:
                    continue
                with pytest.raises(st.TransitionCommandeInterdite):
                    st.verifier_transition(actuel, cible)

    @pytest.mark.parametrize("statut", ["en_lavage", "en_sechage"])
    def test_annulation_en_cycle_message_explicite(self, statut):
        with pytest.raises(st.TransitionCommandeInterdite, match="terminez d'abord le cycle"):
            st.verifier_transition(statut, "annulee")

    @pytest.mark.parametrize("statut", ["pret", "livre", "annulee"])
    def test_annulation_impossible_apres_pret(self, statut):
        with pytest.raises(st.TransitionCommandeInterdite):
            st.verifier_transition(statut, "annulee")

    def test_statuts_finaux_sans_sortie(self):
        assert st.transitions_depuis("livre") == frozenset()
        assert st.transitions_depuis("annulee") == frozenset()

    def test_statut_inconnu(self):
        with pytest.raises(PressingRegleError):
            st.verifier_transition("recue", "perdue")

    def test_annulables(self):
        assert st.STATUTS_ANNULABLES == {"recue", "en_attente_machine", "attente_sechage"}

    def test_etape_initiale(self):
        assert st.etape_initiale(True, True) == "lavage"
        assert st.etape_initiale(False, True) == "sechage"
        assert st.etape_initiale(False, False) is None


# ---------------------------------------------------------------------------- alertes
def snap(etat, **extra):
    return tc.MachineSnapshot(uuid.uuid4(), "Machine", etat, **extra)


class TestAlertes:
    def test_retard_seulement_en_cycle(self):
        en_retard = snap("en_cycle", fin_estimee=T0 - timedelta(minutes=5))
        a_l_heure = snap("en_cycle", fin_estimee=T0 + timedelta(minutes=5))
        libre = snap("libre", fin_estimee=T0 - timedelta(minutes=5))
        alertes = tc.calculer_alertes([en_retard, a_l_heure, libre], [], [], T0)
        assert [a["type"] for a in alertes] == ["retard"]
        assert alertes[0]["niveau"] == "avertissement" and alertes[0]["machine_id"] == en_retard.machine_id

    def test_retard_critique_au_dela_de_30_min(self):
        m = snap("en_cycle", fin_estimee=T0 - timedelta(minutes=45))
        assert tc.calculer_alertes([m], [], [], T0)[0]["niveau"] == "critique"

    def test_panne(self):
        panne = tc.PanneOuverte(uuid.uuid4(), "Lave 1", "moteur")
        alertes = tc.calculer_alertes([], [panne], [], T0)
        assert alertes[0]["type"] == "panne" and alertes[0]["niveau"] == "critique"
        assert alertes[0]["machine_id"] == panne.machine_id

    def test_intervention(self):
        m = snap("en_cycle", fin_estimee=T0 + timedelta(minutes=30), intervention_humaine=True, programme="Manuel")
        alertes = tc.calculer_alertes([m], [], [], T0)
        assert [a["type"] for a in alertes] == ["intervention"]
        assert alertes[0]["niveau"] == "info"

    @pytest.mark.parametrize("etat", ["cycle_termine", "attente_dechargement"])
    def test_attente_dechargement_au_dela_de_15_min(self, etat):
        court = snap(etat, fin_cycle_reelle=T0 - timedelta(minutes=15))
        long = snap(etat, fin_cycle_reelle=T0 - timedelta(minutes=16))
        tres_long = snap(etat, fin_cycle_reelle=T0 - timedelta(minutes=90))
        alertes = tc.calculer_alertes([court, long, tres_long], [], [], T0)
        assert [(a["type"], a["niveau"]) for a in alertes] == [
            ("attente_dechargement", "critique"),
            ("attente_dechargement", "avertissement"),
        ]

    def test_dechargement_tardif_apres_2h(self):
        ok = tc.CommandePrete(uuid.uuid4(), "PR-1", T0 - timedelta(hours=2))
        tard = tc.CommandePrete(uuid.uuid4(), "PR-2", T0 - timedelta(hours=2, minutes=1))
        alertes = tc.calculer_alertes([], [], [ok, tard], T0)
        assert [(a["type"], a["commande_id"]) for a in alertes] == [("dechargement_tardif", tard.commande_id)]
        assert "PR-2" in alertes[0]["message"]

    def test_tri_critiques_d_abord(self):
        m = snap("en_cycle", fin_estimee=T0 - timedelta(minutes=5), intervention_humaine=True)
        panne = tc.PanneOuverte(uuid.uuid4(), "X", "y")
        niveaux = [a["niveau"] for a in tc.calculer_alertes([m], [panne], [], T0)]
        assert niveaux == ["critique", "avertissement", "info"]

    def test_aucune_alerte(self):
        assert tc.calculer_alertes([snap("libre"), snap("maintenance")], [], [], T0) == []


def _types_niveaux(alertes):
    return [(a["type"], a["niveau"]) for a in alertes]


class TestNouvellesAlertes:
    def test_reservation_non_demarree_seuils(self):
        def reservee(minutes):
            return tc.MachineSnapshot(
                uuid.uuid4(), "Lave-linge 2", "reservee", commande_numero="PR-20261010-007",
                debut_prevu=T0 - timedelta(minutes=minutes),
            )

        assert tc.calculer_alertes([reservee(15)], [], [], T0) == []
        alertes = tc.calculer_alertes([reservee(20)], [], [], T0)
        assert _types_niveaux(alertes) == [("reservation_non_demarree", "avertissement")]
        # 07:40 UTC = 08:40 à Douala.
        assert alertes[0]["message"] == (
            "Lave-linge 2 réservé pour PR-20261010-007 depuis 20 min sans démarrage "
            "(début prévu à 08:40)"
        )
        assert _types_niveaux(tc.calculer_alertes([reservee(45)], [], [], T0)) == [
            ("reservation_non_demarree", "avertissement")
        ]
        assert _types_niveaux(tc.calculer_alertes([reservee(46)], [], [], T0)) == [
            ("reservation_non_demarree", "critique")
        ]
        # Sans début prévu, ou machine dans un autre état : rien.
        sans = tc.MachineSnapshot(uuid.uuid4(), "X", "reservee")
        libre = tc.MachineSnapshot(uuid.uuid4(), "X", "libre", debut_prevu=T0 - timedelta(hours=2))
        assert tc.calculer_alertes([sans, libre], [], [], T0) == []

    def test_prise_en_charge_seuils(self):
        def recue(minutes):
            return tc.CommandeRecue(uuid.uuid4(), "PR-1", T0 - timedelta(minutes=minutes))

        assert tc.calculer_alertes([], [], [], T0, recues=[recue(30)]) == []
        alertes = tc.calculer_alertes([], [], [], T0, recues=[recue(31)])
        assert _types_niveaux(alertes) == [("prise_en_charge", "avertissement")]
        assert "reçue à 08:29" in alertes[0]["message"] and "31 min" in alertes[0]["message"]
        assert _types_niveaux(tc.calculer_alertes([], [], [], T0, recues=[recue(90)])) == [
            ("prise_en_charge", "avertissement")
        ]
        assert _types_niveaux(tc.calculer_alertes([], [], [], T0, recues=[recue(91)])) == [
            ("prise_en_charge", "critique")
        ]

    def test_charge_restante(self):
        lavage = tc.CommandeAReaffecter(uuid.uuid4(), "PR-20261010-003", "lavage", 6000)
        sechage = tc.CommandeAReaffecter(uuid.uuid4(), "PR-4", "sechage", 2500)
        rien = tc.CommandeAReaffecter(uuid.uuid4(), "PR-5", "lavage", 0)
        alertes = tc.calculer_alertes([], [], [], T0, a_reaffecter=[lavage, sechage, rien])
        assert _types_niveaux(alertes) == [("charge_restante", "avertissement")] * 2
        assert alertes[0]["message"] == "PR-20261010-003 : il reste 6 kg à laver"
        assert alertes[1]["message"] == "PR-4 : il reste 2,5 kg à sécher"
        assert alertes[0]["commande_id"] == lavage.commande_id

    def test_sechage_en_attente_seuils(self):
        def lave(minutes):
            return tc.CommandeAttenteSechage(uuid.uuid4(), "PR-9", T0 - timedelta(minutes=minutes))

        assert tc.calculer_alertes([], [], [], T0, sechages=[lave(20)]) == []
        alertes = tc.calculer_alertes([], [], [], T0, sechages=[lave(25)])
        assert _types_niveaux(alertes) == [("sechage_en_attente", "avertissement")]
        assert "depuis 25 min" in alertes[0]["message"]
        assert "lavage terminé à 08:35" in alertes[0]["message"]  # 07:35 UTC
        assert _types_niveaux(tc.calculer_alertes([], [], [], T0, sechages=[lave(60)])) == [
            ("sechage_en_attente", "avertissement")
        ]
        assert _types_niveaux(tc.calculer_alertes([], [], [], T0, sechages=[lave(61)])) == [
            ("sechage_en_attente", "critique")
        ]

    def test_paiement_apres_cloture(self):
        assert tc.calculer_alertes([], [], [], T0, encaisse_apres_cloture=None) == []
        alertes = tc.calculer_alertes([], [], [], T0, encaisse_apres_cloture=1500)
        assert _types_niveaux(alertes) == [("paiement_apres_cloture", "avertissement")]
        assert alertes[0]["message"] == "Paiements enregistrés après la clôture du jour : 1500 FCFA"
        # Une contre-passation seule après la clôture : le montant net peut être négatif.
        alertes = tc.calculer_alertes([], [], [], T0, encaisse_apres_cloture=-500)
        assert "-500 FCFA" in alertes[0]["message"]

    def test_tri_avec_les_nouvelles_alertes(self):
        reservee = tc.MachineSnapshot(
            uuid.uuid4(), "L", "reservee", debut_prevu=T0 - timedelta(minutes=50)
        )
        alertes = tc.calculer_alertes(
            [reservee], [], [], T0,
            a_reaffecter=[tc.CommandeAReaffecter(uuid.uuid4(), "PR-1", "lavage", 1000)],
        )
        assert [a["niveau"] for a in alertes] == ["critique", "avertissement"]


class TestUtilisation:
    def test_minutes_par_etat(self):
        debut, fin = T0, T0 + timedelta(hours=4)
        evenements = [
            (T0 + timedelta(hours=1), "en_cycle"),
            (T0 + timedelta(hours=2), "cycle_termine"),
            (T0 + timedelta(hours=2, minutes=30), "libre"),
            (T0 + timedelta(hours=3), "maintenance"),
        ]
        par_etat = tc.minutes_par_etat(evenements, "libre", debut, fin)
        assert par_etat == {"libre": 60 + 30, "en_cycle": 60, "cycle_termine": 30, "maintenance": 60}
        occupees, disponibles = tc.utilisation(par_etat)
        assert occupees == 90 and disponibles == 180
        assert tc.taux_pct(occupees, disponibles) == 50.0

    def test_evenements_hors_fenetre_ignores_et_etat_initial(self):
        evenements = [(T0 - timedelta(hours=5), "libre"), (T0 + timedelta(hours=9), "en_cycle")]
        par_etat = tc.minutes_par_etat(evenements, "en_cycle", T0, T0 + timedelta(hours=1))
        assert par_etat == {"en_cycle": 60}

    def test_taux_sans_minutes_disponibles(self):
        assert tc.taux_pct(0, 0) == 0.0
        occupees, disponibles = tc.utilisation({"hors_service": 120})
        assert (occupees, disponibles) == (0, 0)
