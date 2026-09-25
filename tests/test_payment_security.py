"""Tests des règles de sécurité des paiements et des webhooks Easy Transact.

Ces tests sont purement unitaires : ils ne touchent pas la base de données.
"""

import hashlib
import hmac
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.payment import CashPaymentCreate
from app.schemas.restaurant import CommandeCreate
from app.services.easy_transact_service import EasyTransactPaymentService
from app.utils.phone import MOBILE_OPERATORS, MobileOperator, normalize_cameroon_mobile


SECRET = "un-secret-de-test-long-suffisamment-long"


def _service() -> EasyTransactPaymentService:
    """Construit un service sans session : verify_webhook n'utilise pas self.db."""
    return EasyTransactPaymentService.__new__(EasyTransactPaymentService)


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class TestWebhookSignature:
    """Vérification HMAC de la signature des webhooks."""

    def test_valid_signature_is_accepted(self, monkeypatch):
        monkeypatch.setattr(
            settings, "EASYTRANSACT_WEBHOOK_SECRET", SECRET, raising=False
        )
        body = b'{"vendor_reference":"MRD-1"}'
        _service().verify_webhook(body, _sign(body))

    def test_sha256_prefix_is_accepted(self, monkeypatch):
        monkeypatch.setattr(
            settings, "EASYTRANSACT_WEBHOOK_SECRET", SECRET, raising=False
        )
        body = b'{"vendor_reference":"MRD-2"}'
        _service().verify_webhook(body, "sha256=" + _sign(body))

    def test_wrong_secret_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            settings, "EASYTRANSACT_WEBHOOK_SECRET", SECRET, raising=False
        )
        with pytest.raises(HTTPException) as exc:
            _service().verify_webhook(b"corps", _sign(b"corps", "autre-secret"))
        assert exc.value.status_code == 401

    def test_tampered_body_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            settings, "EASYTRANSACT_WEBHOOK_SECRET", SECRET, raising=False
        )
        with pytest.raises(HTTPException) as exc:
            _service().verify_webhook(b"corps-modifie", _sign(b"corps-originel"))
        assert exc.value.status_code == 401

    def test_missing_signature_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            settings, "EASYTRANSACT_WEBHOOK_SECRET", SECRET, raising=False
        )
        with pytest.raises(HTTPException) as exc:
            _service().verify_webhook(b"corps", None)
        assert exc.value.status_code == 401

    def test_missing_secret_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            settings, "EASYTRANSACT_WEBHOOK_SECRET", None, raising=False
        )
        with pytest.raises(HTTPException) as exc:
            _service().verify_webhook(b"corps", _sign(b"corps"))
        assert exc.value.status_code == 401

    def test_unsupported_algorithm_fails_closed(self, monkeypatch):
        monkeypatch.setattr(
            settings, "EASYTRANSACT_WEBHOOK_SECRET", SECRET, raising=False
        )
        monkeypatch.setattr(
            settings, "EASYTRANSACT_WEBHOOK_SIGNATURE_ALGORITHM", "md5", raising=False
        )
        with pytest.raises(HTTPException) as exc:
            _service().verify_webhook(b"corps", _sign(b"corps"))
        assert exc.value.status_code == 503


class TestCommandeCreateBoundary:
    """Le client ne doit jamais pouvoir imposer les montants d'une commande."""

    def test_client_supplied_total_is_rejected(self):
        with pytest.raises(ValidationError):
            CommandeCreate(total="1000")

    def test_client_supplied_service_rate_is_rejected(self):
        with pytest.raises(ValidationError):
            CommandeCreate(taux_service="50")

    def test_minimal_payload_is_accepted(self):
        commande = CommandeCreate()
        assert commande.statut == "en_cours"
        assert commande.table_id is None
        assert not hasattr(commande, "total")


class TestCashPaymentSchema:
    """Validation de la création d'un paiement cash."""

    def test_valid_payload(self):
        payload = CashPaymentCreate(
            restaurant_id=uuid.uuid4(),
            commande_id=uuid.uuid4(),
            amount_fcfa=5000,
            idempotency_key="cash-2026-0001",
            received_by=uuid.uuid4(),
        )
        assert payload.amount_fcfa == 5000

    def test_non_positive_amount_is_rejected(self):
        with pytest.raises(ValidationError):
            CashPaymentCreate(
                restaurant_id=uuid.uuid4(),
                commande_id=uuid.uuid4(),
                amount_fcfa=0,
                idempotency_key="cash-2026-0002",
                received_by=uuid.uuid4(),
            )

    def test_short_idempotency_key_is_rejected(self):
        with pytest.raises(ValidationError):
            CashPaymentCreate(
                restaurant_id=uuid.uuid4(),
                commande_id=uuid.uuid4(),
                amount_fcfa=100,
                idempotency_key="court",
                received_by=uuid.uuid4(),
            )

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError):
            CashPaymentCreate(
                restaurant_id=uuid.uuid4(),
                commande_id=uuid.uuid4(),
                amount_fcfa=100,
                idempotency_key="cash-2026-0003",
                received_by=uuid.uuid4(),
                statut="succes",
            )

    def test_idempotency_key_is_stripped(self):
        payload = CashPaymentCreate(
            restaurant_id=uuid.uuid4(),
            commande_id=uuid.uuid4(),
            amount_fcfa=100,
            idempotency_key="  cash-2026-0004  ",
            received_by=uuid.uuid4(),
        )
        assert payload.idempotency_key == "cash-2026-0004"


class TestOperatorPrefixResolution:
    """L'opérateur retenu doit être celui du plus long préfixe réellement trouvé."""

    def test_known_prefixes_map_to_expected_operator(self):
        cases = {
            "650123456": "MTN_CM",
            "655123456": "ORANGE_CM",
            "671234567": "MTN_CM",
            "691234567": "ORANGE_CM",
        }
        for national, expected in cases.items():
            _, operator = normalize_cameroon_mobile("+237" + national)
            assert operator.code == expected, national

    def test_longest_matching_prefix_wins(self):
        # A possède "69999" (ne matche pas) et "6" (matche) ; B matche "699",
        # plus long que "6" : B doit l'emporter.
        a = MobileOperator("A", "Opérateur A", ("6", "69999"))
        b = MobileOperator("B", "Opérateur B", ("699",))
        _, operator = normalize_cameroon_mobile("+237699123456", operators=(a, b))
        assert operator.code == "B"

    def test_unsupported_prefix_raises(self):
        with pytest.raises(ValueError, match="not supported"):
            normalize_cameroon_mobile("+237600000000")

    def test_non_mobile_number_raises(self):
        with pytest.raises(ValueError):
            normalize_cameroon_mobile("+237233123456")

    def test_foreign_country_is_rejected(self):
        with pytest.raises(ValueError, match="Cameroon"):
            normalize_cameroon_mobile("+33123456789")

    def test_default_operators_do_not_share_prefixes(self):
        prefixes = [
            prefix for operator in MOBILE_OPERATORS for prefix in operator.prefixes
        ]
        # Un préfixe partagé rendrait la résolution dépendante de l'ordre de
        # déclaration des opérateurs.
        assert len(set(prefixes)) == len(prefixes)
