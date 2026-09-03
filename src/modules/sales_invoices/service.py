import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src.decimal_utils import quantity_base_for_unit, quantize_base_quantity
from src.foundation_enums import (
    DocumentStatus,
    PartyStatus,
    SourceType,
    StockBatchStatus,
    StockMovementType,
)
from src.modules.audit_logs.service import record_audit_log
from src.modules.catalog.models import ProductVariant, VariantLocationSetting, VariantUnit
from src.modules.customers.models import Customer
from src.modules.document_numbers.service import generate_document_no
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.price_levels.models import PriceLevel
from src.modules.price_rules.service import resolve_unit_price
from src.modules.sales_invoices.exceptions import (
    InvalidSalesInvoiceCustomer,
    InvalidSalesInvoiceDiscount,
    InvalidSalesInvoiceLineDiscount,
    InvalidSalesInvoiceLineLocations,
    InvalidSalesInvoiceLineProduct,
    InvalidSalesInvoiceLineSourceLocation,
    InvalidSalesInvoiceLineUnit,
    InvalidSalesInvoiceLocation,
    InvalidSalesInvoicePriceLevel,
    MissingSalesInvoiceLinePrice,
    MissingSalesInvoicePriceLevel,
    SalesInvoiceDocumentNoConflict,
    SalesInvoiceHasNoLines,
    SalesInvoiceInsufficientStock,
    SalesInvoiceLineMeasuredQuantityRequired,
    SalesInvoiceLineNoConflict,
    SalesInvoiceLineNotFound,
    SalesInvoiceNotCancellable,
    SalesInvoiceNotDraft,
    SalesInvoiceNotFound,
    SalesInvoiceNotPostable,
)
from src.modules.sales_invoices.models import (
    SalesInvoice,
    SalesInvoiceLine,
    SalesInvoiceLineCost,
    SalesInvoiceLineLocation,
)
from src.modules.sales_invoices.schemas import (
    SalesInvoiceCreate,
    SalesInvoiceFilters,
    SalesInvoiceLineCostFilters,
    SalesInvoiceLineCreate,
    SalesInvoiceLineFilters,
    SalesInvoiceLineUpdate,
    SalesInvoiceUpdate,
)
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import (
    SortSpec,
    apply_sort,
    search_clause,
    where_gte_if_not_none,
    where_lte_if_not_none,
)

SALES_INVOICE_SORT_COLUMNS = {
    "document_no": SalesInvoice.document_no,
    "invoice_date": SalesInvoice.invoice_date,
    "status": SalesInvoice.status,
    "total_amount": SalesInvoice.total_amount,
    "created_at": SalesInvoice.created_at,
    "id": SalesInvoice.id,
}
SALES_INVOICE_LINE_SORT_COLUMNS = {
    "line_no": SalesInvoiceLine.line_no,
    "product_variant_id": SalesInvoiceLine.product_variant_id,
    "id": SalesInvoiceLine.id,
}
SALES_INVOICE_LINE_COST_SORT_COLUMNS = {
    "stock_batch_id": SalesInvoiceLineCost.stock_batch_id,
    "quantity_base": SalesInvoiceLineCost.quantity_base,
    "total_cost": SalesInvoiceLineCost.total_cost,
    "id": SalesInvoiceLineCost.id,
}
ZERO = Decimal("0")
MONEY_QUANT = Decimal("0.0001")


@dataclass(frozen=True)
class FifoAllocation:
    line: SalesInvoiceLine
    variant: ProductVariant
    location_id: uuid.UUID
    balance: StockBalance
    batch: StockBatch
    quantity_base: Decimal


@dataclass(frozen=True)
class SalesVariantUnit:
    variant: ProductVariant
    variant_unit: VariantUnit


