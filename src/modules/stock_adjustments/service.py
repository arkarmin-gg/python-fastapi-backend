import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.decimal_utils import quantity_base_for_unit
from src.foundation_enums import (
    DocumentStatus,
    SourceType,
    StockAdjustmentReason,
    StockBatchStatus,
    StockMovementType,
)
from src.modules.audit_logs.service import record_audit_log
from src.modules.catalog.models import ProductVariant, VariantUnit
from src.modules.document_numbers.service import generate_document_no, generate_lot_number
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.stock_adjustments.exceptions import (
    InvalidStockAdjustmentLineBatch,
    InvalidStockAdjustmentLineProduct,
    InvalidStockAdjustmentLineUnit,
    InvalidStockAdjustmentLocation,
    StockAdjustmentDocumentNoConflict,
    StockAdjustmentHasNoLines,
    StockAdjustmentLineBatchNotAllowed,
    StockAdjustmentLineBatchRequired,
    StockAdjustmentLineCostRequired,
    StockAdjustmentLineNoConflict,
    StockAdjustmentLineNotFound,
    StockAdjustmentNegativeBalance,
    StockAdjustmentNotCancellable,
    StockAdjustmentNotDraft,
    StockAdjustmentNotFound,
    StockAdjustmentNotPostable,
)
from src.modules.stock_adjustments.models import StockAdjustment, StockAdjustmentLine
from src.modules.stock_adjustments.schemas import (
    StockAdjustmentCreate,
    StockAdjustmentFilters,
    StockAdjustmentLineCreate,
    StockAdjustmentLineFilters,
    StockAdjustmentLineUpdate,
    StockAdjustmentUpdate,
)
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import (
    SortSpec,
    apply_sort,
    search_clause,
    where_gte_if_not_none,
    where_lte_if_not_none,
)

STOCK_ADJUSTMENT_SORT_COLUMNS = {
    "document_no": StockAdjustment.document_no,
    "reason": StockAdjustment.reason,
    "status": StockAdjustment.status,
    "created_at": StockAdjustment.created_at,
    "id": StockAdjustment.id,
}
STOCK_ADJUSTMENT_LINE_SORT_COLUMNS = {
    "line_no": StockAdjustmentLine.line_no,
    "product_variant_id": StockAdjustmentLine.product_variant_id,
    "stock_batch_id": StockAdjustmentLine.stock_batch_id,
    "variant_unit_id": StockAdjustmentLine.variant_unit_id,
    "id": StockAdjustmentLine.id,
}
ZERO = Decimal("0")
DAMAGE_LOSS_REASONS = {
    StockAdjustmentReason.DAMAGE,
    StockAdjustmentReason.LOSS,
    StockAdjustmentReason.EXPIRY,
}


@dataclass(frozen=True)
class AdjustmentVariantUnit:
    variant: ProductVariant
    variant_unit: VariantUnit


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
) -> StockAdjustment | None:
    return await db.scalar(
        select(StockAdjustment).where(
            StockAdjustment.tenant_id == tenant_id,
            StockAdjustment.id == stock_adjustment_id,
        )
    )


async def get_adjustment_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
) -> StockAdjustment | None:
    return await db.scalar(
        select(StockAdjustment)
        .options(selectinload(StockAdjustment.lines))
        .where(
            StockAdjustment.tenant_id == tenant_id,
            StockAdjustment.id == stock_adjustment_id,
        )
    )


