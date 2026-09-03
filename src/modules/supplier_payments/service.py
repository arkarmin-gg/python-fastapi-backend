import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.foundation_enums import (
    DocumentStatus,
    PartyStatus,
    SourceType,
    SupplierLedgerEntryType,
)
from src.modules.audit_logs.service import record_audit_log
from src.modules.document_numbers.service import generate_document_no
from src.modules.purchase_invoices.models import PurchaseInvoice
from src.modules.supplier_payments.exceptions import (
    InvalidSupplierPaymentAllocationInvoice,
    InvalidSupplierPaymentSupplier,
    SupplierPaymentAllocationInvoiceConflict,
    SupplierPaymentAllocationNotEditable,
    SupplierPaymentAllocationNotFound,
    SupplierPaymentDocumentNoConflict,
    SupplierPaymentInvoiceOverpaid,
    SupplierPaymentNotCancellable,
    SupplierPaymentNotDraft,
    SupplierPaymentNotFound,
    SupplierPaymentNotPostable,
    SupplierPaymentNotReversible,
    SupplierPaymentOverAllocated,
)
from src.modules.supplier_payments.models import (
    SupplierBalance,
    SupplierLedgerEntry,
    SupplierPayment,
    SupplierPaymentAllocation,
)
from src.modules.supplier_payments.schemas import (
    SupplierBalanceFilters,
    SupplierLedgerEntryFilters,
    SupplierPaymentAllocationCreate,
    SupplierPaymentAllocationFilters,
    SupplierPaymentAllocationUpdate,
    SupplierPaymentCreate,
    SupplierPaymentFilters,
    SupplierPaymentUpdate,
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

PAYMENT_SORT_COLUMNS = {
    "document_no": SupplierPayment.document_no,
    "payment_date": SupplierPayment.payment_date,
    "status": SupplierPayment.status,
    "amount": SupplierPayment.amount,
    "created_at": SupplierPayment.created_at,
    "id": SupplierPayment.id,
}
ALLOCATION_SORT_COLUMNS = {
    "purchase_invoice_id": SupplierPaymentAllocation.purchase_invoice_id,
    "allocated_amount": SupplierPaymentAllocation.allocated_amount,
    "id": SupplierPaymentAllocation.id,
}
LEDGER_SORT_COLUMNS = {
    "posted_at": SupplierLedgerEntry.posted_at,
    "supplier_id": SupplierLedgerEntry.supplier_id,
    "entry_type": SupplierLedgerEntry.entry_type,
    "id": SupplierLedgerEntry.id,
}
BALANCE_SORT_COLUMNS = {
    "supplier_id": SupplierBalance.supplier_id,
    "balance_amount": SupplierBalance.balance_amount,
    "updated_at": SupplierBalance.updated_at,
    "id": SupplierBalance.id,
}
ZERO = Decimal("0")
MONEY_QUANT = Decimal("0.0001")


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> SupplierPayment | None:
    stmt = select(SupplierPayment).where(
        SupplierPayment.tenant_id == tenant_id,
        SupplierPayment.id == supplier_payment_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def get_by_idempotency_key(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    idempotency_key: str,
) -> SupplierPayment | None:
    return await db.scalar(
        select(SupplierPayment).where(
            SupplierPayment.tenant_id == tenant_id,
            SupplierPayment.idempotency_key == idempotency_key,
        )
    )


async def get_payment_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
) -> SupplierPayment | None:
    return await db.scalar(
        select(SupplierPayment)
        .options(selectinload(SupplierPayment.allocations))
        .where(
            SupplierPayment.tenant_id == tenant_id,
            SupplierPayment.id == supplier_payment_id,
        )
    )


async def list_supplier_payments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: SupplierPaymentFilters,
    sort: tuple[SortSpec, ...],
) -> Page[SupplierPayment]:
    stmt = _apply_payment_filters(
        select(SupplierPayment).where(SupplierPayment.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, PAYMENT_SORT_COLUMNS)
    count_stmt = _apply_payment_filters(
        select(func.count(SupplierPayment.id)).where(SupplierPayment.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: SupplierPaymentCreate,
    *,
    actor_user_id: uuid.UUID,
    idempotency_key: str | None = None,
) -> SupplierPayment:
    if idempotency_key is not None:
        existing = await get_by_idempotency_key(db, tenant_id, idempotency_key)
        if existing is not None:
            detail = await get_payment_detail_by_id(db, tenant_id, existing.id)
            assert detail is not None
            return detail
    try:
        payment = await _create_payment_draft(
            db,
            tenant_id,
            data,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(payment)
    detail = await get_payment_detail_by_id(db, tenant_id, payment.id)
    assert detail is not None
    return detail


async def _create_payment_draft(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: SupplierPaymentCreate,
    *,
    actor_user_id: uuid.UUID,
    idempotency_key: str | None = None,
) -> SupplierPayment:
    await _ensure_active_supplier(db, tenant_id, data.supplier_id)
    payment = SupplierPayment(
        tenant_id=tenant_id,
        status=DocumentStatus.DRAFT,
        created_by=actor_user_id,
        idempotency_key=idempotency_key,
        document_no=await generate_document_no(
            db, tenant_id, "supplier_payment", data.payment_date
        ),
        **data.model_dump(exclude={"allocations"}),
    )
    db.add(payment)
    await db.flush()

    allocations: list[SupplierPaymentAllocation] = []
    for allocation_data in data.allocations:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation_data.purchase_invoice_id,
            payment.supplier_id,
        )
        if allocation_data.allocated_amount > invoice.balance_amount:
            raise SupplierPaymentInvoiceOverpaid()
        allocation = SupplierPaymentAllocation(
            tenant_id=tenant_id,
            supplier_payment_id=payment.id,
            **allocation_data.model_dump(),
        )
        allocations.append(allocation)
    db.add_all(allocations)
    await db.flush()

    if sum_allocations(allocations) > payment.amount:
        raise SupplierPaymentOverAllocated()

    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="supplier_payments.post",
        entity_type="supplier_payment",
        entity_id=payment.id,
        after_json=_payment_loggable(payment)
        | {"allocations": [_allocation_loggable(allocation) for allocation in allocations]},
    )
    await db.commit()
    return payment


async def update_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    data: SupplierPaymentUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> SupplierPayment:
    payment = await _get_existing_payment(db, tenant_id, supplier_payment_id)
    _ensure_draft(payment)
    before = _payment_loggable(payment)
    fields = data.model_dump(exclude_unset=True)
    if "supplier_id" in fields:
        await _ensure_active_supplier(db, tenant_id, fields["supplier_id"])
    for key, value in fields.items():
        setattr(payment, key, value)

    allocations = await _payment_allocations(db, tenant_id, payment.id)
    if sum_allocations(allocations) > payment.amount:
        raise SupplierPaymentOverAllocated()
    for allocation in allocations:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation.purchase_invoice_id,
            payment.supplier_id,
        )
        if allocation.allocated_amount > invoice.balance_amount:
            raise SupplierPaymentInvoiceOverpaid()

    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="supplier_payments.update",
        entity_type="supplier_payment",
        entity_id=payment.id,
        before_json=before,
        after_json=_payment_loggable(payment),
    )
    await db.commit()
    await db.refresh(payment)
    return payment


