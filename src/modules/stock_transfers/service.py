import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.decimal_utils import quantity_base_for_unit
from src.foundation_enums import DocumentStatus, SourceType, StockBatchStatus, StockMovementType
from src.modules.audit_logs.service import record_audit_log
from src.modules.catalog.models import ProductVariant, VariantUnit
from src.modules.document_numbers.service import generate_document_no
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.stock_transfers.exceptions import (
    InvalidStockTransferLineBatch,
    InvalidStockTransferLineLocation,
    InvalidStockTransferLineProduct,
    InvalidStockTransferLineUnit,
    StockTransferDocumentNoConflict,
    StockTransferHasNoLines,
    StockTransferInsufficientBalance,
    StockTransferLineNoConflict,
    StockTransferLineNotFound,
    StockTransferNotCancellable,
    StockTransferNotDraft,
    StockTransferNotFound,
    StockTransferNotPostable,
)
from src.modules.stock_transfers.models import StockTransfer, StockTransferLine
from src.modules.stock_transfers.schemas import (
    StockTransferCreate,
    StockTransferFilters,
    StockTransferLineCreate,
    StockTransferLineFilters,
    StockTransferLineUpdate,
    StockTransferUpdate,
)
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import (
    SortSpec,
    apply_sort,
    search_clause,
    where_gte_if_not_none,
    where_lte_if_not_none,
)

TRANSFER_SORT_COLUMNS = {
    "document_no": StockTransfer.document_no,
    "status": StockTransfer.status,
    "created_at": StockTransfer.created_at,
    "id": StockTransfer.id,
}
LINE_SORT_COLUMNS = {
    "line_no": StockTransferLine.line_no,
    "product_variant_id": StockTransferLine.product_variant_id,
    "from_location_id": StockTransferLine.from_location_id,
    "to_location_id": StockTransferLine.to_location_id,
    "id": StockTransferLine.id,
}
ZERO = Decimal("0")


@dataclass(frozen=True)
class TransferVariantUnit:
    variant: ProductVariant
    variant_unit: VariantUnit


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
) -> StockTransfer | None:
    return await db.scalar(
        select(StockTransfer).where(
            StockTransfer.tenant_id == tenant_id,
            StockTransfer.id == stock_transfer_id,
        )
    )


async def get_transfer_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
) -> StockTransfer | None:
    return await db.scalar(
        select(StockTransfer)
        .options(selectinload(StockTransfer.lines))
        .where(
            StockTransfer.tenant_id == tenant_id,
            StockTransfer.id == stock_transfer_id,
        )
    )


async def list_stock_transfers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockTransferFilters,
    sort: tuple[SortSpec, ...],
) -> Page[StockTransfer]:
    stmt = _apply_transfer_filters(
        select(StockTransfer).where(StockTransfer.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, TRANSFER_SORT_COLUMNS)
    count_stmt = _apply_transfer_filters(
        select(func.count(StockTransfer.id)).where(StockTransfer.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_transfer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: StockTransferCreate,
    *,
    actor_user_id: uuid.UUID,
) -> StockTransfer:
    try:
        transfer = await _create_transfer_draft(db, tenant_id, data, actor_user_id=actor_user_id)
    except Exception:
        await db.rollback()
        raise
    await db.refresh(transfer)
    detail = await get_transfer_detail_by_id(db, tenant_id, transfer.id)
    assert detail is not None
    return detail


async def _create_transfer_draft(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: StockTransferCreate,
    *,
    actor_user_id: uuid.UUID,
) -> StockTransfer:
    transfer = StockTransfer(
        tenant_id=tenant_id,
        status=DocumentStatus.DRAFT,
        requested_by=actor_user_id,
        document_no=await generate_document_no(db, tenant_id, "stock_transfer", datetime.now(UTC)),
        notes=data.notes,
    )
    db.add(transfer)
    await db.flush()

    lines = [await _build_line(db, tenant_id, transfer.id, line_data) for line_data in data.lines]
    db.add_all(lines)
    await db.flush()

    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_transfers.create",
        entity_type="stock_transfer",
        entity_id=transfer.id,
        after_json=_transfer_loggable(transfer),
    )
    await db.commit()
    return transfer


async def update_transfer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    data: StockTransferUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> StockTransfer:
    transfer = await _get_existing_transfer(db, tenant_id, stock_transfer_id)
    _ensure_draft(transfer)
    before = _transfer_loggable(transfer)
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(transfer, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_transfers.update",
        entity_type="stock_transfer",
        entity_id=transfer.id,
        before_json=before,
        after_json=_transfer_loggable(transfer),
    )
    await db.commit()
    await db.refresh(transfer)
    detail = await get_transfer_detail_by_id(db, tenant_id, transfer.id)
    assert detail is not None
    return detail


async def cancel_transfer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    transfer = await _get_existing_transfer(db, tenant_id, stock_transfer_id)
    if transfer.status != DocumentStatus.DRAFT:
        raise StockTransferNotCancellable()
    before = _transfer_loggable(transfer)
    transfer.status = DocumentStatus.CANCELLED
    transfer.cancelled_at = datetime.now(UTC)
    transfer.cancelled_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_transfers.cancel",
        entity_type="stock_transfer",
        entity_id=transfer.id,
        before_json=before,
        after_json=_transfer_loggable(transfer),
    )
    await db.commit()


