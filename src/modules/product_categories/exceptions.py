from fastapi import status

from src.exceptions import AppException, ConflictError, NotFoundError


class ProductCategoryNotFound(NotFoundError):
    error_code = "product_category_not_found"
    detail = "Product category not found."


class ProductCategoryCodeConflict(ConflictError):
    error_code = "product_category_code_conflict"
    detail = "A product category with this code already exists for the tenant."


class InvalidParentProductCategory(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_parent_product_category"
    detail = "Parent product category must exist in the same tenant and cannot create a cycle."
