from fastapi import status

from src.exceptions import AppException, NotFoundError


class LocationAssignmentNotFound(NotFoundError):
    error_code = "location_assignment_not_found"
    detail = "Location assignment not found."


class InvalidLocationAssignmentLocation(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_location_assignment_location"
    detail = "Location must be an active location in the same tenant."


class InvalidLocationAssignmentEmployee(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_location_assignment_employee"
    detail = "Employee must be an active employee in the same tenant."


class InvalidLocationAssignmentPeriod(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_location_assignment_period"
    detail = "Assignment end date must be on or after the start date."


class LocationAssignmentOverlapConflict(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "location_assignment_overlap_conflict"
    detail = "An overlapping assignment already exists for this location and role."
