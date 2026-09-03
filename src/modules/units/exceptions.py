from src.exceptions import ConflictError, NotFoundError


class UnitNotFound(NotFoundError):
    error_code = "unit_not_found"
    detail = "Unit not found."


class UnitCodeConflict(ConflictError):
    error_code = "unit_code_conflict"
    detail = "A unit with this code already exists."


class UnitInUse(ConflictError):
    error_code = "unit_in_use"
    detail = "A referenced unit cannot be reclassified, renamed by code, or deactivated."
