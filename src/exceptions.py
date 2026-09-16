from typing import Any

from fastapi import status


class AppException(Exception):
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"
    detail: str = "An unexpected error occurred."

    def __init__(
        self,
        detail: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        if detail is not None:
            self.detail = detail
        self.details = details
        super().__init__(self.detail)


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"
    detail = "Resource not found."


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"
    detail = "Resource already exists."


class UnauthorizedError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"
    detail = "Authentication required."


class ForbiddenError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"
    detail = "You do not have permission to perform this action."


class InvalidCredentials(UnauthorizedError):
    """Shared invalid-login response shape for organization membership auth."""

    error_code = "invalid_credentials"
    detail = "Incorrect email or password."


class InvalidToken(UnauthorizedError):
    error_code = "invalid_token"
    detail = "Token is missing, invalid, or expired."


class InvalidCurrentPassword(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_current_password"
    detail = "Current password is incorrect."
