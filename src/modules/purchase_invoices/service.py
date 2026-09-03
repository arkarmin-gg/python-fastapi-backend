import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.decimal_utils import quantity_base_for_unit
from src.foundation_enums import (
    DocumentStatus,
    LandedCostAllocationMethod,
    PartyStatus,
    SourceType,
    StockBatchStatus,
    StockMovementType,
)
from src.modules.audit_logs.service import record_audit_log
from src.modules.catalog.models import ProductVariant, VariantUnit
from src.modules.document_numbers.service import generate_document_no, generate_lot_number
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.purchase_invoices.exceptions import (
    InvalidPurchaseInvoiceLineProduct,
    InvalidPurchaseInvoiceLineUnit,
    InvalidPurchaseInvoiceLocation,
    InvalidPurchaseInvoiceSupplier,
    InvalidPurchaseLandedCostAllocation,
    PurchaseInvoiceDocumentNoConflict,
    PurchaseInvoiceHasNoLines,
    PurchaseInvoiceLineMeasuredQuantityRequired,
    PurchaseInvoiceLineMissingExpiryDate,
    PurchaseInvoiceLineMissingLotNumber,
    PurchaseInvoiceLineNoConflict,
    PurchaseInvoiceLineNotFound,
    PurchaseInvoiceLineProductNotInventoryTracked,
    PurchaseInvoiceNotCancellable,
    PurchaseInvoiceNotDraft,
    PurchaseInvoiceNotFound,
    PurchaseInvoiceNotPostable,
    PurchaseLandedCostNotFound,
)
from src.modules.purchase_invoices.models import (
    PurchaseInvoice,
    PurchaseInvoiceLine,
    PurchaseLandedCost,
)
from src.modules.purchase_invoices.schemas import (
    PurchaseInvoiceCreate,
    PurchaseInvoiceFilters,
    PurchaseInvoiceLineCreate,
    PurchaseInvoiceLineFilters,
    PurchaseInvoiceLineUpdate,
    PurchaseInvoiceUpdate,
    PurchaseLandedCostCreate,
    PurchaseLandedCostFilters,
    PurchaseLandedCostUpdate,
)
from src.modules.suppliers.models import Supplier
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import (
    SortSpec,
    apply_sort,
    search_clause,
    where_gte_if_not_none,
    where_lte_if_not_none,
)

PURCHASE_INVOICE_SORT_COLUMNS = {
    "document_no": PurchaseInvoice.document_no,
    "invoice_date": PurchaseInvoice.invoice_date,
    "status": PurchaseInvoice.status,
    "total_amount": PurchaseInvoice.total_amount,
    "created_at": PurchaseInvoice.created_at,
    "id": PurchaseInvoice.id,
}
PURCHASE_INVOICE_LINE_SORT_COLUMNS = {
    "line_no": PurchaseInvoiceLine.line_no,
    "product_variant_id": PurchaseInvoiceLine.product_variant_id,
    "variant_unit_id": PurchaseInvoiceLine.variant_unit_id,
    "id": PurchaseInvoiceLine.id,
}
PURCHASE_LANDED_COST_SORT_COLUMNS = {
    "cost_type": PurchaseLandedCost.cost_type,
    "amount": PurchaseLandedCost.amount,
    "created_at": PurchaseLandedCost.created_at,
    "id": PurchaseLandedCost.id,
}
ZERO = Decimal("0")


@dataclass(frozen=True)
class PurchaseVariantUnit:
    variant: ProductVariant
    variant_unit: VariantUnit


def _effective_conversion(
    variant_unit: VariantUnit,
    measured_quantity: Decimal | None,
) -> Decimal:
    """Base units contained in one purchase unit for this line.

    ``measured_quantity`` records the actually weighed content of one purchase
    unit (e.g. a nominal 25-viss bag weighing 24.4 viss), so when present it is
    the effective conversion; otherwise the static catalog conversion applies.
    Keeps the invariant ``quantity_base == quantity * conversion_to_base``.
    """
    if measured_quantity is not None:
        return measured_quantity
    return variant_unit.conversion_to_base


