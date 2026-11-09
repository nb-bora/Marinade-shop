"""Catalogue français (langue par défaut). Clés stables : ne jamais les renommer.

Gabarits ``{nom}`` remplis par ``app.i18n.t``. Une clé absente renvoie la clé elle-même
(repli visible sans erreur) ; le catalogue sera complété au fil des lots.
"""

MESSAGES = {
    # Erreurs génériques
    "common.error": "Une erreur est survenue.",
    "common.validation_error": "Les données envoyées sont invalides.",
    "common.not_found": "Ressource introuvable.",
    "common.conflict": "Conflit avec une ressource existante.",
    "common.business_rule": "Opération refusée par les règles métier.",
    "common.database_error": "Erreur de base de données.",
    # Authentification
    "auth.authentication_failed": "Authentification échouée.",
    "auth.forbidden": "Accès refusé.",
    "auth.activation_required": "Votre compte n'est pas encore activé. Saisissez le code reçu par email.",
    "auth.activation_code_invalid": "Code d'activation incorrect.",
    "auth.activation_code_expired": "Ce code a expiré. Demandez-en un nouveau.",
    "auth.activation_too_many_attempts": "Trop d'essais incorrects. Demandez un nouveau code.",
    # HTTP
    "http.bad_request": "Requête invalide.",
    "http.unauthorized": "Authentification requise.",
    "http.forbidden": "Accès refusé.",
    "http.not_found": "Ressource introuvable.",
    "http.method_not_allowed": "Méthode non autorisée.",
    "http.not_acceptable": "Format de réponse non acceptable.",
    "http.conflict": "Conflit avec une ressource existante.",
    "http.gone": "Ressource disparue.",
    "http.payload_too_large": "Requête trop volumineuse.",
    "http.unsupported_media_type": "Type de contenu non pris en charge.",
    "http.unprocessable": "Données non traitables.",
    "http.too_many_requests": "Trop de requêtes, réessayez plus tard.",
    "http.internal_error": "Erreur interne du serveur.",
    "http.bad_gateway": "Passerelle invalide.",
    "http.service_unavailable": "Service temporairement indisponible.",
    "http.error": "Erreur.",
    "http.title.default": "Erreur",
    "http.title.400": "Requête invalide",
    "http.title.401": "Non authentifié",
    "http.title.403": "Accès refusé",
    "http.title.404": "Introuvable",
    "http.title.409": "Conflit",
    "http.title.422": "Données invalides",
    "http.title.429": "Trop de requêtes",
    "http.title.500": "Erreur interne",
    # Validation (Pydantic)
    "validation.failed": "{count} erreurs de validation.",
    "validation.failed_one": "Champ « {field} » : {detail}",
    "validation.invalid": "Valeur invalide.",
    "validation.missing": "Champ obligatoire manquant.",
    "validation.string_too_short": "Au moins {min_length} caractères.",
    "validation.string_too_long": "Au plus {max_length} caractères.",
    "validation.int_parsing": "Nombre entier attendu.",
    "validation.float_parsing": "Nombre attendu.",
    "validation.greater_than": "Doit être supérieur à {gt}.",
    "validation.greater_than_equal": "Doit être supérieur ou égal à {ge}.",
    "validation.less_than": "Doit être inférieur à {lt}.",
    "validation.less_than_equal": "Doit être inférieur ou égal à {le}.",
    "validation.uuid_parsing": "Identifiant UUID attendu.",
    "validation.date_parsing": "Date attendue au format AAAA-MM-JJ.",
    "validation.datetime_parsing": "Date et heure attendues au format ISO 8601.",
    "validation.bool_parsing": "Booléen attendu.",
    "validation.extra_forbidden": "Champ non autorisé.",
    "validation.literal_error": "Valeur non autorisée.",
    "validation.value_error": "Valeur invalide.",
    "validation.assertion_error": "Valeur invalide.",
    # Stock
    "stock.insufficient": "Stock insuffisant pour cette demande.",
}


from app.i18n.messages_fiches import FR as _FICHES_FR  # noqa: E402

MESSAGES.update(_FICHES_FR)
