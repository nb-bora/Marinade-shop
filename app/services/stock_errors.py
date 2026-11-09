"""Erreurs du module stock : un code stable (``stock.motif_obligatoire``) et un message français.

Le gestionnaire d'erreurs rend une exception métier en ``application/problem+json`` ; ``problem_code``
est le code stable lu par l'interface. Quand l'erreur vise un champ de formulaire, ``champ`` le nomme et
le gestionnaire l'ajoute à ``errors`` (``[{field, code, detail}]``), ce que le front affiche sous le champ.
"""

from __future__ import annotations

from typing import Any, List, Optional

from app.utils.exceptions import MarinadeException


class StockError(MarinadeException):
    """Base : ``code`` stable, ``message`` français, ``http_status`` choisi par la sous-classe."""

    http_status = 409

    def __init__(
        self,
        code: str,
        message: str,
        *,
        champ: Optional[str] = None,
        details: Optional[Any] = None,
        params: Optional[dict] = None,
    ):
        super().__init__(message, details, params=params)
        self._code = code
        self.champ = champ

    @property
    def problem_code(self) -> str:  # type: ignore[override]
        return self._code

    def localized(self, locale: Optional[str] = None) -> str:
        return self.message

    @property
    def errors(self) -> Optional[List[dict]]:
        if not self.champ:
            return None
        return [{"field": self.champ, "code": self._code, "detail": self.message}]


class StockValidationError(StockError):
    """Saisie invalide (précision, motif manquant, unité inconnue) : 422."""

    http_status = 422


class StockConflict(StockError):
    """L'état actuel interdit l'opération (nom pris, stock insuffisant, composant utilisé) : 409."""

    http_status = 409


class StockNotFound(StockError):
    """Élément introuvable dans ce restaurant : 404."""

    http_status = 404