async def post_transfer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockTransfer:
    try:
        transfer = await _post_transfer_atomically(
            db,
            tenant_id,
            stock_transfer_id,
            actor_user_id=actor_user_id,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(transfer)
    detail = await get_transfer_detail_by_id(db, tenant_id, transfer.id)
    assert detail is not None
    return detail


async def _post_transfer_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockTransfer:
    transfer = await _get_existing_transfer(db, tenant_id, stock_transfer_id)
    if transfer.status != DocumentStatus.DRAFT:
        raise StockTransferNotPostable()
    lines = await _transfer_lines(db, tenant_id, transfer.id)
    if not lines:
        raise StockTransferHasNoLines()
    before = _transfer_loggable(transfer)

    posted_at = datetime.now(UTC)
    posted_inventory: list[dict[str, str]] = []

    for line in lines:
        await _ensure_line_references(
            db,
            tenant_id,
            line.product_variant_id,
            line.stock_batch_id,
            line.variant_unit_id,
            line.from_location_id,
            line.to_location_id,
        )
        source_balance = await _get_balance(
            db,
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            location_id=line.from_location_id,
            stock_batch_id=line.stock_batch_id,
        )
        if source_balance is None or source_balance.quantity_base - line.quantity_base < ZERO:
            raise StockTransferInsufficientBalance()
        destination_balance = await _get_or_create_balance(
            db,
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            location_id=line.to_location_id,
            stock_batch_id=line.stock_batch_id,
            updated_at=posted_at,
        )
        source_balance.quantity_base -= line.quantity_base
        source_balance.updated_at = posted_at
        destination_balance.quantity_base += line.quantity_base
        destination_balance.updated_at = posted_at

        batch = await _get_existing_batch(
            db, tenant_id, line.product_variant_id, line.stock_batch_id
        )
        transfer_out = StockMovement(
            tenant_id=tenant_id,
            movement_type=StockMovementType.TRANSFER_OUT,
            source_type=SourceType.STOCK_TRANSFER,
            source_id=transfer.id,
            source_line_id=line.id,
            product_variant_id=line.product_variant_id,
            stock_batch_id=line.stock_batch_id,
            location_id=line.from_location_id,
            quantity_base=-line.quantity_base,
            unit_cost_base=batch.unit_cost_base,
            total_cost=-line.quantity_base * batch.unit_cost_base,
            notes=f"Stock transfer {transfer.document_no}",
            posted_at=posted_at,
            posted_by=actor_user_id,
            created_at=posted_at,
        )
        transfer_in = StockMovement(
            tenant_id=tenant_id,
            movement_type=StockMovementType.TRANSFER_IN,
            source_type=SourceType.STOCK_TRANSFER,
            source_id=transfer.id,
            source_line_id=line.id,
            product_variant_id=line.product_variant_id,
            stock_batch_id=line.stock_batch_id,
            location_id=line.to_location_id,
            quantity_base=line.quantity_base,
            unit_cost_base=batch.unit_cost_base,
            total_cost=line.quantity_base * batch.unit_cost_base,
            notes=f"Stock transfer {transfer.document_no}",
            posted_at=posted_at,
            posted_by=actor_user_id,
            created_at=posted_at,
        )
        db.add_all([transfer_out, transfer_in])
        await db.flush()
        posted_inventory.append(
            {
                "line_id": str(line.id),
                "stock_batch_id": str(line.stock_batch_id),
                "transfer_out_movement_id": str(transfer_out.id),
                "transfer_in_movement_id": str(transfer_in.id),
                "source_balance_id": str(source_balance.id),
                "destination_balance_id": str(destination_balance.id),
            }
        )

    transfer.status = DocumentStatus.POSTED
    transfer.posted_at = posted_at
    transfer.posted_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_transfers.post",
        entity_type="stock_transfer",
        entity_id=transfer.id,
        before_json=before,
        after_json=_transfer_loggable(transfer) | {"posted_inventory": posted_inventory},
    )
    await db.commit()
    return transfer


