from fastapi import status

from src.exceptions import AppException, ConflictError, NotFoundError


class LocationNotFound(NotFoundError):
    error_code = "location_not_found"
    detail = "Location not found."


class LocationCodeConflict(ConflictError):
    error_code = "location_code_conflict"
    detail = "A location with this code already exists for the tenant."


class InvalidParentLocation(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_parent_location"
    detail = "Parent location must be an active location in the same tenant."