def _resolve_quantity_base(
    variant_unit: VariantUnit,
    quantity: Decimal,
    measured_quantity: Decimal | None,
) -> Decimal:
    if variant_unit.requires_measured_quantity and measured_quantity is None:
        raise PurchaseInvoiceLineMeasuredQuantityRequired()
    return quantity_base_for_unit(
        quantity,
        measured_quantity if measured_quantity is not None else variant_unit.conversion_to_base,
        allow_decimal_quantity=variant_unit.allow_decimal_quantity,
        rounding_precision=variant_unit.rounding_precision,
    )


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> PurchaseInvoice | None:
    return await db.scalar(
        _purchase_invoice_by_id_stmt(tenant_id, purchase_invoice_id, for_update=for_update)
    )


def _purchase_invoice_by_id_stmt(
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Select[tuple[PurchaseInvoice]]:
    stmt = select(PurchaseInvoice).where(
        PurchaseInvoice.tenant_id == tenant_id,
        PurchaseInvoice.id == purchase_invoice_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return stmt


async def get_invoice_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
) -> PurchaseInvoice | None:
    return await db.scalar(
        select(PurchaseInvoice)
        .options(
            joinedload(PurchaseInvoice.posted_by_user),
            selectinload(PurchaseInvoice.lines),
            selectinload(PurchaseInvoice.landed_costs),
        )
        .where(
            PurchaseInvoice.tenant_id == tenant_id,
            PurchaseInvoice.id == purchase_invoice_id,
        )
    )


async def list_purchase_invoices(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: PurchaseInvoiceFilters,
    sort: tuple[SortSpec, ...],
) -> Page[PurchaseInvoice]:
    stmt = _apply_invoice_filters(
        select(PurchaseInvoice)
        .options(joinedload(PurchaseInvoice.posted_by_user))
        .where(PurchaseInvoice.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, PURCHASE_INVOICE_SORT_COLUMNS)
    count_stmt = _apply_invoice_filters(
        select(func.count(distinct(PurchaseInvoice.id))).where(
            PurchaseInvoice.tenant_id == tenant_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: PurchaseInvoiceCreate,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseInvoice:
    try:
        invoice = await _create_invoice_draft(
            db,
            tenant_id,
            data,
            actor_user_id=actor_user_id,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(invoice)
    detail = await get_invoice_detail_by_id(db, tenant_id, invoice.id)
    assert detail is not None
    return detail


async def _create_invoice_draft(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: PurchaseInvoiceCreate,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseInvoice:
    await _ensure_active_supplier(db, tenant_id, data.supplier_id)
    invoice = PurchaseInvoice(
        tenant_id=tenant_id,
        created_by=actor_user_id,
        status=DocumentStatus.DRAFT,
        document_no=await generate_document_no(
            db, tenant_id, "purchase_invoice", data.invoice_date
        ),
        **data.model_dump(exclude={"lines", "landed_costs"}),
    )
    db.add(invoice)
    await db.flush()

    lines = [await _build_line(db, tenant_id, invoice.id, line_data) for line_data in data.lines]
    db.add_all(line for line, _variant in lines)
    await db.flush()

    for cost_data in data.landed_costs:
        _ensure_supported_allocation(cost_data.allocation_method)
        db.add(
            PurchaseLandedCost(
                tenant_id=tenant_id,
                purchase_invoice_id=invoice.id,
                **cost_data.model_dump(),
            )
        )
    await db.flush()

    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_invoices.create",
        entity_type="purchase_invoice",
        entity_id=invoice.id,
        after_json=_invoice_loggable(invoice),
    )
    await db.commit()
    return invoice


async def update_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    data: PurchaseInvoiceUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseInvoice:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    _ensure_draft(invoice)
    before = _invoice_loggable(invoice)
    fields = data.model_dump(exclude_unset=True)
    if "supplier_id" in fields:
        await _ensure_active_supplier(db, tenant_id, fields["supplier_id"])
    for key, value in fields.items():
        setattr(invoice, key, value)
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_invoices.update",
        entity_type="purchase_invoice",
        entity_id=invoice.id,
        before_json=before,
        after_json=_invoice_loggable(invoice),
    )
    await db.commit()
    await db.refresh(invoice)
    detail = await get_invoice_detail_by_id(db, tenant_id, invoice.id)
    assert detail is not None
    return detail


async def cancel_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    if invoice.status != DocumentStatus.DRAFT:
        raise PurchaseInvoiceNotCancellable()
    before = _invoice_loggable(invoice)
    invoice.status = DocumentStatus.CANCELLED
    invoice.cancelled_at = datetime.now(UTC)
    invoice.cancelled_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_invoices.cancel",
        entity_type="purchase_invoice",
        entity_id=invoice.id,
        before_json=before,
        after_json=_invoice_loggable(invoice),
    )
    await db.commit()


async def post_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseInvoice:
    try:
        invoice = await _post_invoice_atomically(
            db,
            tenant_id,
            purchase_invoice_id,
            actor_user_id=actor_user_id,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(invoice)
    detail = await get_invoice_detail_by_id(db, tenant_id, invoice.id)
    assert detail is not None
    return detail


async def _post_invoice_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseInvoice:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    if invoice.status != DocumentStatus.DRAFT:
        raise PurchaseInvoiceNotPostable()
    lines = await _invoice_lines(db, tenant_id, invoice.id)
    if not lines:
        raise PurchaseInvoiceHasNoLines()
    await _recalculate_invoice_totals(db, invoice)
    before = _invoice_loggable(invoice)

    for line in lines:
        variant = await _ensure_active_purchase_variant(db, tenant_id, line.product_variant_id)
        if variant.track_batches and not line.lot_number:
            line.lot_number = await generate_lot_number(db, tenant_id, datetime.now(UTC))
        _ensure_line_postable(line, variant)
    for location_id in {line.location_id for line in lines}:
        await _ensure_active_location(db, tenant_id, location_id)

    posted_at = datetime.now(UTC)
    posted_inventory: list[dict[str, str]] = []
    for line in lines:
        batch = StockBatch(
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            source_type=SourceType.PURCHASE_INVOICE,
            source_id=invoice.id,
            source_line_id=line.id,
            supplier_id=invoice.supplier_id,
            received_at=posted_at,
            expiry_date=line.expiry_date,
            manufactured_date=line.manufactured_date,
            lot_number=line.lot_number,
            initial_quantity_base=line.quantity_base,
            unit_cost_base=line.unit_cost_base,
            total_cost=line.total_line_cost,
            conversion_to_base=line.conversion_to_base,
            status=StockBatchStatus.ACTIVE,
            created_at=posted_at,
        )
        db.add(batch)
        await db.flush()
        line.created_stock_batch_id = batch.id

        movement = StockMovement(
            tenant_id=tenant_id,
            movement_type=StockMovementType.PURCHASE_RECEIVE,
            source_type=SourceType.PURCHASE_INVOICE,
            source_id=invoice.id,
            source_line_id=line.id,
            product_variant_id=line.product_variant_id,
            stock_batch_id=batch.id,
            location_id=line.location_id,
            quantity_base=line.quantity_base,
            unit_cost_base=line.unit_cost_base,
            total_cost=line.total_line_cost,
            notes=f"Purchase invoice {invoice.document_no}",
            posted_at=posted_at,
            posted_by=actor_user_id,
            created_at=posted_at,
        )
        db.add(movement)
        balance = await _get_or_create_balance(
            db,
            tenant_id=tenant_id,
            product_variant_id=line.product_variant_id,
            location_id=line.location_id,
            stock_batch_id=batch.id,
            updated_at=posted_at,
        )
        balance.quantity_base += line.quantity_base
        balance.updated_at = posted_at
        await db.flush()
        posted_inventory.append(
            {
                "line_id": str(line.id),
                "stock_batch_id": str(batch.id),
                "stock_movement_id": str(movement.id),
                "stock_balance_id": str(balance.id),
            }
        )

    invoice.status = DocumentStatus.POSTED
    invoice.posted_at = posted_at
    invoice.posted_by = actor_user_id
    await db.flush()
    from src.modules.supplier_payments.service import ensure_invoice_ledger_entry

    supplier_ledger_entry = await ensure_invoice_ledger_entry(
        db,
        invoice,
        actor_user_id=actor_user_id,
        posted_at=posted_at,
    )
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_invoices.post",
        entity_type="purchase_invoice",
        entity_id=invoice.id,
        before_json=before,
        after_json=_invoice_loggable(invoice)
        | {
            "posted_inventory": posted_inventory,
            "supplier_ledger_entry_id": str(supplier_ledger_entry.id)
            if supplier_ledger_entry is not None
            else None,
        },
    )
    await db.commit()
    return invoice


async def _build_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    data: PurchaseInvoiceLineCreate,
) -> tuple[PurchaseInvoiceLine, ProductVariant]:
    purchase_variant_unit = await _ensure_active_purchase_variant_unit(
        db,
        tenant_id,
        data.product_variant_id,
        data.variant_unit_id,
    )
    await _ensure_active_location(db, tenant_id, data.location_id)
    quantity_base = _resolve_quantity_base(
        purchase_variant_unit.variant_unit, data.quantity, data.measured_quantity
    )
    effective_conversion = _effective_conversion(
        purchase_variant_unit.variant_unit, data.measured_quantity
    )
    line = PurchaseInvoiceLine(
        tenant_id=tenant_id,
        purchase_invoice_id=purchase_invoice_id,
        conversion_to_base=effective_conversion,
        quantity_base=quantity_base,
        line_amount=data.quantity * data.unit_cost,
        unit_cost_base=data.unit_cost / effective_conversion,
        total_line_cost=data.quantity * data.unit_cost,
        **data.model_dump(),
    )
    if purchase_variant_unit.variant.track_batches and not line.lot_number:
        line.lot_number = await generate_lot_number(db, tenant_id, datetime.now(UTC))
    return line, purchase_variant_unit.variant


async def create_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    data: PurchaseInvoiceLineCreate,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseInvoiceLine:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    _ensure_draft(invoice)
    await _ensure_line_no_available(db, tenant_id, purchase_invoice_id, data.line_no)
    line, _variant = await _build_line(db, tenant_id, purchase_invoice_id, data)
    db.add(line)
    await db.flush()
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_invoice_lines.create",
        entity_type="purchase_invoice_line",
        entity_id=line.id,
        after_json=_line_loggable(line),
    )
    await db.commit()
    await db.refresh(line)
    return line


async def update_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    data: PurchaseInvoiceLineUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseInvoiceLine:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    _ensure_draft(invoice)
    line = await _get_existing_line(db, tenant_id, purchase_invoice_id, line_id)
    before = _line_loggable(line)
    fields = data.model_dump(exclude_unset=True)
    new_line_no = fields.get("line_no")
    if new_line_no is not None and new_line_no != line.line_no:
        await _ensure_line_no_available(
            db,
            tenant_id,
            purchase_invoice_id,
            new_line_no,
            line_id=line.id,
        )
    product_variant_id = fields.get("product_variant_id", line.product_variant_id)
    variant_unit_id = fields.get("variant_unit_id", line.variant_unit_id)
    purchase_variant_unit = await _ensure_active_purchase_variant_unit(
        db,
        tenant_id,
        product_variant_id,
        variant_unit_id,
    )
    if "location_id" in fields:
        await _ensure_active_location(db, tenant_id, fields["location_id"])
    for key, value in fields.items():
        setattr(line, key, value)
    line.product_variant_id = product_variant_id
    line.variant_unit_id = variant_unit_id
    line.conversion_to_base = _effective_conversion(
        purchase_variant_unit.variant_unit, line.measured_quantity
    )
    line.quantity_base = _resolve_quantity_base(
        purchase_variant_unit.variant_unit, line.quantity, line.measured_quantity
    )
    line.line_amount = line.quantity * line.unit_cost
    line.unit_cost_base = line.unit_cost / line.conversion_to_base
    line.total_line_cost = line.line_amount
    if purchase_variant_unit.variant.track_batches and not line.lot_number:
        line.lot_number = await generate_lot_number(db, tenant_id, datetime.now(UTC))
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_invoice_lines.update",
        entity_type="purchase_invoice_line",
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
    purchase_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    _ensure_draft(invoice)
    line = await _get_existing_line(db, tenant_id, purchase_invoice_id, line_id)
    before = _line_loggable(line)
    await db.delete(line)
    await db.flush()
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_invoice_lines.delete",
        entity_type="purchase_invoice_line",
        entity_id=line.id,
        before_json=before,
    )
    await db.commit()


