import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.foundation_enums import PartyStatus, PaymentMethod
from src.modules.audit_logs.service import record_audit_log
from src.modules.customer_payments import service as customer_payment_service
from src.modules.customer_payments.models import (
    CustomerBalance,
    CustomerPayment,
)
from src.modules.customer_payments.schemas import (
    CustomerPaymentAllocationCreate,
    CustomerPaymentCreate,
)
from src.modules.customers.models import Customer
from src.modules.pos_checkouts.exceptions import (
    PosCheckoutCreditLimitExceeded,
    PosCheckoutIdempotencyConflict,
    PosCheckoutTotalChanged,
)
from src.modules.pos_checkouts.models import PosCheckout
from src.modules.pos_checkouts.schemas import PosCheckoutCreate
from src.modules.sales_invoices import service as sales_invoice_service
from src.modules.sales_invoices.models import SalesInvoice, SalesInvoiceLine

ZERO = Decimal("0")
MONEY_QUANT = Decimal("0.0001")


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pos_checkout_id: uuid.UUID,
) -> PosCheckout | None:
    return await db.scalar(
        _detail_stmt().where(
            PosCheckout.tenant_id == tenant_id,
            PosCheckout.id == pos_checkout_id,
        )
    )


async def get_customer_credit(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> dict[str, uuid.UUID | Decimal | None] | None:
    customer = await db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.id == customer_id,
            Customer.status == PartyStatus.ACTIVE,
        )
    )
    if customer is None:
        return None
    balance = await db.scalar(
        select(CustomerBalance.balance_amount).where(
            CustomerBalance.tenant_id == tenant_id,
            CustomerBalance.customer_id == customer_id,
        )
    )
    balance_amount = _money(balance or ZERO)
    return {
        "customer_id": customer.id,
        "balance_amount": balance_amount,
        "credit_limit": customer.credit_limit,
        "available_credit": None
        if customer.credit_limit is None
        else _money(customer.credit_limit - balance_amount),
    }


async def get_by_sales_invoice_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    sales_invoice_id: uuid.UUID,
) -> PosCheckout | None:
    return await db.scalar(
        _detail_stmt().where(
            PosCheckout.tenant_id == tenant_id,
            PosCheckout.sales_invoice_id == sales_invoice_id,
        )
    )


async def get_by_idempotency_key(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    idempotency_key: str,
) -> PosCheckout | None:
    return await db.scalar(
        _detail_stmt().where(
            PosCheckout.tenant_id == tenant_id,
            PosCheckout.idempotency_key == idempotency_key,
        )
    )


