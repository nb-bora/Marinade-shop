"""Historique des transactions par restaurant : isolé, instantané, paginé.

Chaque restaurant a son préfixe de référence ; il ne voit que ses transactions, lues
dans la base de Marinade (pas chez la passerelle) ; un paiement confirmé par webhook
apparaît dans la liste dès la réponse du webhook.

Exige TEST_DATABASE_URL (voir tests/conftest.py).
"""

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.integrations.easy_transact import EasyTransactClient, EasyTransactError
from app.utils.payment_references import PREFIX_PATTERN, belongs_to_prefix
from tests.support import count_queries, headers_for, make_member, register, sql_as_platform_admin

BASE = "/v1/payments/easytransact"


# --------------------------------------------------------------------------- #
# Aides
# --------------------------------------------------------------------------- #
@pytest.fixture
def shop(client):
    user = register(client, "pay")
    headers = headers_for(client, user)
    response = client.post("/v1/restaurants", headers=headers, json={"name": "Maquis", "taux_service": 10})
    assert response.status_code == 201, response.text
    return {**user, "headers": headers, "rid": response.json()["id"]}


def configure(client, shop):
    response = client.put(f"{BASE}/configuration", headers=shop["headers"], json={"restaurant_id": shop["rid"]})
    assert response.status_code in (200, 201), response.text
    shop["prefix"] = response.json()["vendor_reference_prefix"]
    return response.json()


@pytest.fixture
def gateway(monkeypatch):
    """Passerelle simulée : un lien de paiement est « créé » sans réseau."""
    calls = []

    def fake_checkout(self, **kwargs):
        calls.append(kwargs)
        return {"checkout_url": f"https://pay.example/{kwargs['vendor_reference']}"}

    monkeypatch.setattr(EasyTransactClient, "create_checkout_link", fake_checkout)
    return calls


