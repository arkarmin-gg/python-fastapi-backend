from src.exceptions import ConflictError, NotFoundError


class EmployeeNotFound(NotFoundError):
    error_code = "employee_not_found"
    detail = "Employee not found."


class EmployeeCodeConflict(ConflictError):
    error_code = "employee_code_conflict"
    detail = "An employee with this code already exists for the tenant."
