import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Query

from src.foundation_enums import PaymentMethod
from src.pagination import Page
from src.query_filters import DEFAULT_DATE_FILTER_TIMEZONE, build_query_model, query_value_error
from src.schemas import RequestSchema, ResponseSchema

DEFAULT_DATE_RANGE_DAYS = 30
MAX_DATE_RANGE_DAYS = 366
UNSPECIFIED_PAYMENT_METHOD = "unspecified"


def _today() -> date:
    return datetime.now(ZoneInfo(DEFAULT_DATE_FILTER_TIMEZONE)).date()


def resolve_date_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Fill in a missing date_from/date_to and enforce a sane, bounded span.

    Both ends are plain calendar dates because the underlying columns
    (invoice_date, payment_date) are dates, not timestamps - there is no
    per-tenant timezone conversion to do here, only a default "today" for an
    omitted bound.
    """
    resolved_to = date_to if date_to is not None else _today()
    resolved_from = (
        date_from
        if date_from is not None
        else resolved_to - timedelta(days=DEFAULT_DATE_RANGE_DAYS - 1)
    )
    if resolved_to < resolved_from:
        raise query_value_error("date_to", "date_to must not be before date_from")
    if (resolved_to - resolved_from).days + 1 > MAX_DATE_RANGE_DAYS:
        raise query_value_error("date_to", f"date range must not exceed {MAX_DATE_RANGE_DAYS} days")
    return resolved_from, resolved_to


class AnalyticsGroupBy(StrEnum):
    LOCATION = "location"


class TimeseriesGranularity(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class TopProductsSortBy(StrEnum):
    REVENUE = "revenue"
    QUANTITY = "quantity"


# --- Sales -------------------------------------------------------------


class SalesRangeFilters(RequestSchema):
    date_from: date
    date_to: date
    location_id: uuid.UUID | None = None


def sales_range_filters(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
) -> SalesRangeFilters:
    resolved_from, resolved_to = resolve_date_range(date_from, date_to)
    return build_query_model(
        SalesRangeFilters,
        date_from=resolved_from,
        date_to=resolved_to,
        location_id=location_id,
    )


class SalesSummaryRow(ResponseSchema):
    location_id: uuid.UUID | None = None
    location_name: str | None = None
    revenue: Decimal
    invoice_count: int
    average_basket: Decimal


class SalesTimeseriesPoint(ResponseSchema):
    period_start: date
    location_id: uuid.UUID | None = None
    location_name: str | None = None
    revenue: Decimal
    invoice_count: int


class PaymentMethodBreakdownRow(ResponseSchema):
    payment_method: str
    revenue: Decimal
    transaction_count: int


# --- Inventory -----------------------------------------------------------


class LowStockFilters(RequestSchema):
    location_id: uuid.UUID | None = None
    search: str | None = None


def low_stock_filters(
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> LowStockFilters:
    return build_query_model(LowStockFilters, location_id=location_id, search=search)


class LowStockRow(ResponseSchema):
    product_variant_id: uuid.UUID
    product_variant_sku: str
    product_variant_name: str
    location_id: uuid.UUID
    location_name: str
    quantity_base: Decimal
    low_stock_quantity_base: Decimal
    shortage_quantity_base: Decimal


LowStockListResponse = Page[LowStockRow]


class TopProductsFilters(RequestSchema):
    date_from: date
    date_to: date
    location_id: uuid.UUID | None = None
    sort_by: TopProductsSortBy = TopProductsSortBy.REVENUE
    limit: int = 10


def top_products_filters(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    sort_by: Annotated[TopProductsSortBy, Query()] = TopProductsSortBy.REVENUE,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> TopProductsFilters:
    resolved_from, resolved_to = resolve_date_range(date_from, date_to)
    return build_query_model(
        TopProductsFilters,
        date_from=resolved_from,
        date_to=resolved_to,
        location_id=location_id,
        sort_by=sort_by,
        limit=limit,
    )


class TopProductRow(ResponseSchema):
    product_variant_id: uuid.UUID
    product_variant_sku: str
    product_variant_name: str
    quantity_sold_base: Decimal
    revenue: Decimal


# --- Financials ------------------------------------------------------------


class PartyBalanceFilters(RequestSchema):
    search: str | None = None


def party_balance_filters(
    search: Annotated[str | None, Query()] = None,
) -> PartyBalanceFilters:
    return build_query_model(PartyBalanceFilters, search=search)


class CustomerBalanceRow(ResponseSchema):
    customer_id: uuid.UUID
    customer_code: str
    customer_name: str
    balance_amount: Decimal


class ReceivablesRead(Page[CustomerBalanceRow]):
    total_outstanding: Decimal


class SupplierBalanceRow(ResponseSchema):
    supplier_id: uuid.UUID
    supplier_code: str
    supplier_name: str
    balance_amount: Decimal


class PayablesRead(Page[SupplierBalanceRow]):
    total_outstanding: Decimal


class CashFlowFilters(RequestSchema):
    date_from: date
    date_to: date


def cash_flow_filters(
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> CashFlowFilters:
    resolved_from, resolved_to = resolve_date_range(date_from, date_to)
    return build_query_model(CashFlowFilters, date_from=resolved_from, date_to=resolved_to)


class CashFlowMethodRow(ResponseSchema):
    payment_method: PaymentMethod
    cash_in: Decimal
    cash_out: Decimal


class CashFlowRead(ResponseSchema):
    date_from: date
    date_to: date
    total_cash_in: Decimal
    total_cash_out: Decimal
    net_cash_flow: Decimal
    by_payment_method: list[CashFlowMethodRow]
