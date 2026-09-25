import pytest
import uuid
from decimal import Decimal
import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.core.database import get_db
from app.models.user import User
from app.models.restaurant import Restaurant
from app.utils.enums import UserRole
from app.utils.ros_enums import (
    CustomerType,
    SessionStatus,
    FulfillmentType,
    OrderChannel,
    RosOrderStatus,
    ProductionStation,
    TicketStatus,
    InvoiceStatus,
    RosPaymentMethod,
    CashShiftStatus,
)
from app.services.auth_service import AuthService


@pytest.fixture
def client():
    return TestClient(app)


from app.core.database import Base


@pytest.fixture
def db_session():
    db = next(get_db())
    try:
        Base.metadata.create_all(bind=db.get_bind())
        yield db
    finally:
        db.close()


@pytest.fixture
def auth_headers(db_session: Session):
    auth_service = AuthService(db_session)
    phone_suffix = uuid.uuid4().hex[:7]
    user = User(
        email=f"ros_owner_{uuid.uuid4().hex[:6]}@marinade.com",
        phone=f"+23769{phone_suffix}",
        password_hash="hashed_password",
        first_name="ROS",
        last_name="Owner",
        role=UserRole.RESTAURANT.value,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = auth_service.create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}, user


@pytest.fixture
def test_restaurant(db_session: Session, auth_headers):
    headers, user = auth_headers
    restaurant = Restaurant(
        user_id=user.id,
        name="Le Grand Maquis Camerounais",
        currency="XAF",
        phone="+237690000000",
    )
    db_session.add(restaurant)
    db_session.commit()
    db_session.refresh(restaurant)
    return restaurant


# -----------------------------------------------------------------------------
# TEST SCENARIO 1: Guest + No Table + Immediate Payment (Fast Counter / Bar Mode)
# -----------------------------------------------------------------------------
def test_sc1_guest_no_table_immediate_payment(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)

    # 1. Create Order directly without table (No Table Mode)
    idempotency_key = str(uuid.uuid4())
    order_payload = {
        "fulfillment_type": "COUNTER",
        "order_channel": "POS",
        "items": [
            {
                "product_name": "Bière Castel 65cl",
                "quantity": 2,
                "unit_price": 1000.00,
                "tax_rate": 19.25,
                "destination_station": "BAR",
            }
        ],
        "idempotency_key": idempotency_key,
    }

    res_order = client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )
    assert res_order.status_code == 201
    order_data = res_order.json()
    order_id = order_data["id"]

    # Verify total = (2 * 1000) + 19.25% tax = 2000 + 385 = 2385.00
    assert float(order_data["total_amount"]) == 2385.00
    assert order_data["status"] == "PENDING_PAYMENT"  # Counter policy = Prepaid

    # 2. Get Invoice for Order
    res_ticket = client.get(
        f"/v1/ros/restaurants/{rest_id}/tickets/BAR", headers=headers
    )
    assert res_ticket.status_code == 200

    # 3. Pay Invoice immediately via Cash
    # First query created invoice
    db = next(get_db())
    from app.models.ros import RosInvoice

    invoice = (
        db.query(RosInvoice).filter(RosInvoice.order_id == uuid.UUID(order_id)).first()
    )
    assert invoice is not None
    inv_id = str(invoice.id)

    pay_payload = {
        "invoice_id": inv_id,
        "payment_method": "CASH",
        "amount": 2385.00,
        "idempotency_key": str(uuid.uuid4()),
    }

    res_pay = client.post(
        f"/v1/ros/restaurants/{rest_id}/payments", json=pay_payload, headers=headers
    )
    assert res_pay.status_code == 201
    pay_data = res_pay.json()
    assert pay_data["status"] == "SUCCEEDED"

    # Verify invoice status updated to PAID
    db.refresh(invoice)
    assert invoice.status == "PAID"
    assert invoice.amount_due == Decimal("0.00")

    # Verify tickets dispatched to BAR station
    tickets = client.get(
        f"/v1/ros/restaurants/{rest_id}/tickets/BAR", headers=headers
    ).json()
    assert len(tickets) >= 1
    assert tickets[0]["station"] == "BAR"


