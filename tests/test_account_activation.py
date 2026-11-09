"""Activation du compte par code à 6 chiffres reçu par email (valable 15 minutes).

Sans base de données : dépôt utilisateur factice en mémoire, vraie session SQLAlchemy sans
connexion (l'email part au commit, comme en production), boîte mémoire pour les emails.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.user import User
from app.services import auth_service as auth_module
from app.services import email_service, email_templates

PASSWORD = "MotDePasseFort123!"
EMAIL = "awa@example.com"
PHONE = "+237670000000"


class FakeUsers:
    """Dépôt en mémoire avec la surface utilisée par AuthService."""

    def __init__(self):
        self.users = []

    def get_by_email(self, email):
        return next((u for u in self.users if u.email == email), None)

    def get_by_phone(self, phone):
        return next((u for u in self.users if u.phone == phone), None)

    def phone_exists(self, phone):
        return self.get_by_phone(phone) is not None

    def create(self, values):
        now = datetime.now(timezone.utc)
        # Les valeurs par défaut (id, dates, drapeaux) viennent de PostgreSQL en production.
        user = User(
            id=uuid.uuid4(),
            is_active=True,
            is_deleted=False,
            activation_code_attempts=0,
            created_at=now,
            updated_at=now,
            **values,
        )
        self.users.append(user)
        return user

    def update(self, user, values):
        for key, value in values.items():
            setattr(user, key, value)
        return user


class FakeRefresh:
    def create(self, values):
        return values


@pytest.fixture
def users(monkeypatch):
    store = FakeUsers()
    monkeypatch.setattr(auth_module, "UserRepository", lambda db: store)
    monkeypatch.setattr(auth_module, "RefreshTokenRepository", lambda db: FakeRefresh())
    # bcrypt n'est pas l'objet de ces tests (et est lent).
    monkeypatch.setattr(auth_module.AuthService, "get_password_hash", lambda self, p: f"h:{p}")
    monkeypatch.setattr(
        auth_module.AuthService, "verify_password", lambda self, p, hashed: hashed == f"h:{p}"
    )
    email_service.OUTBOX.clear()
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    yield store
    email_service.OUTBOX.clear()


@pytest.fixture
def client(users):
    def fake_get_db():
        db = Session()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = fake_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def register(client, email=EMAIL, phone=PHONE, password=PASSWORD, first="Awa"):
    return client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "phone": phone,
            "password": password,
            "first_name": first,
            "last_name": "Mballa",
            "role": "restaurant",
        },
    )


def mails_to(email):
    return [m for m in email_service.OUTBOX if m.to == email]


def last_code(email=EMAIL):
    mail = mails_to(email)[-1]
    return re.search(r"Code : (\d{6})", mail.text).group(1)


def activate(client, code, email=EMAIL):
    return client.post("/v1/auth/activate", json={"email": email, "code": code})


def wrong_code(real):
    return "000000" if real != "000000" else "111111"


def login(client, email=EMAIL, password=PASSWORD):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


# --------------------------------------------------------------------------- inscription


class TestRegistration:
    def test_creates_an_inactive_account_and_sends_one_email(self, client, users):
        response = register(client)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["activation_required"] is True
        assert body["email_verified_at"] is None
        assert body["activation_expires_in_seconds"] == 15 * 60
        assert body["resend_available_in_seconds"] == settings.ACTIVATION_CODE_RESEND_SECONDS
        assert len(mails_to(EMAIL)) == 1

    def test_the_code_is_six_digits_and_never_in_the_response(self, client, users):
        response = register(client)
        code = last_code()
        assert re.fullmatch(r"\d{6}", code)
        assert code not in response.text
        assert body_has_no_code(response.json())

    def test_the_code_is_stored_hashed_not_in_clear(self, client, users):
        register(client)
        code = last_code()
        user = users.get_by_email(EMAIL)
        assert user.activation_code_hash and code not in user.activation_code_hash
        assert len(user.activation_code_hash) == 64

    def test_the_code_is_valid_fifteen_minutes(self, client, users):
        register(client)
        user = users.get_by_email(EMAIL)
        lifetime = user.activation_code_expires_at - user.activation_code_sent_at
        assert lifetime == timedelta(minutes=15)

    def test_no_email_is_sent_when_the_registration_is_refused(self, client, users):
        register(client)
        activate(client, last_code())
        email_service.OUTBOX.clear()
        assert register(client).status_code == 409  # déjà activé
        assert not mails_to(EMAIL)

    def test_an_already_used_phone_is_a_conflict(self, client, users):
        register(client)
        other = register(client, email="autre@example.com")
        assert other.status_code == 409
        assert not mails_to("autre@example.com")


# --------------------------------------------------------------------------- l'email


class TestActivationEmail:
    def test_subject_code_validity_and_link(self, client, users):
        register(client)
        mail = mails_to(EMAIL)[0]
        code = last_code()
        assert mail.subject == "Votre code d'activation Marinade"
        assert code in mail.text and code in mail.html
        assert "15 minutes" in mail.text and "15 minutes" in mail.html
        assert f"/activate-account?email=awa%40example.com" in mail.text
        assert "Awa" in mail.text
        assert "ne vous le demandera jamais" in mail.text

    def test_english_version(self):
        mail = email_templates.build(
            "activation_code", {"first_name": "Awa", "code": "482913", "email": EMAIL}, "en"
        )
        assert mail.subject == "Your Marinade activation code"
        assert "482913" in mail.text and "15 minutes" in mail.text

    def test_code_is_not_in_the_subject(self):
        mail = email_templates.build("activation_code", {"code": "482913"}, "fr")
        assert "482913" not in mail.subject

    def test_html_is_escaped_for_the_name(self):
        mail = email_templates.build(
            "activation_code", {"first_name": "<b>x</b>", "code": "123456"}, "fr"
        )
        assert "<b>x</b>" not in mail.html


# --------------------------------------------------------------------------- activation


class TestActivation:
    def test_good_code_activates_and_opens_a_session(self, client, users):
        register(client)
        response = activate(client, last_code())
        assert response.status_code == 200, response.text
        assert response.json()["access_token"] and response.json()["refresh_token"]
        user = users.get_by_email(EMAIL)
        assert user.email_verified_at is not None
        assert user.activation_code_hash is None

    def test_a_welcome_email_follows_the_activation(self, client, users):
        register(client)
        activate(client, last_code())
        assert "Bienvenue" in mails_to(EMAIL)[-1].subject

    def test_the_code_works_only_once(self, client, users):
        register(client)
        code = last_code()
        assert activate(client, code).status_code == 200
        again = activate(client, code)
        assert again.status_code == 400
        assert again.json()["code"] == "auth.activation_code_invalid"

    def test_spaces_in_the_code_are_tolerated(self, client, users):
        register(client)
        code = last_code()
        assert activate(client, f"{code[:3]} {code[3:]}").status_code == 200

    def test_wrong_code_counts_down_the_attempts(self, client, users):
        register(client)
        bad = wrong_code(last_code())
        first = activate(client, bad)
        assert first.status_code == 400
        assert first.json()["code"] == "auth.activation_code_invalid"
        assert first.json()["details"]["attempts_left"] == settings.ACTIVATION_CODE_MAX_ATTEMPTS - 1
        second = activate(client, bad)
        assert second.json()["details"]["attempts_left"] == settings.ACTIVATION_CODE_MAX_ATTEMPTS - 2

    def test_the_attempt_counter_survives_the_failed_request(self, client, users):
        register(client)
        activate(client, wrong_code(last_code()))
        assert users.get_by_email(EMAIL).activation_code_attempts == 1

    def test_too_many_wrong_codes_invalidate_the_code_even_for_the_right_one(self, client, users):
        register(client)
        real = last_code()
        bad = wrong_code(real)
        for _ in range(settings.ACTIVATION_CODE_MAX_ATTEMPTS - 1):
            assert activate(client, bad).json()["code"] == "auth.activation_code_invalid"
        last = activate(client, bad)
        assert last.json()["code"] == "auth.activation_too_many_attempts"
        # Le bon code ne fonctionne plus : il faut en demander un nouveau.
        assert activate(client, real).status_code == 400
        assert users.get_by_email(EMAIL).email_verified_at is None

    def test_an_expired_code_is_refused(self, client, users):
        register(client)
        real = last_code()
        user = users.get_by_email(EMAIL)
        user.activation_code_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        response = activate(client, real)
        assert response.status_code == 400
        assert response.json()["code"] == "auth.activation_code_expired"
        assert users.get_by_email(EMAIL).email_verified_at is None

    def test_a_code_just_under_fifteen_minutes_still_works(self, client, users):
        register(client)
        real = last_code()
        user = users.get_by_email(EMAIL)
        user.activation_code_expires_at = datetime.now(timezone.utc) + timedelta(seconds=5)
        assert activate(client, real).status_code == 200

    def test_unknown_email_answers_like_a_wrong_code(self, client, users):
        response = activate(client, "123456", email="personne@example.com")
        assert response.status_code == 400
        assert response.json()["code"] == "auth.activation_code_invalid"
        assert "details" not in response.json()

    def test_a_code_is_bound_to_its_own_account(self):
        # Le même code chez deux comptes donne deux empreintes : on ne peut pas activer le
        # compte d'un autre avec son propre code.
        first, second = uuid.uuid4(), uuid.uuid4()
        assert auth_module._hash_activation_code(first, "123456") != auth_module._hash_activation_code(
            second, "123456"
        )


# --------------------------------------------------------------------------- compte déjà existant


class TestExistingPendingAccount:
    def test_registering_again_resends_instead_of_failing(self, client, users):
        register(client)
        user = users.get_by_email(EMAIL)
        user.activation_code_sent_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        again = register(client)
        assert again.status_code == 200, again.text
        assert again.json()["activation_required"] is True
        assert len(users.users) == 1
        assert len(mails_to(EMAIL)) == 2

    def test_the_new_code_replaces_the_old_one(self, client, users):
        register(client)
        first = last_code()
        users.get_by_email(EMAIL).activation_code_sent_at = datetime.now(timezone.utc) - timedelta(
            minutes=2
        )
        register(client)
        second = last_code()
        if first != second:
            assert activate(client, first).status_code == 400
        assert activate(client, second).status_code == 200

    def test_a_quick_second_registration_does_not_send_another_email(self, client, users):
        register(client)
        again = register(client)
        assert again.status_code == 200
        assert len(mails_to(EMAIL)) == 1
        assert 0 < again.json()["resend_available_in_seconds"] <= settings.ACTIVATION_CODE_RESEND_SECONDS

    def test_the_last_registration_decides_the_password(self, client, users):
        register(client, password="AncienMotDePasse123!")
        users.get_by_email(EMAIL).activation_code_sent_at = datetime.now(timezone.utc) - timedelta(
            minutes=2
        )
        register(client, password=PASSWORD)
        activate(client, last_code())
        assert login(client, password="AncienMotDePasse123!").status_code == 401
        assert login(client, password=PASSWORD).status_code == 200

    def test_the_phone_of_the_pending_account_can_change(self, client, users):
        register(client)
        register(client, phone="+237680000000")
        assert users.get_by_email(EMAIL).phone == "+237680000000"

    def test_a_phone_used_by_someone_else_is_still_a_conflict(self, client, users):
        register(client)
        register(client, email="b@example.com", phone="+237671111111")
        clash = register(client, phone="+237671111111")
        assert clash.status_code == 409

    def test_an_activated_account_is_a_conflict_not_a_resend(self, client, users):
        register(client)
        activate(client, last_code())
        assert register(client).status_code == 409


# --------------------------------------------------------------------------- connexion


class TestLoginBeforeActivation:
    def test_login_is_refused_and_points_to_the_activation_page(self, client, users):
        register(client)
        response = login(client)
        assert response.status_code == 401
        body = response.json()
        assert body["code"] == "auth.activation_required"
        assert body["details"]["activation_required"] is True
        assert body["details"]["email"] == EMAIL

    def test_a_wrong_password_never_reveals_the_pending_state(self, client, users):
        register(client)
        response = login(client, password="MauvaisMotDePasse123!")
        assert response.status_code == 401
        assert response.json()["code"] != "auth.activation_required"

    def test_login_with_an_expired_code_sends_a_fresh_one(self, client, users):
        register(client)
        user = users.get_by_email(EMAIL)
        user.activation_code_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        user.activation_code_sent_at = datetime.now(timezone.utc) - timedelta(minutes=16)
        before = len(mails_to(EMAIL))
        assert login(client).json()["code"] == "auth.activation_required"
        assert len(mails_to(EMAIL)) == before + 1
        assert activate(client, last_code()).status_code == 200

    def test_login_within_a_minute_does_not_spam_the_mailbox(self, client, users):
        register(client)
        before = len(mails_to(EMAIL))
        login(client)
        login(client)
        assert len(mails_to(EMAIL)) == before

    def test_login_works_after_activation(self, client, users):
        register(client)
        activate(client, last_code())
        assert login(client).status_code == 200

    def test_accounts_created_by_an_admin_are_active(self):
        from app.services.user_service import UserService

        captured = {}

        class Repo:
            def email_exists(self, email):
                return False

            def phone_exists(self, phone):
                return False

            def create(self, values):
                captured.update(values)
                return values

        service = UserService.__new__(UserService)
        service.user_repo = Repo()
        from app.schemas.user import UserCreate

        service.create_user(
            UserCreate(
                email="a@example.com", phone=PHONE, password=PASSWORD,
                first_name="A", last_name="B", role="pos",
            )
        )
        assert captured["email_verified_at"] is not None


# --------------------------------------------------------------------------- renvoi


class TestResend:
    def test_resend_sends_a_new_code_after_the_delay(self, client, users):
        register(client)
        users.get_by_email(EMAIL).activation_code_sent_at = datetime.now(timezone.utc) - timedelta(
            minutes=2
        )
        response = client.post("/v1/auth/resend-activation", json={"email": EMAIL})
        assert response.status_code == 200
        assert len(mails_to(EMAIL)) == 2
        assert activate(client, last_code()).status_code == 200

    def test_resend_within_the_delay_sends_nothing(self, client, users):
        register(client)
        client.post("/v1/auth/resend-activation", json={"email": EMAIL})
        assert len(mails_to(EMAIL)) == 1

    def test_the_answer_is_identical_for_unknown_and_activated_accounts(self, client, users):
        register(client)
        activate(client, last_code())
        email_service.OUTBOX.clear()
        known = client.post("/v1/auth/resend-activation", json={"email": EMAIL})
        unknown = client.post("/v1/auth/resend-activation", json={"email": "x@example.com"})
        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        assert not email_service.OUTBOX

    def test_resend_resets_the_attempt_counter(self, client, users):
        register(client)
        activate(client, wrong_code(last_code()))
        users.get_by_email(EMAIL).activation_code_sent_at = datetime.now(timezone.utc) - timedelta(
            minutes=2
        )
        client.post("/v1/auth/resend-activation", json={"email": EMAIL})
        assert users.get_by_email(EMAIL).activation_code_attempts == 0


def body_has_no_code(body):
    return "activation_code" not in body or body["activation_code"] is None


def test_dev_flag_exposes_the_code_only_when_enabled(client, users, monkeypatch):
    monkeypatch.setattr(settings, "DEV_EXPOSE_AUTH_TOKENS", True)
    response = register(client)
    assert response.json()["activation_code"] == last_code()
