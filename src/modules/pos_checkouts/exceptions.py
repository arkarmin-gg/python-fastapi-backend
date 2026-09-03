from decimal import Decimal

from src.exceptions import AppException, ConflictError, NotFoundError


class PosCheckoutNotFound(NotFoundError):
    error_code = "pos_checkout_not_found"
    detail = "POS checkout not found."


class PosCheckoutIdempotencyConflict(ConflictError):
    error_code = "pos_checkout_idempotency_conflict"
    detail = "The idempotency key was already used for a different checkout request."


class PosCheckoutTotalChanged(ConflictError):
    error_code = "pos_checkout_total_changed"
    detail = "The authoritative sale total changed. Confirm the updated total and retry."

    def __init__(self, authoritative_total: Decimal) -> None:
        super().__init__(details={"authoritative_total": format(authoritative_total, "f")})


class PosCheckoutCreditLimitExceeded(AppException):
    status_code = 400
    error_code = "pos_checkout_credit_limit_exceeded"
    detail = "The checkout would exceed the customer's credit limit."

    def __init__(self, *, available_credit: Decimal, charged_to_account: Decimal) -> None:
        super().__init__(
            details={
                "available_credit": format(available_credit, "f"),
                "charged_to_account": format(charged_to_account, "f"),
            }
        )
