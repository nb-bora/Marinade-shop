"""2FA réelle : activation, vérification au login, codes de secours, et absence de
secrets dans les réponses HTTP. Sans base de données (dépôts factices en mémoire).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.core.config import Settings, settings
from app.core.database import get_db
from app.main import app
from app.models.user import User
from app.schemas.user import UserLogin
from app.services import auth_service as auth_module
from app.services.auth_service import AuthService, _get_totp
from app.utils.crypto import decrypt_secret, encrypt_secret
from app.utils.exceptions import AuthenticationError, ValidationError


class FakeUserRepo:
    """Mémoire d'un seul utilisateur, avec la surface utilisée par AuthService."""

    def __init__(self, user):
        self.user = user

    def get(self, user_id):
        return self.user if str(user_id) == str(self.user.id) else None

    def get_by_email(self, email):
        return self.user if email == self.user.email else None

    def get_by_phone(self, phone):
        return None

    def save_2fa_secret(self, user_id, secret):
        self.user.two_factor_secret_hash = secret
        return self.user

    def get_2fa_secret(self, user_id):
        return self.user.two_factor_secret_hash

    def save_2fa_recovery_codes(self, user_id, codes):
        self.user.two_factor_recovery_codes_jsonb = codes
        return self.user

    def get_2fa_recovery_codes(self, user_id):
        return self.user.two_factor_recovery_codes_jsonb

    def confirm_2fa_enabled(self, user_id, confirmed_at=None):
        self.user.two_factor_confirmed_at = confirmed_at
        return self.user

    def get_by_reset_token_hash(self, token_hash):
        if token_hash == self.user.password_reset_token_hash:
            return self.user
        return None

    def update(self, user, values):
        for key, value in values.items():
            setattr(user, key, value)
        return user

    def clear_reset_token(self, user_id):
        self.user.password_reset_token_hash = None
        self.user.password_reset_expires_at = None
        return self.user


class FakeRefreshRepo:
    def __init__(self):
        self.deleted_for = []

    def delete_by_user_id(self, user_id):
        self.deleted_for.append(user_id)


def _make_user():
    # Vraie instance ORM, jamais persistée : AuthService distingue un User d'une
    # chaîne (email ou téléphone) par isinstance.
    return User(
        id=uuid.uuid4(),
        email="gerant@example.com",
        phone="+237600000000",
        first_name="Jean",
        last_name="Test",
        role="restaurant",
        is_active=True,
        password_hash="unused",
    )


@pytest.fixture
def service():
    svc = AuthService.__new__(AuthService)
    svc.db = None
    svc.user_repo = FakeUserRepo(_make_user())
    svc.refresh_token_repo = FakeRefreshRepo()
    # bcrypt n'est pas l'objet de ces tests (et est lent) : le mot de passe est accepté.
    svc.verify_password = lambda plain, hashed: True
    svc.get_password_hash = lambda plain: "hashed"
    return svc


def _enable_2fa(svc):
    setup = svc.setup_two_factor(svc.user_repo.user.id)
    svc.confirm_two_factor(svc.user_repo.user.id, _get_totp(setup.secret).now())
    return setup


def _login(svc, code=None):
    return svc.authenticate_user(
        UserLogin(email="gerant@example.com", password="x", two_factor_code=code)
    )


class TestSecretStorage:
    def test_secret_is_encrypted_at_rest_but_recoverable(self, service):
        setup = service.setup_two_factor(service.user_repo.user.id)
        stored = service.user_repo.user.two_factor_secret_hash
        assert stored.startswith("enc:")
        assert setup.secret not in stored
        assert decrypt_secret(stored) == setup.secret

    def test_legacy_plaintext_secret_stays_readable(self):
        assert decrypt_secret("JBSWY3DPEHPK3PXP") == "JBSWY3DPEHPK3PXP"

    def test_tampered_ciphertext_is_unusable_not_a_crash(self):
        assert decrypt_secret(encrypt_secret("ABCDEFGH")[:-4] + "AAAA") is None

    def test_recovery_codes_are_stored_hashed(self, service):
        setup = service.setup_two_factor(service.user_repo.user.id)
        stored = service.user_repo.user.two_factor_recovery_codes_jsonb
        assert len(stored) == len(setup.recovery_codes) == 8
        assert not set(stored) & set(setup.recovery_codes)


class TestConfirmation:
    def test_wrong_code_does_not_enable_2fa(self, service):
        service.setup_two_factor(service.user_repo.user.id)
        with pytest.raises(ValidationError):
            service.confirm_two_factor(service.user_repo.user.id, "000000")
        assert service.user_repo.user.two_factor_confirmed_at is None

    def test_the_secret_itself_is_not_a_valid_confirmation_code(self, service):
        """Régression : l'ancienne route comparait le hash du jeton au hash du secret."""
        setup = service.setup_two_factor(service.user_repo.user.id)
        with pytest.raises(ValidationError):
            service.confirm_two_factor(service.user_repo.user.id, setup.secret[:8])

    def test_current_totp_code_enables_2fa(self, service):
        _enable_2fa(service)
        assert service.user_repo.user.two_factor_confirmed_at is not None


