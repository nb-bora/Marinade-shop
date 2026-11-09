"""Moteur de stock : réception (receive), lots, coût moyen pondéré, journal et FIFO.

Travaille sur la vraie base de test (rôle applicatif, RLS active) via ``postgres_test_session`` : chaque
test est annulé en fin de transaction.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.restaurant import Composant, StockComposant, StockMouvement
from app.models.stock import StockLot
from app.services.stock_engine import StockEngine, check_quantity
from app.services.stock_errors import StockValidationError
from app.utils.exceptions import InsufficientStockError


@pytest.fixture
def ctx(postgres_test_session):
    db = postgres_test_session["db"]
    restaurant = postgres_test_session["restaurant"]
    return db, restaurant


def make_composant(db, restaurant, nom="Riz", *, suit_peremption=False, stock_unite="kg"):
    composant = Composant(
        restaurant_id=restaurant.id,
        nom=nom,
        type="base",
        stock_unite=stock_unite,
        suit_peremption=suit_peremption,
    )
    db.add(composant)
    db.flush()
    db.add(StockComposant(composant_id=composant.id))
    db.flush()
    return composant


def stock_of(db, composant):
    db.refresh(composant)
    return db.execute(select(StockComposant).where(StockComposant.composant_id == composant.id)).scalar_one()


def test_receive_adds_stock_and_journals_an_entree(ctx):
    db, restaurant = ctx
    riz = make_composant(db, restaurant)
    mouvement = StockEngine(db).receive(restaurant.id, riz.id, Decimal("10"), cout_unitaire=Decimal("2000"))

    assert stock_of(db, riz).quantite == Decimal("10.000")
    assert mouvement.type == "entree"
    assert mouvement.motif == "reception"
    assert mouvement.delta == Decimal("10")
    assert mouvement.quantite == Decimal("10")
    assert mouvement.stock_apres == Decimal("10")
    assert mouvement.restaurant_id == restaurant.id
    assert mouvement.lot_id is None


def test_receive_without_lot_information_creates_no_lot(ctx):
    db, restaurant = ctx
    riz = make_composant(db, restaurant)
    StockEngine(db).receive(restaurant.id, riz.id, Decimal("3"))
    lots = db.execute(select(StockLot).where(StockLot.composant_id == riz.id)).scalars().all()
    assert lots == []


def test_receive_creates_a_lot_when_a_date_or_number_is_given(ctx):
    db, restaurant = ctx
    lait = make_composant(db, restaurant, "Lait", stock_unite="l")
    mouvement = StockEngine(db).receive(
        restaurant.id,
        lait.id,
        Decimal("6"),
        lot_numero="L-2026-11",
        date_peremption=date(2026, 11, 20),
    )
    lot = db.execute(select(StockLot).where(StockLot.id == mouvement.lot_id)).scalar_one()
    assert lot.quantite_initiale == Decimal("6.000")
    assert lot.quantite_restante == Decimal("6.000")
    assert lot.numero == "L-2026-11"
    assert lot.date_peremption == date(2026, 11, 20)


def test_a_component_that_follows_expiry_gets_a_lot_even_without_date(ctx):
    db, restaurant = ctx
    poisson = make_composant(db, restaurant, "Poisson", suit_peremption=True)
    mouvement = StockEngine(db).receive(restaurant.id, poisson.id, Decimal("2"))
    assert mouvement.lot_id is not None


def test_weighted_average_cost_is_updated_on_each_receipt(ctx):
    db, restaurant = ctx
    huile = make_composant(db, restaurant, "Huile", stock_unite="l")
    engine = StockEngine(db)
    engine.receive(restaurant.id, huile.id, Decimal("10"), cout_unitaire=Decimal("1000"))
    engine.receive(restaurant.id, huile.id, Decimal("10"), cout_unitaire=Decimal("2000"))
    db.refresh(huile)
    # (10 x 1000 + 10 x 2000) / 20 = 1500
    assert huile.cout_unitaire == Decimal("1500.0000")
    assert huile.cout_maj_le is not None


def test_cost_falls_back_to_the_last_price_when_stock_was_empty(ctx):
    db, restaurant = ctx
    sel = make_composant(db, restaurant, "Sel")
    engine = StockEngine(db)
    engine.receive(restaurant.id, sel.id, Decimal("5"), cout_unitaire=Decimal("300"))
    engine.sortie_manuelle(restaurant.id, sel.id, Decimal("5"), motif="perte")
    engine.receive(restaurant.id, sel.id, Decimal("5"), cout_unitaire=Decimal("500"))
    db.refresh(sel)
    assert sel.cout_unitaire == Decimal("500.0000")


def test_receive_without_cost_keeps_the_existing_cost(ctx):
    db, restaurant = ctx
    farine = make_composant(db, restaurant, "Farine")
    engine = StockEngine(db)
    engine.receive(restaurant.id, farine.id, Decimal("4"), cout_unitaire=Decimal("800"))
    engine.receive(restaurant.id, farine.id, Decimal("4"))
    db.refresh(farine)
    assert farine.cout_unitaire == Decimal("800.0000")


def test_more_than_three_decimals_is_refused_not_rounded(ctx):
    db, restaurant = ctx
    riz = make_composant(db, restaurant)
    with pytest.raises(StockValidationError) as info:
        StockEngine(db).receive(restaurant.id, riz.id, Decimal("1.23456"))
    assert info.value.problem_code == "stock.precision"
    assert info.value.http_status == 422
    assert stock_of(db, riz).quantite == Decimal("0.000")


def test_quantity_below_the_minimum_is_refused(ctx):
    db, restaurant = ctx
    riz = make_composant(db, restaurant)
    with pytest.raises(StockValidationError) as info:
        StockEngine(db).receive(restaurant.id, riz.id, Decimal("0.0004"))
    assert info.value.problem_code == "stock.quantite_minimum"


def test_receive_refuses_a_component_of_another_restaurant(ctx):
    from app.services.stock_errors import StockNotFound

    db, restaurant = ctx
    riz = make_composant(db, restaurant)
    with pytest.raises(StockNotFound):
        StockEngine(db).receive(
            restaurant.id.__class__(int=1), riz.id, Decimal("1")
        )


def test_consumption_is_fifo_by_expiry_and_journals_each_lot(ctx):
    db, restaurant = ctx
    poulet = make_composant(db, restaurant, "Poulet", suit_peremption=True)
    engine = StockEngine(db)
    proche = engine.receive(
        restaurant.id, poulet.id, Decimal("3"), lot_numero="J2", date_peremption=date(2026, 11, 11)
    )
    loin = engine.receive(
        restaurant.id, poulet.id, Decimal("10"), lot_numero="J10", date_peremption=date(2026, 11, 19)
    )
    engine.sortie_manuelle(restaurant.id, poulet.id, Decimal("5"), motif="usage_interne")

    assert stock_of(db, poulet).quantite == Decimal("8.000")
    lot_proche = db.get(StockLot, proche.lot_id)
    lot_loin = db.get(StockLot, loin.lot_id)
    assert lot_proche.quantite_restante == Decimal("0.000")
    assert lot_loin.quantite_restante == Decimal("8.000")

    sorties = (
        db.execute(
            select(StockMouvement)
            .where(StockMouvement.composant_id == poulet.id, StockMouvement.type == "sortie")
            .order_by(StockMouvement.created_at, StockMouvement.id)
        )
        .scalars()
        .all()
    )
    assert [(m.lot_id, m.delta) for m in sorties] == [
        (proche.lot_id, Decimal("-3")),
        (loin.lot_id, Decimal("-2")),
    ]
    assert sorties[-1].stock_apres == Decimal("8")


def test_manual_outflow_requires_stock_and_reports_it_in_french(ctx):
    db, restaurant = ctx
    riz = make_composant(db, restaurant)
    StockEngine(db).receive(restaurant.id, riz.id, Decimal("2"))
    with pytest.raises(InsufficientStockError) as info:
        StockEngine(db).sortie_manuelle(restaurant.id, riz.id, Decimal("3"), motif="perte")
    assert info.value.problem_code == "stock.insufficient"
    assert "Stock insuffisant" in info.value.message
    assert stock_of(db, riz).quantite == Decimal("2.000")


def test_adjustment_journals_the_signed_difference_not_the_absolute_value(ctx):
    db, restaurant = ctx
    riz = make_composant(db, restaurant)
    engine = StockEngine(db)
    engine.receive(restaurant.id, riz.id, Decimal("11.2"))
    mouvement = engine.ajustement(restaurant.id, riz.id, Decimal("3"), motif="inventaire")
    assert mouvement.type == "ajustement"
    assert mouvement.delta == Decimal("-8.2")
    assert mouvement.quantite == Decimal("8.2")
    assert mouvement.stock_apres == Decimal("3")
    assert stock_of(db, riz).quantite == Decimal("3.000")


def test_stock_can_be_set_to_zero_by_adjustment(ctx):
    db, restaurant = ctx
    riz = make_composant(db, restaurant)
    engine = StockEngine(db)
    engine.receive(restaurant.id, riz.id, Decimal("4"))
    engine.ajustement(restaurant.id, riz.id, Decimal("0"), motif="inventaire")
    assert stock_of(db, riz).quantite == Decimal("0.000")


def test_alert_rule_zero_threshold_means_no_alert(ctx):
    from app.services.stock_engine import ETAT_ALERTE, ETAT_RUPTURE, ETAT_SUFFISANT, etat_stock

    assert etat_stock(Decimal("0"), Decimal("0"), Decimal("0")) == ETAT_RUPTURE
    assert etat_stock(Decimal("6"), Decimal("0"), Decimal("0")) == ETAT_SUFFISANT
    assert etat_stock(Decimal("6"), Decimal("5"), Decimal("5")) == ETAT_ALERTE
    assert etat_stock(Decimal("6"), Decimal("1"), Decimal("5")) == ETAT_ALERTE


def test_check_quantity_accepts_three_decimals_exactly():
    assert check_quantity("0.001") == Decimal("0.001")
    assert check_quantity("12.345") == Decimal("12.345")