async def get_line_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> PurchaseInvoiceLine | None:
    return await db.scalar(
        select(PurchaseInvoiceLine).where(
            PurchaseInvoiceLine.tenant_id == tenant_id,
            PurchaseInvoiceLine.purchase_invoice_id == purchase_invoice_id,
            PurchaseInvoiceLine.id == line_id,
        )
    )


async def list_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    pagination: PaginationParams,
    filters: PurchaseInvoiceLineFilters,
    sort: tuple[SortSpec, ...],
) -> Page[PurchaseInvoiceLine]:
    await _get_existing_invoice(db, tenant_id, purchase_invoice_id)
    stmt = _apply_line_filters(
        select(PurchaseInvoiceLine).where(
            PurchaseInvoiceLine.tenant_id == tenant_id,
            PurchaseInvoiceLine.purchase_invoice_id == purchase_invoice_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, PURCHASE_INVOICE_LINE_SORT_COLUMNS)
    count_stmt = _apply_line_filters(
        select(func.count(PurchaseInvoiceLine.id)).where(
            PurchaseInvoiceLine.tenant_id == tenant_id,
            PurchaseInvoiceLine.purchase_invoice_id == purchase_invoice_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_landed_cost(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    data: PurchaseLandedCostCreate,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseLandedCost:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    _ensure_draft(invoice)
    _ensure_supported_allocation(data.allocation_method)
    landed_cost = PurchaseLandedCost(
        tenant_id=tenant_id,
        purchase_invoice_id=purchase_invoice_id,
        **data.model_dump(),
    )
    db.add(landed_cost)
    await db.flush()
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_landed_costs.create",
        entity_type="purchase_landed_cost",
        entity_id=landed_cost.id,
        after_json=_landed_cost_loggable(landed_cost),
    )
    await db.commit()
    await db.refresh(landed_cost)
    return landed_cost


async def update_landed_cost(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    cost_id: uuid.UUID,
    data: PurchaseLandedCostUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> PurchaseLandedCost:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    _ensure_draft(invoice)
    landed_cost = await _get_existing_landed_cost(db, tenant_id, purchase_invoice_id, cost_id)
    before = _landed_cost_loggable(landed_cost)
    fields = data.model_dump(exclude_unset=True)
    allocation_method = fields.get("allocation_method")
    if allocation_method is not None:
        _ensure_supported_allocation(allocation_method)
    for key, value in fields.items():
        setattr(landed_cost, key, value)
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_landed_costs.update",
        entity_type="purchase_landed_cost",
        entity_id=landed_cost.id,
        before_json=before,
        after_json=_landed_cost_loggable(landed_cost),
    )
    await db.commit()
    await db.refresh(landed_cost)
    return landed_cost


async def delete_landed_cost(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    cost_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    invoice = await _get_existing_invoice(db, tenant_id, purchase_invoice_id, for_update=True)
    _ensure_draft(invoice)
    landed_cost = await _get_existing_landed_cost(db, tenant_id, purchase_invoice_id, cost_id)
    before = _landed_cost_loggable(landed_cost)
    await db.delete(landed_cost)
    await db.flush()
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="purchase_landed_costs.delete",
        entity_type="purchase_landed_cost",
        entity_id=landed_cost.id,
        before_json=before,
    )
    await db.commit()


async def get_landed_cost_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    cost_id: uuid.UUID,
) -> PurchaseLandedCost | None:
    return await db.scalar(
        select(PurchaseLandedCost).where(
            PurchaseLandedCost.tenant_id == tenant_id,
            PurchaseLandedCost.purchase_invoice_id == purchase_invoice_id,
            PurchaseLandedCost.id == cost_id,
        )
    )


async def list_landed_costs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    pagination: PaginationParams,
    filters: PurchaseLandedCostFilters,
    sort: tuple[SortSpec, ...],
) -> Page[PurchaseLandedCost]:
    await _get_existing_invoice(db, tenant_id, purchase_invoice_id)
    stmt = _apply_landed_cost_filters(
        select(PurchaseLandedCost).where(
            PurchaseLandedCost.tenant_id == tenant_id,
            PurchaseLandedCost.purchase_invoice_id == purchase_invoice_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, PURCHASE_LANDED_COST_SORT_COLUMNS)
    count_stmt = _apply_landed_cost_filters(
        select(func.count(PurchaseLandedCost.id)).where(
            PurchaseLandedCost.tenant_id == tenant_id,
            PurchaseLandedCost.purchase_invoice_id == purchase_invoice_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def _get_existing_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> PurchaseInvoice:
    invoice = await get_by_id(db, tenant_id, purchase_invoice_id, for_update=for_update)
    if invoice is None:
        raise PurchaseInvoiceNotFound()
    return invoice


async def _get_existing_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> PurchaseInvoiceLine:
    line = await get_line_by_id(db, tenant_id, purchase_invoice_id, line_id)
    if line is None:
        raise PurchaseInvoiceLineNotFound()
    return line


async def _get_existing_landed_cost(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    cost_id: uuid.UUID,
) -> PurchaseLandedCost:
    landed_cost = await get_landed_cost_by_id(db, tenant_id, purchase_invoice_id, cost_id)
    if landed_cost is None:
        raise PurchaseLandedCostNotFound()
    return landed_cost


def _ensure_draft(invoice: PurchaseInvoice) -> None:
    if invoice.status != DocumentStatus.DRAFT:
        raise PurchaseInvoiceNotDraft()


def _ensure_supported_allocation(method: LandedCostAllocationMethod) -> None:
    if method == LandedCostAllocationMethod.MANUAL:
        raise InvalidPurchaseLandedCostAllocation()


async def _ensure_document_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_no: str,
    *,
    purchase_invoice_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(PurchaseInvoice).where(
            PurchaseInvoice.tenant_id == tenant_id,
            PurchaseInvoice.document_no == document_no,
        )
    )
    if existing is not None and existing.id != purchase_invoice_id:
        raise PurchaseInvoiceDocumentNoConflict()


async def _ensure_line_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    line_no: int,
    *,
    line_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(PurchaseInvoiceLine).where(
            PurchaseInvoiceLine.tenant_id == tenant_id,
            PurchaseInvoiceLine.purchase_invoice_id == purchase_invoice_id,
            PurchaseInvoiceLine.line_no == line_no,
        )
    )
    if existing is not None and existing.id != line_id:
        raise PurchaseInvoiceLineNoConflict()


async def _ensure_active_supplier(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
) -> Supplier:
    supplier = await db.scalar(
        select(Supplier).where(
            Supplier.tenant_id == tenant_id,
            Supplier.id == supplier_id,
            Supplier.status == PartyStatus.ACTIVE,
        )
    )
    if supplier is None:
        raise InvalidPurchaseInvoiceSupplier()
    return supplier


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
        raise InvalidPurchaseInvoiceLocation()
    return location


async def _ensure_active_purchase_variant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
) -> ProductVariant:
    variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == product_variant_id,
            ProductVariant.is_active.is_(True),
        )
    )
    if variant is None:
        raise InvalidPurchaseInvoiceLineProduct()
    return variant