async def _build_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    data: StockTransferLineCreate,
) -> StockTransferLine:
    transfer_variant_unit = await _ensure_line_references(
        db,
        tenant_id,
        data.product_variant_id,
        data.stock_batch_id,
        data.variant_unit_id,
        data.from_location_id,
        data.to_location_id,
    )
    quantity_base = quantity_base_for_unit(
        data.quantity,
        transfer_variant_unit.variant_unit.conversion_to_base,
        allow_decimal_quantity=transfer_variant_unit.variant_unit.allow_decimal_quantity,
        rounding_precision=transfer_variant_unit.variant_unit.rounding_precision,
    )
    return StockTransferLine(
        tenant_id=tenant_id,
        stock_transfer_id=stock_transfer_id,
        conversion_to_base=transfer_variant_unit.variant_unit.conversion_to_base,
        quantity_base=quantity_base,
        **data.model_dump(),
    )


async def create_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    data: StockTransferLineCreate,
    *,
    actor_user_id: uuid.UUID,
) -> StockTransferLine:
    transfer = await _get_existing_transfer(db, tenant_id, stock_transfer_id)
    _ensure_draft(transfer)
    await _ensure_line_no_available(db, tenant_id, stock_transfer_id, data.line_no)
    line = await _build_line(db, tenant_id, stock_transfer_id, data)
    db.add(line)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_transfer_lines.create",
        entity_type="stock_transfer_line",
        entity_id=line.id,
        after_json=_line_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def update_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    line_id: uuid.UUID,
    data: StockTransferLineUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> StockTransferLine:
    transfer = await _get_existing_transfer(db, tenant_id, stock_transfer_id)
    _ensure_draft(transfer)
    line = await _get_existing_line(db, tenant_id, stock_transfer_id, line_id)
    before = _line_loggable(line)
    fields = data.model_dump(exclude_unset=True)
    new_line_no = fields.get("line_no")
    if new_line_no is not None and new_line_no != line.line_no:
        await _ensure_line_no_available(
            db,
            tenant_id,
            stock_transfer_id,
            new_line_no,
            line_id=line.id,
        )
    product_variant_id = fields.get("product_variant_id", line.product_variant_id)
    stock_batch_id = fields.get("stock_batch_id", line.stock_batch_id)
    variant_unit_id = fields.get("variant_unit_id", line.variant_unit_id)
    from_location_id = fields.get("from_location_id", line.from_location_id)
    to_location_id = fields.get("to_location_id", line.to_location_id)
    transfer_variant_unit = await _ensure_line_references(
        db,
        tenant_id,
        product_variant_id,
        stock_batch_id,
        variant_unit_id,
        from_location_id,
        to_location_id,
    )
    for key, value in fields.items():
        setattr(line, key, value)
    line.product_variant_id = product_variant_id
    line.stock_batch_id = stock_batch_id
    line.variant_unit_id = variant_unit_id
    line.from_location_id = from_location_id
    line.to_location_id = to_location_id
    line.conversion_to_base = transfer_variant_unit.variant_unit.conversion_to_base
    line.quantity_base = quantity_base_for_unit(
        line.quantity,
        line.conversion_to_base,
        allow_decimal_quantity=transfer_variant_unit.variant_unit.allow_decimal_quantity,
        rounding_precision=transfer_variant_unit.variant_unit.rounding_precision,
    )
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_transfer_lines.update",
        entity_type="stock_transfer_line",
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
    stock_transfer_id: uuid.UUID,
    line_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    transfer = await _get_existing_transfer(db, tenant_id, stock_transfer_id)
    _ensure_draft(transfer)
    line = await _get_existing_line(db, tenant_id, stock_transfer_id, line_id)
    before = _line_loggable(line)
    await db.delete(line)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_transfer_lines.delete",
        entity_type="stock_transfer_line",
        entity_id=line.id,
        before_json=before,
    )
    await db.commit()