async def cancel_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    payment = await _get_existing_payment(db, tenant_id, supplier_payment_id)
    if payment.status != DocumentStatus.DRAFT:
        raise SupplierPaymentNotCancellable()
    before = _payment_loggable(payment)
    payment.status = DocumentStatus.CANCELLED
    payment.cancelled_at = datetime.now(UTC)
    payment.cancelled_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="supplier_payments.cancel",
        entity_type="supplier_payment",
        entity_id=payment.id,
        before_json=before,
        after_json=_payment_loggable(payment),
    )
    await db.commit()


async def post_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> SupplierPayment:
    try:
        payment = await _post_payment_atomically(
            db,
            tenant_id,
            supplier_payment_id,
            actor_user_id=actor_user_id,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(payment)
    detail = await get_payment_detail_by_id(db, tenant_id, payment.id)
    assert detail is not None
    return detail


async def _post_payment_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> SupplierPayment:
    payment = await _get_existing_payment(db, tenant_id, supplier_payment_id, for_update=True)
    if payment.status != DocumentStatus.DRAFT:
        raise SupplierPaymentNotPostable()
    await _ensure_active_supplier(db, tenant_id, payment.supplier_id)
    allocations = await _payment_allocations(db, tenant_id, payment.id)
    if sum_allocations(allocations) > payment.amount:
        raise SupplierPaymentOverAllocated()

    before = _payment_loggable(payment)
    posted_at = datetime.now(UTC)
    posted_allocations: list[dict[str, str]] = []
    for allocation in allocations:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation.purchase_invoice_id,
            payment.supplier_id,
            for_update=True,
        )
        if allocation.allocated_amount > invoice.balance_amount:
            raise SupplierPaymentInvoiceOverpaid()
        await ensure_invoice_ledger_entry(
            db,
            invoice,
            actor_user_id=actor_user_id,
            posted_at=invoice.posted_at or posted_at,
        )
        invoice.paid_amount = _money(invoice.paid_amount + allocation.allocated_amount)
        invoice.balance_amount = _money(invoice.total_amount - invoice.paid_amount)
        posted_allocations.append(
            {
                "allocation_id": str(allocation.id),
                "purchase_invoice_id": str(invoice.id),
                "allocated_amount": str(allocation.allocated_amount),
            }
        )

    payment.status = DocumentStatus.POSTED
    payment.posted_at = posted_at
    payment.posted_by = actor_user_id
    ledger_entry = SupplierLedgerEntry(
        tenant_id=tenant_id,
        supplier_id=payment.supplier_id,
        entry_type=SupplierLedgerEntryType.PAYMENT,
        debit_amount=_money(payment.amount),
        credit_amount=_money(ZERO),
        balance_effect=_money(-payment.amount),
        source_type=SourceType.SUPPLIER_PAYMENT,
        source_id=payment.id,
        posted_at=posted_at,
        posted_by=actor_user_id,
    )
    db.add(ledger_entry)
    await db.flush()
    await _apply_supplier_balance_effect(
        db,
        tenant_id=tenant_id,
        supplier_id=payment.supplier_id,
        amount=_money(-payment.amount),
        updated_at=posted_at,
    )
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="supplier_payments.create",
        entity_type="supplier_payment",
        entity_id=payment.id,
        before_json=before,
        after_json=_payment_loggable(payment)
        | {
            "supplier_ledger_entry_id": str(ledger_entry.id),
            "posted_allocations": posted_allocations,
            "unapplied_amount": str(_money(payment.amount - sum_allocations(allocations))),
        },
    )
    await db.commit()
    return payment


