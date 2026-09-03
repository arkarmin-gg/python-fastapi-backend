from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.analytics import service
from src.modules.analytics.schemas import (
    AnalyticsGroupBy,
    CashFlowFilters,
    CashFlowRead,
    LowStockFilters,
    LowStockListResponse,
    PartyBalanceFilters,
    PayablesRead,
    PaymentMethodBreakdownRow,
    ReceivablesRead,
    SalesRangeFilters,
    SalesSummaryRow,
    SalesTimeseriesPoint,
    TimeseriesGranularity,
    TopProductRow,
    TopProductsFilters,
    cash_flow_filters,
    low_stock_filters,
    party_balance_filters,
    sales_range_filters,
    top_products_filters,
)
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/analytics", tags=["Analytics"])

AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
LOW_STOCK_SORT_FIELDS = {"shortage_quantity_base", "quantity_base", "product_variant_name", "id"}
LOW_STOCK_DEFAULT_SORT = ("-shortage_quantity_base", "id")
PARTY_BALANCE_SORT_FIELDS = {"balance_amount", "id"}
CUSTOMER_BALANCE_SORT_FIELDS = PARTY_BALANCE_SORT_FIELDS | {"customer_name"}
SUPPLIER_BALANCE_SORT_FIELDS = PARTY_BALANCE_SORT_FIELDS | {"supplier_name"}
PARTY_BALANCE_DEFAULT_SORT = ("-balance_amount", "id")


def low_stock_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=LOW_STOCK_SORT_FIELDS, default=LOW_STOCK_DEFAULT_SORT)


def receivables_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort, allowed_fields=CUSTOMER_BALANCE_SORT_FIELDS, default=PARTY_BALANCE_DEFAULT_SORT
    )


def payables_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(
        sort, allowed_fields=SUPPLIER_BALANCE_SORT_FIELDS, default=PARTY_BALANCE_DEFAULT_SORT
    )


@router.get(
    "/sales/summary",
    response_model=list[SalesSummaryRow],
    dependencies=[Depends(require_permission("analytics.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_sales_summary(
    db: DbSession,
    current: CurrentUser,
    filters: Annotated[SalesRangeFilters, Depends(sales_range_filters)],
    group_by: Annotated[AnalyticsGroupBy | None, Query()] = None,
):
    return await service.get_sales_summary(db, current.tenant_id, filters, group_by)


@router.get(
    "/sales/timeseries",
    response_model=list[SalesTimeseriesPoint],
    dependencies=[Depends(require_permission("analytics.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_sales_timeseries(
    db: DbSession,
    current: CurrentUser,
    filters: Annotated[SalesRangeFilters, Depends(sales_range_filters)],
    granularity: Annotated[TimeseriesGranularity, Query()] = TimeseriesGranularity.DAY,
    group_by: Annotated[AnalyticsGroupBy | None, Query()] = None,
):
    return await service.get_sales_timeseries(db, current.tenant_id, filters, granularity, group_by)


@router.get(
    "/sales/by-payment-method",
    response_model=list[PaymentMethodBreakdownRow],
    dependencies=[Depends(require_permission("analytics.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_sales_by_payment_method(
    db: DbSession,
    current: CurrentUser,
    filters: Annotated[SalesRangeFilters, Depends(sales_range_filters)],
):
    return await service.get_sales_by_payment_method(db, current.tenant_id, filters)


@router.get(
    "/inventory/low-stock",
    response_model=LowStockListResponse,
    dependencies=[Depends(require_permission("analytics.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_low_stock(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[LowStockFilters, Depends(low_stock_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(low_stock_sort)],
):
    return await service.get_low_stock(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/inventory/top-products",
    response_model=list[TopProductRow],
    dependencies=[Depends(require_permission("analytics.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_top_products(
    db: DbSession,
    current: CurrentUser,
    filters: Annotated[TopProductsFilters, Depends(top_products_filters)],
):
    return await service.get_top_products(db, current.tenant_id, filters)


@router.get(
    "/financials/receivables",
    response_model=ReceivablesRead,
    dependencies=[Depends(require_permission("analytics.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_receivables(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[PartyBalanceFilters, Depends(party_balance_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(receivables_sort)],
):
    return await service.get_receivables(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/financials/payables",
    response_model=PayablesRead,
    dependencies=[Depends(require_permission("analytics.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_payables(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[PartyBalanceFilters, Depends(party_balance_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(payables_sort)],
):
    return await service.get_payables(db, current.tenant_id, pagination, filters, sort)


@router.get(
    "/financials/cash-flow",
    response_model=CashFlowRead,
    dependencies=[Depends(require_permission("analytics.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def get_cash_flow(
    db: DbSession,
    current: CurrentUser,
    filters: Annotated[CashFlowFilters, Depends(cash_flow_filters)],
):
    return await service.get_cash_flow(db, current.tenant_id, filters)