async def get_line_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    line_id: uuid.UUID,
) -> StockTransferLine | None:
    return await db.scalar(
        select(StockTransferLine).where(
            StockTransferLine.tenant_id == tenant_id,
            StockTransferLine.stock_transfer_id == stock_transfer_id,
            StockTransferLine.id == line_id,
        )
    )


async def list_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockTransferLineFilters,
    sort: tuple[SortSpec, ...],
) -> Page[StockTransferLine]:
    await _get_existing_transfer(db, tenant_id, stock_transfer_id)
    stmt = _apply_line_filters(
        select(StockTransferLine).where(
            StockTransferLine.tenant_id == tenant_id,
            StockTransferLine.stock_transfer_id == stock_transfer_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, LINE_SORT_COLUMNS)
    count_stmt = _apply_line_filters(
        select(func.count(StockTransferLine.id)).where(
            StockTransferLine.tenant_id == tenant_id,
            StockTransferLine.stock_transfer_id == stock_transfer_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def _get_existing_transfer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
) -> StockTransfer:
    transfer = await get_by_id(db, tenant_id, stock_transfer_id)
    if transfer is None:
        raise StockTransferNotFound()
    return transfer


async def _get_existing_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    line_id: uuid.UUID,
) -> StockTransferLine:
    line = await get_line_by_id(db, tenant_id, stock_transfer_id, line_id)
    if line is None:
        raise StockTransferLineNotFound()
    return line


def _ensure_draft(transfer: StockTransfer) -> None:
    if transfer.status != DocumentStatus.DRAFT:
        raise StockTransferNotDraft()


async def _ensure_document_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_no: str,
    *,
    stock_transfer_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(StockTransfer).where(
            StockTransfer.tenant_id == tenant_id,
            StockTransfer.document_no == document_no,
        )
    )
    if existing is not None and existing.id != stock_transfer_id:
        raise StockTransferDocumentNoConflict()


async def _ensure_line_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    line_no: int,
    *,
    line_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(StockTransferLine).where(
            StockTransferLine.tenant_id == tenant_id,
            StockTransferLine.stock_transfer_id == stock_transfer_id,
            StockTransferLine.line_no == line_no,
        )
    )
    if existing is not None and existing.id != line_id:
        raise StockTransferLineNoConflict()


async def _ensure_line_references(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    from_location_id: uuid.UUID,
    to_location_id: uuid.UUID,
) -> TransferVariantUnit:
    if from_location_id == to_location_id:
        raise InvalidStockTransferLineLocation()
    from_location = await _get_active_location(db, tenant_id, from_location_id)
    to_location = await _get_active_location(db, tenant_id, to_location_id)
    if from_location is None or to_location is None:
        raise InvalidStockTransferLineLocation()
    variant = await _ensure_active_variant(db, tenant_id, product_variant_id)
    await _get_existing_batch(db, tenant_id, product_variant_id, stock_batch_id)
    variant_unit = await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.id == variant_unit_id,
            VariantUnit.product_variant_id == product_variant_id,
            VariantUnit.is_active.is_(True),
        )
    )
    if variant_unit is None:
        raise InvalidStockTransferLineUnit()
    return TransferVariantUnit(variant=variant, variant_unit=variant_unit)


async def _ensure_active_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
) -> ProductVariant:
    variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == product_variant_id,
            ProductVariant.is_active.is_(True),
            ProductVariant.track_inventory.is_(True),
        )
    )
    if variant is None:
        raise InvalidStockTransferLineProduct()
    return variant


