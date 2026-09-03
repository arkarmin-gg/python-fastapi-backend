from enum import StrEnum

OWNER_ROLE_CODE = "owner"


class ActionType(StrEnum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"


FOUNDATION_PERMISSION_MODULES = (
    "tenants",
    "employees",
    "users",
    "roles",
    "permissions",
    "audit_logs",
    "units",
    "product_categories",
    "catalog",
    "price_levels",
    "price_rules",
    "customers",
    "customer_payments",
    "suppliers",
    "supplier_payments",
    "locations",
    "location_assignments",
    "purchase_invoices",
    "stock_adjustments",
    "stock_counts",
    "stock_transfers",
    "repack_orders",
    "sales_invoices",
    "inventory",
    "analytics",
)


MODULE_EXTRA_ACTIONS: dict[str, tuple[str, ...]] = {
    "customer_payments": ("reverse",),
    "sales_invoices": ("create_credit",),
    "supplier_payments": ("reverse",),
}


def permission_code(module: str, action: ActionType) -> str:
    return f"{module}.{action.value}"


def extra_permission_code(module: str, action: str) -> str:
    return f"{module}.{action}"
