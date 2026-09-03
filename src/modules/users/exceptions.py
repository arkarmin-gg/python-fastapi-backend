from src.exceptions import ConflictError, NotFoundError


class UserNotFound(NotFoundError):
    error_code = "user_not_found"
    detail = "User not found."


class UserIdentifierConflict(ConflictError):
    error_code = "user_identifier_conflict"
    detail = "A user with this email already exists for the tenant."


class SelfDeactivateConflict(ConflictError):
    error_code = "user_self_deactivate"
    detail = "A user cannot self deactivate."


class InvalidRole(NotFoundError):
    error_code = "invalid_role"
    detail = "One or more roles were not found for this tenant."
