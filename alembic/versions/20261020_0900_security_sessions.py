"""Sécurité ASVS : sessions, rotation des jetons de rafraîchissement, limitation de débit.

* ``auth_sessions`` : une session = une famille de jetons de rafraîchissement ;
* ``refresh_tokens.session_id`` / ``used_at`` : rotation avec détection de réutilisation
  (colonnes nullables : les anciens jetons restent valables jusqu'à leur expiration) ;
* ``auth_throttle`` : compteurs de limitation de débit et de verrouillage (partagés entre workers) ;
* ``auth_one_time_use`` : anti-rejeu des codes TOTP.

Tables globales (identité, comme ``users``/``refresh_tokens``) : sans RLS, lues avant tout
contexte de restaurant. Les privilèges du rôle applicatif viennent des
``ALTER DEFAULT PRIVILEGES`` du rôle propriétaire (voir README).

Revision ID: 20261020_0900
Revises: 20261012_0900
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261020_0900"
down_revision = "20261012_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(40), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
    )
    op.create_index("idx_auth_sessions_user", "auth_sessions", ["user_id", "revoked_at"])

    op.add_column(
        "refresh_tokens",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("refresh_tokens", sa.Column("used_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])

    op.create_table(
        "auth_throttle",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_auth_throttle_updated", "auth_throttle", ["updated_at"])

    op.create_table(
        "auth_one_time_use",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_auth_one_time_use_expires", "auth_one_time_use", ["expires_at"])

    # Filet de sécurité si les privilèges par défaut du rôle applicatif n'existent pas.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'marinade_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON auth_sessions, auth_throttle, auth_one_time_use TO marinade_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("idx_auth_one_time_use_expires", table_name="auth_one_time_use")
    op.drop_table("auth_one_time_use")
    op.drop_index("idx_auth_throttle_updated", table_name="auth_throttle")
    op.drop_table("auth_throttle")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "used_at")
    op.drop_column("refresh_tokens", "session_id")
    op.drop_index("idx_auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")
