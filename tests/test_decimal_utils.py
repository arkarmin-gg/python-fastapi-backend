from decimal import Decimal

import pytest
from src.decimal_utils import quantity_base_for_unit
from src.exceptions import InvalidUnitQuantity


def test_quantity_base_for_unit_enforces_whole_quantity_policy() -> None:
    with pytest.raises(InvalidUnitQuantity, match="whole quantities"):
        quantity_base_for_unit(
            Decimal("0.5"),
            Decimal("12"),
            allow_decimal_quantity=False,
            rounding_precision=Decimal("1"),
        )


def test_quantity_base_for_unit_enforces_increment_and_rounding_policy() -> None:
    with pytest.raises(InvalidUnitQuantity, match="rounding precision"):
        quantity_base_for_unit(
            Decimal("1.005"),
            Decimal("1"),
            allow_decimal_quantity=True,
            rounding_precision=Decimal("0.01"),
        )

    assert quantity_base_for_unit(
        Decimal("1.01"),
        Decimal("0.33333333"),
        allow_decimal_quantity=True,
        rounding_precision=Decimal("0.01"),
    ) == Decimal("0.33666666")


def test_quantity_base_for_unit_preserves_signed_adjustments() -> None:
    assert quantity_base_for_unit(
        Decimal("-2"),
        Decimal("12"),
        allow_decimal_quantity=False,
        rounding_precision=Decimal("1"),
        allow_negative=True,
    ) == Decimal("-24.00000000")