# -----------------------------------------------------------------------------
# TEST SCENARIO 2: Guest + Food & Drink Routing + Postpaid Dine-In
# -----------------------------------------------------------------------------
def test_sc2_food_drink_routing_postpaid(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)

    # 1. Open Session with free context ("Terrasse Gauche")
    session_payload = {"table_context": "Terrasse Gauche"}
    res_sess = client.post(
        f"/v1/ros/restaurants/{rest_id}/sessions", json=session_payload, headers=headers
    )
    assert res_sess.status_code == 201
    session_id = res_sess.json()["id"]

    # 2. Create Order containing both FOOD and DRINKS
    order_payload = {
        "session_id": session_id,
        "fulfillment_type": "DINE_IN",
        "order_channel": "POS",
        "items": [
            {
                "product_name": "Poulet Braisé Demi",
                "quantity": 1,
                "unit_price": 4000.00,
                "tax_rate": 19.25,
                "destination_station": "KITCHEN",
            },
            {
                "product_name": "Jus d'Ananas Naturel",
                "quantity": 2,
                "unit_price": 1500.00,
                "tax_rate": 19.25,
                "destination_station": "BAR",
            },
        ],
    }

    res_order = client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )
    assert res_order.status_code == 201
    order_data = res_order.json()
    assert (
        order_data["status"] == "CONFIRMED"
    )  # Postpaid Dine-In = Confirmed immediately

    # 3. Check Kitchen and Bar Ticket queues
    k_tickets = client.get(
        f"/v1/ros/restaurants/{rest_id}/tickets/KITCHEN", headers=headers
    ).json()
    b_tickets = client.get(
        f"/v1/ros/restaurants/{rest_id}/tickets/BAR", headers=headers
    ).json()

    assert any(t["order_id"] == order_data["id"] for t in k_tickets)
    assert any(t["order_id"] == order_data["id"] for t in b_tickets)


# -----------------------------------------------------------------------------
# TEST SCENARIO 3: Split Bill (Multi-Method Payments)
# -----------------------------------------------------------------------------
def test_sc3_split_bill_multi_method(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)

    # Create Order
    order_payload = {
        "fulfillment_type": "DINE_IN",
        "items": [
            {
                "product_name": "Poisson Capitaine Grillé",
                "quantity": 1,
                "unit_price": 10000.00,
                "tax_rate": 0.00,
                "destination_station": "KITCHEN",
            }
        ],
    }
    res_order = client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )
    order_id = res_order.json()["id"]

    db = next(get_db())
    from app.models.ros import RosInvoice

    invoice = (
        db.query(RosInvoice).filter(RosInvoice.order_id == uuid.UUID(order_id)).first()
    )

    # Split Bill: 6000 Cash + 4000 MTN MoMo
    split_payload = {
        "invoice_id": str(invoice.id),
        "payments": [
            {"payment_method": "CASH", "amount": 6000.00},
            {
                "payment_method": "MTN_MOMO",
                "amount": 4000.00,
                "external_reference": "MOMO-237690123456",
            },
        ],
    }

    res_split = client.post(
        f"/v1/ros/restaurants/{rest_id}/payments/split",
        json=split_payload,
        headers=headers,
    )
    assert res_split.status_code == 201
    txns = res_split.json()
    assert len(txns) == 2

    db.refresh(invoice)
    assert invoice.status == "PAID"
    assert invoice.amount_paid == Decimal("10000.00")
    assert invoice.amount_due == Decimal("0.00")