async def reverse_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    reason: str,
    *,
    actor_user_id: uuid.UUID,
) -> SupplierPayment:
    try:
        payment = await _reverse_payment_atomically(
            db,
            tenant_id,
            supplier_payment_id,
            reason,
            actor_user_id=actor_user_id,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(payment)
    detail = await get_payment_detail_by_id(db, tenant_id, payment.id)
    assert detail is not None
    return detail


async def _reverse_payment_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    reason: str,
    *,
    actor_user_id: uuid.UUID,
) -> SupplierPayment:
    payment = await _get_existing_payment(db, tenant_id, supplier_payment_id, for_update=True)
    if payment.status != DocumentStatus.POSTED:
        raise SupplierPaymentNotReversible()

    before = _payment_loggable(payment)
    reversed_at = datetime.now(UTC)
    allocations = await _payment_allocations(db, tenant_id, payment.id)
    reversed_allocations: list[dict[str, str]] = []
    for allocation in allocations:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation.purchase_invoice_id,
            payment.supplier_id,
            for_update=True,
        )
        invoice.paid_amount = _money(invoice.paid_amount - allocation.allocated_amount)
        invoice.balance_amount = _money(invoice.total_amount - invoice.paid_amount)
        reversed_allocations.append(
            {
                "allocation_id": str(allocation.id),
                "purchase_invoice_id": str(invoice.id),
                "allocated_amount": str(allocation.allocated_amount),
            }
        )

    payment.status = DocumentStatus.REVERSED
    payment.reversed_at = reversed_at
    payment.reversed_by = actor_user_id
    payment.reversal_reason = reason
    ledger_entry = SupplierLedgerEntry(
        tenant_id=tenant_id,
        supplier_id=payment.supplier_id,
        entry_type=SupplierLedgerEntryType.REVERSAL,
        debit_amount=_money(ZERO),
        credit_amount=_money(payment.amount),
        balance_effect=_money(payment.amount),
        source_type=SourceType.SUPPLIER_PAYMENT,
        source_id=payment.id,
        posted_at=reversed_at,
        posted_by=actor_user_id,
    )
    db.add(ledger_entry)
    await db.flush()
    await _apply_supplier_balance_effect(
        db,
        tenant_id=tenant_id,
        supplier_id=payment.supplier_id,
        amount=_money(payment.amount),
        updated_at=reversed_at,
    )
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="supplier_payments.reverse",
        entity_type="supplier_payment",
        entity_id=payment.id,
        before_json=before,
        after_json=_payment_loggable(payment)
        | {
            "reversal_ledger_entry_id": str(ledger_entry.id),
            "reversed_allocations": reversed_allocations,
        },
    )
    await db.commit()
    return payment


