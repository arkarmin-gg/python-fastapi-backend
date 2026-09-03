from fastapi import status

from src.exceptions import AppException, ConflictError, NotFoundError


class PriceRuleNotFound(NotFoundError):
    error_code = "price_rule_not_found"
    detail = "Price rule not found."


class PriceRuleOverlapConflict(ConflictError):
    error_code = "price_rule_overlap_conflict"
    detail = "An active price rule already overlaps this scope and effective period."


class InvalidPriceRuleVariant(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_price_rule_variant"
    detail = "Product variant must be active and belong to the same tenant."


class InvalidPriceRuleVariantUnit(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_price_rule_variant_unit"
    detail = "Variant unit must be active and belong to the selected product variant."


class InvalidPriceRulePriceLevel(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_price_rule_price_level"
    detail = "Price level must be active and belong to the same tenant."


class InvalidPriceRuleCustomer(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_price_rule_customer"
    detail = "Customer must be active and belong to the same tenant."


class InvalidPriceRuleEffectivePeriod(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_price_rule_effective_period"
    detail = "effective_to must be later than effective_from."