# -----------------------------------------------------------------------------
# TEST SCENARIO 4: Shift Caisse & Audit des Écarts (Variance)
# -----------------------------------------------------------------------------
def test_sc4_cash_shift_variance_audit(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)

    # 1. Open Operator Shift
    open_payload = {"opening_balance": 15000.00}
    res_open = client.post(
        f"/v1/ros/restaurants/{rest_id}/shifts/open", json=open_payload, headers=headers
    )
    assert res_open.status_code == 201
    shift_data = res_open.json()
    assert shift_data["status"] == "OPEN"

    # Cannot open second active shift for same operator
    res_open_dup = client.post(
        f"/v1/ros/restaurants/{rest_id}/shifts/open", json=open_payload, headers=headers
    )
    assert res_open_dup.status_code == 409

    # 2. Perform Cash Sale
    order_payload = {
        "fulfillment_type": "COUNTER",
        "items": [
            {
                "product_name": "Soda",
                "quantity": 1,
                "unit_price": 1000.00,
                "tax_rate": 0,
                "destination_station": "BAR",
            }
        ],
    }
    res_ord = client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )
    order_id = res_ord.json()["id"]

    db = next(get_db())
    from app.models.ros import RosInvoice, RosAuditLog

    invoice = (
        db.query(RosInvoice).filter(RosInvoice.order_id == uuid.UUID(order_id)).first()
    )

    client.post(
        f"/v1/ros/restaurants/{rest_id}/payments",
        json={
            "invoice_id": str(invoice.id),
            "payment_method": "CASH",
            "amount": 1000.00,
        },
        headers=headers,
    )

    # Expected Closing Balance = 15,000 + 1,000 = 16,000.
    # Suppose Counted Balance = 15,500 (Variance = -500 XAF)
    close_payload = {"closing_balance_counted": 15500.00}
    res_close = client.post(
        f"/v1/ros/restaurants/{rest_id}/shifts/close",
        json=close_payload,
        headers=headers,
    )
    assert res_close.status_code == 200
    closed_data = res_close.json()

    assert closed_data["status"] == "CLOSED"
    assert float(closed_data["closing_balance_expected"]) == 16000.00
    assert float(closed_data["variance"]) == -500.00

    # Verify Audit Log entry recorded for shift variance
    audit_entry = (
        db.query(RosAuditLog).filter(RosAuditLog.action == "CLOSE_CASH_SHIFT").first()
    )
    assert audit_entry is not None
    assert "variance" in audit_entry.after_state


# -----------------------------------------------------------------------------
# TEST SCENARIO 5: Offline Batch Sync & Idempotency Protection
# -----------------------------------------------------------------------------
def test_sc5_offline_batch_sync_idempotency(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)

    key1 = str(uuid.uuid4())
    sync_payload = {
        "orders": [
            {
                "fulfillment_type": "DINE_IN",
                "items": [
                    {
                        "product_name": "Eau Minérale 1.5L",
                        "quantity": 1,
                        "unit_price": 500.00,
                        "tax_rate": 0,
                        "destination_station": "BAR",
                    }
                ],
                "idempotency_key": key1,
            }
        ],
        "payments": [],
    }

    # First sync attempt
    res_sync1 = client.post(
        f"/v1/ros/restaurants/{rest_id}/sync", json=sync_payload, headers=headers
    )
    assert res_sync1.status_code == 200
    assert res_sync1.json()["processed_orders"] == 1

    # Second sync attempt with exact same payload (Idempotency replay)
    res_sync2 = client.post(
        f"/v1/ros/restaurants/{rest_id}/sync", json=sync_payload, headers=headers
    )
    assert res_sync2.status_code == 200
    assert (
        res_sync2.json()["processed_orders"] == 1
    )  # Replayed cleanly without creating duplicate order records


# -----------------------------------------------------------------------------
# TEST SCENARIO 6: KDS Ticket Progression
# -----------------------------------------------------------------------------
def test_sc6_kds_ticket_progression(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)

    # Create Order
    order_payload = {
        "fulfillment_type": "DINE_IN",
        "items": [
            {
                "product_name": "Ndolé Viande",
                "quantity": 1,
                "unit_price": 3500.00,
                "tax_rate": 0,
                "destination_station": "KITCHEN",
            }
        ],
    }
    client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )

    # Get Pending Kitchen Ticket
    tickets = client.get(
        f"/v1/ros/restaurants/{rest_id}/tickets/KITCHEN", headers=headers
    ).json()
    ticket_id = tickets[0]["id"]
    assert tickets[0]["status"] == "QUEUED"

    # Progress Ticket: QUEUED -> IN_PREPARATION -> READY
    res_in_prep = client.put(
        f"/v1/ros/restaurants/{rest_id}/tickets/{ticket_id}/status",
        json={"status": "IN_PREPARATION"},
        headers=headers,
    )
    assert res_in_prep.json()["status"] == "IN_PREPARATION"

    res_ready = client.put(
        f"/v1/ros/restaurants/{rest_id}/tickets/{ticket_id}/status",
        json={"status": "READY"},
        headers=headers,
    )
    assert res_ready.json()["status"] == "READY"
    assert res_ready.json()["ready_at"] is not None


