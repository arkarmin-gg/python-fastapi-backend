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
from src.modules.document_numbers.service import generate_document_no, generate_lot_number
from src.modules.employees.models import Employee
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.repack_orders.exceptions import (
    InvalidRepackOrderEmployee,
    InvalidRepackOrderInputBatch,
    InvalidRepackOrderInputProduct,
    InvalidRepackOrderInputUnit,
    InvalidRepackOrderLocation,
    InvalidRepackOrderOutputProduct,
    InvalidRepackOrderOutputUnit,
    RepackOrderDocumentNoConflict,
    RepackOrderHasNoInputs,
    RepackOrderHasNoOutputs,
    RepackOrderInputLineNoConflict,
    RepackOrderInputNotFound,
    RepackOrderInsufficientBalance,
    RepackOrderNotCancellable,
    RepackOrderNotDraft,
    RepackOrderNotFound,
    RepackOrderNotPostable,
    RepackOrderOutputCostExceedsInputCost,
    RepackOrderOutputLineNoConflict,
    RepackOrderOutputNotFound,
    RepackOrderOutputQuantityExceedsInputQuantity,
)
from src.modules.repack_orders.models import (
    RepackOrder,
    RepackOrderInput,
    RepackOrderOutput,
)
from src.modules.repack_orders.schemas import (
    RepackOrderCreate,
    RepackOrderFilters,
    RepackOrderInputCreate,
    RepackOrderInputFilters,
    RepackOrderInputUpdate,
    RepackOrderOutputCreate,
    RepackOrderOutputFilters,
    RepackOrderOutputUpdate,
    RepackOrderUpdate,
)
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import (
    SortSpec,
    apply_sort,
    search_clause,
    where_gte_if_not_none,
    where_lte_if_not_none,
)

ORDER_SORT_COLUMNS = {
    "document_no": RepackOrder.document_no,
    "status": RepackOrder.status,
    "created_at": RepackOrder.created_at,
    "id": RepackOrder.id,
}
INPUT_SORT_COLUMNS = {
    "line_no": RepackOrderInput.line_no,
    "product_variant_id": RepackOrderInput.product_variant_id,
    "stock_batch_id": RepackOrderInput.stock_batch_id,
    "id": RepackOrderInput.id,
}
OUTPUT_SORT_COLUMNS = {
    "line_no": RepackOrderOutput.line_no,
    "product_variant_id": RepackOrderOutput.product_variant_id,
    "created_stock_batch_id": RepackOrderOutput.created_stock_batch_id,
    "id": RepackOrderOutput.id,
}
ZERO = Decimal("0")


@dataclass(frozen=True)
class RepackVariantUnit:
    variant: ProductVariant
    variant_unit: VariantUnit


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
) -> RepackOrder | None:
    return await db.scalar(
        select(RepackOrder).where(
            RepackOrder.tenant_id == tenant_id,
            RepackOrder.id == repack_order_id,
        )
    )


async def get_order_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
) -> RepackOrder | None:
    return await db.scalar(
        select(RepackOrder)
        .options(
            selectinload(RepackOrder.inputs),
            selectinload(RepackOrder.outputs),
        )
        .where(
            RepackOrder.tenant_id == tenant_id,
            RepackOrder.id == repack_order_id,
        )
    )