async def list_stock_adjustments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockAdjustmentFilters,
    sort: tuple[SortSpec, ...],
) -> Page[StockAdjustment]:
    stmt = _apply_adjustment_filters(
        select(StockAdjustment).where(StockAdjustment.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, STOCK_ADJUSTMENT_SORT_COLUMNS)
    count_stmt = _apply_adjustment_filters(
        select(func.count(StockAdjustment.id)).where(StockAdjustment.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_adjustment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: StockAdjustmentCreate,
    *,
    actor_user_id: uuid.UUID,
) -> StockAdjustment:
    try:
        adjustment = await _create_adjustment_draft(
            db, tenant_id, data, actor_user_id=actor_user_id
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(adjustment)
    detail = await get_adjustment_detail_by_id(db, tenant_id, adjustment.id)
    assert detail is not None
    return detail


async def _create_adjustment_draft(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: StockAdjustmentCreate,
    *,
    actor_user_id: uuid.UUID,
) -> StockAdjustment:
    await _ensure_active_location(db, tenant_id, data.location_id)
    adjustment = StockAdjustment(
        tenant_id=tenant_id,
        status=DocumentStatus.DRAFT,
        created_by=actor_user_id,
        document_no=await generate_document_no(
            db, tenant_id, "stock_adjustment", datetime.now(UTC)
        ),
        location_id=data.location_id,
        reason=data.reason,
        notes=data.notes,
    )
    db.add(adjustment)
    await db.flush()

    lines = [
        await _build_line(db, tenant_id, adjustment.id, adjustment.reason, line_data)
        for line_data in data.lines
    ]
    db.add_all(lines)
    await db.flush()

    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_adjustments.create",
        entity_type="stock_adjustment",
        entity_id=adjustment.id,
        after_json=_adjustment_loggable(adjustment),
    )
    await db.commit()
    return adjustment


async def update_adjustment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    data: StockAdjustmentUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> StockAdjustment:
    adjustment = await _get_existing_adjustment(db, tenant_id, stock_adjustment_id)
    _ensure_draft(adjustment)
    before = _adjustment_loggable(adjustment)
    fields = data.model_dump(exclude_unset=True)
    if "location_id" in fields:
        await _ensure_active_location(db, tenant_id, fields["location_id"])
    for key, value in fields.items():
        setattr(adjustment, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_adjustments.update",
        entity_type="stock_adjustment",
        entity_id=adjustment.id,
        before_json=before,
        after_json=_adjustment_loggable(adjustment),
    )
    await db.commit()
    await db.refresh(adjustment)
    detail = await get_adjustment_detail_by_id(db, tenant_id, adjustment.id)
    assert detail is not None
    return detail


async def cancel_adjustment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    adjustment = await _get_existing_adjustment(db, tenant_id, stock_adjustment_id)
    if adjustment.status != DocumentStatus.DRAFT:
        raise StockAdjustmentNotCancellable()
    before = _adjustment_loggable(adjustment)
    adjustment.status = DocumentStatus.CANCELLED
    adjustment.cancelled_at = datetime.now(UTC)
    adjustment.cancelled_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_adjustments.cancel",
        entity_type="stock_adjustment",
        entity_id=adjustment.id,
        before_json=before,
        after_json=_adjustment_loggable(adjustment),
    )
    await db.commit()


async def post_adjustment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockAdjustment:
    try:
        adjustment = await _post_adjustment_atomically(
            db,
            tenant_id,
            stock_adjustment_id,
            actor_user_id=actor_user_id,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(adjustment)
    detail = await get_adjustment_detail_by_id(db, tenant_id, adjustment.id)
    assert detail is not None
    return detail


async def _post_adjustment_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockAdjustment:
    adjustment = await _get_existing_adjustment(db, tenant_id, stock_adjustment_id)
    if adjustment.status != DocumentStatus.DRAFT:
        raise StockAdjustmentNotPostable()
    lines = await _adjustment_lines(db, tenant_id, adjustment.id)
    if not lines:
        raise StockAdjustmentHasNoLines()
    before = _adjustment_loggable(adjustment)
    posted_at = datetime.now(UTC)
    posted_inventory: list[dict[str, str]] = []
    movement_type = _movement_type_for_reason(adjustment.reason)

    for line in lines:
        adjustment_variant_unit = await _ensure_active_variant_unit(
            db,
            tenant_id,
            line.product_variant_id,
            line.variant_unit_id,
            allow_inactive_unit=True,
        )
        if (
            adjustment.reason == StockAdjustmentReason.OPENING_BALANCE
            and line.stock_batch_id is None
            and adjustment_variant_unit.variant.track_batches
            and not line.lot_number
        ):
            line.lot_number = await generate_lot_number(db, tenant_id, posted_at)
        batch = await _resolve_posting_batch(db, tenant_id, adjustment, line, posted_at)
        balance = await _get_or_create_balance(
            db,
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            location_id=adjustment.location_id,
            stock_batch_id=batch.id,
            updated_at=posted_at,
        )
        new_quantity = balance.quantity_base + line.quantity_base
        if new_quantity < ZERO:
            raise StockAdjustmentNegativeBalance()
        balance.quantity_base = new_quantity
        balance.updated_at = posted_at

        movement = StockMovement(
            tenant_id=tenant_id,
            movement_type=movement_type,
            source_type=SourceType.STOCK_ADJUSTMENT,
            source_id=adjustment.id,
            source_line_id=line.id,
            product_variant_id=line.product_variant_id,
            stock_batch_id=batch.id,
            location_id=adjustment.location_id,
            quantity_base=line.quantity_base,
            unit_cost_base=line.unit_cost_base,
            total_cost=line.quantity_base * line.unit_cost_base if line.unit_cost_base else None,
            notes=f"Stock adjustment {adjustment.document_no}",
            posted_at=posted_at,
            posted_by=actor_user_id,
            created_at=posted_at,
        )
        db.add(movement)
        await db.flush()
        posted_inventory.append(
            {
                "line_id": str(line.id),
                "stock_batch_id": str(batch.id),
                "stock_movement_id": str(movement.id),
                "stock_balance_id": str(balance.id),
            }
        )

    adjustment.status = DocumentStatus.POSTED
    adjustment.posted_at = posted_at
    adjustment.posted_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_adjustments.post",
        entity_type="stock_adjustment",
        entity_id=adjustment.id,
        before_json=before,
        after_json=_adjustment_loggable(adjustment) | {"posted_inventory": posted_inventory},
    )
    await db.commit()
    return adjustment


async def _build_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    reason: StockAdjustmentReason,
    data: StockAdjustmentLineCreate,
) -> StockAdjustmentLine:
    adjustment_variant_unit = await _ensure_active_variant_unit(
        db,
        tenant_id,
        data.product_variant_id,
        data.variant_unit_id,
    )
    batch = await _validate_line_batch(db, tenant_id, reason, data)
    unit_cost_base = _line_unit_cost_base(
        reason,
        data.stock_batch_id,
        data.unit_cost_base,
        batch,
    )
    line = StockAdjustmentLine(
        tenant_id=tenant_id,
        stock_adjustment_id=stock_adjustment_id,
        conversion_to_base=adjustment_variant_unit.variant_unit.conversion_to_base,
        quantity_base=quantity_base_for_unit(
            data.quantity,
            adjustment_variant_unit.variant_unit.conversion_to_base,
            allow_decimal_quantity=adjustment_variant_unit.variant_unit.allow_decimal_quantity,
            rounding_precision=adjustment_variant_unit.variant_unit.rounding_precision,
            allow_negative=True,
        ),
        unit_cost_base=unit_cost_base,
        **data.model_dump(exclude={"unit_cost_base"}),
    )
    if (
        reason == StockAdjustmentReason.OPENING_BALANCE
        and data.stock_batch_id is None
        and adjustment_variant_unit.variant.track_batches
        and not line.lot_number
    ):
        line.lot_number = await generate_lot_number(db, tenant_id, datetime.now(UTC))
    return line


