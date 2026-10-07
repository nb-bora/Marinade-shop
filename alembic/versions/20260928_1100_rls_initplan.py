"""RLS : evaluer le contexte de session une seule fois par requete, pas par ligne.

Une politique ecrite ``app_is_platform_admin() OR restaurant_id = app_current_tenant_id()``
appelle ses fonctions pour CHAQUE ligne candidate. Le planificateur ne peut alors plus
traiter ``restaurant_id = app_current_tenant_id()`` comme une constante : il sous-estime
le nombre de lignes et, des qu'un curseur de pagination s'ajoute, abandonne le parcours
ordonne de l'index pour un Bitmap Scan suivi d'un tri de toutes les lignes du restaurant
(mesure : 13 ms pour 20 000 lignes, et lineaire en leur nombre).

Enveloppees dans ``(SELECT ...)``, les fonctions deviennent des InitPlan evalues une
fois : la meme requete repasse a 0,3 ms avec un Index Scan ordonne, quel que soit le
nombre de transactions du restaurant. Le sens de la politique est strictement inchange.

La migration reecrit toutes les politiques ``*_tenant_isolation`` et la politique des
utilisateurs, donc aussi celles que l'on ajoutera plus tard avec l'ancienne ecriture
si cette migration est rejouee.

Revision ID: 20260928_1100
Revises: 20260928_1000
"""

import re

from alembic import op
import sqlalchemy as sa

revision = "20260928_1100"
down_revision = "20260928_1000"
branch_labels = None
depends_on = None

CONTEXT_FUNCTIONS = "app_is_platform_admin|app_current_tenant_id|app_current_user_id"
BARE = re.compile(rf"(?<!SELECT )\b({CONTEXT_FUNCTIONS})\(\)")
WRAPPED = re.compile(rf"\(SELECT ({CONTEXT_FUNCTIONS})\(\)\)")


def _rewrite(rewrite) -> None:
    bind = op.get_bind()
    policies = bind.execute(
        sa.text(
            "SELECT schemaname, tablename, policyname, qual, with_check "
            "FROM pg_policies WHERE schemaname = current_schema()"
        )
    ).fetchall()
    for _schema, table, name, qual, check in policies:
        if not qual and not check:
            continue
        new_qual = rewrite(qual) if qual else None
        new_check = rewrite(check) if check else None
        if new_qual == qual and new_check == check:
            continue
        clauses = []
        if new_qual:
            clauses.append(f"USING ({new_qual})")
        if new_check:
            clauses.append(f"WITH CHECK ({new_check})")
        op.execute(f'ALTER POLICY "{name}" ON "{table}" {" ".join(clauses)}')


def upgrade() -> None:
    _rewrite(lambda expr: BARE.sub(r"(SELECT \1())", expr))


def downgrade() -> None:
    _rewrite(lambda expr: WRAPPED.sub(r"\1()", expr))