async def _ensure_active_purchase_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
) -> PurchaseVariantUnit:
    variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == product_variant_id,
            ProductVariant.is_active.is_(True),
        )
    )
    if variant is None:
        raise InvalidPurchaseInvoiceLineProduct()
    variant_unit = await db.scalar(
        select(VariantUnit).where(
            VariantUnit.tenant_id == tenant_id,
            VariantUnit.id == variant_unit_id,
            VariantUnit.product_variant_id == product_variant_id,
            VariantUnit.is_active.is_(True),
            VariantUnit.is_purchase_unit.is_(True),
        )
    )
    if variant_unit is None:
        raise InvalidPurchaseInvoiceLineUnit()
    return PurchaseVariantUnit(variant=variant, variant_unit=variant_unit)


async def _recalculate_invoice_totals(db: AsyncSession, invoice: PurchaseInvoice) -> None:
    lines = await _invoice_lines(db, invoice.tenant_id, invoice.id)
    landed_costs = await _invoice_landed_costs(db, invoice.tenant_id, invoice.id)
    subtotal = sum((line.line_amount for line in lines), ZERO)
    landed_total = sum((cost.amount for cost in landed_costs), ZERO)
    for line in lines:
        line.allocated_landed_cost = ZERO
        line.total_line_cost = line.line_amount
        line.unit_cost_base = line.unit_cost / line.conversion_to_base

    for cost in landed_costs:
        if not lines:
            continue
        if cost.allocation_method == LandedCostAllocationMethod.BY_BASE_QUANTITY:
            basis = [line.quantity_base for line in lines]
        else:
            basis = [line.line_amount for line in lines]
        _allocate_cost(lines, basis, cost.amount)

    for line in lines:
        line.total_line_cost = line.line_amount + line.allocated_landed_cost
        line.unit_cost_base = line.total_line_cost / line.quantity_base

    invoice.subtotal_amount = subtotal
    invoice.landed_cost_amount = landed_total
    invoice.total_amount = subtotal + landed_total
    invoice.paid_amount = ZERO
    invoice.balance_amount = invoice.total_amount - invoice.paid_amount
    await db.flush()


