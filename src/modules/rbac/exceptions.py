from fastapi import status

from src.exceptions import AppException, ConflictError, ForbiddenError, NotFoundError


class PermissionDenied(ForbiddenError):
    error_code = "permission_denied"
    detail = "You do not have permission to perform this action."


class RoleNotFound(NotFoundError):
    error_code = "role_not_found"
    detail = "Role not found."


class PermissionNotFound(NotFoundError):
    error_code = "permission_not_found"
    detail = "Permission not found."


class RolePermissionNotFound(NotFoundError):
    error_code = "role_permission_not_found"
    detail = "Role permission assignment not found."


class MembershipRoleNotFound(NotFoundError):
    error_code = "user_role_not_found"
    detail = "Membership role assignment not found."


class RoleCodeConflict(ConflictError):
    error_code = "role_code_conflict"
    detail = "A role with this code already exists for the organization."


class RolePermissionConflict(ConflictError):
    error_code = "role_permission_conflict"
    detail = "This permission is already assigned to the role."


class MembershipRoleConflict(ConflictError):
    error_code = "user_role_conflict"
    detail = "This role is already assigned to the membership."


class InvalidPermission(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_permission"
    detail = "One or more permissions do not exist."


class InvalidRole(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_role"
    detail = "Role must be active and belong to the organization."


class InvalidUser(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "invalid_user"
    detail = "Membership must be active in this organization."


class ProtectedRole(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "protected_role"
    detail = "System roles cannot be deactivated or deleted."


class RoleAssigned(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "role_assigned"
    detail = "Role is assigned to at least one active membership."
