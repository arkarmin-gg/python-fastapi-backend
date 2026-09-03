import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.foundation_enums import DocumentStatus, SourceType, StockBatchStatus, StockMovementType
from src.modules.audit_logs.service import record_audit_log
from src.modules.catalog.models import ProductVariant
from src.modules.document_numbers.service import generate_document_no
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.stock_counts.exceptions import (
    InvalidStockCountLineBatch,
    InvalidStockCountLineProduct,
    InvalidStockCountLocation,
    StockCountDocumentNoConflict,
    StockCountHasNoLines,
    StockCountLineNoConflict,
    StockCountLineNotFound,
    StockCountNegativeBalance,
    StockCountNotApproved,
    StockCountNotCancellable,
    StockCountNotDraft,
    StockCountNotFound,
    StockCountNotPendingApproval,
    StockCountNotSubmittable,
)
from src.modules.stock_counts.models import StockCount, StockCountLine
from src.modules.stock_counts.schemas import (
    StockCountCreate,
    StockCountFilters,
    StockCountLineCreate,
    StockCountLineFilters,
    StockCountLineUpdate,
    StockCountUpdate,
)
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import (
    SortSpec,
    apply_sort,
    search_clause,
    where_gte_if_not_none,
    where_lte_if_not_none,
)

COUNT_SORT_COLUMNS = {
    "document_no": StockCount.document_no,
    "status": StockCount.status,
    "counted_at": StockCount.counted_at,
    "created_at": StockCount.created_at,
    "id": StockCount.id,
}
LINE_SORT_COLUMNS = {
    "line_no": StockCountLine.line_no,
    "product_variant_id": StockCountLine.product_variant_id,
    "stock_batch_id": StockCountLine.stock_batch_id,
    "id": StockCountLine.id,
}
ZERO = Decimal("0")


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
) -> StockCount | None:
    return await db.scalar(
        select(StockCount).where(
            StockCount.tenant_id == tenant_id,
            StockCount.id == stock_count_id,
        )
    )


async def get_count_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
) -> StockCount | None:
    return await db.scalar(
        select(StockCount)
        .options(selectinload(StockCount.lines))
        .where(
            StockCount.tenant_id == tenant_id,
            StockCount.id == stock_count_id,
        )
    )


async def list_stock_counts(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockCountFilters,
    sort: tuple[SortSpec, ...],
) -> Page[StockCount]:
    stmt = _apply_count_filters(
        select(StockCount).where(StockCount.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, COUNT_SORT_COLUMNS)
    count_stmt = _apply_count_filters(
        select(func.count(StockCount.id)).where(StockCount.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: StockCountCreate,
    *,
    actor_user_id: uuid.UUID,
) -> StockCount:
    await _ensure_active_location(db, tenant_id, data.location_id)
    fields = data.model_dump()
    counted_at = fields.pop("counted_at") or datetime.now(UTC)
    count = StockCount(
        tenant_id=tenant_id,
        status=DocumentStatus.DRAFT,
        counted_by=actor_user_id,
        counted_at=counted_at,
        document_no=await generate_document_no(db, tenant_id, "stock_count", counted_at),
        **fields,
    )
    db.add(count)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_counts.create",
        entity_type="stock_count",
        entity_id=count.id,
        after_json=_count_loggable(count),
    )
    await db.commit()
    await db.refresh(count)
    return count


async def update_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    data: StockCountUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> StockCount:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    _ensure_draft(count)
    before = _count_loggable(count)
    fields = data.model_dump(exclude_unset=True)
    if "location_id" in fields:
        await _ensure_active_location(db, tenant_id, fields["location_id"])
    for key, value in fields.items():
        setattr(count, key, value)
    if "location_id" in fields:
        await _refresh_lines_expected(db, count)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_counts.update",
        entity_type="stock_count",
        entity_id=count.id,
        before_json=before,
        after_json=_count_loggable(count),
    )
    await db.commit()
    await db.refresh(count)
    return count


async def submit_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockCount:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    if count.status != DocumentStatus.DRAFT:
        raise StockCountNotSubmittable()
    if not await _has_lines(db, tenant_id, count.id):
        raise StockCountHasNoLines()
    before = _count_loggable(count)
    count.status = DocumentStatus.PENDING_APPROVAL
    count.approved_at = None
    count.approved_by = None
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_counts.submit",
        entity_type="stock_count",
        entity_id=count.id,
        before_json=before,
        after_json=_count_loggable(count),
    )
    await db.commit()
    await db.refresh(count)
    return count


