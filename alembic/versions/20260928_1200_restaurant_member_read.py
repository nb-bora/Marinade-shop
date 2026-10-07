"""Un membre de l'équipe peut LIRE les restaurants dont il est membre.

La politique de ``restaurants`` ne laissait voir que le restaurant du tenant actif ou
dont on est propriétaire. Un employé n'avait donc aucun moyen de découvrir, sans déjà
connaître son identifiant, dans quel restaurant il travaille (GET /users/me/access).

La nouvelle politique est en lecture seule (SELECT) : elle n'ouvre aucune écriture. Elle
s'ajoute à la politique existante (les politiques permissives se cumulent en OU) et ne
dépend d'aucune politique de ``restaurants`` depuis ``restaurant_members``, donc sans
récursion.

Revision ID: 20260928_1200
Revises: 20260928_1100
"""

from alembic import op

revision = "20260928_1200"
down_revision = "20260928_1100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS restaurants_member_read ON restaurants")
    op.execute(
        """
        CREATE POLICY restaurants_member_read ON restaurants FOR SELECT
        USING (EXISTS (
            SELECT 1 FROM restaurant_members m
            WHERE m.restaurant_id = restaurants.id
              AND m.user_id = (SELECT app_current_user_id())
              AND m.is_active
        ))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS restaurants_member_read ON restaurants")
