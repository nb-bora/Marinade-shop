"""Toutes les erreurs de l'API en ``application/problem+json`` (RFC 9457), traduites.

Corps : ``type`` (URI stable ``https://marinade.app/problems/<code>``), ``title`` (court,
traduit), ``status``, ``detail`` (phrase traduite), ``code`` (identifiant stable), ``params``
(valeurs injectées, facultatif), ``errors`` (validation : ``[{field, code, detail}]``),
``instance`` (chemin de la requête). Les exceptions métier gardent aussi ``message`` (= detail)
et ``details`` pendant la transition du front.

La langue est celle de la requête (voir ``app.i18n`` et ``LocaleMiddleware``) ; chaque réponse
d'erreur porte ``Content-Language`` et ``Vary: Accept-Language``.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.i18n import locale_courante, parametres_json, t
from app.utils.exceptions import ApiError, I18nValueError, MarinadeException
from app.utils.logging import get_logger

logger = get_logger(__name__)

PROBLEM_TYPE_BASE = "https://marinade.app/problems/"
PROBLEM_MEDIA_TYPE = "application/problem+json"

_CODES_HTTP = {
    400: "http.bad_request",
    401: "http.unauthorized",
    403: "http.forbidden",
    404: "http.not_found",
    405: "http.method_not_allowed",
    406: "http.not_acceptable",
    409: "http.conflict",
    410: "http.gone",
    413: "http.payload_too_large",
    415: "http.unsupported_media_type",
    422: "http.unprocessable",
    429: "http.too_many_requests",
    500: "http.internal_error",
    502: "http.bad_gateway",
    503: "http.service_unavailable",
}


class ProblemJSONResponse(JSONResponse):
    media_type = PROBLEM_MEDIA_TYPE


def titre(status_code: int, locale: Optional[str] = None) -> str:
    cle = f"http.title.{status_code}"
    texte = t(cle, locale)
    if texte != cle:
        return texte
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return t("http.title.default", locale)


def problem_response(
    request: Optional[Request],
    status_code: int,
    code: str,
    detail: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    errors: Optional[List[dict]] = None,
    extra: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> ProblemJSONResponse:
    locale = locale_courante()
    corps: Dict[str, Any] = {
        "type": PROBLEM_TYPE_BASE + code,
        "title": titre(status_code, locale),
        "status": status_code,
        "detail": detail,
        "code": code,
    }
    rendus = parametres_json(params)
    if rendus:
        corps["params"] = rendus
    if errors is not None:
        corps["errors"] = errors
    if request is not None:
        corps["instance"] = request.url.path
    if extra:
        corps.update(extra)
    entetes = dict(headers or {})
    entetes["Content-Language"] = locale
    vary = entetes.get("Vary")
    entetes["Vary"] = f"{vary}, Accept-Language" if vary else "Accept-Language"
    return ProblemJSONResponse(
        status_code=status_code, content=jsonable_encoder(corps), headers=entetes
    )


# --------------------------------------------------------------------------- métier
async def marinade_exception_handler(request: Request, exc: MarinadeException):
    status_code = getattr(exc, "http_status", 500) or 500
    if status_code >= 500:
        logger.error(f"Marinade exception: {exc.message}", extra={"details": exc.details})
    else:
        logger.info("Marinade exception %s: %s", exc.problem_code, exc.message)
    detail = exc.localized(locale_courante())
    extra: Dict[str, Any] = {"message": detail}
    if exc.details is not None:
        extra["details"] = exc.details
    return problem_response(
        request,
        status_code,
        exc.problem_code,
        detail,
        params=exc.params,
        errors=getattr(exc, "errors", None),
        extra=extra,
    )


# ------------------------------------------------------------------------------ HTTP
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    status_code = exc.status_code
    headers = getattr(exc, "headers", None)
    if isinstance(exc, ApiError):
        return problem_response(
            request, status_code, exc.code, t(exc.code, None, **exc.params),
            params=exc.params, headers=headers,
        )
    code = _CODES_HTTP.get(status_code, "http.error")
    brut = exc.detail
    extra = None
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = None
    if isinstance(brut, str) and brut and brut != phrase:
        detail = brut  # message en dur non encore migré vers le catalogue (repli)
    else:
        detail = t(code)
        if brut is not None and not isinstance(brut, str):
            extra = {"details": brut}
    return problem_response(request, status_code, code, detail, extra=extra, headers=headers)


# ------------------------------------------------------------------------ validation
_LOCATIONS = {"body", "query", "path", "header", "cookie"}

# Types d'erreurs Pydantic v2 -> code du catalogue (``validation.<type>``). Les paramètres
# du contexte (min_length, ge, pattern...) sont injectés dans le gabarit.
_TYPES_PYDANTIC = {
    "missing", "extra_forbidden", "string_type", "string_too_short", "string_too_long",
    "string_pattern_mismatch", "int_type", "int_parsing", "int_from_float", "float_type",
    "float_parsing", "decimal_type", "decimal_parsing", "decimal_max_digits",
    "decimal_max_places", "decimal_whole_digits", "bool_type", "bool_parsing",
    "greater_than", "greater_than_equal", "less_than", "less_than_equal", "multiple_of",
    "literal_error", "enum", "uuid_type", "uuid_parsing", "date_type", "date_parsing",
    "date_from_datetime_parsing", "datetime_type", "datetime_parsing", "datetime_from_date_parsing",
    "time_type", "time_parsing", "list_type", "dict_type", "model_type", "model_attributes_type",
    "too_short", "too_long", "json_invalid", "json_type", "value_error", "assertion_error",
    "url_type", "url_parsing", "finite_number", "timezone_aware", "timezone_naive",
    "date_past", "date_future", "datetime_past", "datetime_future", "union_tag_invalid",
    "union_tag_not_found", "bytes_type", "is_instance_of", "none_required", "frozen_field",
    "uuid_version", "dataclass_type", "set_type", "tuple_type",
}


def _champ(loc) -> str:
    parties = list(loc or ())
    if len(parties) > 1 and parties[0] in _LOCATIONS:
        parties = parties[1:]
    return ".".join(str(p) for p in parties)


def _erreur_validation(erreur: dict, locale: str) -> dict:
    type_ = erreur.get("type", "")
    ctx = erreur.get("ctx") or {}
    cause = ctx.get("error")
    if isinstance(cause, I18nValueError):
        return {
            "field": _champ(erreur.get("loc")),
            "code": cause.code,
            "detail": t(cause.code, locale, **cause.params),
        }
    if type_ in ("value_error", "assertion_error"):
        message = str(erreur.get("msg", ""))
        for prefixe in ("Value error, ", "Assertion failed, "):
            if message.startswith(prefixe):
                message = message[len(prefixe):]
        return {
            "field": _champ(erreur.get("loc")),
            "code": f"validation.{type_}",
            "detail": message or t(f"validation.{type_}", locale),
        }
    code = f"validation.{type_}" if type_ in _TYPES_PYDANTIC else "validation.invalid"
    params = {k: v for k, v in ctx.items() if isinstance(v, (str, int, float))}
    if "expected" in ctx:
        params["expected"] = str(ctx["expected"])
    detail = t(code, locale, **params)
    return {"field": _champ(erreur.get("loc")), "code": code, "detail": detail}


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    locale = locale_courante()
    errors = [_erreur_validation(e, locale) for e in exc.errors()]
    if len(errors) == 1:
        e = errors[0]
        detail = t("validation.failed_one", locale, field=e["field"] or "-", detail=e["detail"])
    else:
        detail = t("validation.failed", locale, count=len(errors))
    return problem_response(
        request, status.HTTP_422_UNPROCESSABLE_ENTITY, "validation.failed", detail,
        params={"count": len(errors)}, errors=errors,
    )


# ----------------------------------------------------------------------------- 500
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return problem_response(
        request, status.HTTP_500_INTERNAL_SERVER_ERROR, "http.internal_error",
        t("http.internal_error"),
    )


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MarinadeException, marinade_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
