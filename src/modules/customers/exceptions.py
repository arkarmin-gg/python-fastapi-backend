from fastapi import status

from src.exceptions import AppException, ConflictError, NotFoundError


class CustomerNotFound(NotFoundError):
    error_code = "customer_not_found"
    detail = "Customer not found."


class CustomerCodeConflict(ConflictError):
    error_code = "customer_code_conflict"
    detail = "A customer with this code already exists for the tenant."


class InvalidCustomerPriceLevel(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_customer_price_level"
    detail = "Price level must be active and belong to the same tenant."