async def create_checkout(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: PosCheckoutCreate,
    *,
    idempotency_key: str,
    actor_user_id: uuid.UUID,
) -> PosCheckout:
    request_hash = _request_hash(data)
    existing = await get_by_idempotency_key(db, tenant_id, idempotency_key)
    if existing is not None:
        _ensure_same_request(existing, request_hash)
        return existing

    try:
        checkout = await _create_checkout_atomically(
            db,
            tenant_id,
            data,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor_user_id=actor_user_id,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await get_by_idempotency_key(db, tenant_id, idempotency_key)
        if existing is None:
            raise
        _ensure_same_request(existing, request_hash)
        return existing
    except Exception:
        await db.rollback()
        raise

    detail = await get_by_id(db, tenant_id, checkout.id)
    assert detail is not None
    return detail


async def _create_checkout_atomically(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: PosCheckoutCreate,
    *,
    idempotency_key: str,
    request_hash: str,
    actor_user_id: uuid.UUID,
) -> PosCheckout:
    customer_id = data.invoice.customer_id
    assert customer_id is not None
    customer = await db.scalar(
        select(Customer)
        .where(
            Customer.tenant_id == tenant_id,
            Customer.id == customer_id,
            Customer.status == PartyStatus.ACTIVE,
        )
        .with_for_update()
    )
    if customer is None:
        # Reuse the established customer-payment vocabulary because this
        # endpoint requires the same active customer invariant.
        from src.modules.customer_payments.exceptions import InvalidCustomerPaymentCustomer

        raise InvalidCustomerPaymentCustomer()

    current_balance = await db.scalar(
        select(CustomerBalance.balance_amount).where(
            CustomerBalance.tenant_id == tenant_id,
            CustomerBalance.customer_id == customer_id,
        )
    )
    balance_before = _money(current_balance or ZERO)

    invoice = await sales_invoice_service._create_invoice_draft(
        db,
        tenant_id,
        data.invoice,
        actor_user_id=actor_user_id,
        commit=False,
    )
    authoritative_total = _money(invoice.total_amount)
    if authoritative_total != _money(data.expected_total):
        raise PosCheckoutTotalChanged(authoritative_total)
    if data.paid_now_amount > authoritative_total:
        raise PosCheckoutTotalChanged(authoritative_total)

    paid_now = _money(data.paid_now_amount)
    charged_to_account = _money(authoritative_total - paid_now)
    balance_after = _money(balance_before + charged_to_account)
    available_after = (
        None if customer.credit_limit is None else _money(customer.credit_limit - balance_after)
    )
    if available_after is not None and available_after < ZERO:
        raise PosCheckoutCreditLimitExceeded(
            available_credit=_money(customer.credit_limit - balance_before),
            charged_to_account=charged_to_account,
        )

    invoice = await sales_invoice_service._post_invoice_atomically(
        db,
        tenant_id,
        invoice.id,
        actor_user_id=actor_user_id,
        commit=False,
    )

    payment: CustomerPayment | None = None
    if paid_now > ZERO:
        assert data.payment_method is not None
        payment = await customer_payment_service._create_payment_draft(
            db,
            tenant_id,
            CustomerPaymentCreate(
                customer_id=customer_id,
                payment_date=invoice.invoice_date,
                payment_method=data.payment_method,
                amount=paid_now,
                notes=f"POS payment for {invoice.document_no}.",
                allocations=[
                    CustomerPaymentAllocationCreate(
                        sales_invoice_id=invoice.id,
                        allocated_amount=paid_now,
                    )
                ],
            ),
            actor_user_id=actor_user_id,
            commit=False,
        )
        payment = await customer_payment_service._post_payment_atomically(
            db,
            tenant_id,
            payment.id,
            actor_user_id=actor_user_id,
            commit=False,
        )

    cash_tendered = (
        _money(data.cash_tendered_amount) if data.cash_tendered_amount is not None else None
    )
    change_due = (
        _money(cash_tendered - paid_now)
        if data.payment_method == PaymentMethod.CASH and cash_tendered is not None
        else _money(ZERO)
    )
    checkout = PosCheckout(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        sales_invoice_id=invoice.id,
        customer_payment_id=payment.id if payment is not None else None,
        payment_method=data.payment_method,
        paid_now_amount=paid_now,
        cash_tendered_amount=cash_tendered,
        change_due_amount=change_due,
        charged_to_account_amount=charged_to_account,
        customer_balance_after=balance_after,
        available_credit_after=available_after,
        created_by=actor_user_id,
    )
    db.add(checkout)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="pos_checkouts.create",
        entity_type="pos_checkout",
        entity_id=checkout.id,
        after_json={
            "sales_invoice_id": str(invoice.id),
            "customer_payment_id": str(payment.id) if payment is not None else None,
            "paid_now_amount": str(paid_now),
            "charged_to_account_amount": str(charged_to_account),
            "customer_balance_after": str(balance_after),
        },
    )
    return checkout


def _detail_stmt():
    return select(PosCheckout).options(
        selectinload(PosCheckout.sales_invoice)
        .selectinload(SalesInvoice.lines)
        .selectinload(SalesInvoiceLine.locations),
        selectinload(PosCheckout.sales_invoice).selectinload(SalesInvoice.posted_by_user),
        selectinload(PosCheckout.customer_payment).selectinload(CustomerPayment.allocations),
    )


def _request_hash(data: PosCheckoutCreate) -> str:
    canonical = json.dumps(
        data.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _ensure_same_request(checkout: PosCheckout, request_hash: str) -> None:
    if checkout.request_hash != request_hash:
        raise PosCheckoutIdempotencyConflict()


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT)
