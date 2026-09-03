import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.foundation_enums import (
    CustomerLedgerEntryType,
    DocumentStatus,
    PartyStatus,
    SourceType,
)
from src.modules.audit_logs.service import record_audit_log
from src.modules.customer_payments.exceptions import (
    CustomerPaymentAllocationInvoiceConflict,
    CustomerPaymentAllocationNotEditable,
    CustomerPaymentAllocationNotFound,
    CustomerPaymentDocumentNoConflict,
    CustomerPaymentInvoiceOverpaid,
    CustomerPaymentNotCancellable,
    CustomerPaymentNotDraft,
    CustomerPaymentNotFound,
    CustomerPaymentNotPostable,
    CustomerPaymentNotReversible,
    CustomerPaymentOverAllocated,
    InvalidCustomerPaymentAllocationInvoice,
    InvalidCustomerPaymentCustomer,
)
from src.modules.customer_payments.models import (
    CustomerBalance,
    CustomerLedgerEntry,
    CustomerPayment,
    CustomerPaymentAllocation,
)
from src.modules.customer_payments.schemas import (
    CustomerBalanceFilters,
    CustomerLedgerEntryFilters,
    CustomerPaymentAllocationCreate,
    CustomerPaymentAllocationFilters,
    CustomerPaymentAllocationUpdate,
    CustomerPaymentCreate,
    CustomerPaymentFilters,
    CustomerPaymentUpdate,
)
from src.modules.customers.models import Customer
from src.modules.document_numbers.service import generate_document_no
from src.modules.sales_invoices.models import SalesInvoice
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import (
    SortSpec,
    apply_sort,
    search_clause,
    where_gte_if_not_none,
    where_lte_if_not_none,
)

PAYMENT_SORT_COLUMNS = {
    "document_no": CustomerPayment.document_no,
    "payment_date": CustomerPayment.payment_date,
    "status": CustomerPayment.status,
    "amount": CustomerPayment.amount,
    "created_at": CustomerPayment.created_at,
    "id": CustomerPayment.id,
}
ALLOCATION_SORT_COLUMNS = {
    "sales_invoice_id": CustomerPaymentAllocation.sales_invoice_id,
    "allocated_amount": CustomerPaymentAllocation.allocated_amount,
    "id": CustomerPaymentAllocation.id,
}
LEDGER_SORT_COLUMNS = {
    "posted_at": CustomerLedgerEntry.posted_at,
    "customer_id": CustomerLedgerEntry.customer_id,
    "entry_type": CustomerLedgerEntry.entry_type,
    "id": CustomerLedgerEntry.id,
}
BALANCE_SORT_COLUMNS = {
    "customer_id": CustomerBalance.customer_id,
    "balance_amount": CustomerBalance.balance_amount,
    "updated_at": CustomerBalance.updated_at,
    "id": CustomerBalance.id,
}
ZERO = Decimal("0")
MONEY_QUANT = Decimal("0.0001")


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> CustomerPayment | None:
    stmt = select(CustomerPayment).where(
        CustomerPayment.tenant_id == tenant_id,
        CustomerPayment.id == customer_payment_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def get_by_idempotency_key(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    idempotency_key: str,
) -> CustomerPayment | None:
    return await db.scalar(
        select(CustomerPayment).where(
            CustomerPayment.tenant_id == tenant_id,
            CustomerPayment.idempotency_key == idempotency_key,
        )
    )


async def get_payment_detail_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
) -> CustomerPayment | None:
    return await db.scalar(
        select(CustomerPayment)
        .options(selectinload(CustomerPayment.allocations))
        .where(
            CustomerPayment.tenant_id == tenant_id,
            CustomerPayment.id == customer_payment_id,
        )
    )