async def approve_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockCount:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    _ensure_pending_approval(count)
    before = _count_loggable(count)
    count.status = DocumentStatus.APPROVED
    count.approved_at = datetime.now(UTC)
    count.approved_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_counts.approve",
        entity_type="stock_count",
        entity_id=count.id,
        before_json=before,
        after_json=_count_loggable(count),
    )
    await db.commit()
    await db.refresh(count)
    return count


async def reject_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockCount:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    _ensure_pending_approval(count)
    before = _count_loggable(count)
    count.status = DocumentStatus.DRAFT
    count.approved_at = None
    count.approved_by = None
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_counts.reject",
        entity_type="stock_count",
        entity_id=count.id,
        before_json=before,
        after_json=_count_loggable(count) | {"rejected_by": str(actor_user_id)},
    )
    await db.commit()
    await db.refresh(count)
    return count


async def cancel_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    if count.status not in {DocumentStatus.DRAFT, DocumentStatus.PENDING_APPROVAL}:
        raise StockCountNotCancellable()
    before = _count_loggable(count)
    count.status = DocumentStatus.CANCELLED
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_counts.cancel",
        entity_type="stock_count",
        entity_id=count.id,
        before_json=before,
        after_json=_count_loggable(count),
    )
    await db.commit()


async def post_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockCount:
    try:
        count = await _post_count_atomically(
            db, tenant_id, stock_count_id, actor_user_id=actor_user_id
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(count)
    return count


async def _post_count_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> StockCount:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    _ensure_approved(count)
    lines = await _count_lines(db, tenant_id, count.id)
    if not lines:
        raise StockCountHasNoLines()

    before = _count_loggable(count)
    posted_at = datetime.now(UTC)
    posted_inventory: list[dict[str, str]] = []

    for line in lines:
        balance = await _get_or_create_balance(
            db,
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            location_id=count.location_id,
            stock_batch_id=line.stock_batch_id,
            updated_at=posted_at,
        )
        new_quantity = balance.quantity_base + line.variance_quantity_base
        if new_quantity < ZERO:
            raise StockCountNegativeBalance()
        balance.quantity_base = new_quantity
        balance.updated_at = posted_at

        if line.variance_quantity_base == ZERO:
            continue
        batch = await _ensure_active_batch(
            db, tenant_id, line.product_variant_id, line.stock_batch_id
        )
        movement = StockMovement(
            tenant_id=tenant_id,
            movement_type=StockMovementType.COUNT_ADJUSTMENT,
            source_type=SourceType.STOCK_COUNT,
            source_id=count.id,
            source_line_id=line.id,
            product_variant_id=line.product_variant_id,
            stock_batch_id=line.stock_batch_id,
            location_id=count.location_id,
            quantity_base=line.variance_quantity_base,
            unit_cost_base=batch.unit_cost_base,
            total_cost=line.variance_quantity_base * batch.unit_cost_base,
            notes=f"Stock count {count.document_no}",
            posted_at=posted_at,
            posted_by=actor_user_id,
            created_at=posted_at,
        )
        db.add(movement)
        await db.flush()
        line.adjustment_movement_id = movement.id
        posted_inventory.append(
            {
                "line_id": str(line.id),
                "stock_movement_id": str(movement.id),
                "stock_balance_id": str(balance.id),
            }
        )

    count.status = DocumentStatus.POSTED
    count.posted_at = posted_at
    count.posted_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_counts.post",
        entity_type="stock_count",
        entity_id=count.id,
        before_json=before,
        after_json=_count_loggable(count) | {"posted_inventory": posted_inventory},
    )
    await db.commit()
    return count


async def get_line_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    line_id: uuid.UUID,
) -> StockCountLine | None:
    return await db.scalar(
        select(StockCountLine).where(
            StockCountLine.tenant_id == tenant_id,
            StockCountLine.stock_count_id == stock_count_id,
            StockCountLine.id == line_id,
        )
    )


