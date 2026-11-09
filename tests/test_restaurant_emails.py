"""Emails du restaurant : envoi après commit, contenu client / propriétaire, et déclenchement
réel par l'API (réservations, reçu de commande, clôture de caisse).

La première partie n'a besoin d'aucune base ; la seconde (PostgreSQL) suit les règles de
conftest : elle s'ignore sans ``TEST_DATABASE_URL``.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.restaurant import Restaurant, Table
from app.models.ros import RosCustomer, RosOrder, RosOrderItem
from app.models.user import User
from app.services import email_service, email_templates, restaurant_emails


@pytest.fixture(autouse=True)
def boite_vide(monkeypatch):
    email_service.OUTBOX.clear()
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    yield
    email_service.OUTBOX.clear()


# --------------------------------------------------------------------------- après commit


class TestSendAfterCommit:
    @pytest.fixture
    def db(self):
        engine = create_engine("sqlite://")
        with Session(engine) as session:
            yield session

    def _queue(self, db, to="a@example.com"):
        email_templates.send_after_commit(db, "welcome", to, {"first_name": "Jean"}, "fr")

    def test_nothing_is_sent_before_the_commit(self, db):
        self._queue(db)
        assert email_service.OUTBOX == []
        db.commit()
        assert [m.to for m in email_service.OUTBOX] == ["a@example.com"]

    def test_rollback_drops_the_email(self, db):
        db.execute(text("select 1"))  # une vraie transaction est ouverte, comme dans une requête
        self._queue(db)
        db.rollback()
        db.commit()
        assert email_service.OUTBOX == []

    def test_a_savepoint_rollback_keeps_the_email(self, db):
        db.execute(text("select 1"))
        self._queue(db)
        nested = db.begin_nested()
        nested.rollback()
        db.commit()
        assert len(email_service.OUTBOX) == 1

    def test_one_email_per_queue_even_over_several_commits(self, db):
        self._queue(db)
        db.commit()
        db.commit()
        assert len(email_service.OUTBOX) == 1

    def test_each_queued_email_is_sent_once(self, db):
        self._queue(db, "a@example.com")
        self._queue(db, "b@example.com")
        db.commit()
        assert sorted(m.to for m in email_service.OUTBOX) == ["a@example.com", "b@example.com"]

    def test_a_bad_template_never_raises(self, db):
        email_templates.send_after_commit(db, "inconnu", "a@example.com", {}, "fr")
        db.commit()
        assert email_service.OUTBOX == []


# --------------------------------------------------------------------------- contenu


RID = uuid.uuid4()
RESTAURANT = SimpleNamespace(id=RID, name="Le Grand Maquis", currency="XAF", user_id=uuid.uuid4())


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self.rows


class FakeDB:
    """Juste ce que lisent les notifications : ``get`` par classe et la liste des lignes."""

    def __init__(self, objects=None, items=()):
        self.objects, self.items = objects or {}, list(items)
        self.commit_hooks = []

    def get(self, model, ident):
        return self.objects.get((model, ident))

    def query(self, model):
        return FakeQuery(self.items)


def _commit(monkeypatch):
    """Envoie immédiatement : la file « après commit » est testée ci-dessus."""
    monkeypatch.setattr(
        email_templates,
        "send_after_commit",
        lambda db, name, to, data, lang="fr": email_templates.send(
            name, to, data, lang, background=False
        ),
    )


def _reservation(**kw):
    base = dict(
        id=uuid.uuid4(), restaurant_id=RID, table_id=None, customer_name="Mme Ngo",
        customer_email="ngo@example.com", party_size=4,
        # 19:00 UTC = 20:00 à Douala (UTC+1)
        reservation_date=datetime(2026, 11, 14, 19, 0, tzinfo=timezone.utc),
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestReservationEmails:
    def db(self, table=None):
        objs = {(Restaurant, RID): RESTAURANT}
        if table:
            objs[(Table, table.id)] = table
        return FakeDB(objs)

    @pytest.mark.parametrize(
        "kind,mot", [("pending", "attente"), ("confirmed", "confirmée"), ("cancelled", "annulée")]
    )
    def test_each_state_has_its_email(self, monkeypatch, kind, mot):
        _commit(monkeypatch)
        restaurant_emails.notify_reservation(self.db(), _reservation(), kind)
        mail = email_service.OUTBOX[0]
        assert mail.to == "ngo@example.com" and mot in mail.subject.lower()
        assert "Le Grand Maquis" in mail.subject

    def test_time_and_date_are_in_the_restaurant_timezone(self, monkeypatch):
        _commit(monkeypatch)
        restaurant_emails.notify_reservation(self.db(), _reservation(), "confirmed")
        text = email_service.OUTBOX[0].text
        assert "20:00" in text and "samedi 14 novembre 2026" in text

    def test_table_number_is_shown(self, monkeypatch):
        _commit(monkeypatch)
        table = SimpleNamespace(id=uuid.uuid4(), numero="T7")
        restaurant_emails.notify_reservation(
            self.db(table), _reservation(table_id=table.id), "confirmed"
        )
        assert "T7" in email_service.OUTBOX[0].text

    def test_no_customer_email_no_mail(self, monkeypatch):
        _commit(monkeypatch)
        for empty in (None, "", "   "):
            restaurant_emails.notify_reservation(
                self.db(), _reservation(customer_email=empty), "confirmed"
            )
        assert email_service.OUTBOX == []

    def test_a_missing_restaurant_never_raises(self, monkeypatch):
        _commit(monkeypatch)
        restaurant_emails.notify_reservation(FakeDB(), _reservation(), "confirmed")
        assert email_service.OUTBOX == []

    def test_english_restaurant_gets_english_mail(self, monkeypatch):
        _commit(monkeypatch)
        en = SimpleNamespace(**{**RESTAURANT.__dict__, "locale": "en"})
        db = FakeDB({(Restaurant, RID): en})
        restaurant_emails.notify_reservation(db, _reservation(), "confirmed")
        assert "Reservation confirmed" in email_service.OUTBOX[0].subject
        assert "Saturday, November 14, 2026" in email_service.OUTBOX[0].text


class TestReceiptEmail:
    def setup_objects(self, email="ngo@example.com", service=0, tax=0):
        order = SimpleNamespace(id=uuid.uuid4(), customer_id=uuid.uuid4())
        customer = SimpleNamespace(id=order.customer_id, name="Mme Ngo", email=email)
        invoice = SimpleNamespace(
            order_id=order.id, restaurant_id=RID, invoice_number="FAC-0042",
            service_charge=Decimal(service), tax_amount=Decimal(tax), total_amount=Decimal("9500.00"),
        )
        items = [
            SimpleNamespace(product_name="Ndolé", quantity=2, unit_price=Decimal("3500.00")),
            SimpleNamespace(product_name="Jus", quantity=1, unit_price=Decimal("2500.00")),
        ]
        db = FakeDB(
            {(Restaurant, RID): RESTAURANT, (RosOrder, order.id): order,
             (RosCustomer, customer.id): customer},
            items,
        )
        return db, invoice

    def test_receipt_lists_lines_total_and_method(self, monkeypatch):
        _commit(monkeypatch)
        db, invoice = self.setup_objects()
        restaurant_emails.notify_receipt(db, invoice, "ORANGE_MONEY")
        mail = email_service.OUTBOX[0]
        assert mail.to == "ngo@example.com" and "FAC-0042" in mail.subject
        assert "Ndolé x2" in mail.text and "Orange Money" in mail.text
        assert "9 500" in mail.text

    def test_service_and_tax_lines_only_when_charged(self, monkeypatch):
        _commit(monkeypatch)
        db, invoice = self.setup_objects(service=500, tax=300)
        restaurant_emails.notify_receipt(db, invoice, "CASH")
        text = email_service.OUTBOX[0].text
        assert "Service" in text and "TVA" in text
        email_service.OUTBOX.clear()
        db, invoice = self.setup_objects()
        restaurant_emails.notify_receipt(db, invoice, "CASH")
        assert "TVA" not in email_service.OUTBOX[0].text

    def test_customer_without_email_gets_nothing(self, monkeypatch):
        _commit(monkeypatch)
        db, invoice = self.setup_objects(email=None)
        restaurant_emails.notify_receipt(db, invoice, "CASH")
        assert email_service.OUTBOX == []

    def test_order_without_customer_gets_nothing(self, monkeypatch):
        _commit(monkeypatch)
        db, invoice = self.setup_objects()
        invoice.order_id = None
        restaurant_emails.notify_receipt(db, invoice, "CASH")
        assert email_service.OUTBOX == []


class TestShiftClosedEmail:
    def run(self, monkeypatch, variance, owner_active=True):
        _commit(monkeypatch)
        owner = SimpleNamespace(
            id=RESTAURANT.user_id, email="patron@example.com", first_name="Brice",
            last_name="N", is_active=owner_active,
        )
        cashier = SimpleNamespace(id=uuid.uuid4(), first_name="Aïcha", last_name="Mbarga")
        db = FakeDB({(Restaurant, RID): RESTAURANT, (User, owner.id): owner, (User, cashier.id): cashier})
        shift = SimpleNamespace(
            restaurant_id=RID, operator_user_id=cashier.id,
            opened_at=datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc),
            closed_at=datetime(2026, 11, 6, 21, 15, tzinfo=timezone.utc),
            opening_balance=Decimal("20000"), closing_balance_expected=Decimal("148500"),
            closing_balance_counted=Decimal("148500") + Decimal(variance), variance=Decimal(variance),
        )
        summary = {
            "payments_by_method": {
                "CASH": {"count": 3, "total": Decimal("128500")},
                "ORANGE_MONEY": {"count": 2, "total": Decimal("64000")},
            },
            "payments_total": Decimal("192500"),
        }
        restaurant_emails.notify_shift_closed(db, shift, summary)

    def test_owner_gets_the_summary(self, monkeypatch):
        self.run(monkeypatch, 0)
        mail = email_service.OUTBOX[0]
        assert mail.to == "patron@example.com" and "Clôture de caisse" in mail.subject
        assert "Aïcha Mbarga" in mail.text and "Orange Money" in mail.text
        assert "192 500" in mail.text and "Caisse juste" in mail.text
        assert "10:00" in mail.text  # 09:00 UTC = 10:00 à Douala

    def test_shortage_and_surplus_are_flagged(self, monkeypatch):
        self.run(monkeypatch, -1500)
        assert "Manquant" in email_service.OUTBOX[0].text
        email_service.OUTBOX.clear()
        self.run(monkeypatch, 1500)
        assert "Excédent" in email_service.OUTBOX[0].text

    def test_inactive_owner_gets_nothing(self, monkeypatch):
        self.run(monkeypatch, 0, owner_active=False)
        assert email_service.OUTBOX == []


# --------------------------------------------------------------------------- API (PostgreSQL)


class TestThroughTheApi:
    @pytest.fixture
    def shop(self, client):
        from tests.support import headers_for, register

        user = register(client, "mailresto")
        headers = headers_for(client, user)
        created = client.post("/v1/restaurants", headers=headers, json={"name": "Chez Mail"})
        assert created.status_code == 201, created.text
        email_service.OUTBOX.clear()  # l'email de bienvenue de l'inscription
        return {**user, "headers": headers, "rid": created.json()["id"]}

    def _book(self, client, shop, **extra):
        when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        payload = {"customer_name": "Mme Ngo", "party_size": 2, "reservation_date": when, **extra}
        return client.post(
            f"/v1/reservations/restaurants/{shop['rid']}/reservations",
            headers=shop["headers"], json=payload,
        )

    def test_reservation_life_cycle_emails_the_customer(self, client, shop):
        res = self._book(client, shop, customer_email="ngo@example.com")
        assert res.status_code == 201, res.text
        rid = res.json()["id"]
        assert [("attente" in m.subject.lower()) for m in email_service.OUTBOX] == [True]

        client.post(f"/v1/reservations/{rid}/confirm", headers=shop["headers"], json={})
        client.post(f"/v1/reservations/{rid}/confirm", headers=shop["headers"], json={})
        client.post(f"/v1/reservations/{rid}/cancel", headers=shop["headers"], json={"reason": "Imprévu"})
        subjects = [m.subject.lower() for m in email_service.OUTBOX]
        assert len(subjects) == 3, "une confirmation répétée ne renvoie pas d'email"
        assert "confirmée" in subjects[1] and "annulée" in subjects[2]
        assert all(m.to == "ngo@example.com" for m in email_service.OUTBOX)

    def test_no_email_without_a_customer_address(self, client, shop):
        assert self._book(client, shop).status_code == 201
        assert email_service.OUTBOX == []

    def test_a_refused_reservation_sends_nothing(self, client, shop):
        res = self._book(client, shop, customer_email="ngo@example.com", table_id=str(uuid.uuid4()))
        assert res.status_code >= 400
        assert email_service.OUTBOX == []

    def test_paid_order_emails_the_receipt_once_settled(self, client, shop):
        rid, h = shop["rid"], shop["headers"]
        customer = client.post(
            f"/v1/ros/restaurants/{rid}/customers", headers=h,
            json={"name": "Mme Ngo", "email": "ngo@example.com"},
        )
        assert customer.status_code == 201, customer.text
        order = client.post(
            f"/v1/ros/restaurants/{rid}/orders", headers=h,
            json={
                "fulfillment_type": "COUNTER", "customer_id": customer.json()["id"],
                "items": [{"product_name": "Ndolé", "quantity": 1, "unit_price": 3000, "tax_rate": 0}],
            },
        ).json()

        def pay(amount, method):
            return client.post(
                f"/v1/ros/restaurants/{rid}/payments", headers=h,
                json={"invoice_id": order["invoice_id"], "payment_method": method, "amount": amount},
            )

        assert pay(1000, "CASH").status_code == 201
        assert email_service.OUTBOX == [], "pas de reçu tant que la facture n'est pas soldée"
        assert pay(2000, "ORANGE_MONEY").status_code == 201
        assert len(email_service.OUTBOX) == 1
        mail = email_service.OUTBOX[0]
        assert mail.to == "ngo@example.com" and "Ndolé" in mail.text

    def test_closing_the_cash_shift_emails_the_owner(self, client, shop):
        rid, h = shop["rid"], shop["headers"]
        assert client.post(
            f"/v1/ros/restaurants/{rid}/shifts/open", headers=h, json={"opening_balance": 5000}
        ).status_code == 201
        closed = client.post(
            f"/v1/ros/restaurants/{rid}/shifts/close", headers=h, json={"closing_balance_counted": 4000}
        )
        assert closed.status_code == 200, closed.text
        assert [m.to for m in email_service.OUTBOX] == [shop["email"]]
        assert "Manquant" in email_service.OUTBOX[0].text