async def _get_existing_batch(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
) -> StockBatch:
    batch = await db.scalar(
        select(StockBatch).where(
            StockBatch.tenant_id == tenant_id,
            StockBatch.id == stock_batch_id,
            StockBatch.product_variant_id == product_variant_id,
            StockBatch.status == StockBatchStatus.ACTIVE,
        )
    )
    if batch is None:
        raise InvalidStockTransferLineBatch()
    return batch


async def _get_active_location(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Location | None:
    return await db.scalar(
        select(Location).where(
            Location.tenant_id == tenant_id,
            Location.id == location_id,
            Location.is_active.is_(True),
        )
    )


async def _get_balance(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
) -> StockBalance | None:
    return await db.scalar(
        select(StockBalance).where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.product_variant_id == product_variant_id,
            StockBalance.location_id == location_id,
            StockBalance.stock_batch_id == stock_batch_id,
        )
    )


async def _get_or_create_balance(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
    updated_at: datetime,
) -> StockBalance:
    balance = await _get_balance(
        db,
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        location_id=location_id,
        stock_batch_id=stock_batch_id,
    )
    if balance is not None:
        return balance
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


async def _transfer_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
) -> list[StockTransferLine]:
    return list(
        (
            await db.execute(
                select(StockTransferLine)
                .where(
                    StockTransferLine.tenant_id == tenant_id,
                    StockTransferLine.stock_transfer_id == stock_transfer_id,
                )
                .order_by(StockTransferLine.line_no, StockTransferLine.id)
            )
        )
        .scalars()
        .all()
    )


def _apply_transfer_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: StockTransferFilters,
) -> StmtT:
    search = search_clause(
        [StockTransfer.document_no, StockTransfer.notes],
        filters.search,
    )
    if search is not None:
        stmt = stmt.where(search)

    if filters.status is not None:
        stmt = stmt.where(StockTransfer.status == filters.status)
    if filters.requested_by is not None:
        stmt = stmt.where(StockTransfer.requested_by == filters.requested_by)
    stmt = where_gte_if_not_none(stmt, StockTransfer.created_at, filters.created_at_gte)
    stmt = where_lte_if_not_none(stmt, StockTransfer.created_at, filters.created_at_lte)
    return stmt


def _apply_line_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: StockTransferLineFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(StockTransferLine.product_variant_id == filters.product_variant_id)
    if filters.stock_batch_id is not None:
        stmt = stmt.where(StockTransferLine.stock_batch_id == filters.stock_batch_id)
    if filters.variant_unit_id is not None:
        stmt = stmt.where(StockTransferLine.variant_unit_id == filters.variant_unit_id)
    if filters.from_location_id is not None:
        stmt = stmt.where(StockTransferLine.from_location_id == filters.from_location_id)
    if filters.to_location_id is not None:
        stmt = stmt.where(StockTransferLine.to_location_id == filters.to_location_id)
    return stmt


def _transfer_loggable(transfer: StockTransfer) -> dict[str, Any]:
    return {
        "id": str(transfer.id),
        "document_no": transfer.document_no,
        "status": transfer.status.value,
        "requested_by": str(transfer.requested_by) if transfer.requested_by else None,
        "posted_by": str(transfer.posted_by) if transfer.posted_by else None,
        "posted_at": transfer.posted_at.isoformat() if transfer.posted_at else None,
        "cancelled_by": str(transfer.cancelled_by) if transfer.cancelled_by else None,
        "cancelled_at": transfer.cancelled_at.isoformat() if transfer.cancelled_at else None,
        "reversal_of_id": str(transfer.reversal_of_id) if transfer.reversal_of_id else None,
        "notes": transfer.notes,
    }


def _line_loggable(line: StockTransferLine) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "stock_transfer_id": str(line.stock_transfer_id),
        "line_no": line.line_no,
        "product_variant_id": str(line.product_variant_id),
        "variant_unit_id": str(line.variant_unit_id),
        "stock_batch_id": str(line.stock_batch_id),
        "quantity": str(line.quantity),
        "conversion_to_base": str(line.conversion_to_base),
        "quantity_base": str(line.quantity_base),
        "from_location_id": str(line.from_location_id),
        "to_location_id": str(line.to_location_id),
    }