async def create_allocation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    data: SupplierPaymentAllocationCreate,
    *,
    actor_user_id: uuid.UUID,
) -> SupplierPaymentAllocation:
    payment = await _get_existing_payment(db, tenant_id, supplier_payment_id, for_update=True)
    _ensure_allocation_mutable(payment)
    is_posted = payment.status == DocumentStatus.POSTED
    await _ensure_allocation_invoice_available(db, tenant_id, payment.id, data.purchase_invoice_id)
    invoice = await _ensure_allocatable_invoice(
        db,
        tenant_id,
        data.purchase_invoice_id,
        payment.supplier_id,
        for_update=is_posted,
    )
    if data.allocated_amount > invoice.balance_amount:
        raise SupplierPaymentInvoiceOverpaid()
    allocations = await _payment_allocations(db, tenant_id, payment.id)
    if sum_allocations(allocations) + data.allocated_amount > payment.amount:
        raise SupplierPaymentOverAllocated()
    allocation = SupplierPaymentAllocation(
        tenant_id=tenant_id,
        supplier_payment_id=payment.id,
        **data.model_dump(),
    )
    db.add(allocation)
    if is_posted:
        invoice.paid_amount = _money(invoice.paid_amount + data.allocated_amount)
        invoice.balance_amount = _money(invoice.total_amount - invoice.paid_amount)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="supplier_payment_allocations.create",
        entity_type="supplier_payment_allocation",
        entity_id=allocation.id,
        after_json=_allocation_loggable(allocation),
    )
    await db.commit()
    await db.refresh(allocation)
    return allocation


async def update_allocation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
    data: SupplierPaymentAllocationUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> SupplierPaymentAllocation:
    try:
        allocation = await _update_allocation_atomically(
            db,
            tenant_id,
            supplier_payment_id,
            allocation_id,
            data,
            actor_user_id=actor_user_id,
        )
    except Exception:
        await db.rollback()
        raise
    await db.refresh(allocation)
    return allocation