async def create_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    data: StockAdjustmentLineCreate,
    *,
    actor_user_id: uuid.UUID,
) -> StockAdjustmentLine:
    adjustment = await _get_existing_adjustment(db, tenant_id, stock_adjustment_id)
    _ensure_draft(adjustment)
    await _ensure_line_no_available(db, tenant_id, stock_adjustment_id, data.line_no)
    line = await _build_line(db, tenant_id, stock_adjustment_id, adjustment.reason, data)
    db.add(line)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_adjustment_lines.create",
        entity_type="stock_adjustment_line",
        entity_id=line.id,
        after_json=_line_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def update_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    line_id: uuid.UUID,
    data: StockAdjustmentLineUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> StockAdjustmentLine:
    adjustment = await _get_existing_adjustment(db, tenant_id, stock_adjustment_id)
    _ensure_draft(adjustment)
    line = await _get_existing_line(db, tenant_id, stock_adjustment_id, line_id)
    before = _line_loggable(line)
    fields = data.model_dump(exclude_unset=True)
    new_line_no = fields.get("line_no")
    if new_line_no is not None and new_line_no != line.line_no:
        await _ensure_line_no_available(
            db,
            tenant_id,
            stock_adjustment_id,
            new_line_no,
            line_id=line.id,
        )
    product_variant_id = fields.get("product_variant_id", line.product_variant_id)
    variant_unit_id = fields.get("variant_unit_id", line.variant_unit_id)
    stock_batch_id = fields.get("stock_batch_id", line.stock_batch_id)
    unit_cost_base = fields.get("unit_cost_base", line.unit_cost_base)
    adjustment_variant_unit = await _ensure_active_variant_unit(
        db,
        tenant_id,
        product_variant_id,
        variant_unit_id,
    )
    batch = await _validate_line_batch_values(
        db,
        tenant_id,
        adjustment.reason,
        product_variant_id=product_variant_id,
        stock_batch_id=stock_batch_id,
        unit_cost_base=unit_cost_base,
    )
    for key, value in fields.items():
        setattr(line, key, value)
    line.product_variant_id = product_variant_id
    line.variant_unit_id = variant_unit_id
    line.stock_batch_id = stock_batch_id
    line.conversion_to_base = adjustment_variant_unit.variant_unit.conversion_to_base
    line.quantity_base = quantity_base_for_unit(
        line.quantity,
        line.conversion_to_base,
        allow_decimal_quantity=adjustment_variant_unit.variant_unit.allow_decimal_quantity,
        rounding_precision=adjustment_variant_unit.variant_unit.rounding_precision,
        allow_negative=True,
    )
    line.unit_cost_base = _line_unit_cost_base(
        adjustment.reason,
        line.stock_batch_id,
        unit_cost_base,
        batch,
    )
    if (
        adjustment.reason == StockAdjustmentReason.OPENING_BALANCE
        and line.stock_batch_id is None
        and adjustment_variant_unit.variant.track_batches
        and not line.lot_number
    ):
        line.lot_number = await generate_lot_number(db, tenant_id, datetime.now(UTC))
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_adjustment_lines.update",
        entity_type="stock_adjustment_line",
        entity_id=line.id,
        before_json=before,
        after_json=_line_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def delete_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    line_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    adjustment = await _get_existing_adjustment(db, tenant_id, stock_adjustment_id)
    _ensure_draft(adjustment)
    line = await _get_existing_line(db, tenant_id, stock_adjustment_id, line_id)
    before = _line_loggable(line)
    await db.delete(line)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_adjustment_lines.delete",
        entity_type="stock_adjustment_line",
        entity_id=line.id,
        before_json=before,
    )
    await db.commit()