def checkout(client, shop, prix=1000):
    """Une vraie commande puis un vrai paiement (le total sert de montant)."""
    h, rid = shop["headers"], shop["rid"]
    plat = client.post(f"/v1/restaurants/{rid}/plats", headers=h, json={"nom": f"P{uuid.uuid4().hex[:4]}", "prix": prix}).json()["id"]
    commande = client.post(f"/v1/restaurants/{rid}/commandes", headers=h, json={}).json()["id"]
    client.post(f"/v1/restaurants/commandes/{commande}/items", headers=h, json={"plat_id": plat, "quantite": 1})
    total = int(float(client.get(f"/v1/restaurants/commandes/{commande}", headers=h).json()["total"]))
    response = client.post(
        f"{BASE}/checkout",
        headers=h,
        json={
            "restaurant_id": rid,
            "commande_id": commande,
            "amount_fcfa": total,
            "description": "Table 4",
            "idempotency_key": f"idem-{uuid.uuid4().hex}",
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json(), commande


def webhook(client, shop, reference, status="SUCCESS", **extra):
    body = json.dumps(
        {"vendor_reference": reference, "event_id": f"evt-{uuid.uuid4().hex}", "status": status, **extra}
    ).encode()
    signature = hmac.new(settings.EASYTRANSACT_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        f"{BASE}/webhook/{shop['rid']}",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )


def seed(engine, shop, rows):
    """Insère des transactions à des dates et statuts choisis (lignes brutes)."""
    ids = []
    for index, (age_minutes, status, amount, fees, inclusive) in enumerate(rows):
        row_id = str(uuid.uuid4())
        moment = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
        sql_as_platform_admin(
            engine,
            "insert into payment_intents (id, restaurant_id, provider, vendor_reference, idempotency_key,"
            " amount_fcfa, currency, status, fees_fcfa, fees_inclusive, created_at, completed_at)"
            " values (:id, :rid, 'easytransact', :ref, :idem, :amount, 'XAF', :status, :fees, :inc, :at, :done)",
            id=row_id,
            rid=shop["rid"],
            ref=f"{shop['prefix']}-{moment:%Y%m%d}-{uuid.uuid4().hex[:12].upper()}",
            idem=f"seed-{row_id}",
            amount=amount,
            status=status,
            fees=fees,
            inc=inclusive,
            at=moment,
            done=moment if status == "success" else None,
        )
        ids.append(row_id)
    return ids


def listing(client, shop, **params):
    response = client.get(f"{BASE}/transactions", headers=shop["headers"], params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Références propres à chaque restaurant
# --------------------------------------------------------------------------- #
class TestReferencesPerRestaurant:
    def test_each_restaurant_gets_a_unique_server_assigned_prefix(self, client, shop, stranger):
        first = configure(client, shop)["vendor_reference_prefix"]
        other = configure(client, stranger)["vendor_reference_prefix"]
        assert PREFIX_PATTERN.match(first) and PREFIX_PATTERN.match(other)
        assert first != other

    def test_the_prefix_is_immutable_and_cannot_be_chosen_by_the_client(self, client, shop):
        prefix = configure(client, shop)["vendor_reference_prefix"]
        again = client.put(
            f"{BASE}/configuration",
            headers=shop["headers"],
            json={"restaurant_id": shop["rid"], "vendor_reference_prefix": "MRD-AAAAAAAA", "service_code": "DEPOSIT"},
        )
        assert again.status_code == 200, again.text
        assert again.json()["vendor_reference_prefix"] == prefix

    def test_every_reference_carries_its_restaurants_prefix(self, client, shop, stranger, gateway):
        configure(client, shop)
        configure(client, stranger)
        mine, _ = checkout(client, shop)
        theirs, _ = checkout(client, stranger)
        refs = {i["vendor_reference"] for i in (mine, theirs)}
        assert len(refs) == 2
        assert gateway[0]["vendor_reference"] == mine["vendor_reference"], "c'est elle qu'on envoie à la passerelle"
        assert belongs_to_prefix(mine["vendor_reference"], shop["prefix"])
        assert belongs_to_prefix(theirs["vendor_reference"], stranger["prefix"])
        assert not belongs_to_prefix(mine["vendor_reference"], stranger["prefix"])


# --------------------------------------------------------------------------- #
# Lecture isolée et instantanée
# --------------------------------------------------------------------------- #
class TestHistory:
    def test_a_restaurant_only_sees_its_own_transactions(self, client, engine, shop, stranger):
        configure(client, shop)
        configure(client, stranger)
        seed(engine, shop, [(5, "success", 1000, None, None), (4, "failed", 2000, None, None)])
        seed(engine, stranger, [(3, "success", 9999, None, None)])
        mine = listing(client, shop)["items"]
        assert [t["amount_fcfa"] for t in mine] == [2000, 1000]
        assert all(belongs_to_prefix(t["reference"], shop["prefix"]) for t in mine)
        assert all(t["restaurant_id"] == shop["rid"] for t in mine)

    def test_another_restaurant_cannot_be_read_by_naming_it(self, client, shop, stranger):
        configure(client, shop)
        response = client.get(
            f"{BASE}/transactions", headers=stranger["headers"], params={"restaurant_id": shop["rid"]}
        )
        assert response.status_code == 404

    def test_a_confirmed_payment_is_visible_immediately(self, client, shop, gateway):
        configure(client, shop)
        intent, _commande = checkout(client, shop)
        assert listing(client, shop)["items"][0]["status"] == "initiated"
        assert webhook(client, shop, intent["vendor_reference"]).status_code == 200
        latest = listing(client, shop)["items"][0]
        assert latest["status"] == "success"
        assert latest["completed_at"] is not None

    def test_the_detail_shows_the_status_history(self, client, shop, gateway):
        configure(client, shop)
        intent, _ = checkout(client, shop)
        webhook(client, shop, intent["vendor_reference"], "PENDING")
        webhook(client, shop, intent["vendor_reference"], "SUCCESS")
        detail = client.get(f"{BASE}/transactions/{intent['id']}", headers=shop["headers"]).json()
        assert [e["status"] for e in detail["events"]] == ["pending", "success"]
        assert detail["checkout_url"].endswith(intent["vendor_reference"])

    def test_fees_net_amount_and_failure_reason_come_from_the_gateway(self, client, shop, gateway):
        configure(client, shop)
        paid, _ = checkout(client, shop, prix=1000)  # 1000 + 10 % de service = 1100
        webhook(
            client, shop, paid["vendor_reference"], "SUCCESS",
            fees="20", is_fees_inclusive=True, completed_at="2026-10-07T10:00:00Z", provider_transaction_id="TXN-9",
        )
        failed, _ = checkout(client, shop, prix=500)
        webhook(client, shop, failed["vendor_reference"], "FAILED", message="Le solde du compte du payeur est insuffisant")

        by_ref = {t["reference"]: t for t in listing(client, shop)["items"]}
        ok = by_ref[paid["vendor_reference"]]
        assert float(ok["fees_fcfa"]) == 20.0
        assert float(ok["net_amount_fcfa"]) == 1100 - 20
        assert ok["provider_transaction_id"] == "TXN-9"
        assert ok["completed_at"].startswith("2026-10-07T10:00:00")
        ko = by_ref[failed["vendor_reference"]]
        assert ko["status"] == "failed"
        assert ko["failure_reason"] == "Le solde du compte du payeur est insuffisant"
        assert ko["net_amount_fcfa"] is None

    def test_only_the_cash_desk_may_read_transactions(self, client, engine, shop):
        configure(client, shop)
        seed(engine, shop, [(1, "success", 100, None, None)])
        waiter = make_member(client, engine, shop, "waiter")
        cashier = make_member(client, engine, shop, "cashier")
        assert client.get(f"{BASE}/transactions", headers=waiter["headers"]).status_code == 403
        assert client.get(f"{BASE}/transactions", headers=cashier["headers"]).status_code == 200
        assert client.get(f"{BASE}/transactions/summary", headers=waiter["headers"]).status_code == 403

    def test_the_status_route_is_no_longer_open_to_the_floor_staff(self, client, engine, shop, gateway):
        configure(client, shop)
        intent, _ = checkout(client, shop)
        waiter = make_member(client, engine, shop, "waiter")
        assert client.get(f"{BASE}/{intent['id']}/status", headers=waiter["headers"]).status_code == 403
        assert client.get(f"{BASE}/{intent['id']}/status", headers=shop["headers"]).status_code == 200


# --------------------------------------------------------------------------- #
# Filtres, pagination, résumé
# --------------------------------------------------------------------------- #
class TestFiltersPaginationSummary:
    @pytest.fixture
    def busy(self, client, engine, shop):
        configure(client, shop)
        rows = [(i, "success" if i % 3 == 0 else "failed" if i % 3 == 1 else "pending", 1000 + i, None, None) for i in range(1, 26)]
        seed(engine, shop, rows)
        return shop

    def test_pages_partition_the_history_without_overlap(self, client, busy):
        everything = [t["id"] for t in listing(client, busy, limit=200)["items"]]
        assert len(everything) == 25
        pages, cursor = [], None
        while True:
            page = listing(client, busy, limit=7, **({"cursor": cursor} if cursor else {}))
            assert len(page["items"]) <= 7
            pages.extend(t["id"] for t in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert pages == everything, "mêmes lignes, même ordre, sans doublon"

    def test_a_new_payment_does_not_shift_the_next_page(self, client, engine, busy):
        first = listing(client, busy, limit=10)
        seed(engine, busy, [(0, "success", 77777, None, None)])  # arrive entre deux pages
        second = listing(client, busy, limit=10, cursor=first["next_cursor"])
        assert not {t["id"] for t in first["items"]} & {t["id"] for t in second["items"]}
        assert 77777 not in [t["amount_fcfa"] for t in second["items"]]
        assert listing(client, busy, limit=1)["items"][0]["amount_fcfa"] == 77777

    def test_newest_first(self, client, busy):
        dates = [t["created_at"] for t in listing(client, busy, limit=200)["items"]]
        assert dates == sorted(dates, reverse=True)

    def test_status_filter_accepts_several_values_and_rejects_unknown_ones(self, client, busy):
        mixed = listing(client, busy, status=["success", "pending"], limit=200)["items"]
        assert {t["status"] for t in mixed} == {"success", "pending"}
        assert client.get(f"{BASE}/transactions", headers=busy["headers"], params={"status": "bogus"}).status_code == 400
        assert listing(client, busy, status="SUCCESS", limit=200)["items"], "insensible à la casse"

    def test_date_range_filter(self, client, busy):
        now = datetime.now(timezone.utc)
        recent = listing(client, busy, limit=200, **{"from": (now - timedelta(minutes=10, seconds=30)).isoformat()})["items"]
        assert 0 < len(recent) < 25
        older = listing(client, busy, limit=200, to=(now - timedelta(minutes=10, seconds=30)).isoformat())["items"]
        assert len(recent) + len(older) == 25

    def test_reference_search_is_a_prefix_search_and_escapes_wildcards(self, client, busy):
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        assert len(listing(client, busy, reference=f"{busy['prefix']}-{today}", limit=200)["items"]) == 25
        assert listing(client, busy, reference="MRD-ZZZZZZZZ")["items"] == []
        assert listing(client, busy, reference="%")["items"] == [], "% n'est pas un joker"

    def test_a_forged_cursor_is_a_clean_400(self, client, busy):
        response = client.get(f"{BASE}/transactions", headers=busy["headers"], params={"cursor": "n'importe quoi"})
        assert response.status_code == 400

    @pytest.mark.parametrize("limit", [0, 201])
    def test_the_page_size_is_bounded(self, client, busy, limit):
        assert client.get(f"{BASE}/transactions", headers=busy["headers"], params={"limit": limit}).status_code == 422

    def test_summary_totals_by_status(self, client, engine, shop):
        configure(client, shop)
        seed(
            engine, shop,
            [
                (5, "success", 1000, 20, True),    # net 980
                (4, "success", 2000, 30, False),   # frais payés en plus : net 2000
                (3, "success", 500, None, None),   # frais encore inconnus : non déduits
                (2, "failed", 700, None, None),
                (1, "pending", 400, None, None),
            ],
        )
        summary = client.get(f"{BASE}/transactions/summary", headers=shop["headers"]).json()
        assert summary["transactions"] == 5
        assert summary["by_status"]["success"] == {"count": 3, "amount_fcfa": 3500}
        assert summary["by_status"]["failed"] == {"count": 1, "amount_fcfa": 700}
        assert summary["collected_fcfa"] == 3500
        assert float(summary["fees_fcfa"]) == 50.0
        assert float(summary["net_collected_fcfa"]) == 980 + 2000 + 500


class TestQueryBudget:
    def test_listing_costs_the_same_whatever_the_page_size_or_history(self, client, engine, shop):
        configure(client, shop)
        seed(engine, shop, [(i, "success", 100 + i, None, None) for i in range(1, 61)])
        with count_queries(engine) as small:
            listing(client, shop, limit=5)
        with count_queries(engine) as large:
            listing(client, shop, limit=60)
        assert small["n"] == large["n"] <= 6, (small["statements"], large["statements"])


# --------------------------------------------------------------------------- #
# Rafraîchissement depuis la passerelle (webhook perdu)
# --------------------------------------------------------------------------- #
class TestRefresh:
    def reply(self, monkeypatch, **payload):
        monkeypatch.setattr(EasyTransactClient, "get_transaction_status", lambda self, *, vendor_reference: {"vendor_reference": vendor_reference, **payload})

    def test_a_lost_webhook_is_recovered_like_a_webhook(self, client, shop, gateway, monkeypatch):
        configure(client, shop)
        intent, commande = checkout(client, shop)
        self.reply(monkeypatch, status="SUCCESS", fees="2", is_fees_inclusive=True, completed_at="2026-10-07T09:00:00Z")
        refreshed = client.post(f"{BASE}/transactions/{intent['id']}/refresh", headers=shop["headers"])
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["status"] == "success"
        assert float(refreshed.json()["fees_fcfa"]) == 2.0
        paid = client.get(f"/v1/restaurants/commandes/{commande}", headers=shop["headers"]).json()
        assert paid["statut"] == "payee", "même effet que le webhook sur la commande"

        again = client.post(f"{BASE}/transactions/{intent['id']}/refresh", headers=shop["headers"])
        assert again.status_code == 200 and again.json()["status"] == "success"
        events = client.get(f"{BASE}/transactions/{intent['id']}", headers=shop["headers"]).json()["events"]
        assert len(events) == 1, "un second rafraîchissement n'ajoute rien"

    def test_nothing_changes_when_the_gateway_fails(self, client, shop, gateway, monkeypatch):
        configure(client, shop)
        intent, _ = checkout(client, shop)

        def broken(self, *, vendor_reference):
            raise EasyTransactError("Easy Transact request failed")

        monkeypatch.setattr(EasyTransactClient, "get_transaction_status", broken)
        assert client.post(f"{BASE}/transactions/{intent['id']}/refresh", headers=shop["headers"]).status_code == 502
        assert listing(client, shop)["items"][0]["status"] == "initiated"

    def test_a_response_about_another_reference_is_refused(self, client, shop, gateway, monkeypatch):
        configure(client, shop)
        intent, _ = checkout(client, shop)
        monkeypatch.setattr(
            EasyTransactClient, "get_transaction_status",
            lambda self, *, vendor_reference: {"vendor_reference": "MRD-OTHER222-20260101-X", "status": "SUCCESS"},
        )
        assert client.post(f"{BASE}/transactions/{intent['id']}/refresh", headers=shop["headers"]).status_code == 502
        assert listing(client, shop)["items"][0]["status"] == "initiated"

    def test_an_unknown_status_is_refused(self, client, shop, gateway, monkeypatch):
        configure(client, shop)
        intent, _ = checkout(client, shop)
        self.reply(monkeypatch, status="SOMETHING_NEW")
        assert client.post(f"{BASE}/transactions/{intent['id']}/refresh", headers=shop["headers"]).status_code == 502

    def test_a_finished_payment_cannot_be_rewritten_by_the_gateway(self, client, shop, gateway, monkeypatch):
        configure(client, shop)
        intent, _ = checkout(client, shop)
        webhook(client, shop, intent["vendor_reference"], "SUCCESS")
        self.reply(monkeypatch, status="FAILED")
        assert client.post(f"{BASE}/transactions/{intent['id']}/refresh", headers=shop["headers"]).status_code == 409
        assert listing(client, shop)["items"][0]["status"] == "success"

    def test_without_a_configured_status_endpoint_it_fails_closed(self, client, shop, gateway, monkeypatch):
        configure(client, shop)
        intent, _ = checkout(client, shop)
        monkeypatch.setattr(settings, "EASYTRANSACT_STATUS_REFERENCE_PARAM", "")
        assert client.post(f"{BASE}/transactions/{intent['id']}/refresh", headers=shop["headers"]).status_code == 503

    def test_only_the_cash_desk_may_refresh(self, client, engine, shop, gateway):
        configure(client, shop)
        intent, _ = checkout(client, shop)
        waiter = make_member(client, engine, shop, "waiter")
        assert client.post(f"{BASE}/transactions/{intent['id']}/refresh", headers=waiter["headers"]).status_code == 403
