"""Une commande ROS doit pouvoir être encaissée depuis l'API seule.

Avant : la réponse d'une commande ne contenait pas l'identifiant de sa facture,
et aucune route ne permettait de la consulter, alors que /payments l'exige.
Sans base de données : dépôts factices.
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.ros import RosInvoice
from app.schemas.ros import InvoiceResponse, OrderResponse
from app.services.ros_service import RosService
from app.utils.exceptions import NotFoundError

MINE = uuid.uuid4()
OTHER = uuid.uuid4()


def test_amount_due_does_not_crash_on_a_fresh_invoice():
    """Régression : `Decimal` n'était pas importé dans le modèle."""
    assert RosInvoice(total_amount=None, amount_paid=None).amount_due == Decimal("0.00")


def test_amount_due_is_total_minus_paid():
    invoice = RosInvoice(total_amount=Decimal("8347.50"), amount_paid=Decimal("5000"))
    assert invoice.amount_due == Decimal("3347.50")


class _InvoiceRepo:
    def __init__(self, by_id=None, by_session=None, by_order=None):
        self._by_id, self._by_session, self._by_order = by_id, by_session, by_order

    def get(self, _id):
        return self._by_id

    def get_by_session(self, _id):
        return self._by_session

    def get_by_order(self, _id):
        return self._by_order


def _service(**kwargs):
    svc = RosService.__new__(RosService)
    svc.invoice_repo = _InvoiceRepo(**kwargs)
    return svc


def _invoice(restaurant_id=MINE):
    return SimpleNamespace(id=uuid.uuid4(), restaurant_id=restaurant_id)


class TestInvoiceForOrder:
    def test_session_order_returns_the_shared_session_invoice(self):
        shared = _invoice()
        order = SimpleNamespace(id=uuid.uuid4(), session_id=uuid.uuid4())
        assert _service(by_session=shared).get_invoice_for_order(order) is shared

    def test_order_without_session_returns_its_own_invoice(self):
        own = _invoice()
        order = SimpleNamespace(id=uuid.uuid4(), session_id=None)
        assert _service(by_order=own).get_invoice_for_order(order) is own


class TestGetInvoice:
    def test_returns_my_invoice(self):
        invoice = _invoice()
        assert _service(by_id=invoice).get_invoice(MINE, invoice.id) is invoice

    def test_another_restaurants_invoice_is_not_found(self):
        foreign = _invoice(OTHER)
        with pytest.raises(NotFoundError):
            _service(by_id=foreign).get_invoice(MINE, foreign.id)

    def test_unknown_invoice_is_not_found(self):
        with pytest.raises(NotFoundError):
            _service(by_id=None).get_invoice(MINE, uuid.uuid4())

    def test_session_invoice_of_another_restaurant_is_not_found(self):
        with pytest.raises(NotFoundError):
            _service(by_session=_invoice(OTHER)).get_session_invoice(MINE, uuid.uuid4())


def test_order_response_carries_the_invoice_reference():
    fields = OrderResponse.model_fields
    assert "invoice_id" in fields
    assert "invoice_number" in fields


def test_invoice_response_exposes_the_amount_still_due():
    assert "amount_due" in InvoiceResponse.model_fields