async def list_customer_payments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: CustomerPaymentFilters,
    sort: tuple[SortSpec, ...],
) -> Page[CustomerPayment]:
    stmt = _apply_payment_filters(
        select(CustomerPayment).where(CustomerPayment.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, PAYMENT_SORT_COLUMNS)
    count_stmt = _apply_payment_filters(
        select(func.count(CustomerPayment.id)).where(CustomerPayment.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: CustomerPaymentCreate,
    *,
    actor_user_id: uuid.UUID,
    idempotency_key: str | None = None,
) -> CustomerPayment:
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
    data: CustomerPaymentCreate,
    *,
    actor_user_id: uuid.UUID,
    idempotency_key: str | None = None,
    commit: bool = True,
) -> CustomerPayment:
    await _ensure_active_customer(db, tenant_id, data.customer_id)
    payment = CustomerPayment(
        tenant_id=tenant_id,
        status=DocumentStatus.DRAFT,
        created_by=actor_user_id,
        idempotency_key=idempotency_key,
        document_no=await generate_document_no(
            db, tenant_id, "customer_payment", data.payment_date
        ),
        **data.model_dump(exclude={"allocations"}),
    )
    db.add(payment)
    await db.flush()

    allocations: list[CustomerPaymentAllocation] = []
    for allocation_data in data.allocations:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation_data.sales_invoice_id,
            payment.customer_id,
        )
        if allocation_data.allocated_amount > invoice.balance_amount:
            raise CustomerPaymentInvoiceOverpaid()
        allocation = CustomerPaymentAllocation(
            tenant_id=tenant_id,
            customer_payment_id=payment.id,
            **allocation_data.model_dump(),
        )
        allocations.append(allocation)
    db.add_all(allocations)
    await db.flush()

    if sum_allocations(allocations) > payment.amount:
        raise CustomerPaymentOverAllocated()

    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="customer_payments.create",
        entity_type="customer_payment",
        entity_id=payment.id,
        after_json=_payment_loggable(payment)
        | {"allocations": [_allocation_loggable(allocation) for allocation in allocations]},
    )
    if commit:
        await db.commit()
    return payment


async def update_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    data: CustomerPaymentUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> CustomerPayment:
    payment = await _get_existing_payment(db, tenant_id, customer_payment_id)
    _ensure_draft(payment)
    before = _payment_loggable(payment)
    fields = data.model_dump(exclude_unset=True)
    if "customer_id" in fields:
        await _ensure_active_customer(db, tenant_id, fields["customer_id"])
    for key, value in fields.items():
        setattr(payment, key, value)

    allocations = await _payment_allocations(db, tenant_id, payment.id)
    if sum_allocations(allocations) > payment.amount:
        raise CustomerPaymentOverAllocated()
    for allocation in allocations:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation.sales_invoice_id,
            payment.customer_id,
        )
        if allocation.allocated_amount > invoice.balance_amount:
            raise CustomerPaymentInvoiceOverpaid()

    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="customer_payments.update",
        entity_type="customer_payment",
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
    customer_payment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    payment = await _get_existing_payment(db, tenant_id, customer_payment_id)
    if payment.status != DocumentStatus.DRAFT:
        raise CustomerPaymentNotCancellable()
    before = _payment_loggable(payment)
    payment.status = DocumentStatus.CANCELLED
    payment.cancelled_at = datetime.now(UTC)
    payment.cancelled_by = actor_user_id
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="customer_payments.cancel",
        entity_type="customer_payment",
        entity_id=payment.id,
        before_json=before,
        after_json=_payment_loggable(payment),
    )
    await db.commit()


