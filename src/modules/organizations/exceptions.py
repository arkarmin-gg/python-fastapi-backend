from src.exceptions import ConflictError, NotFoundError


class OrganizationNotFound(NotFoundError):
    def __init__(self) -> None:
        super().__init__("Organization not found.")


class OrganizationCodeConflict(ConflictError):
    def __init__(self) -> None:
        super().__init__("Organization code already exists.")
