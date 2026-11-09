"""Middleware ASGI de sécurité HTTP (ASVS V3.4, V4.1, V13.4, V16.2).

Pour chaque requête :

* identifiant de corrélation : ``X-Request-ID`` reçu s'il est sûr (lettres, chiffres,
  ``.-_``, 64 caractères au plus), sinon généré ; renvoyé dans la réponse et posé
  dans le contexte de journalisation ;
* en-têtes de sécurité sur TOUTES les réponses (y compris erreurs et 404) : CSP
  restrictive (assouplie pour la seule documentation interactive), nosniff,
  Referrer-Policy, CORP/COOP, Permissions-Policy, X-Frame-Options, HSTS si activé ;
* ``Cache-Control: no-store`` sur les réponses de l'API (données authentifiées ou
  jetons), sauf si la route a posé sa propre politique de cache ;
* refus (413) d'un corps de requête plus gros que ``MAX_REQUEST_BODY_BYTES``.

ASGI pur (pas de BaseHTTPMiddleware) : aucun coût de mise en tampon et compatible avec
les réponses en flux et les WebSockets.
"""

from __future__ import annotations

import re
import uuid
from typing import Iterable

from app.core.config import settings
from app.utils.logging import client_ip_var, request_id_var

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger UI et ReDoc chargent leurs scripts depuis jsDelivr et utilisent un script en
# ligne : cette politique ne s'applique qu'à leurs pages HTML.
DOCS_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "font-src https://fonts.gstatic.com; "
    "connect-src 'self'; worker-src 'self' blob:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
DOCS_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect"})
PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
    "microphone=(), payment=(), usb=(), interest-cohort=()"
)


class RequestTooLarge(Exception):
    pass


def _header_names(headers: Iterable[tuple[bytes, bytes]]) -> set[bytes]:
    return {name.lower() for name, _ in headers}


def security_headers_for(path: str) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-resource-policy", b"same-origin"),
        (b"cross-origin-opener-policy", b"same-origin"),
        (b"x-frame-options", b"DENY"),
        (b"permissions-policy", PERMISSIONS_POLICY.encode()),
        (
            b"content-security-policy",
            (DOCS_CSP if path in DOCS_PATHS else API_CSP).encode(),
        ),
    ]
    if settings.hsts_enabled:
        headers.append(
            (
                b"strict-transport-security",
                f"max-age={settings.HSTS_MAX_AGE_SECONDS}; includeSubDomains".encode(),
            )
        )
    if path.startswith("/v1"):
        headers.append((b"cache-control", b"no-store"))
    return headers


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        client = scope.get("client")
        rid_token = request_id_var.set(request_id)
        ip_token = client_ip_var.set(client[0] if client else "-")
        try:
            if scope["type"] == "websocket":
                await self.app(scope, receive, send)
                return
            await self._http(scope, receive, send, request_id)
        finally:
            request_id_var.reset(rid_token)
            client_ip_var.reset(ip_token)

    async def _http(self, scope, receive, send, request_id: str):
        path = scope.get("path", "")
        extra = security_headers_for(path)
        limit = settings.MAX_REQUEST_BODY_BYTES
        started = False

        async def send_with_headers(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers") or [])
                present = _header_names(headers)
                headers.extend((n, v) for n, v in extra if n not in present)
                headers = [(n, v) for n, v in headers if n.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                # Le serveur n'annonce pas sa technologie (ASVS 13.4.6).
                headers = [(n, v) for n, v in headers if n.lower() not in (b"server", b"x-powered-by")]
                message = {**message, "headers": headers}
            await send(message)

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                too_big = True
            if too_big:
                await self._reject_too_large(send_with_headers)
                return

        received = 0

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestTooLarge()
            return message

        try:
            await self.app(scope, counting_receive, send_with_headers)
        except RequestTooLarge:
            if not started:
                await self._reject_too_large(send_with_headers)

    @staticmethod
    async def _reject_too_large(send):
        body = b'{"detail":"Request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