class TestLogin:
    def test_login_without_2fa_is_unchanged(self, service):
        assert _login(service) is service.user_repo.user

    def test_code_is_required_once_2fa_is_enabled(self, service):
        _enable_2fa(service)
        with pytest.raises(AuthenticationError) as exc:
            _login(service)
        assert exc.value.details == {"two_factor_required": True}

    def test_wrong_code_is_rejected(self, service):
        _enable_2fa(service)
        with pytest.raises(AuthenticationError):
            _login(service, "000000")

    def test_valid_totp_code_logs_in(self, service):
        setup = _enable_2fa(service)
        assert _login(service, _get_totp(setup.secret).now()) is service.user_repo.user

    def test_recovery_code_logs_in_once_only(self, service):
        setup = _enable_2fa(service)
        code = setup.recovery_codes[0]
        assert _login(service, code) is service.user_repo.user
        with pytest.raises(AuthenticationError):
            _login(service, code)

    def test_unusable_legacy_secret_cannot_crash_login_with_a_500(self, service):
        """Anciennes lignes : un hash hexadécimal n'est pas du base32 valide."""
        setup = _enable_2fa(service)
        service.user_repo.user.two_factor_secret_hash = "a" * 64
        with pytest.raises(AuthenticationError):
            _login(service, "123456")
        # Le code de secours reste la porte de sortie pour ces comptes.
        assert _login(service, setup.recovery_codes[0]) is service.user_repo.user

    def test_regenerating_codes_invalidates_the_previous_set(self, service):
        setup = _enable_2fa(service)
        fresh = service.regenerate_recovery_codes(service.user_repo.user.id)
        with pytest.raises(AuthenticationError):
            _login(service, setup.recovery_codes[0])
        assert _login(service, fresh[0]) is service.user_repo.user


def test_resetting_a_password_revokes_open_sessions(service):
    user = service.user_repo.user
    user.password_reset_token_hash = auth_module._hash_token("RAW")
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    service.reset_password("RAW", "a-brand-new-password")

    assert user.password_hash == "hashed"
    assert service.refresh_token_repo.deleted_for == [user.id]


# --------------------------------------------------------------------------- #
# Routes : aucun secret dans les réponses HTTP
# --------------------------------------------------------------------------- #
SECRET = "RAW-SECRET-TOKEN-1234"


@pytest.fixture
def client(monkeypatch):
    user = _make_user()
    monkeypatch.setattr(AuthService, "forgot_password", lambda self, email: SECRET)
    monkeypatch.setattr(AuthService, "send_email_verification", lambda self, uid: SECRET)
    monkeypatch.setattr(AuthService, "send_phone_verification", lambda self, uid: SECRET)

    def fake_get_db():
        yield None

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


ROUTES = [
    ("/v1/auth/forgot-password", {"email": "gerant@example.com"}),
    ("/v1/auth/send-verification-email", None),
    ("/v1/auth/send-verification-phone", None),
]


def _post(client, path, body):
    return client.post(path, json=body) if body else client.post(path)


@pytest.mark.parametrize("path,body", ROUTES)
def test_tokens_never_appear_in_responses_by_default(client, path, body):
    assert settings.DEV_EXPOSE_AUTH_TOKENS is False
    response = _post(client, path, body)
    assert response.status_code == 200, response.text
    assert SECRET not in response.text


@pytest.mark.parametrize("path,body", ROUTES)
def test_tokens_appear_only_with_the_explicit_dev_flag(client, monkeypatch, path, body):
    monkeypatch.setattr(settings, "DEV_EXPOSE_AUTH_TOKENS", True)
    assert SECRET in _post(client, path, body).text


def test_forgot_password_answers_identically_for_any_account(client):
    response = client.post("/v1/auth/forgot-password", json={"email": "nobody@x.com"})
    assert response.json() == {"message": "Reset email sent"}


def test_the_old_2fa_routes_no_longer_exist(client):
    """Anciennes routes cassées : elles ne doivent plus répondre du tout."""
    assert client.post("/v1/auth/2fa/verify-login").status_code == 404
    assert client.get("/v1/auth/2fa/recovery-codes").status_code == 405


def test_production_refuses_to_boot_with_token_exposure_enabled():
    with pytest.raises(ValueError, match="DEV_EXPOSE_AUTH_TOKENS"):
        Settings(
            ENVIRONMENT="production",
            DEBUG=False,
            SECRET_KEY="x" * 40,
            ALLOW_ORIGINS="https://app.example.com",
            SKIP_DB_INIT=True,
            EASYTRANSACT_API_BASE_URL="https://api.example.com",
            EASYTRANSACT_API_TOKEN="t",
            EASYTRANSACT_WEBHOOK_SECRET="s",
            DEV_EXPOSE_AUTH_TOKENS=True,
        )
