"""Audit automatique du multi-tenant : la RLS est partout, et elle isole vraiment.

Deux niveaux :

1. Structure (catalogue PostgreSQL) : aucune table ne peut être ajoutée sans RLS
   forcée, aucune politique sans WITH CHECK, aucune table de restaurant sans index
   qui commence par ``restaurant_id``, et le rôle applicatif n'ignore pas la RLS.
2. Données : deux restaurants reçoivent des lignes dans CHAQUE table ; sous le contexte
   de l'un, l'autre est invisible en lecture, en modification et en suppression, et
   sans contexte rien n'est visible.

Exige TEST_DATABASE_URL (voir tests/conftest.py).
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from tests.support import ITEMS

# Tables volontairement SANS RLS : identité et référentiels globaux.
NO_RLS = {"users", "refresh_tokens", "subscription_tiers", "alembic_version"}

# Table fille -> (colonne de rattachement, table parente) : pas de restaurant_id propre,
# l'isolement passe par la ligne parente.
CHILDREN = {
    "ros_order_items": ("order_id", "ros_orders"),
    "reservation_guests": ("reservation_id", "reservations"),
    "plat_composants": ("plat_id", "plats"),
    "commande_items": ("commande_id", "commandes"),
    "commande_refunds": ("commande_id", "commandes"),
    "combinaison_composants": ("combinaison_id", "combinaisons"),
    "stock_composants": ("composant_id", "composants"),
    "stock_mouvements": ("composant_id", "composants"),
    "payment_events": ("payment_intent_id", "payment_intents"),
}

# Tables dont les données DOIVENT être vérifiées (jamais « vide donc vacuously vrai »).
MUST_BE_PROVEN = {
    "menus", "menu_categories", "composants", "combinaisons", "plats", "boissons",
    "tables", "commandes", "reservations", "waitlist_entries", "ros_customers",
    "ros_orders", "ros_invoices", "production_tickets", "ros_audit_logs",
    "service_sessions", "ros_payment_transactions", "ros_cash_shifts",
    "ros_order_items", "stock_composants", "stock_mouvements", "plat_composants",
    "commande_items", "combinaison_composants", "reservation_guests",
}


def scalar(engine, sql, *, tenant="", user="", admin=False, **params):
    """Exécute ``sql`` dans une transaction annulée, sous ce contexte RLS."""
    with engine.connect() as conn:
        with conn.begin() as tx:
            conn.execute(
                text(
                    "select set_config('app.current_user_id', :u, true),"
                    " set_config('app.current_tenant_id', :t, true),"
                    " set_config('app.is_platform_admin', :a, true)"
                ),
                {"u": str(user), "t": str(tenant), "a": "true" if admin else "false"},
            )
            result = conn.execute(text(sql), params)
            value = result.scalar() if result.returns_rows else result.rowcount
            tx.rollback()
    return value


def rowcount(engine, sql, **context):
    with engine.connect() as conn:
        with conn.begin() as tx:
            conn.execute(
                text(
                    "select set_config('app.current_user_id', :u, true),"
                    " set_config('app.current_tenant_id', :t, true),"
                    " set_config('app.is_platform_admin', 'false', true)"
                ),
                {"u": str(context.get("user", "")), "t": str(context.get("tenant", ""))},
            )
            count = conn.execute(text(sql), context.get("params", {})).rowcount
            tx.rollback()
    return count


# --------------------------------------------------------------------------- #
# 1) Structure
# --------------------------------------------------------------------------- #
class TestRlsStructure:
    def tables(self, engine):
        with engine.connect() as conn:
            return conn.execute(
                text(
                    "select c.relname, c.relrowsecurity, c.relforcerowsecurity, pg_get_userbyid(c.relowner) as owner"
                    " from pg_class c where c.relkind = 'r' and c.relnamespace = 'public'::regnamespace"
                )
            ).all()

    def test_every_table_has_forced_rls_except_the_declared_global_ones(self, engine):
        unprotected = sorted(
            t.relname
            for t in self.tables(engine)
            if t.relname not in NO_RLS and not (t.relrowsecurity and t.relforcerowsecurity)
        )
        assert not unprotected, (
            f"tables sans RLS forcée : {unprotected}. Ajoutez une politique de restaurant "
            "(migration) ou, si la table est réellement globale, déclarez-la dans NO_RLS."
        )

    def test_the_global_tables_list_has_no_stale_entry(self, engine):
        existing = {t.relname for t in self.tables(engine)}
        assert NO_RLS <= existing

    def test_every_policy_checks_writes_as_well_as_reads(self, engine):
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "select c.relname, p.polname, p.polqual is null as no_using, p.polwithcheck is null as no_check"
                    " from pg_policy p join pg_class c on c.oid = p.polrelid"
                )
            ).all()
        assert rows, "aucune politique trouvée"
        weak = [(r.relname, r.polname) for r in rows if r.no_using or r.no_check]
        assert not weak, f"politiques sans USING ou sans WITH CHECK (écriture croisée possible) : {weak}"

    def test_every_rls_table_has_a_policy(self, engine):
        with engine.connect() as conn:
            bare = conn.execute(
                text(
                    "select c.relname from pg_class c where c.relkind = 'r' and c.relrowsecurity"
                    " and c.relnamespace = 'public'::regnamespace"
                    " and not exists (select 1 from pg_policy p where p.polrelid = c.oid)"
                )
            ).scalars().all()
        assert not bare, f"RLS activée sans aucune politique (table inaccessible) : {bare}"

    def test_context_functions_are_stable_and_not_security_definer(self, engine):
        with engine.connect() as conn:
            rows = conn.execute(
                text("select proname, provolatile, prosecdef from pg_proc where proname like 'app\\_%'")
            ).all()
        names = {r.proname for r in rows}
        assert {"app_current_user_id", "app_current_tenant_id", "app_is_platform_admin"} <= names
        for r in rows:
            assert r.provolatile == "s", f"{r.proname} doit être STABLE (planifiable et constante par requête)"
            assert not r.prosecdef, f"{r.proname} ne doit pas être SECURITY DEFINER"

    def test_every_restaurant_table_has_an_index_starting_with_restaurant_id(self, engine):
        with engine.connect() as conn:
            missing = conn.execute(
                text(
                    "select c.relname from pg_class c"
                    " join pg_attribute a on a.attrelid = c.oid and a.attname = 'restaurant_id' and not a.attisdropped"
                    " where c.relkind = 'r' and c.relnamespace = 'public'::regnamespace"
                    " and not exists (select 1 from pg_index i where i.indrelid = c.oid and i.indkey[0] = a.attnum)"
                )
            ).scalars().all()
        assert not missing, f"tables de restaurant sans index sur restaurant_id : {missing}"

    def test_child_tables_are_indexed_on_their_parent_key(self, engine):
        with engine.connect() as conn:
            for child, (column, _parent) in CHILDREN.items():
                indexed = conn.execute(
                    text(
                        "select 1 from pg_index i join pg_class c on c.oid = i.indrelid"
                        " join pg_attribute a on a.attrelid = c.oid and a.attnum = i.indkey[0]"
                        " where c.relname = :t and a.attname = :col"
                    ),
                    {"t": child, "col": column},
                ).first()
                assert indexed, f"{child}.{column} n'est pas indexé : la politique de RLS filtre dessus"

    def test_the_application_role_cannot_bypass_rls(self, engine):
        with engine.connect() as conn:
            role = conn.execute(
                text("select rolsuper, rolbypassrls, current_user from pg_roles where rolname = current_user")
            ).one()
            owned = conn.execute(
                text(
                    "select count(*) from pg_class where relkind = 'r' and relnamespace = 'public'::regnamespace"
                    " and pg_get_userbyid(relowner) = current_user"
                )
            ).scalar()
        assert not role.rolsuper and not role.rolbypassrls
        assert owned == 0, "le rôle applicatif ne doit posséder aucune table (le propriétaire contourne la RLS sans FORCE)"


# --------------------------------------------------------------------------- #
# 2) Données : deux restaurants, chaque table
# --------------------------------------------------------------------------- #
def seed(client, who):
    """Une ligne (au moins) dans chaque table métier du restaurant."""
    h, rid = who["headers"], who["rid"]
    tag = uuid.uuid4().hex[:6]
    riz = client.post(f"/v1/restaurants/{rid}/composants", headers=h, json={"nom": f"riz{tag}", "type": "base"}).json()["id"]
    client.post(f"/v1/restaurants/composants/{riz}/stock/mouvements", headers=h, json={"type": "entree", "quantite": 50})
    menu = client.post(f"/v1/restaurants/{rid}/menus", headers=h, json={"name": f"m{tag}"}).json()["id"]
    client.post(f"/v1/restaurants/menus/{menu}/categories", headers=h, json={"name": "Plats", "ordre": 1})
    plat = client.post(f"/v1/restaurants/{rid}/plats", headers=h, json={"nom": f"p{tag}", "prix": 1000, "composant_ids": [riz]}).json()["id"]
    client.post(f"/v1/restaurants/{rid}/combinaisons", headers=h, json={"nom": f"k{tag}", "prix": 900, "composant_ids": [riz]})
    client.post(f"/v1/restaurants/{rid}/boissons", headers=h, json={"nom": f"b{tag}", "prix": 500})
    client.post(f"/v1/restaurants/{rid}/tables", headers=h, json={"numero": f"T{tag}", "capacite": 2})
    commande = client.post(f"/v1/restaurants/{rid}/commandes", headers=h, json={}).json()["id"]
    client.post(f"/v1/restaurants/commandes/{commande}/items", headers=h, json={"plat_id": plat, "quantite": 1})
    client.post(f"/v1/ros/restaurants/{rid}/customers", headers=h, json={"customer_type": "GUEST", "name": "Client"})
    session = client.post(f"/v1/ros/restaurants/{rid}/sessions", headers=h, json={"table_context": "T"}).json()["id"]
    order = client.post(
        f"/v1/ros/restaurants/{rid}/orders",
        headers=h,
        json={"session_id": session, "fulfillment_type": "DINE_IN", "items": [{"product_id": plat, "quantity": 1}]},
    ).json()
    client.post(
        f"/v1/ros/restaurants/{rid}/payments",
        headers=h,
        json={"invoice_id": order["invoice_id"], "payment_method": "CASH", "amount": 100},
    )
    client.post(f"/v1/ros/restaurants/{rid}/shifts/open", headers=h, json={"opening_balance": 100})
    client.post(
        f"/v1/reservations/restaurants/{rid}/reservations",
        headers=h,
        json={
            "customer_name": "C",
            "party_size": 2,
            "reservation_date": datetime.now(timezone.utc).isoformat(),
            "invites": [{"name": "i"}],
        },
    )
    client.post(f"/v1/reservations/restaurants/{rid}/waitlist", headers=h, json={"customer_name": "W", "party_size": 2})


@pytest.fixture(scope="module")
def two_seeded_restaurants(client, owner, stranger):
    seed(client, owner)
    seed(client, stranger)
    return owner, stranger


def admin_count(engine, sql, **params):
    return scalar(engine, sql, admin=True, **params)


class TestTenantsAreIsolatedInEveryTable:
    def restaurant_tables(self, engine):
        with engine.connect() as conn:
            return conn.execute(
                text(
                    "select c.relname from pg_class c"
                    " join pg_attribute a on a.attrelid = c.oid and a.attname = 'restaurant_id' and not a.attisdropped"
                    " where c.relkind = 'r' and c.relnamespace = 'public'::regnamespace order by 1"
                )
            ).scalars().all()

    def test_a_restaurant_never_sees_modifies_or_deletes_another_ones_rows(self, engine, two_seeded_restaurants):
        a, b = two_seeded_restaurants
        proven = set()
        for table in self.restaurant_tables(engine):
            rows_a = admin_count(engine, f"select count(*) from {table} where restaurant_id = :r", r=a["rid"])
            rows_b = admin_count(engine, f"select count(*) from {table} where restaurant_id = :r", r=b["rid"])
            if not (rows_a and rows_b):
                continue
            proven.add(table)

            seen = scalar(engine, f"select count(*) from {table}", tenant=a["rid"], user=a["id"])
            assert seen == rows_a, f"{table}: A voit {seen} lignes au lieu de ses {rows_a}"
            leaked = scalar(
                engine, f"select count(*) from {table} where restaurant_id = :b", tenant=a["rid"], user=a["id"], b=b["rid"]
            )
            assert leaked == 0, f"{table}: A lit {leaked} lignes de B"
            assert rowcount(
                engine, f"update {table} set restaurant_id = restaurant_id where restaurant_id = :b",
                tenant=a["rid"], user=a["id"], params={"b": b["rid"]},
            ) == 0, f"{table}: A peut modifier des lignes de B"
            assert rowcount(
                engine, f"delete from {table} where restaurant_id = :b",
                tenant=a["rid"], user=a["id"], params={"b": b["rid"]},
            ) == 0, f"{table}: A peut supprimer des lignes de B"
            assert scalar(engine, f"select count(*) from {table}") == 0, f"{table}: lisible sans aucun contexte"

        unproven = (MUST_BE_PROVEN & set(self.restaurant_tables(engine))) - proven
        assert not unproven, f"tables non vérifiées faute de données dans les deux restaurants : {sorted(unproven)}"

    def test_child_tables_follow_their_parent(self, engine, two_seeded_restaurants):
        a, b = two_seeded_restaurants
        proven = set()
        for child, (column, parent) in CHILDREN.items():
            ids_b = [
                row[0]
                for row in self._admin_rows(
                    engine, f"select c.{column} from {child} c join {parent} p on p.id = c.{column} where p.restaurant_id = :r",
                    r=b["rid"],
                )
            ]
            if not ids_b:
                continue
            proven.add(child)
            leaked = scalar(
                engine, f"select count(*) from {child} where {column} = any(cast(:ids as uuid[]))",
                tenant=a["rid"], user=a["id"], ids=[str(i) for i in ids_b],
            )
            assert leaked == 0, f"{child}: A lit des lignes rattachées à B"
            assert rowcount(
                engine, f"delete from {child} where {column} = any(cast(:ids as uuid[]))",
                tenant=a["rid"], user=a["id"], params={"ids": [str(i) for i in ids_b]},
            ) == 0, f"{child}: A peut supprimer des lignes de B"
        assert {"ros_order_items", "stock_composants", "plat_composants", "commande_items"} <= proven

    def _admin_rows(self, engine, sql, **params):
        with engine.connect() as conn:
            with conn.begin() as tx:
                conn.execute(text("select set_config('app.is_platform_admin', 'true', true)"))
                rows = conn.execute(text(sql), params).all()
                tx.rollback()
        return rows

    def test_the_restaurants_table_itself_is_isolated(self, engine, two_seeded_restaurants):
        a, b = two_seeded_restaurants
        assert scalar(engine, "select count(*) from restaurants where id = :b", tenant=a["rid"], user=a["id"], b=b["rid"]) == 0
        assert scalar(engine, "select count(*) from restaurants where id = :a", tenant=a["rid"], user=a["id"], a=a["rid"]) == 1
        assert scalar(engine, "select count(*) from restaurants") == 0

    def test_a_row_cannot_be_written_into_another_restaurant(self, engine, two_seeded_restaurants):
        a, b = two_seeded_restaurants
        for statement, params in (
            ("insert into ros_customers (id, restaurant_id, customer_type, loyalty_points) values (gen_random_uuid(), :b, 'GUEST', 0)", {"b": b["rid"]}),
            ("insert into tables (id, restaurant_id, numero, capacite, statut) values (gen_random_uuid(), :b, 'X', 2, 'libre')", {"b": b["rid"]}),
            ("insert into plats (id, restaurant_id, nom, prix, devise) values (gen_random_uuid(), :b, 'X', 10, 'XAF')", {"b": b["rid"]}),
        ):
            with pytest.raises(Exception) as refused:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "select set_config('app.current_user_id', :u, true), set_config('app.current_tenant_id', :t, true),"
                            " set_config('app.is_platform_admin', 'false', true)"
                        ),
                        {"u": a["id"], "t": a["rid"]},
                    )
                    conn.execute(text(statement), params)
            assert "row-level security" in str(refused.value), statement

    def test_a_platform_admin_sees_every_restaurant(self, engine, two_seeded_restaurants):
        a, b = two_seeded_restaurants
        assert admin_count(engine, "select count(*) from restaurants where id in (:a, :b)", a=a["rid"], b=b["rid"]) == 2
        assert admin_count(engine, "select count(distinct restaurant_id) from plats where restaurant_id in (:a, :b)", a=a["rid"], b=b["rid"]) == 2
