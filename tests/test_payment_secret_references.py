"""Un restaurant ne doit jamais pouvoir désigner le secret qui authentifie ses webhooks.

Sans base de données.
"""

import hashlib
import hmac
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.payment import PaymentConfigurationUpsert
from app.services.easy_transact_service import EasyTransactPaymentService
from app.utils.payment_secrets import (
    is_allowed_credential_env_key,
    is_allowed_webhook_secret_env_key,
    resolve_secret,
)

# Variables dont la valeur est publique ou devinable par n'importe quel client.
GUESSABLE = [
    "ENVIRONMENT",
    "ALLOW_ORIGINS",
    "ALLOW_METHODS",
    "APP_NAME",
    "PATH",
    "DB_USER",
    "EASYTRANSACT_API_BASE_URL",
    "EASYTRANSACT_WEBHOOK_SIGNATURE_HEADER",
    "EASYTRANSACT_WEBHOOK_SIGNATURE_ALGORITHM",
]


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _service() -> EasyTransactPaymentService:
    return EasyTransactPaymentService.__new__(EasyTransactPaymentService)


@pytest.mark.parametrize("name", GUESSABLE + ["", "easytransact_webhook_secret"])
def test_arbitrary_variable_names_are_refused(name):
    assert not is_allowed_webhook_secret_env_key(name)
    assert not is_allowed_credential_env_key(name)


@pytest.mark.parametrize(
    "name", ["EASYTRANSACT_WEBHOOK_SECRETX", "EASYTRANSACT_WEBHOOK_SECRET_"]
)
def test_lookalike_names_are_refused(name):
    assert not is_allowed_webhook_secret_env_key(name)


@pytest.mark.parametrize(
    "name",
    [
        "EASYTRANSACT_WEBHOOK_SECRET",
        "EASYTRANSACT_WEBHOOK_SECRET_CHEZMAMA",
        "EASYTRANSACT_WEBHOOK_SECRET_RESTO_2",
    ],
)
def test_reserved_webhook_secret_names_are_accepted(name):
    assert is_allowed_webhook_secret_env_key(name)


def test_credential_and_webhook_name_families_are_not_interchangeable():
    assert not is_allowed_credential_env_key("EASYTRANSACT_WEBHOOK_SECRET")
    assert not is_allowed_webhook_secret_env_key("EASYTRANSACT_API_TOKEN")


@pytest.mark.parametrize("name", GUESSABLE)
def test_schema_rejects_guessable_webhook_secret_reference(name):
    with pytest.raises(ValidationError):
        PaymentConfigurationUpsert(
            restaurant_id=uuid.uuid4(), webhook_secret_env_key=name
        )


def test_schema_rejects_guessable_credential_reference():
    with pytest.raises(ValidationError):
        PaymentConfigurationUpsert(
            restaurant_id=uuid.uuid4(), credential_env_key="ALLOW_ORIGINS"
        )


def test_schema_defaults_are_accepted():
    config = PaymentConfigurationUpsert(restaurant_id=uuid.uuid4())
    assert config.webhook_secret_env_key == "EASYTRANSACT_WEBHOOK_SECRET"


class TestWebhookWithTenantConfiguration:
    def test_forged_webhook_signed_with_a_public_variable_is_rejected(self, monkeypatch):
        """Attaque d'origine : signer avec la valeur d'ENVIRONMENT que l'on connaît."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        poisoned_row = SimpleNamespace(webhook_secret_env_key="ENVIRONMENT")
        body = b'{"vendor_reference":"MRD-1","status":"success"}'
        with pytest.raises(HTTPException) as exc:
            _service().verify_webhook(body, _sign(body, "production"), poisoned_row)
        assert exc.value.status_code == 503

    def test_reserved_variable_is_resolved_and_verified(self, monkeypatch):
        monkeypatch.setenv("EASYTRANSACT_WEBHOOK_SECRET_CHEZMAMA", "s3cret-chez-mama")
        config = SimpleNamespace(
            webhook_secret_env_key="EASYTRANSACT_WEBHOOK_SECRET_CHEZMAMA"
        )
        body = b'{"vendor_reference":"MRD-2"}'
        _service().verify_webhook(body, _sign(body, "s3cret-chez-mama"), config)
        with pytest.raises(HTTPException) as exc:
            _service().verify_webhook(body, _sign(body, "wrong"), config)
        assert exc.value.status_code == 401

    def test_unset_reserved_variable_fails_closed(self, monkeypatch):
        monkeypatch.delenv("EASYTRANSACT_WEBHOOK_SECRET_GHOST", raising=False)
        config = SimpleNamespace(
            webhook_secret_env_key="EASYTRANSACT_WEBHOOK_SECRET_GHOST"
        )
        with pytest.raises(HTTPException) as exc:
            _service().verify_webhook(b"x", _sign(b"x", ""), config)
        assert exc.value.status_code == 401


class TestSecretResolution:
    def test_default_names_fall_back_to_settings_when_not_exported(self, monkeypatch):
        """Un .env chargé par pydantic n'alimente pas os.environ."""
        monkeypatch.delenv("EASYTRANSACT_WEBHOOK_SECRET", raising=False)
        assert resolve_secret("EASYTRANSACT_WEBHOOK_SECRET") == (
            settings.EASYTRANSACT_WEBHOOK_SECRET
        )

    def test_environment_wins_over_settings(self, monkeypatch):
        monkeypatch.setenv("EASYTRANSACT_WEBHOOK_SECRET", "from-environment")
        assert resolve_secret("EASYTRANSACT_WEBHOOK_SECRET") == "from-environment"

    def test_unknown_names_never_fall_back_to_settings(self, monkeypatch):
        monkeypatch.delenv("EASYTRANSACT_WEBHOOK_SECRET_GHOST", raising=False)
        assert resolve_secret("EASYTRANSACT_WEBHOOK_SECRET_GHOST") is None


class TestWhoMayChangeSecretReferences:
    DEFAULT = PaymentConfigurationUpsert(restaurant_id=uuid.uuid4())
    CUSTOM = PaymentConfigurationUpsert(
        restaurant_id=uuid.uuid4(),
        webhook_secret_env_key="EASYTRANSACT_WEBHOOK_SECRET_CHEZMAMA",
    )

    def test_owner_may_keep_default_references(self):
        _service()._enforce_secret_references(self.DEFAULT, None, False)

    def test_owner_may_not_pick_a_custom_reference(self):
        with pytest.raises(HTTPException) as exc:
            _service()._enforce_secret_references(self.CUSTOM, None, False)
        assert exc.value.status_code == 403

    def test_owner_may_resubmit_the_reference_an_admin_set(self):
        existing = SimpleNamespace(
            credential_env_key="EASYTRANSACT_API_TOKEN",
            webhook_secret_env_key="EASYTRANSACT_WEBHOOK_SECRET_CHEZMAMA",
        )
        _service()._enforce_secret_references(self.CUSTOM, existing, False)

    def test_platform_admin_may_set_a_custom_reference(self):
        _service()._enforce_secret_references(self.CUSTOM, None, True)