def _allocate_cost(
    lines: list[PurchaseInvoiceLine],
    basis: list[Decimal],
    amount: Decimal,
) -> None:
    total_basis = sum(basis, ZERO)
    if total_basis <= ZERO:
        return
    allocated = ZERO
    for index, line in enumerate(lines):
        if index == len(lines) - 1:
            share = amount - allocated
        else:
            share = amount * basis[index] / total_basis
            allocated += share
        line.allocated_landed_cost += share


async def _invoice_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
) -> list[PurchaseInvoiceLine]:
    result = await db.execute(
        select(PurchaseInvoiceLine)
        .where(
            PurchaseInvoiceLine.tenant_id == tenant_id,
            PurchaseInvoiceLine.purchase_invoice_id == purchase_invoice_id,
        )
        .order_by(PurchaseInvoiceLine.line_no.asc(), PurchaseInvoiceLine.id.asc())
    )
    return list(result.scalars().all())


async def _invoice_landed_costs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
) -> list[PurchaseLandedCost]:
    result = await db.execute(
        select(PurchaseLandedCost)
        .where(
            PurchaseLandedCost.tenant_id == tenant_id,
            PurchaseLandedCost.purchase_invoice_id == purchase_invoice_id,
        )
        .order_by(PurchaseLandedCost.created_at.asc(), PurchaseLandedCost.id.asc())
    )
    return list(result.scalars().all())


