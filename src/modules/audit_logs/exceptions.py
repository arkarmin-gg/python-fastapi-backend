from src.exceptions import NotFoundError


class AuditLogNotFound(NotFoundError):
    error_code = "audit_log_not_found"
    detail = "Audit log not found."