async def post_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> CustomerPayment:
    try:
        payment = await _post_payment_atomically(
            db,
            tenant_id,
            customer_payment_id,
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
    customer_payment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    commit: bool = True,
) -> CustomerPayment:
    payment = await _get_existing_payment(db, tenant_id, customer_payment_id, for_update=True)
    if payment.status != DocumentStatus.DRAFT:
        raise CustomerPaymentNotPostable()
    await _ensure_active_customer(db, tenant_id, payment.customer_id)
    allocations = await _payment_allocations(db, tenant_id, payment.id)
    if sum_allocations(allocations) > payment.amount:
        raise CustomerPaymentOverAllocated()

    before = _payment_loggable(payment)
    posted_at = datetime.now(UTC)
    posted_allocations: list[dict[str, str]] = []
    for allocation in allocations:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation.sales_invoice_id,
            payment.customer_id,
            for_update=True,
        )
        if allocation.allocated_amount > invoice.balance_amount:
            raise CustomerPaymentInvoiceOverpaid()
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
                "sales_invoice_id": str(invoice.id),
                "allocated_amount": str(allocation.allocated_amount),
            }
        )

    payment.status = DocumentStatus.POSTED
    payment.posted_at = posted_at
    payment.posted_by = actor_user_id
    ledger_entry = CustomerLedgerEntry(
        tenant_id=tenant_id,
        customer_id=payment.customer_id,
        entry_type=CustomerLedgerEntryType.PAYMENT,
        debit_amount=_money(ZERO),
        credit_amount=_money(payment.amount),
        balance_effect=_money(-payment.amount),
        source_type=SourceType.CUSTOMER_PAYMENT,
        source_id=payment.id,
        posted_at=posted_at,
        posted_by=actor_user_id,
    )
    db.add(ledger_entry)
    await db.flush()
    await _apply_customer_balance_effect(
        db,
        tenant_id=tenant_id,
        customer_id=payment.customer_id,
        amount=_money(-payment.amount),
        updated_at=posted_at,
    )
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="customer_payments.post",
        entity_type="customer_payment",
        entity_id=payment.id,
        before_json=before,
        after_json=_payment_loggable(payment)
        | {
            "customer_ledger_entry_id": str(ledger_entry.id),
            "posted_allocations": posted_allocations,
            "unapplied_amount": str(_money(payment.amount - sum_allocations(allocations))),
        },
    )
    if commit:
        await db.commit()
    return payment


async def reverse_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    reason: str,
    *,
    actor_user_id: uuid.UUID,
) -> CustomerPayment:
    try:
        payment = await _reverse_payment_atomically(
            db,
            tenant_id,
            customer_payment_id,
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
    customer_payment_id: uuid.UUID,
    reason: str,
    *,
    actor_user_id: uuid.UUID,
) -> CustomerPayment:
    payment = await _get_existing_payment(db, tenant_id, customer_payment_id, for_update=True)
    if payment.status != DocumentStatus.POSTED:
        raise CustomerPaymentNotReversible()

    before = _payment_loggable(payment)
    reversed_at = datetime.now(UTC)
    allocations = await _payment_allocations(db, tenant_id, payment.id)
    reversed_allocations: list[dict[str, str]] = []
    for allocation in allocations:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation.sales_invoice_id,
            payment.customer_id,
            for_update=True,
        )
        invoice.paid_amount = _money(invoice.paid_amount - allocation.allocated_amount)
        invoice.balance_amount = _money(invoice.total_amount - invoice.paid_amount)
        reversed_allocations.append(
            {
                "allocation_id": str(allocation.id),
                "sales_invoice_id": str(invoice.id),
                "allocated_amount": str(allocation.allocated_amount),
            }
        )

    payment.status = DocumentStatus.REVERSED
    payment.reversed_at = reversed_at
    payment.reversed_by = actor_user_id
    payment.reversal_reason = reason
    ledger_entry = CustomerLedgerEntry(
        tenant_id=tenant_id,
        customer_id=payment.customer_id,
        entry_type=CustomerLedgerEntryType.REVERSAL,
        debit_amount=_money(payment.amount),
        credit_amount=_money(ZERO),
        balance_effect=_money(payment.amount),
        source_type=SourceType.CUSTOMER_PAYMENT,
        source_id=payment.id,
        posted_at=reversed_at,
        posted_by=actor_user_id,
    )
    db.add(ledger_entry)
    await db.flush()
    await _apply_customer_balance_effect(
        db,
        tenant_id=tenant_id,
        customer_id=payment.customer_id,
        amount=_money(payment.amount),
        updated_at=reversed_at,
    )
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="customer_payments.reverse",
        entity_type="customer_payment",
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
    customer_payment_id: uuid.UUID,
    data: CustomerPaymentAllocationCreate,
    *,
    actor_user_id: uuid.UUID,
) -> CustomerPaymentAllocation:
    payment = await _get_existing_payment(db, tenant_id, customer_payment_id, for_update=True)
    _ensure_allocation_mutable(payment)
    is_posted = payment.status == DocumentStatus.POSTED
    await _ensure_allocation_invoice_available(db, tenant_id, payment.id, data.sales_invoice_id)
    invoice = await _ensure_allocatable_invoice(
        db,
        tenant_id,
        data.sales_invoice_id,
        payment.customer_id,
        for_update=is_posted,
    )
    if data.allocated_amount > invoice.balance_amount:
        raise CustomerPaymentInvoiceOverpaid()
    allocations = await _payment_allocations(db, tenant_id, payment.id)
    if sum_allocations(allocations) + data.allocated_amount > payment.amount:
        raise CustomerPaymentOverAllocated()
    allocation = CustomerPaymentAllocation(
        tenant_id=tenant_id,
        customer_payment_id=payment.id,
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
        action="customer_payment_allocations.create",
        entity_type="customer_payment_allocation",
        entity_id=allocation.id,
        after_json=_allocation_loggable(allocation),
    )
    await db.commit()
    await db.refresh(allocation)
    return allocation