def _ensure_line_postable(line: PurchaseInvoiceLine, variant: ProductVariant) -> None:
    if not variant.track_inventory:
        raise PurchaseInvoiceLineProductNotInventoryTracked()
    if variant.track_batches and not line.lot_number:
        raise PurchaseInvoiceLineMissingLotNumber()
    if variant.track_expiry and line.expiry_date is None:
        raise PurchaseInvoiceLineMissingExpiryDate()


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


def _apply_invoice_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: PurchaseInvoiceFilters,
) -> StmtT:
    search = search_clause(
        [PurchaseInvoice.document_no, PurchaseInvoice.supplier_invoice_no, PurchaseInvoice.notes],
        filters.search,
    )
    if search is not None:
        stmt = stmt.where(search)
    if filters.supplier_id is not None:
        stmt = stmt.where(PurchaseInvoice.supplier_id == filters.supplier_id)
    if filters.location_id is not None:
        stmt = (
            stmt.join(
                PurchaseInvoiceLine,
                PurchaseInvoiceLine.purchase_invoice_id == PurchaseInvoice.id,
            )
            .where(PurchaseInvoiceLine.location_id == filters.location_id)
            .distinct()
        )
    if filters.status is not None:
        stmt = stmt.where(PurchaseInvoice.status == filters.status)
    stmt = where_gte_if_not_none(stmt, PurchaseInvoice.invoice_date, filters.invoice_date_gte)
    stmt = where_lte_if_not_none(stmt, PurchaseInvoice.invoice_date, filters.invoice_date_lte)
    return stmt


