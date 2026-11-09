"""Envoi d'emails : transport, gabarit, sécurité des en-têtes, parcours d'authentification
et point d'accès administrateur. Sans réseau ni base de données : SMTP est simulé."""

import smtplib
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.dependencies import get_current_user
from app.core.config import settings
from app.main import app
from app.models.user import User
from app.services import auth_emails, email_service, email_templates
from app.services.auth_service import AuthService


@pytest.fixture(autouse=True)
def boite_vide(monkeypatch):
    email_service.OUTBOX.clear()
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    yield
    email_service.OUTBOX.clear()


def _user(**kw):
    return User(
        id=uuid.uuid4(),
        email="gerant@example.com",
        phone="+237600000000",
        first_name="Jean",
        last_name="Test",
        role="restaurant",
        is_active=True,
        password_hash="x",
        **kw,
    )


class FakeSMTP:
    instances = []
    fail_times = 0
    error = smtplib.SMTPServerDisconnected("coupé")

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.calls = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        if FakeSMTP.fail_times > 0:
            FakeSMTP.fail_times -= 1
            raise FakeSMTP.error
        self.calls.append(("send", msg))


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.fail_times = [], 0
    FakeSMTP.error = smtplib.SMTPServerDisconnected("coupé")
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(settings, "SMTP_USERNAME", "app@gmail.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", SecretStr("abcd efgh ijkl mnop"))
    monkeypatch.setattr(settings, "EMAIL_FROM", "app@gmail.com")
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_service.time, "sleep", lambda s: None)
    return FakeSMTP


class TestTransport:
    def test_memory_backend_keeps_the_message(self):
        r = email_service.send_email("a@example.com", "Sujet", "texte", "<p>html</p>")
        assert r["success"] and r["backend"] == "memory"
        assert [m.to for m in email_service.OUTBOX] == ["a@example.com"]

    def test_auto_without_credentials_does_not_send(self, monkeypatch):
        monkeypatch.setattr(settings, "EMAIL_BACKEND", "auto")
        monkeypatch.setattr(settings, "SMTP_USERNAME", "")
        monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
        assert email_service.active_backend() == "console"

    def test_auto_with_credentials_uses_smtp(self, monkeypatch):
        monkeypatch.setattr(settings, "EMAIL_BACKEND", "auto")
        monkeypatch.setattr(settings, "SMTP_USERNAME", "app@gmail.com")
        monkeypatch.setattr(settings, "SMTP_PASSWORD", SecretStr("secret"))
        assert email_service.active_backend() == "smtp"

    def test_disabled_backend_reports_failure(self, monkeypatch):
        monkeypatch.setattr(settings, "EMAIL_BACKEND", "disabled")
        assert not email_service.send_email("a@example.com", "S", "t")["success"]

    def test_header_injection_is_refused(self):
        r = email_service.send_email("a@example.com\nBcc: x@evil.test", "S", "t")
        assert not r["success"] and not email_service.OUTBOX
        r = email_service.send_email("a@example.com", "Sujet\r\nBcc: x@evil.test", "t")
        assert not r["success"] and not email_service.OUTBOX


class TestSmtp:
    def test_starttls_login_and_send(self, smtp):
        r = email_service.send_email("a@example.com", "Sujet", "texte", "<p>h</p>")
        assert r["success"] and r["backend"] == "smtp"
        calls = smtp.instances[0].calls
        assert "starttls" in calls
        # les espaces du mot de passe d'application Google sont ignorés
        assert ("login", "app@gmail.com", "abcdefghijklmnop") in calls
        sent = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "send")
        assert sent["To"] == "a@example.com"
        assert "app@gmail.com" in sent["From"]
        assert sent.is_multipart()

    def test_transient_error_is_retried(self, smtp):
        smtp.fail_times = 2
        r = email_service.send_email("a@example.com", "S", "t")
        assert r["success"] and len(smtp.instances) == 3

    def test_gives_up_after_max_attempts(self, smtp):
        smtp.fail_times = 99
        r = email_service.send_email("a@example.com", "S", "t")
        assert not r["success"] and len(smtp.instances) == settings.SMTP_MAX_ATTEMPTS

    def test_refused_credentials_are_not_retried(self, smtp):
        smtp.fail_times = 99
        smtp.error = smtplib.SMTPAuthenticationError(535, b"bad")
        r = email_service.send_email("a@example.com", "S", "t")
        assert not r["success"] and len(smtp.instances) == 1

    def test_password_never_appears_in_error_or_logs(self, smtp, caplog):
        smtp.fail_times = 99
        smtp.error = smtplib.SMTPAuthenticationError(535, b"abcdefghijklmnop")
        with caplog.at_level("DEBUG"):
            r = email_service.send_email("a@example.com", "S", "t")
        assert "abcdefghijklmnop" not in str(r) + caplog.text

    def test_missing_credentials_with_smtp_backend_fails_cleanly(self, smtp, monkeypatch):
        monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
        r = email_service.send_email("a@example.com", "S", "t")
        assert not r["success"] and "SMTP" in r["error"]