async def update_allocation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
    data: CustomerPaymentAllocationUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> CustomerPaymentAllocation:
    try:
        allocation = await _update_allocation_atomically(
            db,
            tenant_id,
            customer_payment_id,
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
    customer_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
    data: CustomerPaymentAllocationUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> CustomerPaymentAllocation:
    payment = await _get_existing_payment(db, tenant_id, customer_payment_id, for_update=True)
    _ensure_allocation_mutable(payment)
    is_posted = payment.status == DocumentStatus.POSTED
    allocation = await _get_existing_allocation(db, tenant_id, customer_payment_id, allocation_id)
    before = _allocation_loggable(allocation)
    old_invoice_id = allocation.sales_invoice_id
    old_allocated_amount = allocation.allocated_amount
    fields = data.model_dump(exclude_unset=True)
    new_invoice_id = fields.get("sales_invoice_id", old_invoice_id)
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
            payment.customer_id,
            for_update=True,
        )
        old_invoice.paid_amount = _money(old_invoice.paid_amount - old_allocated_amount)
        old_invoice.balance_amount = _money(old_invoice.total_amount - old_invoice.paid_amount)

    if invoice_changed:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            new_invoice_id,
            payment.customer_id,
            for_update=is_posted,
        )
    elif old_invoice is not None:
        invoice = old_invoice
    else:
        invoice = await _ensure_allocatable_invoice(
            db, tenant_id, new_invoice_id, payment.customer_id
        )

    if new_allocated_amount > invoice.balance_amount:
        raise CustomerPaymentInvoiceOverpaid()
    allocations = await _payment_allocations(db, tenant_id, payment.id)
    other_total = sum_allocations([item for item in allocations if item.id != allocation.id])
    if other_total + new_allocated_amount > payment.amount:
        raise CustomerPaymentOverAllocated()
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
        action="customer_payment_allocations.update",
        entity_type="customer_payment_allocation",
        entity_id=allocation.id,
        before_json=before,
        after_json=_allocation_loggable(allocation),
    )
    await db.commit()
    return allocation


async def delete_allocation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    payment = await _get_existing_payment(db, tenant_id, customer_payment_id, for_update=True)
    _ensure_allocation_mutable(payment)
    allocation = await _get_existing_allocation(db, tenant_id, customer_payment_id, allocation_id)
    before = _allocation_loggable(allocation)
    if payment.status == DocumentStatus.POSTED:
        invoice = await _ensure_allocatable_invoice(
            db,
            tenant_id,
            allocation.sales_invoice_id,
            payment.customer_id,
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
        action="customer_payment_allocations.delete",
        entity_type="customer_payment_allocation",
        entity_id=allocation.id,
        before_json=before,
    )
    await db.commit()


async def get_allocation_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
) -> CustomerPaymentAllocation | None:
    return await db.scalar(
        select(CustomerPaymentAllocation).where(
            CustomerPaymentAllocation.tenant_id == tenant_id,
            CustomerPaymentAllocation.customer_payment_id == customer_payment_id,
            CustomerPaymentAllocation.id == allocation_id,
        )
    )


