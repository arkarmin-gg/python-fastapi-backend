import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.decimal_utils import quantize_to_increment
from src.modules.catalog.models import CatalogItem, ProductVariant, VariantBarcode, VariantUnit
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.inventory.schemas import (
    StockBalanceFilters,
    StockBalanceGroupBy,
    StockBalanceRead,
    StockBalanceSummaryRead,
    StockBatchFilters,
    StockMovementFilters,
)
from src.modules.locations.models import Location
from src.modules.units.models import Unit
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import (
    SortSpec,
    apply_sort,
    normalize_search,
    where_gte_if_not_none,
    where_lte_if_not_none,
)

ZERO = Decimal("0")

STOCK_BATCH_SORT_COLUMNS = {
    "received_at": StockBatch.received_at,
    "product_variant_id": StockBatch.product_variant_id,
    "expiry_date": StockBatch.expiry_date,
    "id": StockBatch.id,
}
STOCK_MOVEMENT_SORT_COLUMNS = {
    "posted_at": StockMovement.posted_at,
    "product_variant_id": StockMovement.product_variant_id,
    "movement_type": StockMovement.movement_type,
    "id": StockMovement.id,
}
STOCK_BALANCE_SORT_COLUMNS = {
    "product_variant_id": StockBalance.product_variant_id,
    "location_id": StockBalance.location_id,
    "updated_at": StockBalance.updated_at,
    "quantity_base": StockBalance.quantity_base,
    "id": StockBalance.id,
    "product_variant_name": ProductVariant.name,
    "location_name": Location.name,
    "expiry_date": StockBatch.expiry_date,
}


STOCK_BATCH_RELATED_OPTIONS = (
    joinedload(StockBatch.product_variant),
    joinedload(StockBatch.supplier),
)
STOCK_MOVEMENT_RELATED_OPTIONS = (
    joinedload(StockMovement.product_variant),
    joinedload(StockMovement.stock_batch),
    joinedload(StockMovement.location),
    joinedload(StockMovement.posted_by_user),
)
STOCK_BALANCE_RELATED_OPTIONS = (
    joinedload(StockBalance.product_variant).joinedload(ProductVariant.base_unit),
    joinedload(StockBalance.stock_batch),
    joinedload(StockBalance.location),
)


async def get_stock_batch_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
) -> StockBatch | None:
    return await db.scalar(
        select(StockBatch)
        .options(*STOCK_BATCH_RELATED_OPTIONS)
        .where(StockBatch.tenant_id == tenant_id, StockBatch.id == stock_batch_id)
    )