async def list_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    pagination: PaginationParams,
    filters: StockCountLineFilters,
    sort: tuple[SortSpec, ...],
) -> Page[StockCountLine]:
    await _get_existing_count(db, tenant_id, stock_count_id)
    stmt = _apply_line_filters(
        select(StockCountLine).where(
            StockCountLine.tenant_id == tenant_id,
            StockCountLine.stock_count_id == stock_count_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, LINE_SORT_COLUMNS)
    count_stmt = _apply_line_filters(
        select(func.count(StockCountLine.id)).where(
            StockCountLine.tenant_id == tenant_id,
            StockCountLine.stock_count_id == stock_count_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    data: StockCountLineCreate,
    *,
    actor_user_id: uuid.UUID,
) -> StockCountLine:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    _ensure_draft(count)
    await _ensure_line_no_available(db, tenant_id, stock_count_id, data.line_no)
    await _ensure_active_variant(db, tenant_id, data.product_variant_id)
    await _ensure_active_batch(db, tenant_id, data.product_variant_id, data.stock_batch_id)
    expected = await _expected_quantity(
        db,
        tenant_id,
        count.location_id,
        data.product_variant_id,
        data.stock_batch_id,
    )
    line = StockCountLine(
        tenant_id=tenant_id,
        stock_count_id=stock_count_id,
        expected_quantity_base=expected,
        variance_quantity_base=data.counted_quantity_base - expected,
        **data.model_dump(),
    )
    db.add(line)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_count_lines.create",
        entity_type="stock_count_line",
        entity_id=line.id,
        after_json=_line_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def update_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    line_id: uuid.UUID,
    data: StockCountLineUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> StockCountLine:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    _ensure_draft(count)
    line = await _get_existing_line(db, tenant_id, stock_count_id, line_id)
    before = _line_loggable(line)
    fields = data.model_dump(exclude_unset=True)
    new_line_no = fields.get("line_no")
    if new_line_no is not None and new_line_no != line.line_no:
        await _ensure_line_no_available(db, tenant_id, stock_count_id, new_line_no, line_id=line.id)
    product_variant_id = fields.get("product_variant_id", line.product_variant_id)
    stock_batch_id = fields.get("stock_batch_id", line.stock_batch_id)
    await _ensure_active_variant(db, tenant_id, product_variant_id)
    await _ensure_active_batch(db, tenant_id, product_variant_id, stock_batch_id)

    for key, value in fields.items():
        setattr(line, key, value)
    expected = await _expected_quantity(
        db,
        tenant_id,
        count.location_id,
        product_variant_id,
        stock_batch_id,
    )
    line.expected_quantity_base = expected
    line.variance_quantity_base = line.counted_quantity_base - expected
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_count_lines.update",
        entity_type="stock_count_line",
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
    stock_count_id: uuid.UUID,
    line_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    count = await _get_existing_count(db, tenant_id, stock_count_id)
    _ensure_draft(count)
    line = await _get_existing_line(db, tenant_id, stock_count_id, line_id)
    before = _line_loggable(line)
    await db.delete(line)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="stock_count_lines.delete",
        entity_type="stock_count_line",
        entity_id=line.id,
        before_json=before,
    )
    await db.commit()


async def _get_existing_count(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
) -> StockCount:
    count = await get_by_id(db, tenant_id, stock_count_id)
    if count is None:
        raise StockCountNotFound()
    return count


async def _get_existing_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    line_id: uuid.UUID,
) -> StockCountLine:
    line = await get_line_by_id(db, tenant_id, stock_count_id, line_id)
    if line is None:
        raise StockCountLineNotFound()
    return line


def _ensure_draft(count: StockCount) -> None:
    if count.status != DocumentStatus.DRAFT:
        raise StockCountNotDraft()


def _ensure_pending_approval(count: StockCount) -> None:
    if count.status != DocumentStatus.PENDING_APPROVAL:
        raise StockCountNotPendingApproval()


def _ensure_approved(count: StockCount) -> None:
    if count.status != DocumentStatus.APPROVED:
        raise StockCountNotApproved()


async def _ensure_document_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_no: str,
    *,
    stock_count_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(StockCount).where(
            StockCount.tenant_id == tenant_id,
            StockCount.document_no == document_no,
        )
    )
    if existing is not None and existing.id != stock_count_id:
        raise StockCountDocumentNoConflict()