class TestTemplate:
    def test_content_is_escaped_in_html(self):
        text, page = email_service.render_email(
            title="<script>alert(1)</script>",
            greeting="Bonjour <b>Jean</b>,",
            paragraphs=["a & b"],
            action_label="Go",
            action_url='https://x.test/?a="1"&b=2',
        )
        assert "<script>" not in page and "<b>Jean</b>" not in page
        assert "&amp;" in page and "&quot;" in page
        assert "a & b" in text  # le texte brut n'est pas échappé

    def test_link_points_to_the_frontend(self, monkeypatch):
        monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com/")
        url = email_service.frontend_url("/reset-password", token="a b+c")
        assert url == "https://app.example.com/reset-password?token=a%20b%2Bc"


class TestAuthFlows:
    def test_welcome_email(self):
        auth_emails.send_welcome(_user())
        m = email_service.OUTBOX[0]
        assert m.to == "gerant@example.com" and "Bienvenue" in m.subject
        assert "Jean" in m.text and "/login" in m.text

    def test_reset_email_carries_the_token_link(self):
        auth_emails.send_password_reset(_user(), "TOKEN123")
        m = email_service.OUTBOX[0]
        assert "/reset-password?token=TOKEN123" in m.text
        assert "/reset-password?token=TOKEN123" in m.html

    def test_english_for_english_locale(self):
        user = _user()
        user.locale = "en-GB"
        auth_emails.send_verification(user, "T")
        assert "Verify" in email_service.OUTBOX[0].subject

    def test_a_mail_failure_never_breaks_the_action(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("down")

        monkeypatch.setattr(email_templates.email_service, "send_email_async", boom)
        auth_emails.send_welcome(_user())  # ne lève pas

    def test_forgot_password_sends_one_email_to_known_user_and_none_otherwise(self):
        user = _user()

        class Repo:
            def get_by_email(self, email):
                return user if email == user.email else None

            def save_reset_token(self, *a):
                pass

        svc = AuthService.__new__(AuthService)
        svc.db, svc.user_repo = None, Repo()
        svc.forgot_password("inconnu@example.com")
        assert email_service.OUTBOX == []
        token = svc.forgot_password("gerant@example.com")
        assert len(email_service.OUTBOX) == 1
        assert f"token={token}" in email_service.OUTBOX[0].text


class TestAdminEndpoint:
    @pytest.fixture
    def http(self):
        yield TestClient(app)
        app.dependency_overrides.clear()

    def _as(self, role):
        user = _user()
        user.role = role
        app.dependency_overrides[get_current_user] = lambda: user

    def test_status_never_exposes_the_password(self, http):
        self._as("admin")
        r = http.get("/v1/emails/status")
        assert r.status_code == 200
        assert "smtp_password" not in r.text and "abcd" not in r.text
        assert r.json()["backend"] == "memory"
        assert "pressing_order" in r.json()["templates"]

    def test_test_email_goes_to_the_admin_by_default(self, http):
        self._as("admin")
        r = http.post("/v1/emails/test", json={})
        assert r.status_code == 200 and r.json()["success"]
        assert email_service.OUTBOX[0].to == "gerant@example.com"

    def test_preview_returns_html_and_sends_nothing(self, http):
        self._as("admin")
        r = http.get("/v1/emails/preview/pressing_order?lang=en")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert "Ready for pickup" in r.text and email_service.OUTBOX == []
        assert http.get("/v1/emails/preview/nope").status_code == 404

    def test_test_endpoint_can_send_any_template(self, http):
        self._as("admin")
        r = http.post("/v1/emails/test", json={"template": "reservation", "lang": "en"})
        assert r.status_code == 200 and "Reservation" in email_service.OUTBOX[0].subject

    def test_non_admin_is_refused(self, http):
        self._as("restaurant")
        assert http.post("/v1/emails/test", json={}).status_code == 403
        assert http.get("/v1/emails/status").status_code == 403
        assert email_service.OUTBOX == []


class TestTemplates:
    @pytest.mark.parametrize("name", sorted(email_templates.BUILDERS))
    @pytest.mark.parametrize("lang", ["fr", "en"])
    def test_every_template_renders_in_both_languages(self, name, lang):
        mail = email_templates.build(name, email_templates.SAMPLES[name], lang)
        assert mail.subject and mail.text and "<html" in mail.html
        assert f'lang="{lang}"' in mail.html
        assert "{" not in mail.subject and "None" not in mail.text

    def test_amounts_follow_the_currency_exponent(self):
        assert email_templates.montant(41870, "XAF") == "41 870"
        assert email_templates.montant(41870, "EUR", "en") == "418.70"

    def test_pressing_shows_balance_only_when_unpaid(self):
        data = dict(email_templates.SAMPLES["pressing_order"])
        assert "Reste à payer" in email_templates.build("pressing_order", data).text
        data["paid"] = data["total"]
        assert "Reste à payer" not in email_templates.build("pressing_order", data).text

    def test_customer_data_cannot_inject_html(self):
        data = dict(email_templates.SAMPLES["order_receipt"])
        data["restaurant"] = "<img src=x onerror=alert(1)>"
        data["lines"] = [("<script>x</script>", 100)]
        page = email_templates.build("order_receipt", data).html
        assert "<img" not in page and "<script>" not in page

    def test_unknown_template_is_an_error_but_send_never_raises(self):
        with pytest.raises(ValueError):
            email_templates.build("inconnu", {})
        assert email_templates.send("inconnu", "a@example.com", {}, background=False)["success"] is False

    def test_password_reset_notifies_the_user(self):
        user = _user()
        user.password_reset_token_hash = "h"
        user.password_reset_expires_at = None
        auth_emails.send_password_changed(user)
        assert "modifi" in email_service.OUTBOX[0].subject
