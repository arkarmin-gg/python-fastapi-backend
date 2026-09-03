import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from fastapi import Query

from src.foundation_enums import SourceType, StockBatchStatus, StockMovementType
from src.pagination import Page
from src.query_filters import build_query_model, parse_datetime_range, query_value_error
from src.schemas import RequestSchema, ResponseSchema


class StockMovementBatchRead(ResponseSchema):
    id: uuid.UUID
    lot_number: str | None
    received_at: datetime
    expiry_date: date | None
    status: StockBatchStatus


class StockBalanceBatchRead(ResponseSchema):
    id: uuid.UUID
    lot_number: str | None
    received_at: datetime
    expiry_date: date | None
    status: StockBatchStatus


class StockBatchRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_variant_id: uuid.UUID | None
    product_variant_sku: str
    product_variant_name: str
    source_type: SourceType
    source_id: uuid.UUID
    source_line_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    supplier_name: str | None
    received_at: datetime
    expiry_date: date | None
    manufactured_date: date | None
    lot_number: str | None
    initial_quantity_base: Decimal
    unit_cost_base: Decimal
    total_cost: Decimal
    conversion_to_base: Decimal | None
    status: StockBatchStatus
    created_at: datetime


StockBatchListResponse = Page[StockBatchRead]


class StockBatchFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    source_type: SourceType | None = None
    source_id: uuid.UUID | None = None
    status: StockBatchStatus | None = None
    expiry_date_gte: date | None = None
    expiry_date_lte: date | None = None


def stock_batch_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    supplier_id: Annotated[uuid.UUID | None, Query()] = None,
    source_type: Annotated[SourceType | None, Query()] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[StockBatchStatus | None, Query()] = None,
    expiry_date_gte: Annotated[date | None, Query()] = None,
    expiry_date_lte: Annotated[date | None, Query()] = None,
) -> StockBatchFilters:
    return build_query_model(
        StockBatchFilters,
        product_variant_id=product_variant_id,
        supplier_id=supplier_id,
        source_type=source_type,
        source_id=source_id,
        status=status,
        expiry_date_gte=expiry_date_gte,
        expiry_date_lte=expiry_date_lte,
    )


class StockMovementRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    movement_type: StockMovementType
    source_type: SourceType
    source_id: uuid.UUID
    source_line_id: uuid.UUID | None
    product_variant_id: uuid.UUID | None
    product_variant_sku: str
    product_variant_name: str
    stock_batch_id: uuid.UUID
    stock_batch: StockMovementBatchRead
    location_id: uuid.UUID
    location_name: str
    quantity_base: Decimal
    unit_cost_base: Decimal | None
    total_cost: Decimal | None
    notes: str | None
    posted_at: datetime
    posted_by: uuid.UUID
    posted_by_name: str
    created_at: datetime


StockMovementListResponse = Page[StockMovementRead]


class StockMovementFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    movement_type: StockMovementType | None = None
    source_type: SourceType | None = None
    source_id: uuid.UUID | None = None
    posted_at_gte: datetime | None = None
    posted_at_lte: datetime | None = None


def stock_movement_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    stock_batch_id: Annotated[uuid.UUID | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    movement_type: Annotated[StockMovementType | None, Query()] = None,
    source_type: Annotated[SourceType | None, Query()] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    posted_at_gte: Annotated[str | None, Query()] = None,
    posted_at_lte: Annotated[str | None, Query()] = None,
) -> StockMovementFilters:
    parsed_gte, parsed_lte = parse_datetime_range(
        posted_at_gte,
        posted_at_lte,
        from_field="posted_at_gte",
        to_field="posted_at_lte",
    )
    return build_query_model(
        StockMovementFilters,
        product_variant_id=product_variant_id,
        stock_batch_id=stock_batch_id,
        location_id=location_id,
        movement_type=movement_type,
        source_type=source_type,
        source_id=source_id,
        posted_at_gte=parsed_gte,
        posted_at_lte=parsed_lte,
    )


class StockBalanceRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    product_variant_id: uuid.UUID | None
    product_variant_sku: str
    product_variant_name: str
    location_id: uuid.UUID
    location_name: str
    stock_batch_id: uuid.UUID
    stock_batch: StockBalanceBatchRead
    quantity_base: Decimal
    unit_id: uuid.UUID
    unit_code: str
    unit_name: str
    display_quantity: Decimal | None = None
    display_unit_id: uuid.UUID | None = None
    display_unit_code: str | None = None
    display_unit_name: str | None = None
    purchase_unit_quantity: Decimal | None = None
    purchase_unit_id: uuid.UUID | None = None
    purchase_unit_code: str | None = None
    purchase_unit_name: str | None = None
    updated_at: datetime


StockBalanceListResponse = Page[StockBalanceRead]


class StockBalanceSummaryRead(ResponseSchema):
    product_variant_id: uuid.UUID
    product_variant_sku: str
    product_variant_name: str
    location_id: uuid.UUID | None = None
    location_name: str | None = None
    unit_id: uuid.UUID
    unit_code: str
    unit_name: str
    quantity_base: Decimal
    display_quantity: Decimal | None = None
    display_unit_id: uuid.UUID | None = None
    display_unit_code: str | None = None
    display_unit_name: str | None = None
    purchase_unit_quantity: Decimal | None = None
    purchase_unit_id: uuid.UUID | None = None
    purchase_unit_code: str | None = None
    purchase_unit_name: str | None = None
    updated_at: datetime


StockBalanceSummaryListResponse = Page[StockBalanceSummaryRead]


class StockBalanceGroupBy(StrEnum):
    PRODUCT_VARIANT = "product_variant"
    PRODUCT_VARIANT_LOCATION = "product_variant_location"


class StockBalanceFilters(RequestSchema):
    product_variant_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    stock_batch_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    search: str | None = None
    batch_status: StockBatchStatus | None = StockBatchStatus.ACTIVE


def _parse_batch_status_filter(value: str | None) -> StockBatchStatus | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "all":
        return None
    try:
        return StockBatchStatus(normalized)
    except ValueError as exc:
        raise query_value_error(
            "batch_status",
            "batch_status must be one of: active, depleted, cancelled, all",
        ) from exc


def stock_balance_filters(
    product_variant_id: Annotated[uuid.UUID | None, Query()] = None,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    stock_batch_id: Annotated[uuid.UUID | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    batch_status: Annotated[
        str | None, Query(description="active, depleted, cancelled, or all")
    ] = "active",
) -> StockBalanceFilters:
    return build_query_model(
        StockBalanceFilters,
        product_variant_id=product_variant_id,
        location_id=location_id,
        stock_batch_id=stock_batch_id,
        category_id=category_id,
        search=search,
        batch_status=_parse_batch_status_filter(batch_status),
    )