async def list_stock_batches(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockBatchFilters,
    sort: tuple[SortSpec, ...],
) -> Page[StockBatch]:
    stmt = _apply_stock_batch_filters(
        select(StockBatch)
        .options(*STOCK_BATCH_RELATED_OPTIONS)
        .where(StockBatch.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, STOCK_BATCH_SORT_COLUMNS)
    count_stmt = _apply_stock_batch_filters(
        select(func.count(StockBatch.id)).where(StockBatch.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_stock_movement_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_movement_id: uuid.UUID,
) -> StockMovement | None:
    return await db.scalar(
        select(StockMovement)
        .options(*STOCK_MOVEMENT_RELATED_OPTIONS)
        .where(
            StockMovement.tenant_id == tenant_id,
            StockMovement.id == stock_movement_id,
        )
    )


async def list_stock_movements(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockMovementFilters,
    sort: tuple[SortSpec, ...],
) -> Page[StockMovement]:
    stmt = _apply_stock_movement_filters(
        select(StockMovement)
        .options(*STOCK_MOVEMENT_RELATED_OPTIONS)
        .where(StockMovement.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, STOCK_MOVEMENT_SORT_COLUMNS)
    count_stmt = _apply_stock_movement_filters(
        select(func.count(StockMovement.id)).where(StockMovement.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_stock_balance_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_balance_id: uuid.UUID,
    *,
    display_unit_id: uuid.UUID | None = None,
) -> StockBalanceRead | None:
    balance = await db.scalar(
        select(StockBalance)
        .options(*STOCK_BALANCE_RELATED_OPTIONS)
        .where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.id == stock_balance_id,
        )
    )
    if balance is None:
        return None
    display_units = await _resolve_display_units(
        db, tenant_id, {balance.product_variant_id}, display_unit_id
    )
    purchase_units = await _resolve_purchase_units(db, tenant_id, {balance.product_variant_id})
    return _to_stock_balance_read(
        balance,
        display_units.get(balance.product_variant_id),
        purchase_units.get(balance.product_variant_id),
    )


async def list_stock_balances(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockBalanceFilters,
    sort: tuple[SortSpec, ...],
    *,
    include_zero: bool = False,
    group_by: StockBalanceGroupBy | None = None,
    display_unit_id: uuid.UUID | None = None,
) -> Page[StockBalanceRead] | Page[StockBalanceSummaryRead]:
    if group_by is not None:
        return await _list_stock_balances_grouped(
            db,
            tenant_id,
            pagination,
            filters,
            sort,
            include_zero=include_zero,
            group_by=group_by,
            display_unit_id=display_unit_id,
        )

    base_where = (
        select(StockBalance)
        .join(ProductVariant, StockBalance.product_variant_id == ProductVariant.id)
        .join(StockBatch, StockBalance.stock_batch_id == StockBatch.id)
        .join(Location, StockBalance.location_id == Location.id)
        .where(StockBalance.tenant_id == tenant_id)
    )
    stmt = _apply_stock_balance_filters(
        base_where.options(*STOCK_BALANCE_RELATED_OPTIONS),
        filters,
    )
    if not include_zero:
        stmt = stmt.where(StockBalance.quantity_base > ZERO)
    stmt = apply_sort(stmt, sort, STOCK_BALANCE_SORT_COLUMNS)

    count_base = (
        select(func.count(StockBalance.id))
        .join(ProductVariant, StockBalance.product_variant_id == ProductVariant.id)
        .join(StockBatch, StockBalance.stock_batch_id == StockBatch.id)
        .join(Location, StockBalance.location_id == Location.id)
        .where(StockBalance.tenant_id == tenant_id)
    )
    count_stmt = _apply_stock_balance_filters(count_base, filters)
    if not include_zero:
        count_stmt = count_stmt.where(StockBalance.quantity_base > ZERO)

    page = await paginate(db, stmt, count_stmt, pagination)

    variant_ids = {balance.product_variant_id for balance in page.items}
    display_units = await _resolve_display_units(db, tenant_id, variant_ids, display_unit_id)
    purchase_units = await _resolve_purchase_units(db, tenant_id, variant_ids)
    items = [
        _to_stock_balance_read(
            balance,
            display_units.get(balance.product_variant_id),
            purchase_units.get(balance.product_variant_id),
        )
        for balance in page.items
    ]
    return Page[StockBalanceRead](
        items=items, total=page.total, limit=page.limit, offset=page.offset
    )


async def _list_stock_balances_grouped(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockBalanceFilters,
    sort: tuple[SortSpec, ...],
    *,
    include_zero: bool,
    group_by: StockBalanceGroupBy,
    display_unit_id: uuid.UUID | None,
) -> Page[StockBalanceSummaryRead]:
    by_location = group_by is StockBalanceGroupBy.PRODUCT_VARIANT_LOCATION

    quantity_sum = func.sum(StockBalance.quantity_base).label("quantity_base")
    updated_at_max = func.max(StockBalance.updated_at).label("updated_at")

    columns: list[Any] = [
        StockBalance.product_variant_id.label("product_variant_id"),
        ProductVariant.sku.label("product_variant_sku"),
        ProductVariant.name.label("product_variant_name"),
        ProductVariant.base_unit_id.label("unit_id"),
        Unit.code.label("unit_code"),
        Unit.name_en.label("unit_name"),
        quantity_sum,
        updated_at_max,
    ]
    group_columns: list[Any] = [
        StockBalance.product_variant_id,
        ProductVariant.sku,
        ProductVariant.name,
        ProductVariant.base_unit_id,
        Unit.code,
        Unit.name_en,
    ]
    sort_columns: dict[str, Any] = {
        "product_variant_id": StockBalance.product_variant_id,
        "product_variant_name": ProductVariant.name,
        "quantity_base": quantity_sum,
    }
    if by_location:
        columns.append(StockBalance.location_id.label("location_id"))
        columns.append(Location.name.label("location_name"))
        group_columns.append(StockBalance.location_id)
        group_columns.append(Location.name)
        sort_columns["location_id"] = StockBalance.location_id
        sort_columns["location_name"] = Location.name

    stmt = (
        select(*columns)
        .join(ProductVariant, StockBalance.product_variant_id == ProductVariant.id)
        .join(Unit, ProductVariant.base_unit_id == Unit.id)
        .join(StockBatch, StockBalance.stock_batch_id == StockBatch.id)
        .where(StockBalance.tenant_id == tenant_id)
    )
    if by_location:
        stmt = stmt.join(Location, StockBalance.location_id == Location.id)

    stmt = _apply_stock_balance_filters(stmt, filters)
    stmt = stmt.group_by(*group_columns)
    if not include_zero:
        stmt = stmt.having(quantity_sum > ZERO)

    count_stmt = select(func.count()).select_from(stmt.subquery())

    stmt = apply_sort(stmt, _grouped_sort_specs(sort, sort_columns), sort_columns)
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.all()
    total = await db.scalar(count_stmt) or 0

    row_variant_ids = {row.product_variant_id for row in rows}
    display_units = await _resolve_display_units(db, tenant_id, row_variant_ids, display_unit_id)
    purchase_units = await _resolve_purchase_units(db, tenant_id, row_variant_ids)
    items = [
        StockBalanceSummaryRead.model_validate(row).model_copy(
            update={
                **_display_fields(row.quantity_base, display_units.get(row.product_variant_id)),
                **_purchase_unit_fields(
                    row.quantity_base, purchase_units.get(row.product_variant_id)
                ),
            }
        )
        for row in rows
    ]
    return Page[StockBalanceSummaryRead](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


def _grouped_sort_specs(
    sort: tuple[SortSpec, ...],
    sort_columns: dict[str, Any],
) -> list[SortSpec]:
    filtered = [spec for spec in sort if spec.field in sort_columns]
    return filtered or [SortSpec(field="product_variant_id")]


async def _resolve_display_units(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_ids: set[uuid.UUID],
    display_unit_id: uuid.UUID | None,
) -> dict[uuid.UUID, VariantUnit]:
    if display_unit_id is None or not product_variant_ids:
        return {}
    rows = await db.scalars(
        select(VariantUnit)
        .options(joinedload(VariantUnit.unit))
        .where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.product_variant_id.in_(product_variant_ids),
            VariantUnit.unit_id == display_unit_id,
            VariantUnit.is_active.is_(True),
        )
    )
    return {row.product_variant_id: row for row in rows}


def _display_fields(
    quantity_base: Decimal,
    variant_unit: VariantUnit | None,
) -> dict[str, Any]:
    if variant_unit is None:
        return {
            "display_quantity": None,
            "display_unit_id": None,
            "display_unit_code": None,
            "display_unit_name": None,
        }
    raw_quantity = quantity_base / variant_unit.conversion_to_base
    return {
        "display_quantity": quantize_to_increment(raw_quantity, variant_unit.rounding_precision),
        "display_unit_id": variant_unit.unit_id,
        "display_unit_code": variant_unit.unit.code,
        "display_unit_name": variant_unit.unit.name_en,
    }


async def _resolve_purchase_units(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_ids: set[uuid.UUID],
) -> dict[uuid.UUID, VariantUnit]:
    """Auto-resolve each variant's own purchase unit, independent of any
    caller-chosen display unit. If a variant has more than one active unit
    flagged ``is_purchase_unit``, the one with the largest
    ``conversion_to_base`` wins (the most "bulk" unit)."""
    if not product_variant_ids:
        return {}
    rows = await db.scalars(
        select(VariantUnit)
        .options(joinedload(VariantUnit.unit))
        .where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.product_variant_id.in_(product_variant_ids),
            VariantUnit.is_purchase_unit.is_(True),
            VariantUnit.is_active.is_(True),
        )
    )
    resolved: dict[uuid.UUID, VariantUnit] = {}
    for row in rows:
        current = resolved.get(row.product_variant_id)
        if current is None or row.conversion_to_base > current.conversion_to_base:
            resolved[row.product_variant_id] = row
    return resolved


def _purchase_unit_fields(
    quantity_base: Decimal,
    variant_unit: VariantUnit | None,
) -> dict[str, Any]:
    if variant_unit is None:
        return {
            "purchase_unit_quantity": None,
            "purchase_unit_id": None,
            "purchase_unit_code": None,
            "purchase_unit_name": None,
        }
    raw_quantity = quantity_base / variant_unit.conversion_to_base
    return {
        "purchase_unit_quantity": quantize_to_increment(
            raw_quantity, variant_unit.rounding_precision
        ),
        "purchase_unit_id": variant_unit.unit_id,
        "purchase_unit_code": variant_unit.unit.code,
        "purchase_unit_name": variant_unit.unit.name_en,
    }


def _to_stock_balance_read(
    balance: StockBalance,
    display_variant_unit: VariantUnit | None,
    purchase_variant_unit: VariantUnit | None,
) -> StockBalanceRead:
    return StockBalanceRead.model_validate(balance).model_copy(
        update={
            **_display_fields(balance.quantity_base, display_variant_unit),
            **_purchase_unit_fields(balance.quantity_base, purchase_variant_unit),
        }
    )


def _apply_stock_batch_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: StockBatchFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(StockBatch.product_variant_id == filters.product_variant_id)
    if filters.supplier_id is not None:
        stmt = stmt.where(StockBatch.supplier_id == filters.supplier_id)
    if filters.source_type is not None:
        stmt = stmt.where(StockBatch.source_type == filters.source_type)
    if filters.source_id is not None:
        stmt = stmt.where(StockBatch.source_id == filters.source_id)
    if filters.status is not None:
        stmt = stmt.where(StockBatch.status == filters.status)
    stmt = where_gte_if_not_none(stmt, StockBatch.expiry_date, filters.expiry_date_gte)
    stmt = where_lte_if_not_none(stmt, StockBatch.expiry_date, filters.expiry_date_lte)
    return stmt


def _apply_stock_movement_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: StockMovementFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(StockMovement.product_variant_id == filters.product_variant_id)
    if filters.stock_batch_id is not None:
        stmt = stmt.where(StockMovement.stock_batch_id == filters.stock_batch_id)
    if filters.location_id is not None:
        stmt = stmt.where(StockMovement.location_id == filters.location_id)
    if filters.movement_type is not None:
        stmt = stmt.where(StockMovement.movement_type == filters.movement_type)
    if filters.source_type is not None:
        stmt = stmt.where(StockMovement.source_type == filters.source_type)
    if filters.source_id is not None:
        stmt = stmt.where(StockMovement.source_id == filters.source_id)
    stmt = where_gte_if_not_none(stmt, StockMovement.posted_at, filters.posted_at_gte)
    stmt = where_lte_if_not_none(stmt, StockMovement.posted_at, filters.posted_at_lte)
    return stmt


def _apply_stock_balance_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: StockBalanceFilters,
) -> StmtT:
    """Add WHERE clauses for stock-balance filters.

    Assumes the caller has already joined ``ProductVariant`` (needed for
    ``search``/``category_id``/name-based sorting regardless of whether those
    are used) and, when relevant, ``StockBatch``/``Location``.
    """
    if filters.product_variant_id is not None:
        stmt = stmt.where(StockBalance.product_variant_id == filters.product_variant_id)
    if filters.location_id is not None:
        stmt = stmt.where(StockBalance.location_id == filters.location_id)
    if filters.stock_batch_id is not None:
        stmt = stmt.where(StockBalance.stock_batch_id == filters.stock_batch_id)
    if filters.batch_status is not None:
        stmt = stmt.where(StockBatch.status == filters.batch_status)
    if filters.category_id is not None:
        stmt = stmt.join(CatalogItem, ProductVariant.catalog_item_id == CatalogItem.id).where(
            CatalogItem.category_id == filters.category_id
        )
    search = normalize_search(filters.search)
    if search is not None:
        pattern = _like_pattern(search)
        stmt = stmt.where(
            or_(
                ProductVariant.sku.ilike(pattern, escape="\\"),
                ProductVariant.name.ilike(pattern, escape="\\"),
                exists(
                    select(VariantBarcode.id).where(
                        VariantBarcode.product_variant_id == ProductVariant.id,
                        VariantBarcode.is_active.is_(True),
                        VariantBarcode.barcode.ilike(pattern, escape="\\"),
                    )
                ),
            )
        )
    return stmt


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