def _effective_conversion(
    variant_unit: VariantUnit,
    measured_quantity: Decimal | None,
) -> Decimal:
    """Base units contained in one sales unit for this line.

    ``measured_quantity`` records the actually weighed content of one sales
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
        raise SalesInvoiceLineMeasuredQuantityRequired()
    return quantity_base_for_unit(
        quantity,
        measured_quantity if measured_quantity is not None else variant_unit.conversion_to_base,
        allow_decimal_quantity=variant_unit.allow_decimal_quantity,
        rounding_precision=variant_unit.rounding_precision,
    )


def _quantity_base_from_line(line: SalesInvoiceLine) -> Decimal:
    """Re-derive quantity_base for an already-valid persisted line.

    Used by `_reprice_invoice_lines`, which runs on every header update and
    on posting — it must NOT re-run the requires_measured_quantity gate,
    since the line already passed it at create/update time and re-validating
    here would incorrectly fail unrelated edits (e.g. a discount change).

    ``conversion_to_base`` always stores the effective conversion (see
    ``_effective_conversion``), so the plain multiplication is exact.
    """
    return quantize_base_quantity(line.quantity * line.conversion_to_base)


async def _resolve_split_plan(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice: SalesInvoice,
    variant: ProductVariant,
    raw_splits: list[tuple[uuid.UUID, Decimal]],
    line_quantity: Decimal,
) -> list[tuple[uuid.UUID, Decimal]]:
    """Validate and normalize the location splits of an inventory-tracked line.

    An empty plan defaults to one implicit split covering the full quantity
    from the invoice's (POS) location. Otherwise splits must reference unique,
    active locations with the variant available, and their quantities
    must sum exactly to the line quantity.
    """
    if not raw_splits:
        plan = [(invoice.location_id, line_quantity)]
    else:
        seen: set[uuid.UUID] = set()
        total = ZERO
        plan = []
        for location_id, quantity in raw_splits:
            if location_id in seen:
                raise InvalidSalesInvoiceLineLocations()
            seen.add(location_id)
            plan.append((location_id, quantity))
            total += quantity
        if total != line_quantity:
            raise InvalidSalesInvoiceLineLocations()
    for location_id in dict.fromkeys(location for location, _qty in plan):
        await _ensure_active_source_location(db, tenant_id, location_id)
        await _ensure_variant_available_at_source(db, tenant_id, variant.id, location_id)
    return plan


async def _materialize_splits(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    line: SalesInvoiceLine,
    plan: list[tuple[uuid.UUID, Decimal]],
) -> None:
    """Replace the line's persisted location splits with the given plan.

    Loads and deletes the previous rows explicitly, then assigns the new
    relationship collection so it stays usable without further IO.
    """
    existing = await db.scalars(
        select(SalesInvoiceLineLocation).where(
            SalesInvoiceLineLocation.sales_invoice_line_id == line.id
        )
    )
    for row in existing:
        await db.delete(row)
    await db.flush()
    await db.refresh(line, attribute_names=["locations"])
    line.locations = [
        SalesInvoiceLineLocation(
            tenant_id=tenant_id,
            sales_invoice_line_id=line.id,
            location_id=location_id,
            quantity=quantity,
            quantity_base=quantize_base_quantity(quantity * line.conversion_to_base),
        )
        for location_id, quantity in plan
    ]


async def _apply_line_locations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice: SalesInvoice,
    line: SalesInvoiceLine,
    variant: ProductVariant,
    raw_splits: list[tuple[uuid.UUID, Decimal]],
) -> None:
    """Replace an inventory-tracked line's location splits and mirror the
    single-split case onto ``source_location_id`` for reporting continuity."""
    if not variant.track_inventory:
        return
    plan = await _resolve_split_plan(db, tenant_id, invoice, variant, raw_splits, line.quantity)
    await _materialize_splits(db, tenant_id, line, plan)
    if len(plan) == 1:
        line.source_location_id = plan[0][0]
    else:
        line.source_location_id = None


async def _line_split_inputs(
    db: AsyncSession,
    line: SalesInvoiceLine,
) -> list[tuple[uuid.UUID, Decimal]]:
    result = await db.execute(
        select(
            SalesInvoiceLineLocation.location_id,
            SalesInvoiceLineLocation.quantity,
        ).where(SalesInvoiceLineLocation.sales_invoice_line_id == line.id)
    )
    return list(result.all())


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
) -> SalesInvoice | None:
    return await db.scalar(
        select(SalesInvoice).where(
            SalesInvoice.tenant_id == tenant_id,
            SalesInvoice.id == sales_invoice_id,
        )
    )


async def get_invoice_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
) -> SalesInvoice | None:
    return await db.scalar(
        select(SalesInvoice)
        .options(
            joinedload(SalesInvoice.posted_by_user),
            selectinload(SalesInvoice.lines).selectinload(SalesInvoiceLine.locations),
        )
        .where(
            SalesInvoice.tenant_id == tenant_id,
            SalesInvoice.id == sales_invoice_id,
        )
    )


async def list_sales_invoices(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: SalesInvoiceFilters,
    sort: tuple[SortSpec, ...],
) -> Page[SalesInvoice]:
    stmt = _apply_invoice_filters(
        select(SalesInvoice)
        .options(joinedload(SalesInvoice.posted_by_user))
        .where(SalesInvoice.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, SALES_INVOICE_SORT_COLUMNS)
    count_stmt = _apply_invoice_filters(
        select(func.count(SalesInvoice.id)).where(SalesInvoice.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: SalesInvoiceCreate,
    *,
    actor_user_id: uuid.UUID,
) -> SalesInvoice:
    try:
        invoice = await _create_invoice_draft(db, tenant_id, data, actor_user_id=actor_user_id)
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
    data: SalesInvoiceCreate,
    *,
    actor_user_id: uuid.UUID,
    commit: bool = True,
) -> SalesInvoice:
    customer = await _ensure_optional_active_customer(db, tenant_id, data.customer_id)
    await _ensure_sellable_location(db, tenant_id, data.location_id)
    price_level = await _resolve_price_level(db, tenant_id, data.price_level_id, customer)
    invoice = SalesInvoice(
        tenant_id=tenant_id,
        created_by=actor_user_id,
        status=DocumentStatus.DRAFT,
        price_level_id=price_level.id,
        paid_amount=_money(ZERO),
        balance_amount=_money(ZERO),
        total_cost=_money(ZERO),
        gross_profit=_money(ZERO),
        document_no=await generate_document_no(db, tenant_id, "sales_invoice", data.invoice_date),
        **data.model_dump(exclude={"price_level_id", "lines"}),
    )
    db.add(invoice)
    await db.flush()

    lines_with_variants = [
        await _build_line(db, tenant_id, invoice, line_data) for line_data in data.lines
    ]
    db.add_all(line for line, _variant in lines_with_variants)
    await db.flush()
    for (line, variant), line_data in zip(lines_with_variants, data.lines, strict=True):
        await _apply_line_locations(
            db,
            tenant_id,
            invoice,
            line,
            variant,
            [(split.location_id, split.quantity) for split in line_data.locations],
        )
    await db.flush()

    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="sales_invoices.create",
        entity_type="sales_invoice",
        entity_id=invoice.id,
        after_json=_invoice_loggable(invoice),
    )
    if commit:
        await db.commit()
    return invoice


async def update_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    data: SalesInvoiceUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> SalesInvoice:
    invoice = await _get_existing_invoice(db, tenant_id, sales_invoice_id)
    _ensure_draft(invoice)
    before = _invoice_loggable(invoice)
    fields = data.model_dump(exclude_unset=True)
    customer = await _ensure_optional_active_customer(db, tenant_id, invoice.customer_id)
    if "customer_id" in fields:
        customer = await _ensure_optional_active_customer(db, tenant_id, fields["customer_id"])
    requested_price_level_id = fields.get("price_level_id", invoice.price_level_id)
    if "location_id" in fields:
        await _ensure_sellable_location(db, tenant_id, fields["location_id"])
    if "customer_id" in fields or "price_level_id" in fields:
        price_level = await _resolve_price_level(db, tenant_id, requested_price_level_id, customer)
        fields["price_level_id"] = price_level.id
    for key, value in fields.items():
        setattr(invoice, key, value)
    await _reprice_invoice_lines(db, invoice)
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="sales_invoices.update",
        entity_type="sales_invoice",
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
    sales_invoice_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    invoice = await _get_existing_invoice(db, tenant_id, sales_invoice_id)
    if invoice.status != DocumentStatus.DRAFT:
        raise SalesInvoiceNotCancellable()
    before = _invoice_loggable(invoice)
    invoice.status = DocumentStatus.CANCELLED
    invoice.cancelled_at = datetime.now(UTC)
    invoice.cancelled_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="sales_invoices.cancel",
        entity_type="sales_invoice",
        entity_id=invoice.id,
        before_json=before,
        after_json=_invoice_loggable(invoice),
    )
    await db.commit()


async def post_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> SalesInvoice:
    try:
        invoice = await _post_invoice_atomically(
            db,
            tenant_id,
            sales_invoice_id,
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
    sales_invoice_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    commit: bool = True,
) -> SalesInvoice:
    invoice = await _get_existing_invoice(db, tenant_id, sales_invoice_id)
    if invoice.status != DocumentStatus.DRAFT:
        raise SalesInvoiceNotPostable()
    lines = await _invoice_lines(db, tenant_id, invoice.id)
    if not lines:
        raise SalesInvoiceHasNoLines()
    await _reprice_invoice_lines(db, invoice)
    await _recalculate_invoice_totals(db, invoice)
    before = _invoice_loggable(invoice)
    variants_by_id = await _ensure_active_sales_variants(
        db,
        tenant_id,
        {line.product_variant_id for line in lines},
    )
    lines_with_variants = [(line, variants_by_id[line.product_variant_id]) for line in lines]
    allocations = await _fifo_allocations(db, tenant_id, invoice, lines_with_variants)
    posted_at = datetime.now(UTC)
    posted_inventory: list[dict[str, str]] = []
    line_costs: dict[uuid.UUID, Decimal] = {line.id: ZERO for line in lines}

    for allocation in allocations:
        allocation.balance.quantity_base -= allocation.quantity_base
        allocation.balance.updated_at = posted_at
        movement_total_cost = _money(allocation.quantity_base * allocation.batch.unit_cost_base)
        movement = StockMovement(
            tenant_id=tenant_id,
            movement_type=StockMovementType.SALE_ISSUE,
            source_type=SourceType.SALES_INVOICE,
            source_id=invoice.id,
            source_line_id=allocation.line.id,
            product_variant_id=allocation.line.product_variant_id,
            stock_batch_id=allocation.batch.id,
            location_id=allocation.location_id,
            quantity_base=-allocation.quantity_base,
            unit_cost_base=allocation.batch.unit_cost_base,
            total_cost=-movement_total_cost,
            notes=f"Sales invoice {invoice.document_no}",
            posted_at=posted_at,
            posted_by=actor_user_id,
            created_at=posted_at,
        )
        db.add(movement)
        await db.flush()
        line_cost = SalesInvoiceLineCost(
            tenant_id=tenant_id,
            sales_invoice_line_id=allocation.line.id,
            stock_batch_id=allocation.batch.id,
            stock_movement_id=movement.id,
            quantity_base=allocation.quantity_base,
            unit_cost_base=allocation.batch.unit_cost_base,
            total_cost=movement_total_cost,
        )
        db.add(line_cost)
        await db.flush()
        line_costs[allocation.line.id] = line_costs[allocation.line.id] + movement_total_cost
        if await _batch_total_quantity(db, tenant_id, allocation.batch.id) == ZERO:
            allocation.batch.status = StockBatchStatus.DEPLETED
        posted_inventory.append(
            {
                "line_id": str(allocation.line.id),
                "sales_invoice_line_cost_id": str(line_cost.id),
                "stock_batch_id": str(allocation.batch.id),
                "stock_movement_id": str(movement.id),
                "stock_balance_id": str(allocation.balance.id),
            }
        )

    total_cost = ZERO
    for line, variant in lines_with_variants:
        cost = _money(line_costs[line.id]) if variant.track_inventory else _money(ZERO)
        line.total_cost = cost
        line.gross_profit = _money(line.line_total - cost)
        total_cost += cost

    invoice.status = DocumentStatus.POSTED
    invoice.posted_at = posted_at
    invoice.posted_by = actor_user_id
    invoice.total_cost = _money(total_cost)
    invoice.gross_profit = _money(invoice.total_amount - invoice.total_cost)
    await db.flush()
    from src.modules.customer_payments.service import ensure_invoice_ledger_entry

    ledger_entry = await ensure_invoice_ledger_entry(
        db,
        invoice,
        actor_user_id=actor_user_id,
        posted_at=posted_at,
    )
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="sales_invoices.post",
        entity_type="sales_invoice",
        entity_id=invoice.id,
        before_json=before,
        after_json=_invoice_loggable(invoice)
        | {
            "posted_inventory": posted_inventory,
            "customer_ledger_entry_id": str(ledger_entry.id) if ledger_entry else None,
        },
    )
    if commit:
        await db.commit()
    return invoice


async def _build_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice: SalesInvoice,
    data: SalesInvoiceLineCreate,
) -> tuple[SalesInvoiceLine, ProductVariant]:
    sales_variant_unit = await _ensure_active_sales_variant_unit(
        db,
        tenant_id,
        data.product_variant_id,
        data.variant_unit_id,
    )
    if not sales_variant_unit.variant.track_inventory:
        source_location_id = await _resolve_line_source_location_id(
            db,
            tenant_id,
            sales_variant_unit.variant,
            data.source_location_id,
            default_location_id=invoice.location_id,
        )
    else:
        # Tracked lines derive ``source_location_id`` from their location
        # splits (see ``_apply_line_locations``).
        source_location_id = None
    unit_price, price_rule_id = await _line_price(
        db,
        invoice,
        product_variant_id=data.product_variant_id,
        variant_unit_id=data.variant_unit_id,
        quantity=data.quantity,
        explicit_unit_price=data.unit_price,
    )
    line_total = _line_total(data.quantity, unit_price, data.discount_amount)
    quantity_base = _resolve_quantity_base(
        sales_variant_unit.variant_unit, data.quantity, data.measured_quantity
    )
    line = SalesInvoiceLine(
        tenant_id=tenant_id,
        sales_invoice_id=invoice.id,
        conversion_to_base=_effective_conversion(
            sales_variant_unit.variant_unit, data.measured_quantity
        ),
        quantity_base=quantity_base,
        unit_price=unit_price,
        line_total=line_total,
        total_cost=_money(ZERO),
        gross_profit=_money(ZERO),
        price_rule_id=price_rule_id,
        source_location_id=source_location_id,
        **data.model_dump(exclude={"unit_price", "source_location_id", "locations"}),
    )
    return line, sales_variant_unit.variant


async def create_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    data: SalesInvoiceLineCreate,
    *,
    actor_user_id: uuid.UUID,
) -> SalesInvoiceLine:
    invoice = await _get_existing_invoice(db, tenant_id, sales_invoice_id)
    _ensure_draft(invoice)
    await _ensure_line_no_available(db, tenant_id, sales_invoice_id, data.line_no)
    line, variant = await _build_line(db, tenant_id, invoice, data)
    db.add(line)
    await db.flush()
    await _apply_line_locations(
        db,
        tenant_id,
        invoice,
        line,
        variant,
        [(split.location_id, split.quantity) for split in data.locations],
    )
    await db.flush()
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="sales_invoice_lines.create",
        entity_type="sales_invoice_line",
        entity_id=line.id,
        after_json=_line_loggable(line),
    )
    await db.commit()
    reloaded = await get_line_by_id(db, tenant_id, sales_invoice_id, line.id)
    assert reloaded is not None
    return reloaded
    return line


async def update_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    data: SalesInvoiceLineUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> SalesInvoiceLine:
    invoice = await _get_existing_invoice(db, tenant_id, sales_invoice_id)
    _ensure_draft(invoice)
    line = await _get_existing_line(db, tenant_id, sales_invoice_id, line_id)
    before = _line_loggable(line)
    fields = data.model_dump(exclude_unset=True)
    new_line_no = fields.get("line_no")
    if new_line_no is not None and new_line_no != line.line_no:
        await _ensure_line_no_available(
            db,
            tenant_id,
            sales_invoice_id,
            new_line_no,
            line_id=line.id,
        )
    product_variant_id = fields.get("product_variant_id", line.product_variant_id)
    variant_unit_id = fields.get("variant_unit_id", line.variant_unit_id)
    source_location_id = fields.get("source_location_id", line.source_location_id)
    sales_variant_unit = await _ensure_active_sales_variant_unit(
        db,
        tenant_id,
        product_variant_id,
        variant_unit_id,
    )
    if not sales_variant_unit.variant.track_inventory:
        source_location_id = await _resolve_line_source_location_id(
            db,
            tenant_id,
            sales_variant_unit.variant,
            source_location_id,
            default_location_id=invoice.location_id,
        )
    for key, value in fields.items():
        setattr(line, key, value)
    line.product_variant_id = product_variant_id
    line.variant_unit_id = variant_unit_id
    line.source_location_id = source_location_id
    line.conversion_to_base = _effective_conversion(
        sales_variant_unit.variant_unit, line.measured_quantity
    )
    line.quantity_base = _resolve_quantity_base(
        sales_variant_unit.variant_unit, line.quantity, line.measured_quantity
    )
    unit_price, price_rule_id = await _line_price(
        db,
        invoice,
        product_variant_id=line.product_variant_id,
        variant_unit_id=line.variant_unit_id,
        quantity=line.quantity,
        explicit_unit_price=fields.get("unit_price", line.unit_price),
    )
    line.unit_price = unit_price
    line.price_rule_id = price_rule_id
    line.line_total = _line_total(line.quantity, line.unit_price, line.discount_amount)
    line.total_cost = _money(ZERO)
    line.gross_profit = line.line_total
    if sales_variant_unit.variant.track_inventory:
        if "locations" in fields:
            raw_splits = [
                (split.location_id, split.quantity) for split in (fields["locations"] or [])
            ]
        else:
            raw_splits = await _line_split_inputs(db, line)
            if sum(quantity for _loc, quantity in raw_splits) != line.quantity:
                # Quantity (or unit) changed without explicit splits: fall
                # back to the implicit default split from the POS location.
                raw_splits = []
        await _apply_line_locations(
            db, tenant_id, invoice, line, sales_variant_unit.variant, raw_splits
        )
    else:
        line.source_location_id = source_location_id
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="sales_invoice_lines.update",
        entity_type="sales_invoice_line",
        entity_id=line.id,
        before_json=before,
        after_json=_line_loggable(line),
    )
    await db.commit()
    reloaded = await get_line_by_id(db, tenant_id, sales_invoice_id, line.id)
    assert reloaded is not None
    return reloaded


async def delete_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    invoice = await _get_existing_invoice(db, tenant_id, sales_invoice_id)
    _ensure_draft(invoice)
    line = await _get_existing_line(db, tenant_id, sales_invoice_id, line_id)
    before = _line_loggable(line)
    await db.delete(line)
    await db.flush()
    await _recalculate_invoice_totals(db, invoice)
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="sales_invoice_lines.delete",
        entity_type="sales_invoice_line",
        entity_id=line.id,
        before_json=before,
    )
    await db.commit()


async def get_line_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> SalesInvoiceLine | None:
    return await db.scalar(
        select(SalesInvoiceLine)
        .options(selectinload(SalesInvoiceLine.locations))
        .where(
            SalesInvoiceLine.tenant_id == tenant_id,
            SalesInvoiceLine.sales_invoice_id == sales_invoice_id,
            SalesInvoiceLine.id == line_id,
        )
    )


async def list_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    pagination: PaginationParams,
    filters: SalesInvoiceLineFilters,
    sort: tuple[SortSpec, ...],
) -> Page[SalesInvoiceLine]:
    await _get_existing_invoice(db, tenant_id, sales_invoice_id)
    stmt = _apply_line_filters(
        select(SalesInvoiceLine)
        .options(selectinload(SalesInvoiceLine.locations))
        .where(
            SalesInvoiceLine.tenant_id == tenant_id,
            SalesInvoiceLine.sales_invoice_id == sales_invoice_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, SALES_INVOICE_LINE_SORT_COLUMNS)
    count_stmt = _apply_line_filters(
        select(func.count(SalesInvoiceLine.id)).where(
            SalesInvoiceLine.tenant_id == tenant_id,
            SalesInvoiceLine.sales_invoice_id == sales_invoice_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_line_cost_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    cost_id: uuid.UUID,
) -> SalesInvoiceLineCost | None:
    await _get_existing_line(db, tenant_id, sales_invoice_id, line_id)
    return await db.scalar(
        select(SalesInvoiceLineCost).where(
            SalesInvoiceLineCost.tenant_id == tenant_id,
            SalesInvoiceLineCost.sales_invoice_line_id == line_id,
            SalesInvoiceLineCost.id == cost_id,
        )
    )


async def list_line_costs(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    pagination: PaginationParams,
    filters: SalesInvoiceLineCostFilters,
    sort: tuple[SortSpec, ...],
) -> Page[SalesInvoiceLineCost]:
    await _get_existing_line(db, tenant_id, sales_invoice_id, line_id)
    stmt = _apply_line_cost_filters(
        select(SalesInvoiceLineCost).where(
            SalesInvoiceLineCost.tenant_id == tenant_id,
            SalesInvoiceLineCost.sales_invoice_line_id == line_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, SALES_INVOICE_LINE_COST_SORT_COLUMNS)
    count_stmt = _apply_line_cost_filters(
        select(func.count(SalesInvoiceLineCost.id)).where(
            SalesInvoiceLineCost.tenant_id == tenant_id,
            SalesInvoiceLineCost.sales_invoice_line_id == line_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def _fifo_allocations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    invoice: SalesInvoice,
    lines_with_variants: list[tuple[SalesInvoiceLine, ProductVariant]],
) -> list[FifoAllocation]:
    allocations: list[FifoAllocation] = []
    remaining_by_balance: dict[uuid.UUID, Decimal] = {}

    for line, variant in lines_with_variants:
        if not variant.track_inventory:
            continue
        splits = await _line_split_inputs(db, line)
        if not splits:
            raise InvalidSalesInvoiceLineLocations()
        for location_id, split_quantity in splits:
            remaining = quantize_base_quantity(split_quantity * line.conversion_to_base)
            available = await _available_fifo_balances(
                db,
                tenant_id=tenant_id,
                product_variant_id=line.product_variant_id,
                location_id=location_id,
            )
            for balance, batch in available:
                balance_remaining = remaining_by_balance.setdefault(
                    balance.id, balance.quantity_base
                )
                if balance_remaining <= ZERO:
                    continue
                consumed = min(remaining, balance_remaining)
                allocations.append(
                    FifoAllocation(
                        line=line,
                        variant=variant,
                        location_id=location_id,
                        balance=balance,
                        batch=batch,
                        quantity_base=consumed,
                    )
                )
                remaining -= consumed
                remaining_by_balance[balance.id] = balance_remaining - consumed
                if remaining == ZERO:
                    break
            if remaining > ZERO:
                location_name = await db.scalar(
                    select(Location.name).where(
                        Location.tenant_id == tenant_id,
                        Location.id == location_id,
                    )
                )
                raise SalesInvoiceInsufficientStock(
                    f"Insufficient stock for variant at location {location_name or location_id}."
                )

    return allocations


async def _available_fifo_balances(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> list[tuple[StockBalance, StockBatch]]:
    result = await db.execute(
        select(StockBalance, StockBatch)
        .join(StockBatch, StockBalance.stock_batch_id == StockBatch.id)
        .where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.product_variant_id == product_variant_id,
            StockBalance.location_id == location_id,
            StockBalance.quantity_base > ZERO,
            StockBatch.tenant_id == tenant_id,
            StockBatch.product_variant_id == product_variant_id,
            StockBatch.status == StockBatchStatus.ACTIVE,
        )
        .order_by(StockBatch.received_at.asc(), StockBatch.id.asc())
        .with_for_update()
    )
    return [(balance, batch) for balance, batch in result.all()]


async def _batch_total_quantity(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(StockBalance.quantity_base), ZERO)).where(
            StockBalance.tenant_id == tenant_id,
            StockBalance.stock_batch_id == stock_batch_id,
        )
    )
    return total or ZERO


async def _get_existing_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
) -> SalesInvoice:
    invoice = await get_by_id(db, tenant_id, sales_invoice_id)
    if invoice is None:
        raise SalesInvoiceNotFound()
    return invoice


async def _get_existing_line(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    line_id: uuid.UUID,
) -> SalesInvoiceLine:
    line = await get_line_by_id(db, tenant_id, sales_invoice_id, line_id)
    if line is None:
        raise SalesInvoiceLineNotFound()
    return line


def _ensure_draft(invoice: SalesInvoice) -> None:
    if invoice.status != DocumentStatus.DRAFT:
        raise SalesInvoiceNotDraft()


async def _ensure_document_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_no: str,
    *,
    sales_invoice_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(SalesInvoice).where(
            SalesInvoice.tenant_id == tenant_id,
            SalesInvoice.document_no == document_no,
        )
    )
    if existing is not None and existing.id != sales_invoice_id:
        raise SalesInvoiceDocumentNoConflict()


async def _ensure_line_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    line_no: int,
    *,
    line_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(SalesInvoiceLine).where(
            SalesInvoiceLine.tenant_id == tenant_id,
            SalesInvoiceLine.sales_invoice_id == sales_invoice_id,
            SalesInvoiceLine.line_no == line_no,
        )
    )
    if existing is not None and existing.id != line_id:
        raise SalesInvoiceLineNoConflict()


async def _ensure_optional_active_customer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID | None,
) -> Customer | None:
    if customer_id is None:
        return None
    customer = await db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.id == customer_id,
            Customer.status == PartyStatus.ACTIVE,
        )
    )
    if customer is None:
        raise InvalidSalesInvoiceCustomer()
    return customer


async def _ensure_active_price_level(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    price_level_id: uuid.UUID,
) -> PriceLevel:
    price_level = await db.scalar(
        select(PriceLevel).where(
            PriceLevel.tenant_id == tenant_id,
            PriceLevel.id == price_level_id,
            PriceLevel.is_active.is_(True),
        )
    )
    if price_level is None:
        raise InvalidSalesInvoicePriceLevel()
    return price_level


async def _resolve_price_level(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    requested_price_level_id: uuid.UUID | None,
    customer: Customer | None,
) -> PriceLevel:
    if requested_price_level_id is not None:
        return await _ensure_active_price_level(db, tenant_id, requested_price_level_id)
    if customer is not None and customer.price_level_id is not None:
        return await _ensure_active_price_level(db, tenant_id, customer.price_level_id)
    default_price_level = await db.scalar(
        select(PriceLevel).where(
            PriceLevel.tenant_id == tenant_id,
            PriceLevel.is_active.is_(True),
            PriceLevel.is_default.is_(True),
        )
    )
    if default_price_level is None:
        raise MissingSalesInvoicePriceLevel()
    return default_price_level


async def _ensure_sellable_location(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> Location:
    location = await db.scalar(
        select(Location).where(
            Location.tenant_id == tenant_id,
            Location.id == location_id,
            Location.is_active.is_(True),
            Location.is_sellable.is_(True),
        )
    )
    if location is None:
        raise InvalidSalesInvoiceLocation()
    return location


async def _ensure_active_sales_variant_unit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    *,
    allow_inactive_unit: bool = False,
) -> SalesVariantUnit:
    variant = await db.scalar(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id == product_variant_id,
            ProductVariant.is_active.is_(True),
        )
    )
    if variant is None:
        raise InvalidSalesInvoiceLineProduct()
    predicates = [
        VariantUnit.tenant_id == tenant_id,
        VariantUnit.id == variant_unit_id,
        VariantUnit.product_variant_id == product_variant_id,
    ]
    if not allow_inactive_unit:
        predicates.extend([VariantUnit.is_active.is_(True), VariantUnit.is_sales_unit.is_(True)])
    variant_unit = await db.scalar(select(VariantUnit).where(*predicates))
    if variant_unit is None:
        raise InvalidSalesInvoiceLineUnit()
    return SalesVariantUnit(variant=variant, variant_unit=variant_unit)


async def _resolve_line_source_location_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    variant: ProductVariant,
    source_location_id: uuid.UUID | None,
    *,
    default_location_id: uuid.UUID,
) -> uuid.UUID | None:
    if not variant.track_inventory:
        if source_location_id is not None:
            await _ensure_active_source_location(db, tenant_id, source_location_id)
            await _ensure_variant_available_at_source(
                db,
                tenant_id,
                variant.id,
                source_location_id,
            )
        return source_location_id

    resolved_location_id = source_location_id or default_location_id
    await _ensure_active_source_location(db, tenant_id, resolved_location_id)
    await _ensure_variant_available_at_source(db, tenant_id, variant.id, resolved_location_id)
    return resolved_location_id


async def _ensure_active_source_location(
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
        raise InvalidSalesInvoiceLineSourceLocation()
    return location


async def _ensure_variant_available_at_source(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> None:
    setting = await db.scalar(
        select(VariantLocationSetting).where(
            VariantLocationSetting.tenant_id == tenant_id,
            VariantLocationSetting.product_variant_id == product_variant_id,
            VariantLocationSetting.location_id == location_id,
        )
    )
    if setting is not None and not setting.is_available:
        raise InvalidSalesInvoiceLineSourceLocation()


async def _ensure_active_sales_variants(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    product_variant_ids: set[uuid.UUID],
) -> dict[uuid.UUID, ProductVariant]:
    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.tenant_id == tenant_id,
            ProductVariant.id.in_(product_variant_ids),
            ProductVariant.is_active.is_(True),
        )
    )
    variants = {variant.id: variant for variant in result.scalars().all()}
    if set(variants) != product_variant_ids:
        raise InvalidSalesInvoiceLineProduct()
    return variants


async def _line_price(
    db: AsyncSession,
    invoice: SalesInvoice,
    *,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    quantity: Decimal,
    explicit_unit_price: Decimal | None,
) -> tuple[Decimal, uuid.UUID | None]:
    if explicit_unit_price is not None:
        return explicit_unit_price, None
    unit_price, price_rule_id = await resolve_unit_price(
        db,
        invoice.tenant_id,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        price_level_id=invoice.price_level_id,
        customer_id=invoice.customer_id,
        quantity=quantity,
        effective_at=datetime.combine(invoice.invoice_date, datetime.min.time(), tzinfo=UTC),
    )
    if unit_price is None:
        raise MissingSalesInvoiceLinePrice()
    return unit_price, price_rule_id


async def _recalculate_invoice_totals(db: AsyncSession, invoice: SalesInvoice) -> None:
    lines = await _invoice_lines(db, invoice.tenant_id, invoice.id)
    subtotal = _money(sum((line.line_total for line in lines), ZERO))
    total = _money(subtotal - invoice.discount_amount)
    if total < ZERO:
        raise InvalidSalesInvoiceDiscount()
    invoice.subtotal_amount = subtotal
    invoice.total_amount = total
    invoice.paid_amount = _money(ZERO)
    invoice.balance_amount = total
    if invoice.status == DocumentStatus.DRAFT:
        invoice.total_cost = _money(ZERO)
        invoice.gross_profit = _money(total)
        for line in lines:
            line.total_cost = _money(ZERO)
            line.gross_profit = _money(line.line_total)
    await db.flush()


async def _reprice_invoice_lines(db: AsyncSession, invoice: SalesInvoice) -> None:
    lines = await _invoice_lines(db, invoice.tenant_id, invoice.id)
    for line in lines:
        sales_variant_unit = await _ensure_active_sales_variant_unit(
            db,
            invoice.tenant_id,
            line.product_variant_id,
            line.variant_unit_id,
            allow_inactive_unit=True,
        )
        # The conversion is a line snapshot.  Repricing must not silently
        # re-express an existing draft in a later catalog conversion.
        line.quantity_base = _quantity_base_from_line(line)
        if sales_variant_unit.variant.track_inventory:
            raw_splits = await _line_split_inputs(db, line)
            plan = await _resolve_split_plan(
                db,
                invoice.tenant_id,
                invoice,
                sales_variant_unit.variant,
                raw_splits,
                line.quantity,
            )
            await _materialize_splits(db, invoice.tenant_id, line, plan)
            if len(plan) == 1:
                line.source_location_id = plan[0][0]
            else:
                line.source_location_id = None
        else:
            line.source_location_id = await _resolve_line_source_location_id(
                db,
                invoice.tenant_id,
                sales_variant_unit.variant,
                line.source_location_id,
                default_location_id=invoice.location_id,
            )
        unit_price, price_rule_id = await _line_price(
            db,
            invoice,
            product_variant_id=line.product_variant_id,
            variant_unit_id=line.variant_unit_id,
            quantity=line.quantity,
            explicit_unit_price=line.unit_price,
        )
        line.unit_price = unit_price
        line.price_rule_id = price_rule_id
        line.line_total = _line_total(line.quantity, line.unit_price, line.discount_amount)
    await db.flush()


async def _invoice_lines(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
) -> list[SalesInvoiceLine]:
    result = await db.execute(
        select(SalesInvoiceLine)
        .options(selectinload(SalesInvoiceLine.locations))
        .where(
            SalesInvoiceLine.tenant_id == tenant_id,
            SalesInvoiceLine.sales_invoice_id == sales_invoice_id,
        )
        .order_by(SalesInvoiceLine.line_no.asc(), SalesInvoiceLine.id.asc())
    )
    return list(result.scalars().all())


def _line_total(quantity: Decimal, unit_price: Decimal, discount_amount: Decimal) -> Decimal:
    total = _money(quantity * unit_price - discount_amount)
    if total < ZERO:
        raise InvalidSalesInvoiceLineDiscount()
    return total


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT)


def _apply_invoice_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: SalesInvoiceFilters,
) -> StmtT:
    search = search_clause([SalesInvoice.document_no, SalesInvoice.notes], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.customer_id is not None:
        stmt = stmt.where(SalesInvoice.customer_id == filters.customer_id)
    if filters.location_id is not None:
        stmt = stmt.where(SalesInvoice.location_id == filters.location_id)
    if filters.price_level_id is not None:
        stmt = stmt.where(SalesInvoice.price_level_id == filters.price_level_id)
    if filters.status is not None:
        stmt = stmt.where(SalesInvoice.status == filters.status)
    stmt = where_gte_if_not_none(stmt, SalesInvoice.invoice_date, filters.invoice_date_gte)
    stmt = where_lte_if_not_none(stmt, SalesInvoice.invoice_date, filters.invoice_date_lte)
    return stmt


def _apply_line_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: SalesInvoiceLineFilters,
) -> StmtT:
    if filters.product_variant_id is not None:
        stmt = stmt.where(SalesInvoiceLine.product_variant_id == filters.product_variant_id)
    if filters.variant_unit_id is not None:
        stmt = stmt.where(SalesInvoiceLine.variant_unit_id == filters.variant_unit_id)
    if filters.source_location_id is not None:
        stmt = stmt.where(SalesInvoiceLine.source_location_id == filters.source_location_id)
    if filters.price_rule_id is not None:
        stmt = stmt.where(SalesInvoiceLine.price_rule_id == filters.price_rule_id)
    return stmt


def _apply_line_cost_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: SalesInvoiceLineCostFilters,
) -> StmtT:
    if filters.stock_batch_id is not None:
        stmt = stmt.where(SalesInvoiceLineCost.stock_batch_id == filters.stock_batch_id)
    if filters.stock_movement_id is not None:
        stmt = stmt.where(SalesInvoiceLineCost.stock_movement_id == filters.stock_movement_id)
    return stmt


def _invoice_loggable(invoice: SalesInvoice) -> dict[str, Any]:
    return {
        "document_no": invoice.document_no,
        "customer_id": str(invoice.customer_id) if invoice.customer_id else None,
        "location_id": str(invoice.location_id),
        "price_level_id": str(invoice.price_level_id),
        "invoice_date": invoice.invoice_date.isoformat(),
        "status": invoice.status.value,
        "subtotal_amount": str(invoice.subtotal_amount),
        "discount_amount": str(invoice.discount_amount),
        "total_amount": str(invoice.total_amount),
        "paid_amount": str(invoice.paid_amount),
        "balance_amount": str(invoice.balance_amount),
        "total_cost": str(invoice.total_cost),
        "gross_profit": str(invoice.gross_profit),
        "notes": invoice.notes,
        "posted_at": invoice.posted_at.isoformat() if invoice.posted_at else None,
        "posted_by": str(invoice.posted_by) if invoice.posted_by else None,
        "cancelled_at": invoice.cancelled_at.isoformat() if invoice.cancelled_at else None,
        "cancelled_by": str(invoice.cancelled_by) if invoice.cancelled_by else None,
        "created_by": str(invoice.created_by) if invoice.created_by else None,
    }


def _line_loggable(line: SalesInvoiceLine) -> dict[str, Any]:
    return {
        "sales_invoice_id": str(line.sales_invoice_id),
        "line_no": line.line_no,
        "product_variant_id": str(line.product_variant_id),
        "variant_unit_id": str(line.variant_unit_id),
        "source_location_id": str(line.source_location_id) if line.source_location_id else None,
        "quantity": str(line.quantity),
        "conversion_to_base": str(line.conversion_to_base),
        "quantity_base": str(line.quantity_base),
        "measured_quantity": str(line.measured_quantity)
        if line.measured_quantity is not None
        else None,
        "unit_price": str(line.unit_price),
        "discount_amount": str(line.discount_amount),
        "line_total": str(line.line_total),
        "total_cost": str(line.total_cost),
        "gross_profit": str(line.gross_profit),
        "price_rule_id": str(line.price_rule_id) if line.price_rule_id else None,
        "locations": [
            {
                "location_id": str(split.location_id),
                "quantity": str(split.quantity),
                "quantity_base": str(split.quantity_base),
            }
            for split in line.locations
        ],
    }
