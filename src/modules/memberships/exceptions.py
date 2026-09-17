from src.exceptions import ConflictError, NotFoundError


class MembershipNotFound(NotFoundError):
    error_code = "membership_not_found"
    detail = "Organization membership not found."


class MembershipConflict(ConflictError):
    error_code = "membership_conflict"
    detail = "User is already a member of this organization."


class MembershipUserNotFound(NotFoundError):
    error_code = "membership_user_not_found"
    detail = "The requested global user identity was not found."


class InvalidMembershipTransition(ConflictError):
    error_code = "invalid_membership_transition"
    detail = "The requested membership status transition is not allowed."
