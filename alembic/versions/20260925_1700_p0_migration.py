"""P0 Features: Extended Roles, Auth Verification, 2FA, BOM PlatComposant, Refunds, Reservations, Soft Delete, Waitlist

Revision ID: 20260925_1700
Revises: 20260925_1600
Create Date: 2026-09-25 17:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260925_1700"
down_revision = "20260925_1600"
branch_labels = None
depends_on = None


def upgrade():
    # ============================================================
    # 1. USER TABLE - Extended roles + verification + 2FA + soft delete
    # ============================================================
    op.drop_constraint("check_role_valid", "users", type_="check")

    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_token_hash", sa.String(length=256), nullable=True
        ),
    )
    op.add_column(
        "users",
        sa.Column("phone_verification_code_hash", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "verification_token_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "users",
        sa.Column("password_reset_token_hash", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "password_reset_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "users",
        sa.Column("two_factor_secret_hash", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "two_factor_recovery_codes_jsonb",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column("two_factor_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=20),
        type_=sa.String(length=30),
        existing_nullable=False,
    )

    op.create_check_constraint(
        "check_role_valid",
        "users",
        "role IN ('admin', 'pos', 'restaurant', 'waiter', 'cashier', 'chef', 'manager', 'delivery')",
    )
    op.create_check_constraint(
        "check_user_deleted_consistency",
        "users",
        "(is_deleted = false AND deleted_at IS NULL) OR (is_deleted = true AND deleted_at IS NOT NULL)",
    )

    # ============================================================
    # 2. RESTAURANT_MEMBERS - Extended roles + staff_role + permissions
    # ============================================================
    op.drop_constraint(
        "check_restaurant_member_role", "restaurant_members", type_="check"
    )

    op.add_column(
        "restaurant_members",
        sa.Column("staff_role", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "restaurant_members",
        sa.Column(
            "permissions_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )

    op.create_check_constraint(
        "check_restaurant_member_role",
        "restaurant_members",
        "role IN ('owner', 'manager', 'cashier', 'kitchen', 'staff', 'waiter', 'chef', 'sous_chef', 'delivery', 'bartender', 'host')",
    )
    op.create_check_constraint(
        "check_restaurant_member_staff_role",
        "restaurant_members",
        "staff_role IS NULL OR staff_role IN ('waiter', 'cashier', 'chef', 'sous_chef', 'manager', 'delivery', 'bartender', 'host')",
    )
    op.create_index(
        "idx_restaurant_member_staff_role",
        "restaurant_members",
        ["restaurant_id", "staff_role"],
    )

    # ============================================================
    # 3. SOFT DELETE COLUMNS - menus, composants, plats, boissons, tables
    # ============================================================
    op.add_column(
        "menus", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("idx_menu_deleted", "menus", ["deleted_at"])

    op.add_column(
        "composants", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("idx_composant_deleted", "composants", ["deleted_at"])

    op.add_column(
        "plats", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("idx_plat_deleted", "plats", ["deleted_at"])

    op.add_column(
        "boissons", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("idx_boisson_deleted", "boissons", ["deleted_at"])

    op.add_column(
        "tables", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("idx_table_deleted", "tables", ["deleted_at"])

    # Rename duplicate check_prix_positive to specific name to avoid collision
    op.drop_constraint("check_prix_positive", "boissons", type_="check")
    op.create_check_constraint("check_boisson_prix_positive", "boissons", "prix > 0")

    # ============================================================
    # 4. PLAT_COMPOSANTS - BOM (Bill of Materials) for plats
    # ============================================================
    op.create_table(
        "plat_composants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plat_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plats.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "composant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("composants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "quantite",
            sa.Numeric(precision=12, scale=3),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "unite", sa.String(length=20), nullable=False, server_default="portion"
        ),
        sa.Column("ordre", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_plat_composant_plat", "plat_composants", ["plat_id"])
    op.create_index("idx_plat_composant_composant", "plat_composants", ["composant_id"])
    op.create_index("idx_plat_composant_ordre", "plat_composants", ["plat_id", "ordre"])
    op.create_unique_constraint(
        "uq_plat_composant", "plat_composants", ["plat_id", "composant_id"]
    )
    op.create_check_constraint(
        "check_plat_composant_quantite_positive", "plat_composants", "quantite > 0"
    )

    # ============================================================
    # 5. COMMANDES - Refund fields + soft delete
    # ============================================================
    op.add_column(
        "commandes",
        sa.Column(
            "refund_status", sa.String(length=20), nullable=False, server_default="none"
        ),
    )
    op.add_column(
        "commandes",
        sa.Column(
            "refunded_amount",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "commandes", sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("commandes", sa.Column("refund_reason", sa.Text(), nullable=True))
    op.add_column(
        "commandes",
        sa.Column(
            "refunded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "commandes",
        sa.Column(
            "refund_idempotency_key",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            unique=True,
        ),
    )
    op.add_column(
        "commandes", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_index("idx_commande_refund_status", "commandes", ["refund_status"])
    op.create_index(
        "idx_commande_refund_idempotency",
        "commandes",
        ["refund_idempotency_key"],
        unique=True,
    )
    op.create_index("idx_commande_deleted", "commandes", ["deleted_at"])

    op.create_check_constraint(
        "check_refunded_amount_positive", "commandes", "refunded_amount >= 0"
    )
    op.create_check_constraint(
        "check_refunded_amount_le_total", "commandes", "refunded_amount <= total"
    )
    op.create_check_constraint(
        "check_commande_refund_status",
        "commandes",
        "refund_status IN ('none', 'requested', 'approved', 'rejected', 'partial', 'completed', 'failed')",
    )

    # ============================================================
    # 6. COMMANDE_ITEMS - Refunded quantity per item
    # ============================================================
    op.add_column(
        "commande_items",
        sa.Column(
            "refunded_quantity", sa.Integer(), nullable=False, server_default="0"
        ),
    )

    # Rename total constraint to specific to avoid collision
    op.drop_constraint("check_total_positive", "commande_items", type_="check")
    op.create_check_constraint(
        "check_item_total_positive", "commande_items", "total >= 0"
    )

    op.create_check_constraint(
        "check_item_refunded_quantity_valid",
        "commande_items",
        "refunded_quantity >= 0 AND refunded_quantity <= quantite",
    )

    # ============================================================
    # 7. COMMANDE_REFUNDS - Full refund audit table
    # ============================================================
    op.create_table(
        "commande_refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "commande_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("commandes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="requested"
        ),
        sa.Column(
            "initiated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "processed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "notes_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_refund_commande", "commande_refunds", ["commande_id"])
    op.create_index("idx_refund_status", "commande_refunds", ["status"])
    op.create_index("idx_refund_created", "commande_refunds", ["created_at"])
    op.create_check_constraint(
        "check_refund_amount_positive", "commande_refunds", "amount > 0"
    )
    op.create_check_constraint(
        "check_refund_status_valid",
        "commande_refunds",
        "status IN ('requested', 'approved', 'rejected', 'partial', 'completed', 'failed')",
    )

    # ============================================================
    # 8. RESERVATIONS - Table booking
    # ============================================================
    op.create_table(
        "reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ros_customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "table_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tables.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("service_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("customer_phone", sa.String(length=50), nullable=True),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="pending"
        ),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("reservation_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "duration_minutes", sa.Integer(), nullable=False, server_default="90"
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="POS"),
        sa.Column(
            "reminder_sent", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("arrival_notes", sa.String(length=255), nullable=True),
        sa.Column(
            "preferences_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancelled_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_reservation_restaurant", "reservations", ["restaurant_id"])
    op.create_index("idx_reservation_table", "reservations", ["table_id"])
    op.create_index("idx_reservation_status", "reservations", ["status"])
    op.create_index(
        "idx_reservation_date", "reservations", ["restaurant_id", "reservation_date"]
    )
    op.create_index(
        "idx_reservation_customer", "reservations", ["customer_phone", "customer_email"]
    )
    op.create_check_constraint(
        "check_reservation_party_size_positive", "reservations", "party_size > 0"
    )
    op.create_check_constraint(
        "check_reservation_duration_positive", "reservations", "duration_minutes > 0"
    )
    op.create_check_constraint(
        "check_reservation_status_valid",
        "reservations",
        "status IN ('pending', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show')",
    )

    # ============================================================
    # 9. RESERVATION_GUESTS - Guest details within a reservation
    # ============================================================
    op.create_table(
        "reservation_guests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reservation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reservations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("age_category", sa.String(length=20), nullable=True),
        sa.Column(
            "is_vegetarian", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("allergenes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index(
        "idx_reservation_guest_reservation", "reservation_guests", ["reservation_id"]
    )

    # ============================================================
    # 10. WAITLIST_ENTRIES - Queue when tables are full
    # ============================================================
    op.create_table(
        "waitlist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("customer_phone", sa.String(length=50), nullable=True),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column(
            "requested_table_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tables.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assigned_table_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tables.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("estimated_wait_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="WAITING"
        ),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="POS"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "preferences_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("seated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("idx_waitlist_restaurant", "waitlist_entries", ["restaurant_id"])
    op.create_index(
        "idx_waitlist_status_position",
        "waitlist_entries",
        ["restaurant_id", "status", "position"],
    )
    op.create_index("idx_waitlist_customer", "waitlist_entries", ["customer_phone"])
    op.create_check_constraint(
        "check_waitlist_party_size_positive", "waitlist_entries", "party_size > 0"
    )
    op.create_check_constraint(
        "check_waitlist_position_positive", "waitlist_entries", "position > 0"
    )
    op.create_check_constraint(
        "check_waitlist_status_valid",
        "waitlist_entries",
        "status IN ('WAITING', 'SEATED', 'EXPIRED', 'REMOVED', 'CANCELLED')",
    )


def downgrade():
    # Reverse order: drop tables first, then columns/constraints

    # 10. WAITLIST
    op.drop_index("idx_waitlist_customer", table_name="waitlist_entries")
    op.drop_index("idx_waitlist_status_position", table_name="waitlist_entries")
    op.drop_index("idx_waitlist_restaurant", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")

    # 9. RESERVATION_GUESTS
    op.drop_index("idx_reservation_guest_reservation", table_name="reservation_guests")
    op.drop_table("reservation_guests")

    # 8. RESERVATIONS
    op.drop_constraint("check_reservation_status_valid", "reservations", type_="check")
    op.drop_constraint(
        "check_reservation_duration_positive", "reservations", type_="check"
    )
    op.drop_constraint(
        "check_reservation_party_size_positive", "reservations", type_="check"
    )
    op.drop_index("idx_reservation_customer", table_name="reservations")
    op.drop_index("idx_reservation_date", table_name="reservations")
    op.drop_index("idx_reservation_status", table_name="reservations")
    op.drop_index("idx_reservation_table", table_name="reservations")
    op.drop_index("idx_reservation_restaurant", table_name="reservations")
    op.drop_table("reservations")

    # 7. COMMANDE_REFUNDS
    op.drop_constraint("check_refund_status_valid", "commande_refunds", type_="check")
    op.drop_constraint(
        "check_refund_amount_positive", "commande_refunds", type_="check"
    )
    op.drop_index("idx_refund_created", table_name="commande_refunds")
    op.drop_index("idx_refund_status", table_name="commande_refunds")
    op.drop_index("idx_refund_commande", table_name="commande_refunds")
    op.drop_table("commande_refunds")

    # 6. COMMANDE_ITEMS - Refunded quantity
    op.drop_constraint(
        "check_item_refunded_quantity_valid", "commande_items", type_="check"
    )
    op.drop_constraint("check_item_total_positive", "commande_items", type_="check")
    # Restore old constraint name
    op.create_check_constraint("check_total_positive", "commande_items", "total >= 0")
    op.drop_column("commande_items", "refunded_quantity")

    # 5. COMMANDES - Refund fields
    op.drop_constraint("check_commande_refund_status", "commandes", type_="check")
    op.drop_constraint("check_refunded_amount_le_total", "commandes", type_="check")
    op.drop_constraint("check_refunded_amount_positive", "commandes", type_="check")
    op.drop_index("idx_commande_deleted", table_name="commandes")
    op.drop_index("idx_commande_refund_idempotency", table_name="commandes")
    op.drop_index("idx_commande_refund_status", table_name="commandes")
    op.drop_column("commandes", "deleted_at")
    op.drop_column("commandes", "refund_idempotency_key")
    op.drop_constraint("commandes_refunded_by_fkey", "commandes", type_="foreignkey")
    op.drop_column("commandes", "refunded_by")
    op.drop_column("commandes", "refund_reason")
    op.drop_column("commandes", "refunded_at")
    op.drop_column("commandes", "refunded_amount")
    op.drop_column("commandes", "refund_status")

    # 4. PLAT_COMPOSANTS
    op.drop_constraint(
        "check_plat_composant_quantite_positive", "plat_composants", type_="check"
    )
    op.drop_constraint("uq_plat_composant", "plat_composants", type_="unique")
    op.drop_index("idx_plat_composant_ordre", table_name="plat_composants")
    op.drop_index("idx_plat_composant_composant", table_name="plat_composants")
    op.drop_index("idx_plat_composant_plat", table_name="plat_composants")
    op.drop_table("plat_composants")

    # 3. SOFT DELETE COLUMNS
    op.drop_index("idx_table_deleted", table_name="tables")
    op.drop_column("tables", "deleted_at")

    op.drop_constraint("check_boisson_prix_positive", "boissons", type_="check")
    # Restore old constraint name
    op.create_check_constraint("check_prix_positive", "boissons", "prix > 0")
    op.drop_index("idx_boisson_deleted", table_name="boissons")
    op.drop_column("boissons", "deleted_at")

    op.drop_index("idx_plat_deleted", table_name="plats")
    op.drop_column("plats", "deleted_at")

    op.drop_index("idx_composant_deleted", table_name="composants")
    op.drop_column("composants", "deleted_at")

    op.drop_index("idx_menu_deleted", table_name="menus")
    op.drop_column("menus", "deleted_at")

    # 2. RESTAURANT_MEMBERS
    op.drop_index("idx_restaurant_member_staff_role", table_name="restaurant_members")
    op.drop_constraint(
        "check_restaurant_member_staff_role", "restaurant_members", type_="check"
    )
    op.drop_constraint(
        "check_restaurant_member_role", "restaurant_members", type_="check"
    )
    op.drop_column("restaurant_members", "permissions_jsonb")
    op.drop_column("restaurant_members", "staff_role")
    op.create_check_constraint(
        "check_restaurant_member_role",
        "restaurant_members",
        "role IN ('owner', 'manager', 'cashier', 'kitchen', 'staff')",
    )

    # 1. USERS
    op.drop_constraint("check_user_deleted_consistency", "users", type_="check")
    op.drop_constraint("check_role_valid", "users", type_="check")
    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(length=30),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "is_deleted")
    op.drop_column("users", "two_factor_confirmed_at")
    op.drop_column("users", "two_factor_recovery_codes_jsonb")
    op.drop_column("users", "two_factor_secret_hash")
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "password_reset_token_hash")
    op.drop_column("users", "verification_token_expires_at")
    op.drop_column("users", "phone_verification_code_hash")
    op.drop_column("users", "email_verification_token_hash")
    op.drop_column("users", "phone_verified_at")
    op.drop_column("users", "email_verified_at")
    op.create_check_constraint(
        "check_role_valid", "users", "role IN ('admin', 'pos', 'restaurant')"
    )
