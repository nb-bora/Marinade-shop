"""Politique d'accès par rôle d'équipe, définie en un seul endroit.

Règle de base : propriétaire, manager et admin plateforme passent partout. Les
autres rôles ne passent que là où ils sont listés ci-dessous. Modifier la
politique d'un restaurant revient donc à modifier ce fichier, pas 40 routes.

Les rôles viennent de ``restaurant_members.staff_role`` (et, pour les anciennes
lignes, de ``restaurant_members.role``).
"""

from typing import get_args

from app.api.dependencies import TenantAccess, require_staff_role
from app.schemas.user import Capability
from app.utils.enums import StaffRole as R

# Prix, carte, recettes, plan de salle : tout ce qui change ce que le restaurant
# vend ou facture. Jamais accessible à un serveur ou un caissier.
MANAGEMENT_ROLES = frozenset({R.MANAGER})

# Mouvements de stock et approvisionnement.
STOCK_ROLES = frozenset({R.MANAGER, R.CHEF, R.SOUS_CHEF})

# Service en salle : prendre une commande, ouvrir/fermer une session, changer
# le statut d'une table.
FRONT_OF_HOUSE_ROLES = frozenset(
    {R.MANAGER, R.WAITER, R.CASHIER, R.HOST, R.BARTENDER}
)

# Argent : encaissement, caisse, demande de remboursement.
CASH_DESK_ROLES = frozenset({R.MANAGER, R.CASHIER})

# Écrans cuisine et bar : voir et faire avancer les tickets de production.
PRODUCTION_ROLES = frozenset(
    {R.MANAGER, R.CHEF, R.SOUS_CHEF, R.BARTENDER, R.WAITER, R.HOST}
)

# Réservations et liste d'attente.
RESERVATION_ROLES = frozenset({R.MANAGER, R.HOST, R.WAITER, R.CASHIER})

MANAGEMENT = require_staff_role(MANAGEMENT_ROLES)
STOCK_KEEPING = require_staff_role(STOCK_ROLES)
FRONT_OF_HOUSE = require_staff_role(FRONT_OF_HOUSE_ROLES)
CASH_DESK = require_staff_role(CASH_DESK_ROLES)
PRODUCTION_TICKETS = require_staff_role(PRODUCTION_ROLES)
RESERVATION_DESK = require_staff_role(RESERVATION_ROLES)

# Décision sur un remboursement : réservée au management.
REFUND_DECISION = MANAGEMENT

# Capacités exposées au client (GET /users/me/access). Le front ne connaît jamais les
# rôles : il demande « puis-je gérer le stock ici ? ». Ajouter un ensemble de rôles
# ci-dessus et l'inscrire ici suffit pour qu'une interface puisse s'en servir.
CAPABILITY_ROLES = {
    "management": MANAGEMENT_ROLES,
    "stock": STOCK_ROLES,
    "front_of_house": FRONT_OF_HOUSE_ROLES,
    "cash_desk": CASH_DESK_ROLES,
    "production": PRODUCTION_ROLES,
    "reservations": RESERVATION_ROLES,
}


# Le contrat OpenAPI (schemas.user.Capability) et cette table doivent rester identiques :
# l'écart ferait renvoyer au client une capacité qu'il ne connaît pas.
assert set(CAPABILITY_ROLES) == set(get_args(Capability)), "Capability et CAPABILITY_ROLES divergent"


def capabilities_of(access: TenantAccess) -> list[str]:
    """Capacités d'un utilisateur dans un restaurant, calculées par la politique elle-même."""
    return sorted(
        name for name, roles in CAPABILITY_ROLES.items() if access.allows(roles)
    )
