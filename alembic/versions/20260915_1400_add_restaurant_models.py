"""add restaurant models

Revision ID: 20260915_1400
Revises: 20260914_1200
Create Date: 2024-09-15 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260915_1400'
down_revision = '20260914_1200'
branch_labels = None
depends_on = None


def upgrade():
    # Update user.role constraint to include restaurant role
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS check_role_valid")
    op.execute("ALTER TABLE users ADD CONSTRAINT check_role_valid CHECK (role IN ('admin', 'pos', 'restaurant'))")

    # Create restaurants table
    op.create_table(
        'restaurants',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('logo_url', sa.String(length=500), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='XAF'),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('horaires_ouverture', postgresql.JSONB(), nullable=True),
        sa.Column('taux_service', sa.Numeric(precision=5, scale=2), nullable=False, server_default='0.0'),
        sa.Column('config_jsonb', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_restaurant_user', 'restaurants', ['user_id'])
    op.create_index('idx_restaurant_active', 'restaurants', ['is_active'])

    # Create menus table
    op.create_table(
        'menus',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('restaurant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('actif', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('config_jsonb', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_menu_restaurant', 'menus', ['restaurant_id'])
    op.create_index('idx_menu_active', 'menus', ['actif'])

    # Create menu_categories table
    op.create_table(
        'menu_categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('restaurant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('menu_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('ordre', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['menu_id'], ['menus.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_category_restaurant', 'menu_categories', ['restaurant_id'])
    op.create_index('idx_category_menu', 'menu_categories', ['menu_id'])
    op.create_index('idx_category_order', 'menu_categories', ['restaurant_id', 'menu_id', 'ordre'])

    # Create plats table
    op.create_table(
        'plats',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('restaurant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('nom', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('prix', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('devise', sa.String(length=3), nullable=False, server_default='XAF'),
        sa.Column('disponible', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('allergenes', postgresql.JSONB(), nullable=True),
        sa.Column('photo_url', sa.String(length=500), nullable=True),
        sa.Column('temps_preparation', sa.Integer(), nullable=True),
        sa.Column('attributs_jsonb', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['menu_categories.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('prix > 0', name='check_prix_positive')
    )
    op.create_index('idx_plat_restaurant', 'plats', ['restaurant_id'])
    op.create_index('idx_plat_category', 'plats', ['category_id'])
    op.create_index('idx_plat_disponible', 'plats', ['disponible'])

    # Create boissons table
    op.create_table(
        'boissons',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('restaurant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('nom', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('prix', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('devise', sa.String(length=3), nullable=False, server_default='XAF'),
        sa.Column('alcool', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('disponible', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('attributs_jsonb', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('prix > 0', name='check_prix_positive')
    )
    op.create_index('idx_boisson_restaurant', 'boissons', ['restaurant_id'])
    op.create_index('idx_boisson_disponible', 'boissons', ['disponible'])
    op.create_index('idx_boisson_category', 'boissons', ['category'])

    # Create tables table
    op.create_table(
        'tables',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('restaurant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('numero', sa.String(length=50), nullable=False),
        sa.Column('capacite', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('emplacement', sa.String(length=50), nullable=True),
        sa.Column('statut', sa.String(length=20), nullable=False, server_default='libre'),
        sa.Column('attributs_jsonb', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('capacite > 0', name='check_capacite_positive')
    )
    op.create_index('idx_table_restaurant', 'tables', ['restaurant_id'])
    op.create_index('idx_table_statut', 'tables', ['statut'])
    op.create_index('idx_table_numero', 'tables', ['restaurant_id', 'numero'])

    # Create commandes table
    op.create_table(
        'commandes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('restaurant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('table_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('statut', sa.String(length=20), nullable=False, server_default='en_cours'),
        sa.Column('total', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('taux_service', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('metadata_jsonb', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['table_id'], ['tables.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('total >= 0', name='check_total_positive')
    )
    op.create_index('idx_commande_restaurant', 'commandes', ['restaurant_id'])
    op.create_index('idx_commande_table', 'commandes', ['table_id'])
    op.create_index('idx_commande_statut', 'commandes', ['statut'])
    op.create_index('idx_commande_date', 'commandes', ['created_at'])

    # Create commande_items table
    op.create_table(
        'commande_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('commande_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plat_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('boisson_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('quantite', sa.Integer(), nullable=False),
        sa.Column('prix_unitaire', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('total', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['commande_id'], ['commandes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plat_id'], ['plats.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['boisson_id'], ['boissons.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('quantite > 0', name='check_quantite_positive'),
        sa.CheckConstraint('total >= 0', name='check_total_positive')
    )
    op.create_index('idx_item_commande', 'commande_items', ['commande_id'])
    op.create_index('idx_item_plat', 'commande_items', ['plat_id'])
    op.create_index('idx_item_boisson', 'commande_items', ['boisson_id'])


def downgrade():
    op.drop_table('commande_items')
    op.drop_table('commandes')
    op.drop_table('tables')
    op.drop_table('boissons')
    op.drop_table('plats')
    op.drop_table('menu_categories')
    op.drop_table('menus')
    op.drop_table('restaurants')

    # Remove RESTAURANT role from user.role constraint
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS check_role_valid")
    op.execute("ALTER TABLE users ADD CONSTRAINT check_role_valid CHECK (role IN ('admin', 'pos'))")