async def list_allocations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    pagination: PaginationParams,
    filters: CustomerPaymentAllocationFilters,
    sort: tuple[SortSpec, ...],
) -> Page[CustomerPaymentAllocation]:
    await _get_existing_payment(db, tenant_id, customer_payment_id)
    stmt = _apply_allocation_filters(
        select(CustomerPaymentAllocation).where(
            CustomerPaymentAllocation.tenant_id == tenant_id,
            CustomerPaymentAllocation.customer_payment_id == customer_payment_id,
        ),
        filters,
    )
    stmt = apply_sort(stmt, sort, ALLOCATION_SORT_COLUMNS)
    count_stmt = _apply_allocation_filters(
        select(func.count(CustomerPaymentAllocation.id)).where(
            CustomerPaymentAllocation.tenant_id == tenant_id,
            CustomerPaymentAllocation.customer_payment_id == customer_payment_id,
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_ledger_entry_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> CustomerLedgerEntry | None:
    return await db.scalar(
        select(CustomerLedgerEntry).where(
            CustomerLedgerEntry.tenant_id == tenant_id,
            CustomerLedgerEntry.id == entry_id,
        )
    )


async def list_ledger_entries(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: CustomerLedgerEntryFilters,
    sort: tuple[SortSpec, ...],
) -> Page[CustomerLedgerEntry]:
    stmt = _apply_ledger_filters(
        select(CustomerLedgerEntry).where(CustomerLedgerEntry.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, LEDGER_SORT_COLUMNS)
    count_stmt = _apply_ledger_filters(
        select(func.count(CustomerLedgerEntry.id)).where(
            CustomerLedgerEntry.tenant_id == tenant_id
        ),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_balance_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    balance_id: uuid.UUID,
) -> CustomerBalance | None:
    return await db.scalar(
        select(CustomerBalance).where(
            CustomerBalance.tenant_id == tenant_id,
            CustomerBalance.id == balance_id,
        )
    )


async def list_balances(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: CustomerBalanceFilters,
    sort: tuple[SortSpec, ...],
) -> Page[CustomerBalance]:
    stmt = _apply_balance_filters(
        select(CustomerBalance).where(CustomerBalance.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, BALANCE_SORT_COLUMNS)
    count_stmt = _apply_balance_filters(
        select(func.count(CustomerBalance.id)).where(CustomerBalance.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def get_balance_reconciliation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    customer_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    ledger_stmt = (
        select(CustomerLedgerEntry.customer_id, func.sum(CustomerLedgerEntry.balance_effect))
        .where(CustomerLedgerEntry.tenant_id == tenant_id)
        .group_by(CustomerLedgerEntry.customer_id)
    )
    if customer_id is not None:
        ledger_stmt = ledger_stmt.where(CustomerLedgerEntry.customer_id == customer_id)
    ledger_totals = {row[0]: _money(row[1]) for row in (await db.execute(ledger_stmt)).all()}

    balance_stmt = select(CustomerBalance).where(CustomerBalance.tenant_id == tenant_id)
    if customer_id is not None:
        balance_stmt = balance_stmt.where(CustomerBalance.customer_id == customer_id)
    balances = (await db.execute(balance_stmt)).scalars().all()

    seen_customer_ids: set[uuid.UUID] = set()
    drifts: list[dict[str, Any]] = []
    for balance in balances:
        seen_customer_ids.add(balance.customer_id)
        ledger_balance = ledger_totals.get(balance.customer_id, ZERO)
        if balance.balance_amount != ledger_balance:
            drifts.append(
                {
                    "customer_id": balance.customer_id,
                    "cached_balance": balance.balance_amount,
                    "ledger_balance": ledger_balance,
                    "delta": _money(balance.balance_amount - ledger_balance),
                }
            )
    for cid, ledger_balance in ledger_totals.items():
        if cid in seen_customer_ids:
            continue
        drifts.append(
            {
                "customer_id": cid,
                "cached_balance": ZERO,
                "ledger_balance": ledger_balance,
                "delta": _money(ZERO - ledger_balance),
            }
        )
    return drifts


async def ensure_invoice_ledger_entry(
    db: AsyncSession,
    invoice: SalesInvoice,
    *,
    actor_user_id: uuid.UUID,
    posted_at: datetime,
) -> CustomerLedgerEntry | None:
    if invoice.customer_id is None:
        return None
    existing = await db.scalar(
        select(CustomerLedgerEntry).where(
            CustomerLedgerEntry.tenant_id == invoice.tenant_id,
            CustomerLedgerEntry.source_type == SourceType.SALES_INVOICE,
            CustomerLedgerEntry.source_id == invoice.id,
            CustomerLedgerEntry.entry_type == CustomerLedgerEntryType.INVOICE,
        )
    )
    if existing is not None:
        return existing
    entry = CustomerLedgerEntry(
        tenant_id=invoice.tenant_id,
        customer_id=invoice.customer_id,
        entry_type=CustomerLedgerEntryType.INVOICE,
        debit_amount=_money(invoice.total_amount),
        credit_amount=_money(ZERO),
        balance_effect=_money(invoice.total_amount),
        source_type=SourceType.SALES_INVOICE,
        source_id=invoice.id,
        posted_at=posted_at,
        posted_by=actor_user_id,
    )
    db.add(entry)
    await db.flush()
    await _apply_customer_balance_effect(
        db,
        tenant_id=invoice.tenant_id,
        customer_id=invoice.customer_id,
        amount=_money(invoice.total_amount),
        updated_at=posted_at,
    )
    return entry


async def _get_existing_payment(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> CustomerPayment:
    payment = await get_by_id(db, tenant_id, customer_payment_id, for_update=for_update)
    if payment is None:
        raise CustomerPaymentNotFound()
    return payment


async def _get_existing_allocation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    allocation_id: uuid.UUID,
) -> CustomerPaymentAllocation:
    allocation = await get_allocation_by_id(db, tenant_id, customer_payment_id, allocation_id)
    if allocation is None:
        raise CustomerPaymentAllocationNotFound()
    return allocation


def _ensure_draft(payment: CustomerPayment) -> None:
    if payment.status != DocumentStatus.DRAFT:
        raise CustomerPaymentNotDraft()


def _ensure_allocation_mutable(payment: CustomerPayment) -> None:
    if payment.status not in (DocumentStatus.DRAFT, DocumentStatus.POSTED):
        raise CustomerPaymentAllocationNotEditable()


async def _ensure_document_no_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_no: str,
    *,
    customer_payment_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(CustomerPayment).where(
            CustomerPayment.tenant_id == tenant_id,
            CustomerPayment.document_no == document_no,
        )
    )
    if existing is not None and existing.id != customer_payment_id:
        raise CustomerPaymentDocumentNoConflict()


async def _ensure_allocation_invoice_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    *,
    allocation_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(CustomerPaymentAllocation).where(
            CustomerPaymentAllocation.tenant_id == tenant_id,
            CustomerPaymentAllocation.customer_payment_id == customer_payment_id,
            CustomerPaymentAllocation.sales_invoice_id == sales_invoice_id,
        )
    )
    if existing is not None and existing.id != allocation_id:
        raise CustomerPaymentAllocationInvoiceConflict()


async def _ensure_active_customer(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> Customer:
    customer = await db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.id == customer_id,
            Customer.status == PartyStatus.ACTIVE,
        )
    )
    if customer is None:
        raise InvalidCustomerPaymentCustomer()
    return customer


async def _ensure_allocatable_invoice(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
    customer_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> SalesInvoice:
    stmt = select(SalesInvoice).where(
        SalesInvoice.tenant_id == tenant_id,
        SalesInvoice.id == sales_invoice_id,
        SalesInvoice.customer_id == customer_id,
        SalesInvoice.status == DocumentStatus.POSTED,
    )
    if for_update:
        stmt = stmt.with_for_update()
    invoice = await db.scalar(stmt)
    if invoice is None:
        raise InvalidCustomerPaymentAllocationInvoice()
    return invoice


async def _payment_allocations(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_payment_id: uuid.UUID,
) -> list[CustomerPaymentAllocation]:
    result = await db.execute(
        select(CustomerPaymentAllocation)
        .where(
            CustomerPaymentAllocation.tenant_id == tenant_id,
            CustomerPaymentAllocation.customer_payment_id == customer_payment_id,
        )
        .order_by(CustomerPaymentAllocation.id.asc())
    )
    return list(result.scalars().all())


def sum_allocations(allocations: list[CustomerPaymentAllocation]) -> Decimal:
    return _money(sum((allocation.allocated_amount for allocation in allocations), ZERO))


async def _apply_customer_balance_effect(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    amount: Decimal,
    updated_at: datetime,
) -> CustomerBalance:
    # Serialize every balance mutation for one customer, including the
    # no-cache-row-yet case where locking only customer_balances cannot
    # prevent two concurrent inserts.
    await db.scalar(
        select(Customer.id)
        .where(Customer.tenant_id == tenant_id, Customer.id == customer_id)
        .with_for_update()
    )
    balance = await db.scalar(
        select(CustomerBalance)
        .where(CustomerBalance.tenant_id == tenant_id, CustomerBalance.customer_id == customer_id)
        .with_for_update()
    )
    if balance is None:
        balance = CustomerBalance(
            tenant_id=tenant_id,
            customer_id=customer_id,
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
    filters: CustomerPaymentFilters,
) -> StmtT:
    search = search_clause([CustomerPayment.document_no, CustomerPayment.notes], filters.search)
    if search is not None:
        stmt = stmt.where(search)
    if filters.customer_id is not None:
        stmt = stmt.where(CustomerPayment.customer_id == filters.customer_id)
    if filters.payment_method is not None:
        stmt = stmt.where(CustomerPayment.payment_method == filters.payment_method)
    if filters.status is not None:
        stmt = stmt.where(CustomerPayment.status == filters.status)
    stmt = where_gte_if_not_none(stmt, CustomerPayment.payment_date, filters.payment_date_gte)
    stmt = where_lte_if_not_none(stmt, CustomerPayment.payment_date, filters.payment_date_lte)
    return stmt


def _apply_allocation_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: CustomerPaymentAllocationFilters,
) -> StmtT:
    if filters.sales_invoice_id is not None:
        stmt = stmt.where(CustomerPaymentAllocation.sales_invoice_id == filters.sales_invoice_id)
    return stmt


def _apply_ledger_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: CustomerLedgerEntryFilters,
) -> StmtT:
    if filters.customer_id is not None:
        stmt = stmt.where(CustomerLedgerEntry.customer_id == filters.customer_id)
    if filters.entry_type is not None:
        stmt = stmt.where(CustomerLedgerEntry.entry_type == filters.entry_type)
    if filters.source_type is not None:
        stmt = stmt.where(CustomerLedgerEntry.source_type == filters.source_type)
    if filters.source_id is not None:
        stmt = stmt.where(CustomerLedgerEntry.source_id == filters.source_id)
    stmt = where_gte_if_not_none(stmt, CustomerLedgerEntry.posted_at, filters.posted_at_gte)
    stmt = where_lte_if_not_none(stmt, CustomerLedgerEntry.posted_at, filters.posted_at_lte)
    return stmt


def _apply_balance_filters[StmtT: Select[Any]](
    stmt: StmtT,
    filters: CustomerBalanceFilters,
) -> StmtT:
    if filters.customer_id is not None:
        stmt = stmt.where(CustomerBalance.customer_id == filters.customer_id)
    return stmt


def _payment_loggable(payment: CustomerPayment) -> dict[str, Any]:
    return {
        "document_no": payment.document_no,
        "customer_id": str(payment.customer_id),
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


def _allocation_loggable(allocation: CustomerPaymentAllocation) -> dict[str, Any]:
    return {
        "customer_payment_id": str(allocation.customer_payment_id),
        "sales_invoice_id": str(allocation.sales_invoice_id),
        "allocated_amount": str(allocation.allocated_amount),
    }