async def list_repack_orders(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: RepackOrderFilters,
    sort: tuple[SortSpec, ...],
) -> Page[RepackOrder]:
    stmt = _apply_order_filters(
        select(RepackOrder).where(RepackOrder.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, ORDER_SORT_COLUMNS)
    count_stmt = _apply_order_filters(
        select(func.count(RepackOrder.id)).where(RepackOrder.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: RepackOrderCreate,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrder:
    try:
        order = await _create_order_draft(db, tenant_id, data, actor_user_id=actor_user_id)
    except Exception:
        await db.rollback()
        raise
    await db.refresh(order)
    detail = await get_order_detail_by_id(db, tenant_id, order.id)
    assert detail is not None
    return detail


async def _create_order_draft(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: RepackOrderCreate,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrder:
    await _ensure_active_location(db, tenant_id, data.location_id)
    if data.performed_by is not None:
        await _ensure_active_employee(db, tenant_id, data.performed_by)
    order = RepackOrder(
        tenant_id=tenant_id,
        status=DocumentStatus.DRAFT,
        created_by=actor_user_id,
        document_no=await generate_document_no(db, tenant_id, "repack_order", datetime.now(UTC)),
        location_id=data.location_id,
        performed_by=data.performed_by,
        notes=data.notes,
    )
    db.add(order)
    await db.flush()

    input_lines = [
        await _build_input_line(db, tenant_id, order.id, line_data) for line_data in data.inputs
    ]
    db.add_all(input_lines)
    await db.flush()

    output_lines = [
        await _build_output_line(db, tenant_id, order.id, line_data) for line_data in data.outputs
    ]
    db.add_all(output_lines)
    await db.flush()

    await _recalculate_totals(order, input_lines, output_lines)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_orders.create",
        entity_type="repack_order",
        entity_id=order.id,
        after_json=_order_loggable(order),
    )
    await db.commit()
    return order


async def update_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    data: RepackOrderUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrder:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    _ensure_draft(order)
    before = _order_loggable(order)
    fields = data.model_dump(exclude_unset=True)
    if "location_id" in fields:
        await _ensure_active_location(db, tenant_id, fields["location_id"])
    if fields.get("performed_by") is not None:
        await _ensure_active_employee(db, tenant_id, fields["performed_by"])
    for key, value in fields.items():
        setattr(order, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_orders.update",
        entity_type="repack_order",
        entity_id=order.id,
        before_json=before,
        after_json=_order_loggable(order),
    )
    await db.commit()
    await db.refresh(order)
    detail = await get_order_detail_by_id(db, tenant_id, order.id)
    assert detail is not None
    return detail


async def cancel_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    if order.status != DocumentStatus.DRAFT:
        raise RepackOrderNotCancellable()
    before = _order_loggable(order)
    order.status = DocumentStatus.CANCELLED
    order.cancelled_at = datetime.now(UTC)
    order.cancelled_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_orders.cancel",
        entity_type="repack_order",
        entity_id=order.id,
        before_json=before,
        after_json=_order_loggable(order),
    )
    await db.commit()


async def post_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrder:
    try:
        order = await _post_order_atomically(
            db,
            tenant_id,
            repack_order_id,
            actor_user_id=actor_user_id,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(order)
    detail = await get_order_detail_by_id(db, tenant_id, order.id)
    assert detail is not None
    return detail


async def _post_order_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrder:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    if order.status != DocumentStatus.DRAFT:
        raise RepackOrderNotPostable()
    input_lines = await _order_inputs(db, tenant_id, order.id)
    if not input_lines:
        raise RepackOrderHasNoInputs()
    output_lines = await _order_outputs(db, tenant_id, order.id)
    if not output_lines:
        raise RepackOrderHasNoOutputs()
    await _ensure_active_location(db, tenant_id, order.location_id)
    if order.performed_by is not None:
        await _ensure_active_employee(db, tenant_id, order.performed_by)
    before = _order_loggable(order)
    await _recalculate_totals(order, input_lines, output_lines)
    posted_at = datetime.now(UTC)
    posted_inventory: list[dict[str, str]] = []

    for line in input_lines:
        await _ensure_input_references(
            db,
            tenant_id,
            line.product_variant_id,
            line.stock_batch_id,
            line.variant_unit_id,
        )
        balance = await _get_balance(
            db,
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            location_id=order.location_id,
            stock_batch_id=line.stock_batch_id,
        )
        if balance is None or balance.quantity_base - line.quantity_base < ZERO:
            raise RepackOrderInsufficientBalance()
        balance.quantity_base -= line.quantity_base
        balance.updated_at = posted_at
        movement = StockMovement(
            tenant_id=tenant_id,
            movement_type=StockMovementType.REPACK_INPUT,
            source_type=SourceType.REPACK_ORDER,
            source_id=order.id,
            source_line_id=line.id,
            product_variant_id=line.product_variant_id,
            stock_batch_id=line.stock_batch_id,
            location_id=order.location_id,
            quantity_base=-line.quantity_base,
            unit_cost_base=line.unit_cost_base,
            total_cost=-line.total_cost,
            notes=f"Repack order {order.document_no}",
            posted_at=posted_at,
            posted_by=actor_user_id,
            created_at=posted_at,
        )
        db.add(movement)
        await db.flush()
        posted_inventory.append(
            {
                "input_line_id": str(line.id),
                "stock_batch_id": str(line.stock_batch_id),
                "stock_movement_id": str(movement.id),
                "stock_balance_id": str(balance.id),
            }
        )

    for line in output_lines:
        variant_unit_pair = await _ensure_output_references(
            db,
            tenant_id,
            line.product_variant_id,
            line.variant_unit_id,
        )
        if variant_unit_pair.variant.track_batches and not line.lot_number:
            line.lot_number = await generate_lot_number(db, tenant_id, posted_at)
        batch = StockBatch(
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            source_type=SourceType.REPACK_ORDER,
            source_id=order.id,
            source_line_id=line.id,
            supplier_id=None,
            received_at=posted_at,
            expiry_date=line.expiry_date,
            manufactured_date=None,
            lot_number=line.lot_number,
            initial_quantity_base=line.quantity_base,
            unit_cost_base=line.unit_cost_base,
            total_cost=line.allocated_cost,
            conversion_to_base=line.conversion_to_base,
            status=StockBatchStatus.ACTIVE,
            created_at=posted_at,
        )
        db.add(batch)
        await db.flush()
        line.created_stock_batch_id = batch.id
        balance = await _get_or_create_balance(
            db,
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            location_id=order.location_id,
            stock_batch_id=batch.id,
            updated_at=posted_at,
        )
        balance.quantity_base += line.quantity_base
        balance.updated_at = posted_at
        movement = StockMovement(
            tenant_id=tenant_id,
            movement_type=StockMovementType.REPACK_OUTPUT,
            source_type=SourceType.REPACK_ORDER,
            source_id=order.id,
            source_line_id=line.id,
            product_variant_id=line.product_variant_id,
            stock_batch_id=batch.id,
            location_id=order.location_id,
            quantity_base=line.quantity_base,
            unit_cost_base=line.unit_cost_base,
            total_cost=line.allocated_cost,
            notes=f"Repack order {order.document_no}",
            posted_at=posted_at,
            posted_by=actor_user_id,
            created_at=posted_at,
        )
        db.add(movement)
        await db.flush()
        posted_inventory.append(
            {
                "output_line_id": str(line.id),
                "stock_batch_id": str(batch.id),
                "stock_movement_id": str(movement.id),
                "stock_balance_id": str(balance.id),
            }
        )

    order.status = DocumentStatus.POSTED
    order.posted_at = posted_at
    order.posted_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_orders.post",
        entity_type="repack_order",
        entity_id=order.id,
        before_json=before,
        after_json=_order_loggable(order) | {"posted_inventory": posted_inventory},
    )
    await db.commit()
    return order


async def _build_input_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    data: RepackOrderInputCreate,
) -> RepackOrderInput:
    variant_unit_pair = await _ensure_input_references(
        db,
        tenant_id,
        data.product_variant_id,
        data.stock_batch_id,
        data.variant_unit_id,
    )
    batch = await _get_existing_batch(db, tenant_id, data.product_variant_id, data.stock_batch_id)
    quantity_base = quantity_base_for_unit(
        data.quantity,
        variant_unit_pair.variant_unit.conversion_to_base,
        allow_decimal_quantity=variant_unit_pair.variant_unit.allow_decimal_quantity,
        rounding_precision=variant_unit_pair.variant_unit.rounding_precision,
    )
    return RepackOrderInput(
        tenant_id=tenant_id,
        repack_order_id=repack_order_id,
        conversion_to_base=variant_unit_pair.variant_unit.conversion_to_base,
        quantity_base=quantity_base,
        unit_cost_base=batch.unit_cost_base,
        total_cost=quantity_base * batch.unit_cost_base,
        **data.model_dump(),
    )


async def _build_output_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    data: RepackOrderOutputCreate,
) -> RepackOrderOutput:
    variant_unit_pair = await _ensure_output_references(
        db, tenant_id, data.product_variant_id, data.variant_unit_id
    )
    quantity_base = quantity_base_for_unit(
        data.quantity,
        variant_unit_pair.variant_unit.conversion_to_base,
        allow_decimal_quantity=variant_unit_pair.variant_unit.allow_decimal_quantity,
        rounding_precision=variant_unit_pair.variant_unit.rounding_precision,
    )
    line = RepackOrderOutput(
        tenant_id=tenant_id,
        repack_order_id=repack_order_id,
        conversion_to_base=variant_unit_pair.variant_unit.conversion_to_base,
        quantity_base=quantity_base,
        unit_cost_base=_unit_cost_base(data.allocated_cost, quantity_base),
        **data.model_dump(),
    )
    if variant_unit_pair.variant.track_batches and not line.lot_number:
        line.lot_number = await generate_lot_number(db, tenant_id, datetime.now(UTC))
    return line