async def _update_allocation_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
    data: SupplierPaymentAllocationUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> SupplierPaymentAllocation:
    payment = await _get_existing_payment(db, tenant_id, supplier_payment_id, for_update=True)
    _ensure_allocation_mutable(payment)
    is_posted = payment.status == DocumentStatus.POSTED
    allocation = await _get_existing_allocation(db, tenant_id, supplier_payment_id, allocation_id)
    before = _allocation_loggable(allocation)
    old_invoice_id = allocation.purchase_invoice_id
    old_allocated_amount = allocation.allocated_amount
    fields = data.model_dump(exclude_unset=True)
    new_invoice_id = fields.get("purchase_invoice_id", old_invoice_id)
    invoice_changed = new_invoice_id != old_invoice_id
    if invoice_changed:
        await _ensure_allocation_invoice_available(
            db,
            tenant_id,
            payment.id,
            new_invoice_id,
            allocation_id=allocation.id,
        )
    new_allocated_amount = fields.get("allocated_amount", allocation.allocated_amount)

    old_invoice = None
    if is_posted:
        old_invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            old_invoice_id,
            payment.supplier_id,
            for_update=True,
        )
        old_invoice.paid_amount = _money(old_invoice.paid_amount - old_allocated_amount)
        old_invoice.balance_amount = _money(old_invoice.total_amount - old_invoice.paid_amount)

    if invoice_changed:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            new_invoice_id,
            payment.supplier_id,
            for_update=is_posted,
        )
    elif old_invoice is not None:
        invoice = old_invoice
    else:
        invoice = await _ensure_allocatable_invoice(
            db, tenant_id, new_invoice_id, payment.supplier_id
        )

    if new_allocated_amount > invoice.balance_amount:
        raise SupplierPaymentInvoiceOverpaid()
    allocations = await _payment_allocations(db, tenant_id, payment.id)
    other_total = sum_allocations([item for item in allocations if item.id != allocation.id])
    if other_total + new_allocated_amount > payment.amount:
        raise SupplierPaymentOverAllocated()
    for key, value in fields.items():
        setattr(allocation, key, value)
    if is_posted:
        invoice.paid_amount = _money(invoice.paid_amount + new_allocated_amount)
        invoice.balance_amount = _money(invoice.total_amount - invoice.paid_amount)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="supplier_payment_allocations.update",
        entity_type="supplier_payment_allocation",
        entity_id=allocation.id,
        before_json=before,
        after_json=_allocation_loggable(allocation),
    )
    await db.commit()
    return allocation


async def delete_allocation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    payment = await _get_existing_payment(db, tenant_id, supplier_payment_id, for_update=True)
    _ensure_allocation_mutable(payment)
    allocation = await _get_existing_allocation(db, tenant_id, supplier_payment_id, allocation_id)
    before = _allocation_loggable(allocation)
    if payment.status == DocumentStatus.POSTED:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation.purchase_invoice_id,
            payment.supplier_id,
            for_update=True,
        )
        invoice.paid_amount = _money(invoice.paid_amount - allocation.allocated_amount)
        invoice.balance_amount = _money(invoice.total_amount - invoice.paid_amount)
    await db.delete(allocation)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="supplier_payment_allocations.delete",
        entity_type="supplier_payment_allocation",
        entity_id=allocation.id,
        before_json=before,
    )
    await db.commit()


async def get_allocation_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
) -> SupplierPaymentAllocation | None:
    return await db.scalar(
        select(SupplierPaymentAllocation).where(
            SupplierPaymentAllocation.tenant_id == tenant_id,
            SupplierPaymentAllocation.supplier_payment_id == supplier_payment_id,
            SupplierPaymentAllocation.id == allocation_id,
        )
    )


