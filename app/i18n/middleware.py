"""Middleware ASGI de langue : négocie ``Accept-Language``, expose la langue à la requête et
ajoute ``Content-Language`` et ``Vary: Accept-Language`` à toutes les réponses HTTP."""

from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.i18n import demarrer_requete


class LocaleMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        etat = demarrer_requete(Headers(scope=scope).get("accept-language"))
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def envoyer(message: Message) -> None:
            if message["type"] == "http.response.start":
                entetes = MutableHeaders(scope=message)
                if "content-language" not in entetes:
                    entetes["Content-Language"] = etat.locale
                vary = entetes.get("vary")
                if not vary:
                    entetes["Vary"] = "Accept-Language"
                elif "accept-language" not in vary.lower():
                    entetes["Vary"] = f"{vary}, Accept-Language"
            await send(message)

        await self.app(scope, receive, envoyer)
