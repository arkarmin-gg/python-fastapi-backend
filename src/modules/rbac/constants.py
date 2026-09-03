from enum import StrEnum

OWNER_ROLE_CODE = "owner"


class ActionType(StrEnum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


FOUNDATION_PERMISSION_MODULES = (
    "tenants",
    "users",
    "roles",
    "permissions",
    "audit_logs",
)


MODULE_EXTRA_ACTIONS: dict[str, tuple[str, ...]] = {}


def permission_code(module: str, action: ActionType) -> str:
    return f"{module}.{action.value}"


def extra_permission_code(module: str, action: str) -> str:
    return f"{module}.{action}"
