from decimal import ROUND_HALF_UP, Decimal

from src.exceptions import InvalidUnitQuantity

BASE_QUANTITY_PLACES = Decimal("0.00000001")


def quantize_base_quantity(value: Decimal) -> Decimal:
    """Round a base-unit quantity to the stock_balances/stock_batches column precision.

    Every module that converts an alt-unit quantity into ``quantity_base`` via
    ``quantity * conversion_to_base`` must pass the result through this before
    persisting, so unit-converted postings can't leave sub-precision drift that
    accumulates into an unexplained system-vs-physical stock mismatch.
    """
    return value.quantize(BASE_QUANTITY_PLACES, rounding=ROUND_HALF_UP)


def quantize_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        raise ValueError("increment must be positive")
    # Numeric(...) columns round-trip through Postgres padded to their full
    # declared scale (e.g. "0.01" comes back as "0.01000000"), so normalize
    # first or the result inherits that padding as bogus extra precision.
    increment = increment.normalize()
    steps = (value / increment).to_integral_value(rounding=ROUND_HALF_UP)
    return steps * increment


def quantity_base_for_unit(
    quantity: Decimal,
    conversion_to_base: Decimal,
    *,
    allow_decimal_quantity: bool,
    rounding_precision: Decimal,
    allow_negative: bool = False,
) -> Decimal:
    """Validate an entered UoM quantity and return its persisted base quantity."""
    if quantity == 0 or conversion_to_base <= 0 or rounding_precision <= 0:
        raise InvalidUnitQuantity()
    if quantity < 0 and not allow_negative:
        raise InvalidUnitQuantity()
    magnitude = abs(quantity)
    if not allow_decimal_quantity and magnitude != magnitude.to_integral_value():
        raise InvalidUnitQuantity("This unit only permits whole quantities.")
    if magnitude != quantize_to_increment(magnitude, rounding_precision):
        raise InvalidUnitQuantity(
            "Quantity must be a multiple of the selected unit's rounding precision."
        )
    quantity_base = quantize_base_quantity(quantity * conversion_to_base)
    if quantity_base == 0:
        raise InvalidUnitQuantity("Quantity is too small to persist in the base unit.")
    return quantity_base
