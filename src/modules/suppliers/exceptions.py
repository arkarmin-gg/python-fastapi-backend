from src.exceptions import ConflictError, NotFoundError


class SupplierNotFound(NotFoundError):
    error_code = "supplier_not_found"
    detail = "Supplier not found."


class SupplierCodeConflict(ConflictError):
    error_code = "supplier_code_conflict"
    detail = "A supplier with this code already exists for the tenant."
