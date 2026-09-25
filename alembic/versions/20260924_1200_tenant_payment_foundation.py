"""Tenant isolation, payment ledger and Cameroon operator registry.

Revision ID: 20260924_1200
Revises: 20260916_1200
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260924_1200"
down_revision = "20260916_1200"
branch_labels = None
depends_on = None


def _rls(table: str, predicate: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"FOR ALL USING ({predicate}) WITH CHECK ({predicate})"
    )


def _context_functions() -> None:
    op.execute("""
    CREATE OR REPLACE FUNCTION app_current_user_id() RETURNS uuid
    LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid $$;
    CREATE OR REPLACE FUNCTION app_current_tenant_id() RETURNS uuid
    LANGUAGE sql STABLE AS $$ SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid $$;
    CREATE OR REPLACE FUNCTION app_is_platform_admin() RETURNS boolean
    LANGUAGE sql STABLE AS $$ SELECT COALESCE(current_setting('app.is_platform_admin', true), 'false') = 'true' $$;
    """)


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    for table in ("subscriptions", "daily_balances", "transactions"):
        op.add_column(
            table,
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    op.execute(
        "UPDATE subscriptions s SET restaurant_id=r.id FROM restaurants r WHERE r.user_id=s.user_id AND s.restaurant_id IS NULL"
    )
    op.execute(
        "UPDATE daily_balances b SET restaurant_id=s.restaurant_id FROM subscriptions s WHERE s.id=b.subscription_id AND b.restaurant_id IS NULL"
    )
    op.execute(
        "UPDATE transactions t SET restaurant_id=s.restaurant_id FROM subscriptions s WHERE s.id=t.subscription_id AND t.restaurant_id IS NULL"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM subscriptions WHERE restaurant_id IS NULL) OR EXISTS (SELECT 1 FROM daily_balances WHERE restaurant_id IS NULL) OR EXISTS (SELECT 1 FROM transactions WHERE restaurant_id IS NULL) THEN RAISE EXCEPTION 'Tenant backfill failed'; END IF; END $$"
    )
    for table in ("subscriptions", "daily_balances", "transactions"):
        op.alter_column(table, "restaurant_id", nullable=False)
    op.create_foreign_key(
        "fk_subscription_restaurant",
        "subscriptions",
        "restaurants",
        ["restaurant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_daily_balance_restaurant",
        "daily_balances",
        "restaurants",
        ["restaurant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_transaction_restaurant",
        "transactions",
        "restaurants",
        ["restaurant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute("DROP INDEX IF EXISTS idx_active_subscription_per_user")
    op.execute(
        "ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_pos_transaction_id_key"
    )
    op.execute(
        "ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_idempotency_key_key"
    )
    op.create_index(
        "idx_active_subscription_per_restaurant",
        "subscriptions",
        ["restaurant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "idx_transaction_pos_id_tenant",
        "transactions",
        ["restaurant_id", "pos_transaction_id"],
        unique=True,
    )
    op.create_index(
        "idx_transaction_idempotency_tenant",
        "transactions",
        ["restaurant_id", "idempotency_key"],
        unique=True,
    )
    op.create_table(
        "restaurant_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="staff"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("restaurant_id", "user_id", name="uq_restaurant_member"),
        sa.CheckConstraint(
            "role IN ('owner', 'manager', 'cashier', 'kitchen', 'staff')",
            name="check_restaurant_member_role",
        ),
    )
    op.create_index("idx_restaurant_member_user", "restaurant_members", ["user_id"])
    op.execute(
        "INSERT INTO restaurant_members (id, restaurant_id, user_id, role) SELECT gen_random_uuid(), id, user_id, 'owner' FROM restaurants"
    )
    op.create_table(
        "mobile_operator_prefixes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("country_code", sa.String(4), nullable=False, server_default="+237"),
        sa.Column("operator_code", sa.String(30), nullable=False),
        sa.Column("operator_name", sa.String(100), nullable=False),
        sa.Column("national_prefix", sa.String(4), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "country_code", "national_prefix", name="uq_mobile_operator_prefix"
        ),
        sa.CheckConstraint(
            "national_prefix ~ '^[0-9]{2,4}$'", name="check_mobile_prefix_digits"
        ),
    )
    op.create_index(
        "idx_mobile_operator_prefix_lookup",
        "mobile_operator_prefixes",
        ["country_code", "national_prefix", "is_active"],
    )
    for code, name, prefixes in (
        ("MTN_CM", "MTN Cameroun", ("650", "651", "652", "653", "654", "67")),
        ("ORANGE_CM", "Orange Cameroun", ("655", "656", "657", "658", "659", "69")),
    ):
        for prefix in prefixes:
            op.execute(
                f"INSERT INTO mobile_operator_prefixes (id, operator_code, operator_name, national_prefix) VALUES (gen_random_uuid(), '{code}', '{name}', '{prefix}')"
            )
    op.create_table(
        "payment_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "provider", sa.String(30), nullable=False, server_default="easytransact"
        ),
        sa.Column(
            "service_code", sa.String(50), nullable=False, server_default="DEPOSIT"
        ),
        sa.Column("webhook_url", sa.String(500)),
        sa.Column("success_url", sa.String(500)),
        sa.Column("failure_url", sa.String(500)),
        sa.Column(
            "vendor_reference_prefix",
            sa.String(30),
            nullable=False,
            server_default="MRD",
        ),
        sa.Column("provider_account_ref", sa.String(255)),
        sa.Column(
            "credential_env_key",
            sa.String(255),
            nullable=False,
            server_default="EASYTRANSACT_API_TOKEN",
        ),
        sa.Column(
            "webhook_secret_env_key",
            sa.String(255),
            nullable=False,
            server_default="EASYTRANSACT_WEBHOOK_SECRET",
        ),
        sa.Column("webhook_token_hash", sa.String(64), unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "restaurant_id", "provider", name="uq_restaurant_payment_provider"
        ),
        sa.CheckConstraint("service_code <> ''", name="check_payment_service_code"),
    )
    op.create_table(
        "payment_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commande_id", postgresql.UUID(as_uuid=True)),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "provider", sa.String(30), nullable=False, server_default="easytransact"
        ),
        sa.Column("vendor_reference", sa.String(100), nullable=False),
        sa.Column("provider_transaction_id", sa.String(255)),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("amount_fcfa", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="XAF"),
        sa.Column("status", sa.String(30), nullable=False, server_default="initiated"),
        sa.Column("checkout_url", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_jsonb", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"], ["restaurants.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["commande_id"], ["commandes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vendor_reference", name="uq_payment_vendor_reference"),
        sa.UniqueConstraint(
            "restaurant_id", "idempotency_key", name="uq_payment_tenant_idempotency"
        ),
        sa.CheckConstraint("amount_fcfa > 0", name="check_payment_amount_positive"),
        sa.CheckConstraint(
            "status IN ('initiated', 'pending', 'processing', 'success', 'failed', 'timeout', 'reversed', 'refunded', 'expired', 'manual_review')",
            name="check_payment_status",
        ),
    )
    op.create_index(
        "idx_payment_intent_restaurant_status",
        "payment_intents",
        ["restaurant_id", "status"],
    )
    op.create_index("idx_payment_intent_commande", "payment_intents", ["commande_id"])
    op.add_column(
        "commandes",
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_commande_payment_intent",
        "commandes",
        "payment_intents",
        ["payment_intent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_commande_payment_intent", "commandes", ["payment_intent_id"]
    )
    op.create_check_constraint(
        "check_commande_status",
        "commandes",
        "statut IN ('en_cours', 'servie', 'annulee', 'payee', 'paiement_en_attente', 'paiement_a_verifier')",
    )
    op.create_table(
        "payment_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("provider_status", sa.String(30), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB()),
        sa.Column("signature", sa.String(512)),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"], ["payment_intents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_event_id", name="uq_payment_event_provider_id"),
    )
    op.create_index(
        "idx_payment_event_intent",
        "payment_events",
        ["payment_intent_id", "received_at"],
    )
    op.create_table(
        "payment_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_type", sa.String(30), nullable=False),
        sa.Column("amount_fcfa", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="XAF"),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("reference", sa.String(255)),
        sa.Column("metadata_jsonb", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"], ["payment_intents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"], ["restaurants.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_payment_ledger_idempotency"),
        sa.CheckConstraint(
            "entry_type IN ('authorization', 'capture', 'reversal', 'refund', 'fee', 'manual_adjustment')",
            name="check_payment_ledger_entry_type",
        ),
        sa.CheckConstraint(
            "amount_fcfa <> 0", name="check_payment_ledger_amount_nonzero"
        ),
    )
    op.create_index(
        "idx_payment_ledger_restaurant_created",
        "payment_ledger",
        ["restaurant_id", "created_at"],
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_restaurant_owner ON restaurants (user_id)"
    )
    _context_functions()
    direct = {
        "restaurants": "(app_is_platform_admin() OR id = app_current_tenant_id() OR user_id = app_current_user_id())",
        "restaurant_members": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id() OR user_id = app_current_user_id())",
        "menus": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "menu_categories": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "composants": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "combinaisons": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "stock_composants": "(app_is_platform_admin() OR EXISTS (SELECT 1 FROM composants c WHERE c.id = stock_composants.composant_id AND c.restaurant_id = app_current_tenant_id()))",
        "plats": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "boissons": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "tables": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "commandes": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "subscriptions": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "daily_balances": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "transactions": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "payment_configurations": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "payment_intents": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
        "payment_ledger": "(app_is_platform_admin() OR restaurant_id = app_current_tenant_id())",
    }
    for table, predicate in direct.items():
        _rls(table, predicate)
    child = {
        "combinaison_composants": "EXISTS (SELECT 1 FROM combinaisons c WHERE c.id = combinaison_composants.combinaison_id AND c.restaurant_id = app_current_tenant_id())",
        "stock_mouvements": "EXISTS (SELECT 1 FROM composants c WHERE c.id = stock_mouvements.composant_id AND c.restaurant_id = app_current_tenant_id())",
        "commande_items": "EXISTS (SELECT 1 FROM commandes c WHERE c.id = commande_items.commande_id AND c.restaurant_id = app_current_tenant_id())",
        "payment_events": "EXISTS (SELECT 1 FROM payment_intents p WHERE p.id = payment_events.payment_intent_id AND p.restaurant_id = app_current_tenant_id())",
    }
    for table, predicate in child.items():
        _rls(table, f"(app_is_platform_admin() OR {predicate})")
    _rls(
        "mobile_operator_prefixes",
        "(app_is_platform_admin() OR app_current_user_id() IS NOT NULL)",
    )


def downgrade() -> None:
    for table in (
        "restaurants",
        "restaurant_members",
        "menus",
        "menu_categories",
        "composants",
        "combinaisons",
        "stock_composants",
        "plats",
        "boissons",
        "tables",
        "commandes",
        "subscriptions",
        "daily_balances",
        "transactions",
        "payment_configurations",
        "payment_intents",
        "payment_events",
        "payment_ledger",
        "mobile_operator_prefixes",
    ):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.drop_table("payment_ledger")
    op.drop_table("payment_events")
    op.drop_constraint("uq_commande_payment_intent", "commandes", type_="unique")
    op.drop_constraint("fk_commande_payment_intent", "commandes", type_="foreignkey")
    op.drop_constraint("check_commande_status", "commandes", type_="check")
    op.drop_column("commandes", "payment_intent_id")
    op.drop_table("payment_intents")
    op.drop_table("payment_configurations")
    op.drop_table("mobile_operator_prefixes")
    op.drop_table("restaurant_members")
    op.execute("DROP INDEX IF EXISTS uq_restaurant_owner")
    op.drop_constraint("fk_transaction_restaurant", "transactions", type_="foreignkey")
    op.drop_constraint(
        "fk_daily_balance_restaurant", "daily_balances", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_subscription_restaurant", "subscriptions", type_="foreignkey"
    )
    op.drop_index("idx_transaction_idempotency_tenant", table_name="transactions")
    op.drop_index("idx_transaction_pos_id_tenant", table_name="transactions")
    op.drop_index("idx_active_subscription_per_restaurant", table_name="subscriptions")
    op.drop_column("transactions", "restaurant_id")
    op.drop_column("daily_balances", "restaurant_id")
    op.drop_column("subscriptions", "restaurant_id")
    op.drop_column("users", "is_active")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant_id()")
    op.execute("DROP FUNCTION IF EXISTS app_current_user_id()")
    op.execute("DROP FUNCTION IF EXISTS app_is_platform_admin()")
