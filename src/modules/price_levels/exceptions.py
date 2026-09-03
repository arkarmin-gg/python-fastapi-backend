from src.exceptions import ConflictError, NotFoundError


class PriceLevelNotFound(NotFoundError):
    error_code = "price_level_not_found"
    detail = "Price level not found."


class PriceLevelCodeConflict(ConflictError):
    error_code = "price_level_code_conflict"
    detail = "A price level with this code already exists for the tenant."
