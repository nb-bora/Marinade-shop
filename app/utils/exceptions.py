"""Exceptions de l'application, rendues en Problem Details (RFC 9457) traduits.

Une exception métier porte un ``code`` stable (snake_case pointé, ex.
``pressing.machine.transition_interdite``) et des ``params`` injectés dans le message du
catalogue ``app/i18n``. Pendant la migration, un message français en dur reste accepté : il
devient le ``detail`` (non traduit) et le code par défaut de la classe s'applique.
"""

from typing import Any, Dict, Optional

from fastapi import HTTPException


class MarinadeException(Exception):
    """Base exception for Marinade application"""

    default_code = "common.error"
    http_status = 500

    def __init__(
        self,
        message: Optional[str] = None,
        details: Optional[Any] = None,
        *,
        code: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ):
        from app.i18n import t

        self.code = code
        self.params = params or {}
        if message is None:
            message = t(code or self.default_code, "fr", **self.params)
        self.message = message
        self.details = details
        super().__init__(self.message)

    @property
    def problem_code(self) -> str:
        return self.code or self.default_code

    def localized(self, locale: Optional[str] = None) -> str:
        """Message dans la langue demandée ; le texte français en dur si aucun code n'est fourni."""
        if self.code is None:
            return self.message
        from app.i18n import t

        return t(self.code, locale, **self.params)


class AuthenticationError(MarinadeException):
    """Authentication related errors"""

    default_code = "auth.authentication_failed"
    http_status = 401


class AuthorizationError(MarinadeException):
    """Authorization related errors"""

    default_code = "auth.forbidden"
    http_status = 403


class ValidationError(MarinadeException):
    """Validation errors"""

    default_code = "common.validation_error"
    http_status = 400


class NotFoundError(MarinadeException):
    """Resource not found errors"""

    default_code = "common.not_found"
    http_status = 404


class ConflictError(MarinadeException):
    """Resource conflict errors (duplicates, etc.)"""

    default_code = "common.conflict"
    http_status = 409


class BusinessLogicError(MarinadeException):
    """Business logic errors"""

    default_code = "common.business_rule"
    http_status = 400


class InsufficientStockError(ConflictError):
    """Le stock libre ne couvre pas la demande (réponse 409, rien n'est consommé).

    ``details`` liste chaque composant en défaut : identifiant, nom, quantité
    requise et quantité disponible.
    """

    default_code = "stock.insufficient"


class DatabaseError(MarinadeException):
    """Database related errors"""

    default_code = "common.database_error"
    http_status = 500


class ApiError(HTTPException):
    """``HTTPException`` porteuse d'un code de catalogue : traduite par le gestionnaire d'erreurs.

    ``detail`` contient le texte français (repli lisible par tout code qui lit encore
    ``exc.detail``).
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        from app.i18n import t

        self.code = code
        self.params = params or {}
        super().__init__(status_code=status_code, detail=t(code, "fr", **self.params), headers=headers)


class I18nValueError(ValueError):
    """``ValueError`` levée dans un validateur Pydantic, avec un code de catalogue.

    Le gestionnaire 422 la retrouve dans ``ctx.error`` et traduit le message.
    """

    def __init__(self, code: str, **params: Any):
        from app.i18n import t

        self.code = code
        self.params = params
        super().__init__(t(code, "fr", **params))
