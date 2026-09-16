from src.exceptions import ConflictError, NotFoundError


class MembershipNotFound(NotFoundError):
    def __init__(self) -> None:
        super().__init__("Organization membership not found.")


class MembershipConflict(ConflictError):
    def __init__(self) -> None:
        super().__init__("User is already a member of this organization.")
