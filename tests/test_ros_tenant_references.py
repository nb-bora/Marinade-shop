"""Le service ROS ne doit jamais accepter l'identifiant d'un AUTRE restaurant.

Une clé étrangère prouve qu'une ligne existe, pas qu'elle appartient à l'appelant.
Sans base de données : dépôts factices.
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.ros import OrderCreate, OrderItemCreate, PaymentCreate, SessionCreate
from app.services.ros_service import RosService
from app.utils.exceptions import ConflictError, ValidationError
from app.utils.ros_enums import RosPaymentMethod

MINE = uuid.uuid4()
OTHER = uuid.uuid4()


class _Repo:
    def __init__(self, row=None):
        self.row = row

    def get(self, _id):
        return self.row

    def get_by_idempotency_key(self, _key):
        return self.row


class _DB:
    def __init__(self, table=None):
        self.table = table

    def get(self, _model, _id):
        return self.table


def _service(session=None, customer=None, table=None, order=None, payment=None):
    svc = RosService.__new__(RosService)
    svc.db = _DB(table)
    svc.session_repo = _Repo(session)
    svc.customer_repo = _Repo(customer)
    svc.order_repo = _Repo(order)
    svc.payment_repo = _Repo(payment)
    return svc


def _row(restaurant_id):
    return SimpleNamespace(restaurant_id=restaurant_id)


def test_a_session_of_another_restaurant_is_refused():
    svc = _service(session=_row(OTHER))
    with pytest.raises(ValidationError, match="session"):
        svc._ensure_references_belong_to(MINE, session_id=uuid.uuid4())


def test_a_customer_of_another_restaurant_is_refused():
    svc = _service(customer=_row(OTHER))
    with pytest.raises(ValidationError, match="customer"):
        svc._ensure_references_belong_to(MINE, customer_id=uuid.uuid4())


def test_a_table_of_another_restaurant_is_refused():
    svc = _service(table=_row(OTHER))
    with pytest.raises(ValidationError, match="table"):
        svc._ensure_references_belong_to(MINE, table_id=uuid.uuid4())


def test_a_missing_reference_is_refused_like_a_foreign_one():
    with pytest.raises(ValidationError):
        _service(session=None)._ensure_references_belong_to(MINE, session_id=uuid.uuid4())


def test_own_references_and_absent_references_pass():
    svc = _service(session=_row(MINE), customer=_row(MINE), table=_row(MINE))
    svc._ensure_references_belong_to(
        MINE, session_id=uuid.uuid4(), customer_id=uuid.uuid4(), table_id=uuid.uuid4()
    )
    svc._ensure_references_belong_to(MINE)


def test_opening_a_session_on_a_foreign_table_is_refused():
    svc = _service(table=_row(OTHER))
    with pytest.raises(ValidationError, match="table"):
        svc.open_session(MINE, SessionCreate(table_id=uuid.uuid4()))


def _order(idempotency_key):
    return OrderCreate(
        idempotency_key=idempotency_key,
        items=[OrderItemCreate(product_name="Soda", quantity=1, unit_price=Decimal("500"))],
    )


def test_an_idempotency_key_used_by_another_restaurant_is_a_conflict_not_a_leak():
    """Sinon la commande (et ses montants) d'un autre restaurant serait renvoyée."""
    svc = _service(order=SimpleNamespace(restaurant_id=OTHER, total_amount=999))
    with pytest.raises(ConflictError):
        svc.create_order(MINE, _order(uuid.uuid4()))


def test_replaying_my_own_idempotency_key_returns_my_order():
    mine = SimpleNamespace(restaurant_id=MINE, total_amount=500)
    assert _service(order=mine).create_order(MINE, _order(uuid.uuid4())) is mine


def test_a_payment_key_used_by_another_restaurant_is_a_conflict():
    svc = _service(payment=SimpleNamespace(restaurant_id=OTHER))
    payment = PaymentCreate(
        invoice_id=uuid.uuid4(),
        payment_method=RosPaymentMethod.CASH,
        amount=Decimal("100"),
        idempotency_key=uuid.uuid4(),
    )
    with pytest.raises(ConflictError):
        svc.process_payment(MINE, payment)