async def create_input(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    data: RepackOrderInputCreate,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrderInput:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    _ensure_draft(order)
    await _ensure_input_line_no_available(db, tenant_id, repack_order_id, data.line_no)
    line = await _build_input_line(db, tenant_id, repack_order_id, data)
    db.add(line)
    await db.flush()
    await _recalculate_order_totals(db, tenant_id, order)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_order_inputs.create",
        entity_type="repack_order_input",
        entity_id=line.id,
        after_json=_input_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def update_input(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    input_id: uuid.UUID,
    data: RepackOrderInputUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrderInput:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    _ensure_draft(order)
    line = await _get_existing_input(db, tenant_id, repack_order_id, input_id)
    before = _input_loggable(line)
    fields = data.model_dump(exclude_unset=True)
    new_line_no = fields.get("line_no")
    if new_line_no is not None and new_line_no != line.line_no:
        await _ensure_input_line_no_available(
            db,
            tenant_id,
            repack_order_id,
            new_line_no,
            input_id=line.id,
        )
    product_variant_id = fields.get("product_variant_id", line.product_variant_id)
    stock_batch_id = fields.get("stock_batch_id", line.stock_batch_id)
    variant_unit_id = fields.get("variant_unit_id", line.variant_unit_id)
    variant_unit_pair = await _ensure_input_references(
        db,
        tenant_id,
        product_variant_id,
        stock_batch_id,
        variant_unit_id,
    )
    batch = await _get_existing_batch(db, tenant_id, product_variant_id, stock_batch_id)
    for key, value in fields.items():
        setattr(line, key, value)
    line.product_variant_id = product_variant_id
    line.stock_batch_id = stock_batch_id
    line.variant_unit_id = variant_unit_id
    line.conversion_to_base = variant_unit_pair.variant_unit.conversion_to_base
    line.quantity_base = quantity_base_for_unit(
        line.quantity,
        line.conversion_to_base,
        allow_decimal_quantity=variant_unit_pair.variant_unit.allow_decimal_quantity,
        rounding_precision=variant_unit_pair.variant_unit.rounding_precision,
    )
    line.unit_cost_base = batch.unit_cost_base
    line.total_cost = line.quantity_base * line.unit_cost_base
    await db.flush()
    await _recalculate_order_totals(db, tenant_id, order)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_order_inputs.update",
        entity_type="repack_order_input",
        entity_id=line.id,
        before_json=before,
        after_json=_input_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def delete_input(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    input_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    _ensure_draft(order)
    line = await _get_existing_input(db, tenant_id, repack_order_id, input_id)
    before = _input_loggable(line)
    await db.delete(line)
    await db.flush()
    await _recalculate_order_totals(db, tenant_id, order)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_order_inputs.delete",
        entity_type="repack_order_input",
        entity_id=line.id,
        before_json=before,
    )
    await db.commit()


async def create_output(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    data: RepackOrderOutputCreate,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrderOutput:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    _ensure_draft(order)
    await _ensure_output_line_no_available(db, tenant_id, repack_order_id, data.line_no)
    line = await _build_output_line(db, tenant_id, repack_order_id, data)
    db.add(line)
    await db.flush()
    await _recalculate_order_totals(db, tenant_id, order)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_order_outputs.create",
        entity_type="repack_order_output",
        entity_id=line.id,
        after_json=_output_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def update_output(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    output_id: uuid.UUID,
    data: RepackOrderOutputUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> RepackOrderOutput:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    _ensure_draft(order)
    line = await _get_existing_output(db, tenant_id, repack_order_id, output_id)
    before = _output_loggable(line)
    fields = data.model_dump(exclude_unset=True)
    new_line_no = fields.get("line_no")
    if new_line_no is not None and new_line_no != line.line_no:
        await _ensure_output_line_no_available(
            db,
            tenant_id,
            repack_order_id,
            new_line_no,
            output_id=line.id,
        )
    product_variant_id = fields.get("product_variant_id", line.product_variant_id)
    variant_unit_id = fields.get("variant_unit_id", line.variant_unit_id)
    variant_unit_pair = await _ensure_output_references(
        db,
        tenant_id,
        product_variant_id,
        variant_unit_id,
    )
    for key, value in fields.items():
        setattr(line, key, value)
    line.product_variant_id = product_variant_id
    line.variant_unit_id = variant_unit_id
    line.conversion_to_base = variant_unit_pair.variant_unit.conversion_to_base
    line.quantity_base = quantity_base_for_unit(
        line.quantity,
        line.conversion_to_base,
        allow_decimal_quantity=variant_unit_pair.variant_unit.allow_decimal_quantity,
        rounding_precision=variant_unit_pair.variant_unit.rounding_precision,
    )
    line.unit_cost_base = _unit_cost_base(line.allocated_cost, line.quantity_base)
    if variant_unit_pair.variant.track_batches and not line.lot_number:
        line.lot_number = await generate_lot_number(db, tenant_id, datetime.now(UTC))
    await db.flush()
    await _recalculate_order_totals(db, tenant_id, order)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_order_outputs.update",
        entity_type="repack_order_output",
        entity_id=line.id,
        before_json=before,
        after_json=_output_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def delete_output(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    output_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    order = await _get_existing_order(db, tenant_id, repack_order_id)
    _ensure_draft(order)
    line = await _get_existing_output(db, tenant_id, repack_order_id, output_id)
    before = _output_loggable(line)
    await db.delete(line)
    await db.flush()
    await _recalculate_order_totals(db, tenant_id, order)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="repack_order_outputs.delete",
        entity_type="repack_order_output",
        entity_id=line.id,
        before_json=before,
    )
    await db.commit()


async def get_input_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    input_id: uuid.UUID,
) -> RepackOrderInput | None:
    return await db.scalar(
        select(RepackOrderInput).where(
            RepackOrderInput.tenant_id == tenant_id,
            RepackOrderInput.repack_order_id == repack_order_id,
            RepackOrderInput.id == input_id,
        )
    )


async def list_inputs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    pagination: PaginationParams,
    filters: RepackOrderInputFilters,
    sort: tuple[SortSpec, ...],
) -> Page[RepackOrderInput]:
    await _get_existing_order(db, tenant_id, repack_order_id)
    stmt = _apply_input_filters(
        select(RepackOrderInput).where(
            RepackOrderInput.tenant_id == tenant_id,
            RepackOrderInput.repack_order_id == repack_order_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, INPUT_SORT_COLUMNS)
    count_stmt = _apply_input_filters(
        select(func.count(RepackOrderInput.id)).where(
            RepackOrderInput.tenant_id == tenant_id,
            RepackOrderInput.repack_order_id == repack_order_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_output_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    output_id: uuid.UUID,
) -> RepackOrderOutput | None:
    return await db.scalar(
        select(RepackOrderOutput).where(
            RepackOrderOutput.tenant_id == tenant_id,
            RepackOrderOutput.repack_order_id == repack_order_id,
            RepackOrderOutput.id == output_id,
        )
    )


async def list_outputs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    pagination: PaginationParams,
    filters: RepackOrderOutputFilters,
    sort: tuple[SortSpec, ...],
) -> Page[RepackOrderOutput]:
    await _get_existing_order(db, tenant_id, repack_order_id)
    stmt = _apply_output_filters(
        select(RepackOrderOutput).where(
            RepackOrderOutput.tenant_id == tenant_id,
            RepackOrderOutput.repack_order_id == repack_order_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, OUTPUT_SORT_COLUMNS)
    count_stmt = _apply_output_filters(
        select(func.count(RepackOrderOutput.id)).where(
            RepackOrderOutput.tenant_id == tenant_id,
            RepackOrderOutput.repack_order_id == repack_order_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def _get_existing_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
) -> RepackOrder:
    order = await get_by_id(db, tenant_id, repack_order_id)
    if order is None:
        raise RepackOrderNotFound()
    return order


async def _get_existing_input(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    input_id: uuid.UUID,
) -> RepackOrderInput:
    line = await get_input_by_id(db, tenant_id, repack_order_id, input_id)
    if line is None:
        raise RepackOrderInputNotFound()
    return line


async def _get_existing_output(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    output_id: uuid.UUID,
) -> RepackOrderOutput:
    line = await get_output_by_id(db, tenant_id, repack_order_id, output_id)
    if line is None:
        raise RepackOrderOutputNotFound()
    return line


def _ensure_draft(order: RepackOrder) -> None:
    if order.status != DocumentStatus.DRAFT:
        raise RepackOrderNotDraft()


async def _ensure_document_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_no: str,
    *,
    repack_order_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(RepackOrder).where(
            RepackOrder.tenant_id == tenant_id,
            RepackOrder.document_no == document_no,
        )
    )
    if existing is not None and existing.id != repack_order_id:
        raise RepackOrderDocumentNoConflict()


async def _ensure_input_line_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    line_no: int,
    *,
    input_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(RepackOrderInput).where(
            RepackOrderInput.tenant_id == tenant_id,
            RepackOrderInput.repack_order_id == repack_order_id,
            RepackOrderInput.line_no == line_no,
        )
    )
    if existing is not None and existing.id != input_id:
        raise RepackOrderInputLineNoConflict()


async def _ensure_output_line_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
    line_no: int,
    *,
    output_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(RepackOrderOutput).where(
            RepackOrderOutput.tenant_id == tenant_id,
            RepackOrderOutput.repack_order_id == repack_order_id,
            RepackOrderOutput.line_no == line_no,
        )
    )
    if existing is not None and existing.id != output_id:
        raise RepackOrderOutputLineNoConflict()


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
        raise InvalidRepackOrderLocation()
    return location


async def _ensure_active_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> Employee:
    employee = await db.scalar(
        select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.id == employee_id,
            Employee.is_active.is_(True),
        )
    )
    if employee is None:
        raise InvalidRepackOrderEmployee()
    return employee


async def _ensure_input_references(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
) -> RepackVariantUnit:
    variant = await _ensure_active_variant(db, tenant_id, product_variant_id, input_line=True)
    await _get_existing_batch(db, tenant_id, product_variant_id, stock_batch_id)
    variant_unit = await _get_active_variant_unit(
        db, tenant_id, product_variant_id, variant_unit_id
    )
    if variant_unit is None:
        raise InvalidRepackOrderInputUnit()
    return RepackVariantUnit(variant=variant, variant_unit=variant_unit)


async def _ensure_output_references(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
) -> RepackVariantUnit:
    variant = await _ensure_active_variant(db, tenant_id, product_variant_id, input_line=False)
    variant_unit = await _get_active_variant_unit(
        db, tenant_id, product_variant_id, variant_unit_id
    )
    if variant_unit is None:
        raise InvalidRepackOrderOutputUnit()
    return RepackVariantUnit(variant=variant, variant_unit=variant_unit)


async def _ensure_active_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    *,
    input_line: bool,
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
        if input_line:
            raise InvalidRepackOrderInputProduct()
        raise InvalidRepackOrderOutputProduct()
    return variant


async def _get_active_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
) -> VariantUnit | None:
    return await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.product_variant_id == product_variant_id,
            VariantUnit.id == variant_unit_id,
            VariantUnit.is_active.is_(True),
        )
    )


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
        raise InvalidRepackOrderInputBatch()
    return batch


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


