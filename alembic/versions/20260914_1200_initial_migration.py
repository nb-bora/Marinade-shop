"""Initial migration with users, subscriptions, transactions

Revision ID: 001
Revises: 
Create Date: 2024-09-14 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260914_1200'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('phone', sa.String(20), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('phone'),
        sa.CheckConstraint("role IN ('admin', 'pos')", name='check_role_valid')
    )

    # Create subscription_tiers table
    op.create_table(
        'subscription_tiers',
        sa.Column('id', sa.Integer, autoincrement=True, primary_key=True),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('daily_limit_fcfa', sa.Integer, nullable=False),
        sa.Column('monthly_price_fcfa', sa.Integer, nullable=False),
        sa.Column('annual_price_fcfa', sa.Integer, nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.UniqueConstraint('name')
    )

    # Create subscriptions table
    op.create_table(
        'subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tier_id', sa.Integer, nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['tier_id'], ['subscription_tiers.id']),
        sa.CheckConstraint('end_date IS NULL OR end_date >= start_date', name='check_end_date_after_start'),
        sa.Index('idx_active_subscription_per_user', 'user_id', unique=True, postgresql_where=sa.text("status = 'active'"))
    )

    # Create daily_balances table
    op.create_table(
        'daily_balances',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('balance_date', sa.Date(), nullable=False),
        sa.Column('initial_balance_fcfa', sa.Integer, nullable=False),
        sa.Column('used_balance_fcfa', sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='RESTRICT'),
        sa.CheckConstraint('initial_balance_fcfa > 0', name='check_initial_balance_positive'),
        sa.CheckConstraint('used_balance_fcfa >= 0', name='check_used_balance_non_negative'),
        sa.CheckConstraint('used_balance_fcfa <= initial_balance_fcfa', name='check_used_balance_within_limit'),
        sa.UniqueConstraint('subscription_id', 'balance_date', name='uq_subscription_balance')
    )

    # Create transactions table
    op.create_table(
        'transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('amount_fcfa', sa.Integer, nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('pos_transaction_id', sa.String(100), nullable=True),
        sa.Column('idempotency_key', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='RESTRICT'),
        sa.CheckConstraint('amount_fcfa > 0', name='check_amount_positive'),
        sa.UniqueConstraint('pos_transaction_id'),
        sa.UniqueConstraint('idempotency_key')
    )

    # Create refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token_hash', sa.String(255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('token_hash')
    )


def downgrade() -> None:
    op.drop_table('refresh_tokens')
    op.drop_table('transactions')
    op.drop_table('daily_balances')
    op.drop_table('subscriptions')
    op.drop_table('subscription_tiers')
    op.drop_table('users')