# -----------------------------------------------------------------------------
# TEST SCENARIO 7: DGI Cameroun SHA-256 Fiscal Hash Verification
# -----------------------------------------------------------------------------
def test_sc7_fiscal_hash_generation(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)

    order_payload = {
        "fulfillment_type": "DINE_IN",
        "items": [
            {
                "product_name": "Eru avec Peau de Bœuf",
                "quantity": 1,
                "unit_price": 2500.00,
                "tax_rate": 19.25,
                "destination_station": "KITCHEN",
            }
        ],
    }
    res_order = client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )
    order_id = res_order.json()["id"]

    db = next(get_db())
    from app.models.ros import RosInvoice

    invoice = (
        db.query(RosInvoice).filter(RosInvoice.order_id == uuid.UUID(order_id)).first()
    )

    assert invoice.fiscal_hash is not None
    assert len(invoice.fiscal_hash) == 64  # SHA-256 hex string length
    assert invoice.invoice_number.startswith(f"INV-{rest_id[:8].upper()}")


# -----------------------------------------------------------------------------
# TEST SCENARIO 8: Automatic Ingredient Stock Deduction & Low Stock Audit
# -----------------------------------------------------------------------------
def test_sc8_automatic_stock_deduction(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)
    db = next(get_db())

    from app.models.restaurant import Composant, StockComposant, StockMouvement
    from app.models.ros import RosAuditLog

    # 1. Create Composant and StockComposant with qty=10, alert threshold=3
    comp = Composant(
        restaurant_id=test_restaurant.id,
        nom="Steak Haché 150g",
        type="VIANDE",
        prix_supplement=500.00,
        disponible=True,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)

    stock = StockComposant(
        composant_id=comp.id,
        quantite=Decimal("10.000"),
        reservee=Decimal("0.000"),
        seuil_alerte=Decimal("3.000"),
    )
    db.add(stock)
    db.commit()

    # 2. Place ROS Order for 8 units of this component
    order_payload = {
        "fulfillment_type": "DINE_IN",
        "items": [
            {
                "product_id": str(comp.id),
                "product_name": "Steak Haché 150g",
                "quantity": 8,
                "unit_price": 2000.00,
                "tax_rate": 0,
                "destination_station": "KITCHEN",
            }
        ],
    }

    res_order = client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )
    assert res_order.status_code == 201

    # 3. Verify stock deducted: 10 - 8 = 2 units (which is <= alert threshold 3)
    db.refresh(stock)
    assert float(stock.quantite) == 2.00

    # 4. Verify StockMouvement recorded
    mvt = (
        db.query(StockMouvement).filter(StockMouvement.composant_id == comp.id).first()
    )
    assert mvt is not None
    assert mvt.type == "SORTIE"
    assert float(mvt.quantite) == 8.00

    # 5. Verify Audit Log entry for low stock alert
    audit = (
        db.query(RosAuditLog)
        .filter(
            RosAuditLog.restaurant_id == test_restaurant.id,
            RosAuditLog.action == "STOCK_ALERT_LOW",
        )
        .first()
    )
    assert audit is not None


# -----------------------------------------------------------------------------
# TEST SCENARIO 9: Multi-Tenant Security & Invoice Isolation Guard
# -----------------------------------------------------------------------------
def test_sc9_multitenant_isolation_security(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)
    db = next(get_db())

    # Create Order in Restaurant A
    order_payload = {
        "fulfillment_type": "DINE_IN",
        "items": [
            {
                "product_name": "Jus de Gingembre",
                "quantity": 1,
                "unit_price": 1000.00,
                "tax_rate": 0,
                "destination_station": "BAR",
            }
        ],
    }
    res_order = client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )
    order_id = res_order.json()["id"]

    from app.models.ros import RosInvoice

    invoice = (
        db.query(RosInvoice).filter(RosInvoice.order_id == uuid.UUID(order_id)).first()
    )

    # Attempt to process payment for Restaurant A invoice using Restaurant B ID (Fake UUID)
    fake_rest_id = str(uuid.uuid4())
    pay_payload = {
        "invoice_id": str(invoice.id),
        "payment_method": "CASH",
        "amount": 1000.00,
    }

    res_cross_pay = client.post(
        f"/v1/ros/restaurants/{fake_rest_id}/payments",
        json=pay_payload,
        headers=headers,
    )
    assert res_cross_pay.status_code == 404


