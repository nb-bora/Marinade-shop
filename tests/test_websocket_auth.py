"""Le WebSocket cuisine/bar s'authentifie lui-même : jamais de connexion anonyme."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.dependencies import authenticate_websocket, websocket_token
from app.main import app


def _ws(**headers):
    return SimpleNamespace(headers={k.replace("_", "-"): v for k, v in headers.items()})


class TestTokenExtraction:
    def test_authorization_header(self):
        assert websocket_token(_ws(authorization="Bearer abc.def.ghi")) == (
            "abc.def.ghi",
            False,
        )

    def test_browser_subprotocol(self):
        """new WebSocket(url, ["bearer", token]) : le jeton reste hors de l'URL."""
        assert websocket_token(_ws(sec_websocket_protocol="bearer, abc.def")) == (
            "abc.def",
            True,
        )

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"authorization": "Basic Zm9vOmJhcg=="},
            {"sec_websocket_protocol": "chat"},
            {"sec_websocket_protocol": "bearer"},
            {"sec_websocket_protocol": "other, abc"},
        ],
    )
    def test_no_usable_token(self, headers):
        assert websocket_token(_ws(**headers))[0] is None


class TestAuthentication:
    def test_missing_token_is_refused(self):
        result = asyncio.run(authenticate_websocket(_ws(), uuid.uuid4(), {"chef"}))
        assert result is None

    def test_garbage_token_is_refused_without_touching_the_database(self):
        ws = _ws(authorization="Bearer not-a-jwt")
        assert asyncio.run(authenticate_websocket(ws, uuid.uuid4(), {"chef"})) is None


class TestEndpoint:
    def test_anonymous_connection_is_rejected_at_the_handshake(self):
        client = TestClient(app)
        url = f"/v1/ros/ws/kds/{uuid.uuid4()}/KITCHEN"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url):
                pass

    def test_forged_token_is_rejected_at_the_handshake(self):
        client = TestClient(app)
        url = f"/v1/ros/ws/kds/{uuid.uuid4()}/BAR"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url, subprotocols=["bearer", "forged.jwt.x"]):
                pass