async def list_allocations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    pagination: PaginationParams,
    filters: SupplierPaymentAllocationFilters,
    sort: tuple[SortSpec, ...],
) -> Page[SupplierPaymentAllocation]:
    await _get_existing_payment(db, tenant_id, supplier_payment_id)
    stmt = _apply_allocation_filters(
        select(SupplierPaymentAllocation).where(
            SupplierPaymentAllocation.tenant_id == tenant_id,
            SupplierPaymentAllocation.supplier_payment_id == supplier_payment_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, ALLOCATION_SORT_COLUMNS)
    count_stmt = _apply_allocation_filters(
        select(func.count(SupplierPaymentAllocation.id)).where(
            SupplierPaymentAllocation.tenant_id == tenant_id,
            SupplierPaymentAllocation.supplier_payment_id == supplier_payment_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_ledger_entry_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> SupplierLedgerEntry | None:
    return await db.scalar(
        select(SupplierLedgerEntry).where(
            SupplierLedgerEntry.tenant_id == tenant_id,
            SupplierLedgerEntry.id == entry_id,
        )
    )


async def list_ledger_entries(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: SupplierLedgerEntryFilters,
    sort: tuple[SortSpec, ...],
) -> Page[SupplierLedgerEntry]:
    stmt = _apply_ledger_filters(
        select(SupplierLedgerEntry).where(SupplierLedgerEntry.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, LEDGER_SORT_COLUMNS)
    count_stmt = _apply_ledger_filters(
        select(func.count(SupplierLedgerEntry.id)).where(
            SupplierLedgerEntry.tenant_id == tenant_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_balance_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    balance_id: uuid.UUID,
) -> SupplierBalance | None:
    return await db.scalar(
        select(SupplierBalance).where(
            SupplierBalance.tenant_id == tenant_id,
            SupplierBalance.id == balance_id,
        )
    )


async def list_balances(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: SupplierBalanceFilters,
    sort: tuple[SortSpec, ...],
) -> Page[SupplierBalance]:
    stmt = _apply_balance_filters(
        select(SupplierBalance).where(SupplierBalance.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, BALANCE_SORT_COLUMNS)
    count_stmt = _apply_balance_filters(
        select(func.count(SupplierBalance.id)).where(SupplierBalance.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_balance_reconciliation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    supplier_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    ledger_stmt = (
        select(SupplierLedgerEntry.supplier_id, func.sum(SupplierLedgerEntry.balance_effect))
        .where(SupplierLedgerEntry.tenant_id == tenant_id)
        .group_by(SupplierLedgerEntry.supplier_id)
    )
    if supplier_id is not None:
        ledger_stmt = ledger_stmt.where(SupplierLedgerEntry.supplier_id == supplier_id)
    ledger_totals = {row[0]: _money(row[1]) for row in (await db.execute(ledger_stmt)).all()}

    balance_stmt = select(SupplierBalance).where(SupplierBalance.tenant_id == tenant_id)
    if supplier_id is not None:
        balance_stmt = balance_stmt.where(SupplierBalance.supplier_id == supplier_id)
    balances = (await db.execute(balance_stmt)).scalars().all()

    seen_supplier_ids: set[uuid.UUID] = set()
    drifts: list[dict[str, Any]] = []
    for balance in balances:
        seen_supplier_ids.add(balance.supplier_id)
        ledger_balance = ledger_totals.get(balance.supplier_id, ZERO)
        if balance.balance_amount != ledger_balance:
            drifts.append(
                {
                    "supplier_id": balance.supplier_id,
                    "cached_balance": balance.balance_amount,
                    "ledger_balance": ledger_balance,
                    "delta": _money(balance.balance_amount - ledger_balance),
                }
            )
    for sid, ledger_balance in ledger_totals.items():
        if sid in seen_supplier_ids:
            continue
        drifts.append(
            {
                "supplier_id": sid,
                "cached_balance": ZERO,
                "ledger_balance": ledger_balance,
                "delta": _money(ZERO - ledger_balance),
            }
        )
    return drifts


async def ensure_invoice_ledger_entry(
    db: AsyncSession,
    invoice: PurchaseInvoice,
    *,
    actor_user_id: uuid.UUID,
    posted_at: datetime,
) -> SupplierLedgerEntry | None:
    if invoice.supplier_id is None:
        return None
    existing = await db.scalar(
        select(SupplierLedgerEntry).where(
            SupplierLedgerEntry.tenant_id == invoice.tenant_id,
            SupplierLedgerEntry.source_type == SourceType.PURCHASE_INVOICE,
            SupplierLedgerEntry.source_id == invoice.id,
            SupplierLedgerEntry.entry_type == SupplierLedgerEntryType.INVOICE,
        )
    )
    if existing is not None:
        return existing
    entry = SupplierLedgerEntry(
        tenant_id=invoice.tenant_id,
        supplier_id=invoice.supplier_id,
        entry_type=SupplierLedgerEntryType.INVOICE,
        debit_amount=_money(ZERO),
        credit_amount=_money(invoice.total_amount),
        balance_effect=_money(invoice.total_amount),
        source_type=SourceType.PURCHASE_INVOICE,
        source_id=invoice.id,
        posted_at=posted_at,
        posted_by=actor_user_id,
    )
    db.add(entry)
    await db.flush()
    await _apply_supplier_balance_effect(
        db,
        tenant_id=invoice.tenant_id,
        supplier_id=invoice.supplier_id,
        amount=_money(invoice.total_amount),
        updated_at=posted_at,
    )
    return entry


async def _get_existing_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> SupplierPayment:
    payment = await get_by_id(db, tenant_id, supplier_payment_id, for_update=for_update)
    if payment is None:
        raise SupplierPaymentNotFound()
    return payment


async def _get_existing_allocation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
) -> SupplierPaymentAllocation:
    allocation = await get_allocation_by_id(db, tenant_id, supplier_payment_id, allocation_id)
    if allocation is None:
        raise SupplierPaymentAllocationNotFound()
    return allocation


def _ensure_draft(payment: SupplierPayment) -> None:
    if payment.status != DocumentStatus.DRAFT:
        raise SupplierPaymentNotDraft()


def _ensure_allocation_mutable(payment: SupplierPayment) -> None:
    if payment.status not in (DocumentStatus.DRAFT, DocumentStatus.POSTED):
        raise SupplierPaymentAllocationNotEditable()


async def _ensure_document_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_no: str,
    *,
    supplier_payment_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(SupplierPayment).where(
            SupplierPayment.tenant_id == tenant_id,
            SupplierPayment.document_no == document_no,
        )
    )
    if existing is not None and existing.id != supplier_payment_id:
        raise SupplierPaymentDocumentNoConflict()


async def _ensure_allocation_invoice_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    *,
    allocation_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(SupplierPaymentAllocation).where(
            SupplierPaymentAllocation.tenant_id == tenant_id,
            SupplierPaymentAllocation.supplier_payment_id == supplier_payment_id,
            SupplierPaymentAllocation.purchase_invoice_id == purchase_invoice_id,
        )
    )
    if existing is not None and existing.id != allocation_id:
        raise SupplierPaymentAllocationInvoiceConflict()


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
        raise InvalidSupplierPaymentSupplier()
    return supplier


async def _ensure_allocatable_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    purchase_invoice_id: uuid.UUID,
    supplier_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> PurchaseInvoice:
    stmt = select(PurchaseInvoice).where(
        PurchaseInvoice.tenant_id == tenant_id,
        PurchaseInvoice.id == purchase_invoice_id,
        PurchaseInvoice.supplier_id == supplier_id,
        PurchaseInvoice.status == DocumentStatus.POSTED,
    )
    if for_update:
        stmt = stmt.with_for_update()
    invoice = await db.scalar(stmt)
    if invoice is None:
        raise InvalidSupplierPaymentAllocationInvoice()
    return invoice


async def _payment_allocations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    supplier_payment_id: uuid.UUID,
) -> list[SupplierPaymentAllocation]:
    result = await db.execute(
        select(SupplierPaymentAllocation)
        .where(
            SupplierPaymentAllocation.tenant_id == tenant_id,
            SupplierPaymentAllocation.supplier_payment_id == supplier_payment_id,
        )
        .order_by(SupplierPaymentAllocation.id.asc())
    )
    return list(result.scalars().all())


def sum_allocations(allocations: list[SupplierPaymentAllocation]) -> Decimal:
    return _money(sum((allocation.allocated_amount for allocation in allocations), ZERO))


async def _apply_supplier_balance_effect(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    amount: Decimal,
    updated_at: datetime,
) -> SupplierBalance:
    balance = await db.scalar(
        select(SupplierBalance)
        .where(SupplierBalance.tenant_id == tenant_id, SupplierBalance.supplier_id == supplier_id)
        .with_for_update()
    )
    if balance is None:
        balance = SupplierBalance(
            tenant_id=tenant_id,
            supplier_id=supplier_id,
            balance_amount=_money(ZERO),
            updated_at=updated_at,
        )
        db.add(balance)
        await db.flush()
    balance.balance_amount = _money(balance.balance_amount + amount)
    balance.updated_at = updated_at
    await db.flush()
    return balance


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT)


def _apply_payment_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: SupplierPaymentFilters,
) -> StmtT:
    search = search_clause([SupplierPayment.document_no, SupplierPayment.notes], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.supplier_id is not None:
        stmt = stmt.where(SupplierPayment.supplier_id == filters.supplier_id)
    if filters.payment_method is not None:
        stmt = stmt.where(SupplierPayment.payment_method == filters.payment_method)
    if filters.status is not None:
        stmt = stmt.where(SupplierPayment.status == filters.status)
    stmt = where_gte_if_not_none(stmt, SupplierPayment.payment_date, filters.payment_date_gte)
    stmt = where_lte_if_not_none(stmt, SupplierPayment.payment_date, filters.payment_date_lte)
    return stmt


def _apply_allocation_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: SupplierPaymentAllocationFilters,
) -> StmtT:
    if filters.purchase_invoice_id is not None:
        stmt = stmt.where(
            SupplierPaymentAllocation.purchase_invoice_id == filters.purchase_invoice_id
        )
    return stmt


def _apply_ledger_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: SupplierLedgerEntryFilters,
) -> StmtT:
    if filters.supplier_id is not None:
        stmt = stmt.where(SupplierLedgerEntry.supplier_id == filters.supplier_id)
    if filters.entry_type is not None:
        stmt = stmt.where(SupplierLedgerEntry.entry_type == filters.entry_type)
    if filters.source_type is not None:
        stmt = stmt.where(SupplierLedgerEntry.source_type == filters.source_type)
    if filters.source_id is not None:
        stmt = stmt.where(SupplierLedgerEntry.source_id == filters.source_id)
    stmt = where_gte_if_not_none(stmt, SupplierLedgerEntry.posted_at, filters.posted_at_gte)
    stmt = where_lte_if_not_none(stmt, SupplierLedgerEntry.posted_at, filters.posted_at_lte)
    return stmt


def _apply_balance_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: SupplierBalanceFilters,
) -> StmtT:
    if filters.supplier_id is not None:
        stmt = stmt.where(SupplierBalance.supplier_id == filters.supplier_id)
    return stmt


