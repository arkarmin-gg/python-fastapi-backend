from src.exceptions import ConflictError, NotFoundError


class TenantNotFound(NotFoundError):
    error_code = "tenant_not_found"
    detail = "Tenant not found."


class TenantCodeConflict(ConflictError):
    error_code = "tenant_code_conflict"
    detail = "A tenant with this code already exists."
