"""Activation du compte par code à usage unique (OTP) envoyé par email.

Ajoute à ``users`` l'empreinte du code, son expiration, la date du dernier envoi (délai minimal
entre deux envois) et le compteur d'essais incorrects.

Un compte n'est utilisable qu'une fois son email confirmé (``email_verified_at``). Les comptes
déjà existants pouvaient se connecter sans cette confirmation : pour ne verrouiller personne,
ils sont marqués comme confirmés à leur date de création.

Revision ID: 20261112_0900
Revises: 20261111_0900
"""

import sqlalchemy as sa
from alembic import op

revision = "20261112_0900"
down_revision = "20261111_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("activation_code_hash", sa.String(128), nullable=True))
    op.add_column(
        "users", sa.Column("activation_code_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("activation_code_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("activation_code_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE users SET email_verified_at = COALESCE(created_at, now()) "
        "WHERE email_verified_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("users", "activation_code_attempts")
    op.drop_column("users", "activation_code_sent_at")
    op.drop_column("users", "activation_code_expires_at")
    op.drop_column("users", "activation_code_hash")
