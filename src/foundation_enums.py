from enum import StrEnum


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    DISABLED = "disabled"
    DELETED = "deleted"


class MembershipStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    REMOVED = "removed"


class ActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"
    SERVICE = "service"
    API_KEY = "api_key"
