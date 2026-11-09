from decimal import Decimal

from app.services.stock_units import (
    convertible_units,
    has_valid_precision,
    normalize_unit,
    to_stock_quantity,
    unit_factor,
)


def test_units_are_normalised():
    assert normalize_unit(" Kg ") == "kg"
    assert normalize_unit("Litres") == "l"
    assert normalize_unit("Pièce") == "piece"
    assert normalize_unit("unités") == "piece"


def test_same_dimension_converts_automatically():
    assert to_stock_quantity(Decimal("150"), "kg", "g") == Decimal("0.150")
    assert to_stock_quantity(Decimal("2"), "g", "kg") == Decimal("2000.000")
    assert to_stock_quantity(Decimal("33"), "l", "cl") == Decimal("0.330")
    assert unit_factor("kg", "kg") == Decimal(1)


def test_counting_units_never_convert_implicitly():
    assert unit_factor("kg", "piece") is None
    assert unit_factor("bouteille", "carton") is None
    assert unit_factor("piece", "kg") is None
    assert unit_factor("kg", "l") is None


def test_custom_conversion_is_used():
    custom = {"carton": Decimal("12")}
    assert unit_factor("bouteille", "carton", custom) == Decimal("12")
    assert to_stock_quantity(Decimal("2"), "bouteille", "Carton", custom) == Decimal("24.000")


def test_precision_rules():
    assert has_valid_precision(Decimal("1.234"))
    assert not has_valid_precision(Decimal("1.2345"))
    assert not has_valid_precision(Decimal("0.0004"))
    assert not has_valid_precision(Decimal("1e12"))


def test_convertible_units_lists_the_dimension_and_custom_units():
    assert convertible_units("kg", {"sac": Decimal("25")}) == ["kg", "g", "mg", "sac"]
    assert convertible_units("portion") == ["portion"]