def _payment_loggable(payment: SupplierPayment) -> dict[str, Any]:
    return {
        "document_no": payment.document_no,
        "supplier_id": str(payment.supplier_id),
        "payment_date": payment.payment_date.isoformat(),
        "payment_method": payment.payment_method.value,
        "amount": str(payment.amount),
        "status": payment.status.value,
        "notes": payment.notes,
        "posted_at": payment.posted_at.isoformat() if payment.posted_at else None,
        "posted_by": str(payment.posted_by) if payment.posted_by else None,
        "cancelled_at": payment.cancelled_at.isoformat() if payment.cancelled_at else None,
        "cancelled_by": str(payment.cancelled_by) if payment.cancelled_by else None,
        "reversed_at": payment.reversed_at.isoformat() if payment.reversed_at else None,
        "reversed_by": str(payment.reversed_by) if payment.reversed_by else None,
        "reversal_reason": payment.reversal_reason,
        "created_by": str(payment.created_by) if payment.created_by else None,
    }


def _allocation_loggable(allocation: SupplierPaymentAllocation) -> dict[str, Any]:
    return {
        "supplier_payment_id": str(allocation.supplier_payment_id),
        "purchase_invoice_id": str(allocation.purchase_invoice_id),
        "allocated_amount": str(allocation.allocated_amount),
    }
