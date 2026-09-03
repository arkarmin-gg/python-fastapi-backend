from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"


class UnitKind(StrEnum):
    WEIGHT = "weight"
    COUNT = "count"
    VOLUME = "volume"
    PACKAGE = "package"
    LENGTH = "length"
    OTHER = "other"


class ProductType(StrEnum):
    STANDARD = "standard"
    BULK = "bulk"
    PACKAGED = "packaged"
    ALCOHOL = "alcohol"
    SERVICE = "service"


class CatalogItemKind(StrEnum):
    STOCKED = "stocked"
    SERVICE = "service"
    COMPOSITE = "composite"


class PosTileShape(StrEnum):
    SQUARE = "square"
    CIRCLE = "circle"
    SCALLOP = "scallop"
    HEXAGON = "hexagon"


class PartyStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


class CustomerType(StrEnum):
    WALK_IN = "walk_in"
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    RESTAURANT = "restaurant"
    HOTEL = "hotel"
    RESELLER = "reseller"
    OTHER = "other"


class SupplierType(StrEnum):
    LOCAL = "local"
    IMPORTER = "importer"
    WHOLESALER = "wholesaler"
    MANUFACTURER = "manufacturer"
    OTHER = "other"


class LocationType(StrEnum):
    WAREHOUSE = "warehouse"
    STORE = "store"
    SUB_WAREHOUSE = "sub_warehouse"
    COUNTER = "counter"
    DAMAGED = "damaged"
    IN_TRANSIT = "in_transit"
    VIRTUAL = "virtual"


class AssignmentRole(StrEnum):
    RESPONSIBLE = "responsible"
    ASSISTANT = "assistant"
    CHECKER = "checker"


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    POSTED = "posted"
    CANCELLED = "cancelled"
    REVERSED = "reversed"
    REJECTED = "rejected"


class PurchaseLandedCostType(StrEnum):
    TRANSPORT = "transport"
    LOADING = "loading"
    UNLOADING = "unloading"
    CUSTOMS = "customs"
    TAX = "tax"
    OTHER = "other"


class LandedCostAllocationMethod(StrEnum):
    BY_VALUE = "by_value"
    BY_BASE_QUANTITY = "by_base_quantity"
    MANUAL = "manual"


class StockBatchStatus(StrEnum):
    ACTIVE = "active"
    DEPLETED = "depleted"
    CANCELLED = "cancelled"


class StockAdjustmentReason(StrEnum):
    COUNT_VARIANCE = "count_variance"
    DAMAGE = "damage"
    LOSS = "loss"
    EXPIRY = "expiry"
    CORRECTION = "correction"
    OPENING_BALANCE = "opening_balance"
    OTHER = "other"


class StockMovementType(StrEnum):
    PURCHASE_RECEIVE = "purchase_receive"
    SALE_ISSUE = "sale_issue"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    REPACK_INPUT = "repack_input"
    REPACK_OUTPUT = "repack_output"
    ADJUSTMENT = "adjustment"
    COUNT_ADJUSTMENT = "count_adjustment"
    DAMAGE_LOSS = "damage_loss"
    REVERSAL = "reversal"


class SourceType(StrEnum):
    PURCHASE_INVOICE = "purchase_invoice"
    SALES_INVOICE = "sales_invoice"
    STOCK_TRANSFER = "stock_transfer"
    STOCK_ADJUSTMENT = "stock_adjustment"
    STOCK_COUNT = "stock_count"
    REPACK_ORDER = "repack_order"
    CUSTOMER_PAYMENT = "customer_payment"
    SUPPLIER_PAYMENT = "supplier_payment"
    MANUAL = "manual"


class PaymentMethod(StrEnum):
    CASH = "cash"
    BANK = "bank"
    MOBILE_MONEY = "mobile_money"
    CARD = "card"
    OTHER = "other"


class CustomerLedgerEntryType(StrEnum):
    INVOICE = "invoice"
    PAYMENT = "payment"
    ADJUSTMENT = "adjustment"
    REVERSAL = "reversal"


class SupplierLedgerEntryType(StrEnum):
    INVOICE = "invoice"
    PAYMENT = "payment"
    ADJUSTMENT = "adjustment"
    REVERSAL = "reversal"