async def _order_inputs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
) -> list[RepackOrderInput]:
    return list(
        (
            await db.execute(
                select(RepackOrderInput)
                .where(
                    RepackOrderInput.tenant_id == tenant_id,
                    RepackOrderInput.repack_order_id == repack_order_id,
                )
                .order_by(RepackOrderInput.line_no, RepackOrderInput.id)
            )
        )
        .scalars()
        .all()
    )


async def _order_outputs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    repack_order_id: uuid.UUID,
) -> list[RepackOrderOutput]:
    return list(
        (
            await db.execute(
                select(RepackOrderOutput)
                .where(
                    RepackOrderOutput.tenant_id == tenant_id,
                    RepackOrderOutput.repack_order_id == repack_order_id,
                )
                .order_by(RepackOrderOutput.line_no, RepackOrderOutput.id)
            )
        )
        .scalars()
        .all()
    )


async def _recalculate_order_totals(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    order: RepackOrder,
) -> None:
    inputs = await _order_inputs(db, tenant_id, order.id)
    outputs = await _order_outputs(db, tenant_id, order.id)
    await _recalculate_totals(order, inputs, outputs)
    await db.flush()


async def _recalculate_totals(
    order: RepackOrder,
    inputs: list[RepackOrderInput],
    outputs: list[RepackOrderOutput],
) -> None:
    total_input_cost = sum((line.total_cost for line in inputs), ZERO)
    total_output_cost = sum((line.allocated_cost for line in outputs), ZERO)
    if total_output_cost > total_input_cost:
        raise RepackOrderOutputCostExceedsInputCost()
    total_input_quantity_base = sum((line.quantity_base for line in inputs), ZERO)
    total_output_quantity_base = sum((line.quantity_base for line in outputs), ZERO)
    if total_output_quantity_base > total_input_quantity_base:
        raise RepackOrderOutputQuantityExceedsInputQuantity()
    order.total_input_cost = total_input_cost
    order.total_output_cost = total_output_cost
    order.waste_cost = total_input_cost - total_output_cost
    order.total_input_quantity_base = total_input_quantity_base
    order.total_output_quantity_base = total_output_quantity_base