# -----------------------------------------------------------------------------
# TEST SCENARIO 10: Recursive Recipe Explosion Stock Deduction
# -----------------------------------------------------------------------------
def test_sc10_recursive_recipe_card_explosion(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)
    db = next(get_db())

    from app.models.restaurant import (
        Composant,
        Combinaison,
        CombinaisonComposant,
        StockComposant,
        StockMouvement,
    )

    # 1. Create 2 sub-ingredients (Bun & Meat)
    bun = Composant(
        restaurant_id=test_restaurant.id,
        nom="Pain Burger",
        type="PAIN",
        prix_supplement=100.00,
    )
    meat = Composant(
        restaurant_id=test_restaurant.id,
        nom="Steak Haché",
        type="VIANDE",
        prix_supplement=400.00,
    )
    db.add_all([bun, meat])
    db.commit()

    stock_bun = StockComposant(
        composant_id=bun.id, quantite=Decimal("20.000"), seuil_alerte=Decimal("5.000")
    )
    stock_meat = StockComposant(
        composant_id=meat.id, quantite=Decimal("15.000"), seuil_alerte=Decimal("5.000")
    )
    db.add_all([stock_bun, stock_meat])
    db.commit()

    # 2. Create Combinaison "Burger Double" made of 2 Buns + 2 Meats
    combo = Combinaison(
        restaurant_id=test_restaurant.id, nom="Burger Double", prix=3500.00
    )
    db.add(combo)
    db.commit()

    link_bun = CombinaisonComposant(
        combinaison_id=combo.id, composant_id=bun.id, quantite=Decimal("2.000")
    )
    link_meat = CombinaisonComposant(
        combinaison_id=combo.id, composant_id=meat.id, quantite=Decimal("2.000")
    )
    db.add_all([link_bun, link_meat])
    db.commit()

    # 3. Order 3 "Burger Double" -> Total Buns needed = 3 * 2 = 6, Meats needed = 3 * 2 = 6
    order_payload = {
        "fulfillment_type": "DINE_IN",
        "items": [
            {
                "product_id": str(combo.id),
                "product_name": "Burger Double",
                "quantity": 3,
                "unit_price": 3500.00,
                "tax_rate": 0,
                "destination_station": "KITCHEN",
            }
        ],
    }

    res_order = client.post(
        f"/v1/ros/restaurants/{rest_id}/orders", json=order_payload, headers=headers
    )
    assert res_order.status_code == 201

    # 4. Verify Bun stock: 20 - 6 = 14
    db.refresh(stock_bun)
    assert float(stock_bun.quantite) == 14.00

    # 5. Verify Meat stock: 15 - 6 = 9
    db.refresh(stock_meat)
    assert float(stock_meat.quantite) == 9.00


# -----------------------------------------------------------------------------
# TEST SCENARIO 11: Auto-Procurement Suggestions Engine
# -----------------------------------------------------------------------------
def test_sc11_auto_procurement_suggestions(client, auth_headers, test_restaurant):
    headers, user = auth_headers
    rest_id = str(test_restaurant.id)
    db = next(get_db())

    from app.models.restaurant import Composant, StockComposant

    # Create component with stock=1 <= seuil_alerte=5
    comp = Composant(
        restaurant_id=test_restaurant.id,
        nom="Tomate Fraîche",
        type="LEGUME",
        prix_supplement=50.00,
    )
    db.add(comp)
    db.commit()

    stock = StockComposant(
        composant_id=comp.id, quantite=Decimal("1.000"), seuil_alerte=Decimal("5.000")
    )
    db.add(stock)
    db.commit()

    res_proc = client.get(
        f"/v1/ros/restaurants/{rest_id}/procurement/suggestions", headers=headers
    )
    assert res_proc.status_code == 200
    data = res_proc.json()

    assert data["restaurant_id"] == rest_id
    assert len(data["items"]) >= 1

    item = next(i for i in data["items"] if i["composant_id"] == str(comp.id))
    # Suggested = (5 * 2) - 1 = 9 units
    assert float(item["suggested_order_qty"]) == 9.00


# -----------------------------------------------------------------------------
# TEST SCENARIO 12: Multi-Site Group Consolidated Reporting
# -----------------------------------------------------------------------------
def test_sc12_group_consolidated_reporting(client, auth_headers, test_restaurant):
    headers, user = auth_headers

    res_rep = client.get("/v1/ros/group/reporting", headers=headers)
    assert res_rep.status_code == 200
    rep_data = res_rep.json()

    assert rep_data["total_restaurants"] >= 1
    assert "total_revenue" in rep_data
    assert "revenue_by_channel" in rep_data