async def get_line_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    line_id: uuid.UUID,
) -> StockAdjustmentLine | None:
    return await db.scalar(
        select(StockAdjustmentLine).where(
            StockAdjustmentLine.tenant_id == tenant_id,
            StockAdjustmentLine.stock_adjustment_id == stock_adjustment_id,
            StockAdjustmentLine.id == line_id,
        )
    )


async def list_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockAdjustmentLineFilters,
    sort: tuple[SortSpec, ...],
) -> Page[StockAdjustmentLine]:
    await _get_existing_adjustment(db, tenant_id, stock_adjustment_id)
    stmt = _apply_line_filters(
        select(StockAdjustmentLine).where(
            StockAdjustmentLine.tenant_id == tenant_id,
            StockAdjustmentLine.stock_adjustment_id == stock_adjustment_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, STOCK_ADJUSTMENT_LINE_SORT_COLUMNS)
    count_stmt = _apply_line_filters(
        select(func.count(StockAdjustmentLine.id)).where(
            StockAdjustmentLine.tenant_id == tenant_id,
            StockAdjustmentLine.stock_adjustment_id == stock_adjustment_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def _get_existing_adjustment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
) -> StockAdjustment:
    adjustment = await get_by_id(db, tenant_id, stock_adjustment_id)
    if adjustment is None:
        raise StockAdjustmentNotFound()
    return adjustment


async def _get_existing_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    line_id: uuid.UUID,
) -> StockAdjustmentLine:
    line = await get_line_by_id(db, tenant_id, stock_adjustment_id, line_id)
    if line is None:
        raise StockAdjustmentLineNotFound()
    return line


def _ensure_draft(adjustment: StockAdjustment) -> None:
    if adjustment.status != DocumentStatus.DRAFT:
        raise StockAdjustmentNotDraft()


async def _ensure_document_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_no: str,
    *,
    stock_adjustment_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(StockAdjustment).where(
            StockAdjustment.tenant_id == tenant_id,
            StockAdjustment.document_no == document_no,
        )
    )
    if existing is not None and existing.id != stock_adjustment_id:
        raise StockAdjustmentDocumentNoConflict()


async def _ensure_line_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
    line_no: int,
    *,
    line_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(StockAdjustmentLine).where(
            StockAdjustmentLine.tenant_id == tenant_id,
            StockAdjustmentLine.stock_adjustment_id == stock_adjustment_id,
            StockAdjustmentLine.line_no == line_no,
        )
    )
    if existing is not None and existing.id != line_id:
        raise StockAdjustmentLineNoConflict()