def _apply_line_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: PurchaseInvoiceLineFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(PurchaseInvoiceLine.product_variant_id == filters.product_variant_id)
    if filters.variant_unit_id is not None:
        stmt = stmt.where(PurchaseInvoiceLine.variant_unit_id == filters.variant_unit_id)
    return stmt


def _apply_landed_cost_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: PurchaseLandedCostFilters,
) -> StmtT:
    if filters.cost_type is not None:
        stmt = stmt.where(PurchaseLandedCost.cost_type == filters.cost_type)
    if filters.allocation_method is not None:
        stmt = stmt.where(PurchaseLandedCost.allocation_method == filters.allocation_method)
    return stmt


def _invoice_loggable(invoice: PurchaseInvoice) -> dict[str, Any]:
    return {
        "document_no": invoice.document_no,
        "supplier_id": str(invoice.supplier_id),
        "invoice_date": invoice.invoice_date.isoformat(),
        "supplier_invoice_no": invoice.supplier_invoice_no,
        "status": invoice.status.value,
        "subtotal_amount": str(invoice.subtotal_amount),
        "landed_cost_amount": str(invoice.landed_cost_amount),
        "total_amount": str(invoice.total_amount),
        "paid_amount": str(invoice.paid_amount),
        "balance_amount": str(invoice.balance_amount),
        "notes": invoice.notes,
        "posted_at": invoice.posted_at.isoformat() if invoice.posted_at else None,
        "posted_by": str(invoice.posted_by) if invoice.posted_by else None,
        "cancelled_at": invoice.cancelled_at.isoformat() if invoice.cancelled_at else None,
        "cancelled_by": str(invoice.cancelled_by) if invoice.cancelled_by else None,
        "created_by": str(invoice.created_by) if invoice.created_by else None,
    }