async def _ensure_line_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
    line_no: int,
    *,
    line_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(StockCountLine).where(
            StockCountLine.tenant_id == tenant_id,
            StockCountLine.stock_count_id == stock_count_id,
            StockCountLine.line_no == line_no,
        )
    )
    if existing is not None and existing.id != line_id:
        raise StockCountLineNoConflict()


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
        raise InvalidStockCountLocation()
    return location


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
        raise InvalidStockCountLineProduct()
    return variant


async def _ensure_active_batch(
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
        raise InvalidStockCountLineBatch()
    return batch


async def _expected_quantity(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
) -> Decimal:
    quantity = await db.scalar(
        select(StockBalance.quantity_base).where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.location_id == location_id,
            StockBalance.product_variant_id == product_variant_id,
            StockBalance.stock_batch_id == stock_batch_id,
        )
    )
    return quantity or ZERO


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


async def _count_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_count_id: uuid.UUID,
) -> list[StockCountLine]:
    result = await db.execute(
        select(StockCountLine)
        .where(
            StockCountLine.tenant_id == tenant_id,
            StockCountLine.stock_count_id == stock_count_id,
        )
        .order_by(StockCountLine.line_no.asc(), StockCountLine.id.asc())
    )
    return list(result.scalars().all())


async def _has_lines(db: AsyncSession, tenant_id: uuid.UUID, stock_count_id: uuid.UUID) -> bool:
    line_count = await db.scalar(
        select(func.count(StockCountLine.id)).where(
            StockCountLine.tenant_id == tenant_id,
            StockCountLine.stock_count_id == stock_count_id,
        )
    )
    return bool(line_count)


async def _refresh_lines_expected(db: AsyncSession, count: StockCount) -> None:
    lines = await _count_lines(db, count.tenant_id, count.id)
    for line in lines:
        expected = await _expected_quantity(
            db,
            count.tenant_id,
            count.location_id,
            line.product_variant_id,
            line.stock_batch_id,
        )
        line.expected_quantity_base = expected
        line.variance_quantity_base = line.counted_quantity_base - expected


def _apply_count_filters[StmtT: Select[Any]](stmt: StmtT, filters: StockCountFilters) -> StmtT:
    search = search_clause([StockCount.document_no, StockCount.notes], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.location_id is not None:
        stmt = stmt.where(StockCount.location_id == filters.location_id)
    if filters.status is not None:
        stmt = stmt.where(StockCount.status == filters.status)
    stmt = where_gte_if_not_none(stmt, StockCount.counted_at, filters.counted_at_gte)
    stmt = where_lte_if_not_none(stmt, StockCount.counted_at, filters.counted_at_lte)
    return stmt


def _apply_line_filters[StmtT: Select[Any]](stmt: StmtT, filters: StockCountLineFilters) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(StockCountLine.product_variant_id == filters.product_variant_id)
    if filters.stock_batch_id is not None:
        stmt = stmt.where(StockCountLine.stock_batch_id == filters.stock_batch_id)
    return stmt


def _count_loggable(count: StockCount) -> dict[str, Any]:
    return {
        "document_no": count.document_no,
        "location_id": str(count.location_id),
        "counted_at": count.counted_at.isoformat(),
        "counted_by": str(count.counted_by),
        "status": count.status.value,
        "approved_at": count.approved_at.isoformat() if count.approved_at else None,
        "approved_by": str(count.approved_by) if count.approved_by else None,
        "posted_at": count.posted_at.isoformat() if count.posted_at else None,
        "posted_by": str(count.posted_by) if count.posted_by else None,
        "notes": count.notes,
    }


def _line_loggable(line: StockCountLine) -> dict[str, Any]:
    return {
        "stock_count_id": str(line.stock_count_id),
        "line_no": line.line_no,
        "product_variant_id": str(line.product_variant_id),
        "stock_batch_id": str(line.stock_batch_id),
        "expected_quantity_base": str(line.expected_quantity_base),
        "counted_quantity_base": str(line.counted_quantity_base),
        "variance_quantity_base": str(line.variance_quantity_base),
        "adjustment_movement_id": str(line.adjustment_movement_id)
        if line.adjustment_movement_id
        else None,
        "notes": line.notes,
    }