async def _ensure_active_location(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Location:
    location = await db.scalar(
        select(Location).where(
            Location.tenant_id == tenant_id,
            Location.id == location_id,
            Location.is_active.is_(True),
        )
    )
    if location is None:
        raise InvalidStockAdjustmentLocation()
    return location


async def _ensure_active_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    *,
    allow_inactive_unit: bool = False,
) -> AdjustmentVariantUnit:
    variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == product_variant_id,
            ProductVariant.is_active.is_(True),
            ProductVariant.track_inventory.is_(True),
        )
    )
    if variant is None:
        raise InvalidStockAdjustmentLineProduct()
    predicates = [
        VariantUnit.tenant_id == tenant_id,
        VariantUnit.id == variant_unit_id,
        VariantUnit.product_variant_id == product_variant_id,
    ]
    if not allow_inactive_unit:
        predicates.append(VariantUnit.is_active.is_(True))
    variant_unit = await db.scalar(select(VariantUnit).where(*predicates))
    if variant_unit is None:
        raise InvalidStockAdjustmentLineUnit()
    return AdjustmentVariantUnit(variant=variant, variant_unit=variant_unit)


async def _validate_line_batch(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    reason: StockAdjustmentReason,
    data: StockAdjustmentLineCreate,
) -> StockBatch | None:
    if data.stock_batch_id is None:
        if reason != StockAdjustmentReason.OPENING_BALANCE:
            raise StockAdjustmentLineBatchRequired()
        if data.unit_cost_base is None:
            raise StockAdjustmentLineCostRequired()
        return None

    batch = await db.scalar(
        select(StockBatch).where(
            StockBatch.tenant_id == tenant_id,
            StockBatch.id == data.stock_batch_id,
            StockBatch.product_variant_id == data.product_variant_id,
            StockBatch.status == StockBatchStatus.ACTIVE,
        )
    )
    if batch is None:
        raise InvalidStockAdjustmentLineBatch()
    return batch


async def _validate_line_batch_values(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    reason: StockAdjustmentReason,
    *,
    product_variant_id: uuid.UUID,
    stock_batch_id: uuid.UUID | None,
    unit_cost_base: Decimal | None,
) -> StockBatch | None:
    if stock_batch_id is None:
        if reason != StockAdjustmentReason.OPENING_BALANCE:
            raise StockAdjustmentLineBatchRequired()
        if unit_cost_base is None:
            raise StockAdjustmentLineCostRequired()
        return None

    batch = await db.scalar(
        select(StockBatch).where(
            StockBatch.tenant_id == tenant_id,
            StockBatch.id == stock_batch_id,
            StockBatch.product_variant_id == product_variant_id,
            StockBatch.status == StockBatchStatus.ACTIVE,
        )
    )
    if batch is None:
        raise InvalidStockAdjustmentLineBatch()
    return batch


def _line_unit_cost_base(
    reason: StockAdjustmentReason,
    stock_batch_id: uuid.UUID | None,
    unit_cost_base: Decimal | None,
    batch: StockBatch | None,
) -> Decimal | None:
    if stock_batch_id is None:
        if reason != StockAdjustmentReason.OPENING_BALANCE:
            raise StockAdjustmentLineBatchNotAllowed()
        if unit_cost_base is None:
            raise StockAdjustmentLineCostRequired()
        return unit_cost_base
    return unit_cost_base if unit_cost_base is not None else batch.unit_cost_base if batch else None


async def _resolve_posting_batch(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    adjustment: StockAdjustment,
    line: StockAdjustmentLine,
    posted_at: datetime,
) -> StockBatch:
    if line.stock_batch_id is not None:
        batch = await db.scalar(
            select(StockBatch).where(
                StockBatch.tenant_id == tenant_id,
                StockBatch.id == line.stock_batch_id,
                StockBatch.product_variant_id == line.product_variant_id,
                StockBatch.status == StockBatchStatus.ACTIVE,
            )
        )
        if batch is None:
            raise InvalidStockAdjustmentLineBatch()
        return batch

    if adjustment.reason != StockAdjustmentReason.OPENING_BALANCE:
        raise StockAdjustmentLineBatchRequired()
    if line.unit_cost_base is None:
        raise StockAdjustmentLineCostRequired()
    batch = StockBatch(
        tenant_id=tenant_id,
        product_variant_id=line.product_variant_id,
        source_type=SourceType.STOCK_ADJUSTMENT,
        source_id=adjustment.id,
        source_line_id=line.id,
        supplier_id=None,
        received_at=posted_at,
        expiry_date=line.expiry_date,
        manufactured_date=line.manufactured_date,
        lot_number=line.lot_number,
        initial_quantity_base=line.quantity_base,
        unit_cost_base=line.unit_cost_base,
        total_cost=line.quantity_base * line.unit_cost_base,
        conversion_to_base=line.conversion_to_base,
        status=StockBatchStatus.ACTIVE,
        created_at=posted_at,
    )
    db.add(batch)
    await db.flush()
    line.stock_batch_id = batch.id
    return batch