def _line_loggable(line: PurchaseInvoiceLine) -> dict[str, Any]:
    return {
        "purchase_invoice_id": str(line.purchase_invoice_id),
        "line_no": line.line_no,
        "product_variant_id": str(line.product_variant_id),
        "variant_unit_id": str(line.variant_unit_id),
        "location_id": str(line.location_id),
        "quantity": str(line.quantity),
        "conversion_to_base": str(line.conversion_to_base),
        "quantity_base": str(line.quantity_base),
        "measured_quantity": str(line.measured_quantity)
        if line.measured_quantity is not None
        else None,
        "unit_cost": str(line.unit_cost),
        "line_amount": str(line.line_amount),
        "allocated_landed_cost": str(line.allocated_landed_cost),
        "total_line_cost": str(line.total_line_cost),
        "unit_cost_base": str(line.unit_cost_base),
        "expiry_date": line.expiry_date.isoformat() if line.expiry_date else None,
        "manufactured_date": line.manufactured_date.isoformat() if line.manufactured_date else None,
        "lot_number": line.lot_number,
        "created_stock_batch_id": str(line.created_stock_batch_id)
        if line.created_stock_batch_id
        else None,
    }


def _landed_cost_loggable(landed_cost: PurchaseLandedCost) -> dict[str, Any]:
    return {
        "purchase_invoice_id": str(landed_cost.purchase_invoice_id),
        "cost_type": landed_cost.cost_type.value,
        "description": landed_cost.description,
        "amount": str(landed_cost.amount),
        "allocation_method": landed_cost.allocation_method.value,
        "created_at": landed_cost.created_at.isoformat() if landed_cost.created_at else None,
    }