def _unit_cost_base(allocated_cost: Decimal, quantity_base: Decimal) -> Decimal:
    return allocated_cost / quantity_base


def _apply_order_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: RepackOrderFilters,
) -> StmtT:
    search = search_clause([RepackOrder.document_no, RepackOrder.notes], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.location_id is not None:
        stmt = stmt.where(RepackOrder.location_id == filters.location_id)
    if filters.status is not None:
        stmt = stmt.where(RepackOrder.status == filters.status)
    if filters.performed_by is not None:
        stmt = stmt.where(RepackOrder.performed_by == filters.performed_by)
    stmt = where_gte_if_not_none(stmt, RepackOrder.created_at, filters.created_at_gte)
    stmt = where_lte_if_not_none(stmt, RepackOrder.created_at, filters.created_at_lte)
    return stmt


def _apply_input_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: RepackOrderInputFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(RepackOrderInput.product_variant_id == filters.product_variant_id)
    if filters.stock_batch_id is not None:
        stmt = stmt.where(RepackOrderInput.stock_batch_id == filters.stock_batch_id)
    if filters.variant_unit_id is not None:
        stmt = stmt.where(RepackOrderInput.variant_unit_id == filters.variant_unit_id)
    return stmt


def _apply_output_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: RepackOrderOutputFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(RepackOrderOutput.product_variant_id == filters.product_variant_id)
    if filters.variant_unit_id is not None:
        stmt = stmt.where(RepackOrderOutput.variant_unit_id == filters.variant_unit_id)
    if filters.created_stock_batch_id is not None:
        stmt = stmt.where(
            RepackOrderOutput.created_stock_batch_id == filters.created_stock_batch_id
        )
    return stmt


def _order_loggable(order: RepackOrder) -> dict[str, Any]:
    return {
        "id": str(order.id),
        "document_no": order.document_no,
        "location_id": str(order.location_id),
        "status": order.status.value,
        "performed_by": str(order.performed_by) if order.performed_by else None,
        "total_input_cost": str(order.total_input_cost),
        "total_output_cost": str(order.total_output_cost),
        "waste_cost": str(order.waste_cost),
        "posted_by": str(order.posted_by) if order.posted_by else None,
        "posted_at": order.posted_at.isoformat() if order.posted_at else None,
        "cancelled_by": str(order.cancelled_by) if order.cancelled_by else None,
        "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
        "reversal_of_id": str(order.reversal_of_id) if order.reversal_of_id else None,
        "notes": order.notes,
        "created_by": str(order.created_by) if order.created_by else None,
    }


def _input_loggable(line: RepackOrderInput) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "repack_order_id": str(line.repack_order_id),
        "line_no": line.line_no,
        "product_variant_id": str(line.product_variant_id),
        "variant_unit_id": str(line.variant_unit_id),
        "stock_batch_id": str(line.stock_batch_id),
        "quantity": str(line.quantity),
        "conversion_to_base": str(line.conversion_to_base),
        "quantity_base": str(line.quantity_base),
        "unit_cost_base": str(line.unit_cost_base),
        "total_cost": str(line.total_cost),
    }


def _output_loggable(line: RepackOrderOutput) -> dict[str, Any]:
    return {
        "id": str(line.id),
        "repack_order_id": str(line.repack_order_id),
        "line_no": line.line_no,
        "product_variant_id": str(line.product_variant_id),
        "variant_unit_id": str(line.variant_unit_id),
        "quantity": str(line.quantity),
        "conversion_to_base": str(line.conversion_to_base),
        "quantity_base": str(line.quantity_base),
        "allocated_cost": str(line.allocated_cost),
        "unit_cost_base": str(line.unit_cost_base),
        "expiry_date": line.expiry_date.isoformat() if line.expiry_date else None,
        "lot_number": line.lot_number,
        "created_stock_batch_id": (
            str(line.created_stock_batch_id) if line.created_stock_batch_id else None
        ),
    }