async def _get_or_create_balance(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
    updated_at: datetime,
) -> StockBalance:
    balance = await db.scalar(
        select(StockBalance).where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.product_variant_id == product_variant_id,
            StockBalance.location_id == location_id,
            StockBalance.stock_batch_id == stock_batch_id,
        )
    )
    if balance is None:
        balance = StockBalance(
            tenant_id=tenant_id,
            product_variant_id=product_variant_id,
            location_id=location_id,
            stock_batch_id=stock_batch_id,
            quantity_base=ZERO,
            updated_at=updated_at,
        )
        db.add(balance)
        await db.flush()
    return balance


def _movement_type_for_reason(reason: StockAdjustmentReason) -> StockMovementType:
    if reason in DAMAGE_LOSS_REASONS:
        return StockMovementType.DAMAGE_LOSS
    return StockMovementType.ADJUSTMENT


def _apply_adjustment_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: StockAdjustmentFilters,
) -> StmtT:
    search = search_clause([StockAdjustment.document_no, StockAdjustment.notes], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.location_id is not None:
        stmt = stmt.where(StockAdjustment.location_id == filters.location_id)
    if filters.reason is not None:
        stmt = stmt.where(StockAdjustment.reason == filters.reason)
    if filters.status is not None:
        stmt = stmt.where(StockAdjustment.status == filters.status)
    stmt = where_gte_if_not_none(stmt, StockAdjustment.created_at, filters.created_at_gte)
    stmt = where_lte_if_not_none(stmt, StockAdjustment.created_at, filters.created_at_lte)
    return stmt


def _apply_line_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: StockAdjustmentLineFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(StockAdjustmentLine.product_variant_id == filters.product_variant_id)
    if filters.stock_batch_id is not None:
        stmt = stmt.where(StockAdjustmentLine.stock_batch_id == filters.stock_batch_id)
    if filters.variant_unit_id is not None:
        stmt = stmt.where(StockAdjustmentLine.variant_unit_id == filters.variant_unit_id)
    return stmt


async def _adjustment_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_adjustment_id: uuid.UUID,
) -> list[StockAdjustmentLine]:
    result = await db.execute(
        select(StockAdjustmentLine)
        .where(
            StockAdjustmentLine.tenant_id == tenant_id,
            StockAdjustmentLine.stock_adjustment_id == stock_adjustment_id,
        )
        .order_by(StockAdjustmentLine.line_no.asc(), StockAdjustmentLine.id.asc())
    )
    return list(result.scalars().all())


def _adjustment_loggable(adjustment: StockAdjustment) -> dict[str, Any]:
    return {
        "document_no": adjustment.document_no,
        "location_id": str(adjustment.location_id),
        "reason": adjustment.reason.value,
        "status": adjustment.status.value,
        "posted_at": adjustment.posted_at.isoformat() if adjustment.posted_at else None,
        "posted_by": str(adjustment.posted_by) if adjustment.posted_by else None,
        "cancelled_at": adjustment.cancelled_at.isoformat() if adjustment.cancelled_at else None,
        "cancelled_by": str(adjustment.cancelled_by) if adjustment.cancelled_by else None,
        "notes": adjustment.notes,
        "created_by": str(adjustment.created_by) if adjustment.created_by else None,
    }


def _line_loggable(line: StockAdjustmentLine) -> dict[str, Any]:
    return {
        "stock_adjustment_id": str(line.stock_adjustment_id),
        "line_no": line.line_no,
        "product_variant_id": str(line.product_variant_id),
        "variant_unit_id": str(line.variant_unit_id),
        "stock_batch_id": str(line.stock_batch_id) if line.stock_batch_id else None,
        "quantity": str(line.quantity),
        "conversion_to_base": str(line.conversion_to_base),
        "quantity_base": str(line.quantity_base),
        "unit_cost_base": str(line.unit_cost_base) if line.unit_cost_base else None,
        "expiry_date": line.expiry_date.isoformat() if line.expiry_date else None,
        "manufactured_date": line.manufactured_date.isoformat() if line.manufactured_date else None,
        "lot_number": line.lot_number,
        "notes": line.notes,
    }
