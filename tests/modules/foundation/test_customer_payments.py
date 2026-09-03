import asyncio
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import (
    CustomerLedgerEntryType,
    DocumentStatus,
    PartyStatus,
    SourceType,
)
from src.modules.audit_logs.models import AuditLog
from src.modules.customer_payments import service
from src.modules.customer_payments.exceptions import CustomerPaymentNotPostable
from src.modules.customer_payments.models import (
    CustomerBalance,
    CustomerLedgerEntry,
    CustomerPayment,
)
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.sales_invoices.models import SalesInvoice

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)
from tests.modules.foundation.test_sales_invoices import (
    make_price_rule,
    make_sales_actor,
    make_sales_setup,
)


async def test_customer_payment_draft_then_post_is_atomic_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-crud")
    other_tenant = await make_tenant(db_session, code="customer-payments-other")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_sales_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="cp-other-unit",
        sku="CP-OTHER",
        price_level_code="cp-other-price",
        customer_code="CP-OTHER-CUST",
        location_code="CP-OTHER-STORE",
    )
    other_payment = CustomerPayment(
        tenant_id=other_tenant.id,
        document_no="CP-001",
        customer_id=other_setup.customer.id,
        payment_date=date(2026, 8, 8),
        amount=Decimal("1000.0000"),
        status=DocumentStatus.POSTED,
    )
    db_session.add(other_payment)
    await db_session.flush()
    posted_at = datetime(2026, 8, 8, 7, 0, tzinfo=UTC)
    invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-PAID",
        total_amount=Decimal("1000.0000"),
        posted_at=posted_at,
    )
    other_invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-OPEN",
        total_amount=Decimal("300.0000"),
        posted_at=posted_at,
    )
    actor = await make_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(setup.customer.id),
            "payment_date": "2026-08-08",
            "payment_method": "cash",
            "amount": "1200.0000",
            "notes": "morning collection",
            "allocations": [{"sales_invoice_id": str(invoice.id), "allocated_amount": "800.0000"}],
        },
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    payment_id = body["id"]
    assert body["status"] == "draft"
    assert body["created_by"] == str(actor.id)
    assert body["posted_by"] is None
    assert len(body["allocations"]) == 1
    assert body["allocations"][0]["allocated_amount"] == "800.0000"

    listed = await client.get(
        (
            "/api/v1/customer-payments?search=morning"
            f"&customer_id={setup.customer.id}"
            "&payment_method=cash"
            "&status=draft"
            "&payment_date_gte=2026-08-08"
            "&payment_date_lte=2026-08-08"
            "&sort=payment_date,document_no,id"
        ),
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [payment_id]

    fetched = await client.get(f"/api/v1/customer-payments/{payment_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert len(fetched.json()["allocations"]) == 1

    not_found = await client.get(f"/api/v1/customer-payments/{other_payment.id}", headers=headers)
    assert not_found.status_code == 404

    allocation_id = body["allocations"][0]["id"]
    await db_session.refresh(invoice)
    await db_session.refresh(other_invoice)
    assert invoice.paid_amount == Decimal("0.0000")
    assert invoice.balance_amount == Decimal("1000.0000")
    assert other_invoice.balance_amount == Decimal("300.0000")

    fetched_allocation = await client.get(
        f"/api/v1/customer-payments/{payment_id}/allocations/{allocation_id}",
        headers=headers,
    )
    assert fetched_allocation.status_code == 200

    posted = await client.post(f"/api/v1/customer-payments/{payment_id}/post", headers=headers)
    assert posted.status_code == 200
    assert posted.json()["status"] == "posted"
    assert posted.json()["posted_by"] == str(actor.id)

    await db_session.refresh(invoice)
    await db_session.refresh(other_invoice)
    assert invoice.paid_amount == Decimal("800.0000")
    assert invoice.balance_amount == Decimal("200.0000")
    assert other_invoice.balance_amount == Decimal("300.0000")

    entries = (
        (
            await db_session.execute(
                select(CustomerLedgerEntry)
                .where(
                    CustomerLedgerEntry.tenant_id == tenant.id,
                    CustomerLedgerEntry.customer_id == setup.customer.id,
                )
                .order_by(
                    CustomerLedgerEntry.posted_at,
                    CustomerLedgerEntry.balance_effect.desc(),
                    CustomerLedgerEntry.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(entry.entry_type, entry.source_type, entry.balance_effect) for entry in entries] == [
        (CustomerLedgerEntryType.INVOICE, SourceType.SALES_INVOICE, Decimal("1000.0000")),
        (CustomerLedgerEntryType.PAYMENT, SourceType.CUSTOMER_PAYMENT, Decimal("-1200.0000")),
    ]
    balance = await db_session.scalar(
        select(CustomerBalance).where(CustomerBalance.customer_id == setup.customer.id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("-200.0000")

    ledger_list = await client.get(
        (
            f"/api/v1/customer-ledger-entries?customer_id={setup.customer.id}"
            "&entry_type=payment&source_type=customer_payment&sort=posted_at,id"
        ),
        headers=headers,
    )
    assert ledger_list.status_code == 200
    assert len(ledger_list.json()["items"]) == 1
    ledger_id = ledger_list.json()["items"][0]["id"]
    ledger_get = await client.get(f"/api/v1/customer-ledger-entries/{ledger_id}", headers=headers)
    assert ledger_get.status_code == 200

    balance_list = await client.get(
        f"/api/v1/customer-balances?customer_id={setup.customer.id}&sort=customer_id,id",
        headers=headers,
    )
    assert balance_list.status_code == 200
    assert Decimal(balance_list.json()["items"][0]["balance_amount"]) == Decimal("-200.0000")

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == uuid.UUID(payment_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert Counter(actions) == Counter(["customer_payments.create", "customer_payments.post"])
    assert other_setup.customer.tenant_id == other_tenant.id


async def test_customer_payment_draft_header_allocation_mutation_and_cancel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-draft")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-DRAFT-MUTATE",
        total_amount=Decimal("1000.0000"),
    )
    second_invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-DRAFT-SECOND",
        total_amount=Decimal("1000.0000"),
    )
    actor = await make_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(setup.customer.id),
            "payment_date": "2026-08-08",
            "amount": "900.0000",
        },
        headers=headers,
    )
    assert created.status_code == 201
    payment_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/customer-payments/{payment_id}",
        json={"amount": "1000.0000"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["document_no"].startswith("CP-2026")

    allocation = await client.post(
        f"/api/v1/customer-payments/{payment_id}/allocations",
        json={"sales_invoice_id": str(invoice.id), "allocated_amount": "300.0000"},
        headers=headers,
    )
    assert allocation.status_code == 201
    allocation_id = allocation.json()["id"]

    duplicate = await client.post(
        f"/api/v1/customer-payments/{payment_id}/allocations",
        json={"sales_invoice_id": str(invoice.id), "allocated_amount": "100.0000"},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "customer_payment_allocation_invoice_conflict"

    changed = await client.patch(
        f"/api/v1/customer-payments/{payment_id}/allocations/{allocation_id}",
        json={
            "sales_invoice_id": str(second_invoice.id),
            "allocated_amount": "450.0000",
        },
        headers=headers,
    )
    assert changed.status_code == 200
    assert changed.json()["sales_invoice_id"] == str(second_invoice.id)
    assert changed.json()["allocated_amount"] == "450.0000"

    deleted = await client.delete(
        f"/api/v1/customer-payments/{payment_id}/allocations/{allocation_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    assert (
        await client.get(
            f"/api/v1/customer-payments/{payment_id}/allocations/{allocation_id}",
            headers=headers,
        )
    ).status_code == 404

    cancelled = await client.delete(f"/api/v1/customer-payments/{payment_id}", headers=headers)
    assert cancelled.status_code == 204
    fetched = await client.get(f"/api/v1/customer-payments/{payment_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "cancelled"
    assert fetched.json()["cancelled_by"] == str(actor.id)

    after_cancel = await client.patch(
        f"/api/v1/customer-payments/{payment_id}",
        json={"notes": "too late"},
        headers=headers,
    )
    assert after_cancel.status_code == 400
    assert after_cancel.json()["error_code"] == "customer_payment_not_draft"


async def test_customer_payment_duplicate_document_no_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-doc-conflict")
    other_tenant = await make_tenant(db_session, code="customer-payments-doc-other")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_sales_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="cp-doc-other-unit",
        sku="CP-DOC-OTHER",
        price_level_code="cp-doc-other-price",
        customer_code="CP-DOC-OTHER-CUST",
        location_code="CP-DOC-OTHER-STORE",
    )
    db_session.add(
        CustomerPayment(
            tenant_id=tenant.id,
            document_no="CP-DUP",
            customer_id=setup.customer.id,
            payment_date=date(2026, 8, 8),
            amount=Decimal("1000.0000"),
        )
    )
    cross_tenant_payment = CustomerPayment(
        tenant_id=other_tenant.id,
        document_no="CP-DUP",
        customer_id=other_setup.customer.id,
        payment_date=date(2026, 8, 8),
        amount=Decimal("1000.0000"),
    )
    db_session.add(cross_tenant_payment)
    await db_session.flush()
    actor = await make_payment_actor(db_session, tenant=tenant)

    duplicate = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(setup.customer.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
        },
        headers=auth_headers(user_access_token(actor)),
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["document_no"].startswith("CP-202608-")
    assert cross_tenant_payment.tenant_id == other_tenant.id


async def test_customer_payment_rejects_invalid_customer_and_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-validation")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    actor = await make_payment_actor(db_session, tenant=tenant)
    read_only = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("customer_payments", ActionType.READ)],
    )

    no_permission = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(setup.customer.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
        },
        headers=auth_headers(user_access_token(read_only)),
    )
    assert no_permission.status_code == 403

    setup.customer.status = PartyStatus.INACTIVE
    await db_session.flush()
    invalid_customer = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(setup.customer.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
        },
        headers=auth_headers(user_access_token(actor)),
    )
    assert invalid_customer.status_code == 400
    assert invalid_customer.json()["error_code"] == "invalid_customer_payment_customer"


async def test_customer_payment_rejects_invalid_allocation_invoice_and_rolls_back(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-alloc-invalid")
    tenant_id = tenant.id
    other_tenant = await make_tenant(db_session, code="customer-payments-alloc-other")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_sales_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="cp-alloc-other-unit",
        sku="CP-ALLOC-OTHER",
        price_level_code="cp-alloc-other-price",
        customer_code="CP-ALLOC-OTHER-CUST",
        location_code="CP-ALLOC-OTHER-STORE",
    )
    posted_invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-ALLOC",
        total_amount=Decimal("1000.0000"),
    )
    draft_invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-DRAFT",
        total_amount=Decimal("1000.0000"),
        status=DocumentStatus.DRAFT,
    )
    other_tenant_invoice = await make_posted_invoice(
        db_session,
        tenant_id=other_tenant.id,
        customer_id=other_setup.customer.id,
        location_id=other_setup.location.id,
        price_level_id=other_setup.price_level.id,
        document_no="SI-OTHER",
        total_amount=Decimal("1000.0000"),
    )
    actor = await make_payment_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    invalid_invoice_body = {
        "customer_id": str(setup.customer.id),
        "payment_date": "2026-08-08",
        "amount": "500.0000",
        "allocations": [
            {"sales_invoice_id": str(draft_invoice.id), "allocated_amount": "100.0000"}
        ],
    }
    cross_tenant_body = {
        "customer_id": str(setup.customer.id),
        "payment_date": "2026-08-08",
        "amount": "500.0000",
        "allocations": [
            {"sales_invoice_id": str(other_tenant_invoice.id), "allocated_amount": "100.0000"}
        ],
    }
    duplicate_allocation_body = {
        "customer_id": str(setup.customer.id),
        "payment_date": "2026-08-08",
        "amount": "500.0000",
        "allocations": [
            {"sales_invoice_id": str(posted_invoice.id), "allocated_amount": "100.0000"},
            {"sales_invoice_id": str(posted_invoice.id), "allocated_amount": "200.0000"},
        ],
    }

    invalid_invoice = await client.post(
        "/api/v1/customer-payments", json=invalid_invoice_body, headers=headers
    )
    cross_tenant = await client.post(
        "/api/v1/customer-payments", json=cross_tenant_body, headers=headers
    )
    duplicate_allocation = await client.post(
        "/api/v1/customer-payments", json=duplicate_allocation_body, headers=headers
    )

    assert invalid_invoice.status_code == 400
    assert invalid_invoice.json()["error_code"] == "invalid_customer_payment_allocation_invoice"
    assert cross_tenant.status_code == 400
    assert cross_tenant.json()["error_code"] == "invalid_customer_payment_allocation_invoice"
    assert duplicate_allocation.status_code == 422

    persisted = (
        (
            await db_session.execute(
                select(CustomerPayment).where(CustomerPayment.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert persisted == []


async def test_customer_payment_rejects_over_allocation_and_invoice_overpayment_atomically(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-over")
    tenant_id = tenant.id
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    over_allocation_invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-OVER",
        total_amount=Decimal("1000.0000"),
    )
    partially_paid_invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-PARTIAL",
        total_amount=Decimal("1000.0000"),
    )
    partially_paid_invoice.balance_amount = Decimal("700.0000")
    actor = await make_payment_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    over_allocated_body = {
        "customer_id": str(setup.customer.id),
        "payment_date": "2026-08-08",
        "amount": "900.0000",
        "allocations": [
            {"sales_invoice_id": str(over_allocation_invoice.id), "allocated_amount": "950.0000"}
        ],
    }
    overpay_body = {
        "customer_id": str(setup.customer.id),
        "payment_date": "2026-08-08",
        "amount": "1200.0000",
        "allocations": [
            {"sales_invoice_id": str(partially_paid_invoice.id), "allocated_amount": "800.0000"}
        ],
    }

    over_allocated = await client.post(
        "/api/v1/customer-payments", json=over_allocated_body, headers=headers
    )
    overpay = await client.post("/api/v1/customer-payments", json=overpay_body, headers=headers)

    assert over_allocated.status_code == 400
    assert over_allocated.json()["error_code"] == "customer_payment_over_allocated"
    assert overpay.status_code == 400
    assert overpay.json()["error_code"] == "customer_payment_invoice_overpaid"

    persisted = (
        (
            await db_session.execute(
                select(CustomerPayment).where(CustomerPayment.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert persisted == []


async def test_customer_payment_posted_documents_are_immutable(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-immutable")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-IMMUTABLE",
        total_amount=Decimal("1000.0000"),
    )
    actor = await make_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    invoice_id = invoice.id
    created = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(setup.customer.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
            "allocations": [{"sales_invoice_id": str(invoice.id), "allocated_amount": "500.0000"}],
        },
        headers=headers,
    )
    assert created.status_code == 201
    payment_id = created.json()["id"]
    immutable_post = await client.post(
        f"/api/v1/customer-payments/{payment_id}/post",
        headers=headers,
    )
    assert immutable_post.status_code == 200

    header_update = await client.patch(
        f"/api/v1/customer-payments/{payment_id}",
        json={"notes": "nope"},
        headers=headers,
    )
    post_again = await client.post(f"/api/v1/customer-payments/{payment_id}/post", headers=headers)
    cancel = await client.delete(f"/api/v1/customer-payments/{payment_id}", headers=headers)
    # Posted payments allow allocation edits (advance-credit application, see the
    # dedicated posted-allocation test below) but re-allocating the SAME invoice
    # a posted payment already covers still conflicts.
    allocation_create = await client.post(
        f"/api/v1/customer-payments/{payment_id}/allocations",
        json={"sales_invoice_id": str(invoice_id), "allocated_amount": "1.0000"},
        headers=headers,
    )

    assert header_update.status_code == 400
    assert header_update.json()["error_code"] == "customer_payment_not_draft"
    assert post_again.status_code == 400
    assert post_again.json()["error_code"] == "customer_payment_not_postable"
    assert cancel.status_code == 400
    assert cancel.json()["error_code"] == "customer_payment_not_cancellable"
    assert allocation_create.status_code == 409
    assert allocation_create.json()["error_code"] == "customer_payment_allocation_invoice_conflict"


async def test_customer_payment_allocations_editable_while_posted(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-posted-alloc")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-POSTED-ALLOC",
        total_amount=Decimal("1000.0000"),
    )
    second_invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-POSTED-ALLOC-2",
        total_amount=Decimal("1000.0000"),
    )
    actor = await make_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(setup.customer.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
            "allocations": [{"sales_invoice_id": str(invoice.id), "allocated_amount": "300.0000"}],
        },
        headers=headers,
    )
    payment_id = created.json()["id"]
    allocation_id = created.json()["allocations"][0]["id"]
    posted = await client.post(f"/api/v1/customer-payments/{payment_id}/post", headers=headers)
    assert posted.status_code == 200

    # Apply the payment's unapplied 200.0000 remainder to a second invoice.
    applied = await client.post(
        f"/api/v1/customer-payments/{payment_id}/allocations",
        json={"sales_invoice_id": str(second_invoice.id), "allocated_amount": "200.0000"},
        headers=headers,
    )
    assert applied.status_code == 201
    second_allocation_id = applied.json()["id"]

    await db_session.refresh(second_invoice)
    assert second_invoice.paid_amount == Decimal("200.0000")
    assert second_invoice.balance_amount == Decimal("800.0000")

    over_applied = await client.post(
        f"/api/v1/customer-payments/{payment_id}/allocations",
        json={"sales_invoice_id": str(second_invoice.id), "allocated_amount": "1.0000"},
        headers=headers,
    )
    assert over_applied.status_code == 409

    updated = await client.patch(
        f"/api/v1/customer-payments/{payment_id}/allocations/{allocation_id}",
        json={"allocated_amount": "1.0000"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["allocated_amount"] == "1.0000"
    await db_session.refresh(invoice)
    assert invoice.paid_amount == Decimal("1.0000")
    assert invoice.balance_amount == Decimal("999.0000")

    deleted = await client.delete(
        f"/api/v1/customer-payments/{payment_id}/allocations/{second_allocation_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    await db_session.refresh(second_invoice)
    assert second_invoice.paid_amount == Decimal("0.0000")
    assert second_invoice.balance_amount == Decimal("1000.0000")


async def test_sales_invoice_posting_creates_customer_ledger_entry(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-sales-ledger")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    setup.product_variant.track_inventory = False
    await make_price_rule(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        variant_unit_id=setup.variant_unit.id,
        price_level_id=setup.customer_price_level.id,
        customer_id=setup.customer.id,
        unit_price=Decimal("100.0000"),
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    invoice_response = await client.post(
        "/api/v1/sales-invoices",
        json={
            "customer_id": str(setup.customer.id),
            "location_id": str(setup.location.id),
            "invoice_date": "2026-08-08",
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "quantity": "2.00000000",
                }
            ],
        },
        headers=headers,
    )
    assert invoice_response.status_code == 201
    invoice_id = invoice_response.json()["id"]
    post_response = await client.post(f"/api/v1/sales-invoices/{invoice_id}/post", headers=headers)
    assert post_response.status_code == 200

    entry = await db_session.scalar(
        select(CustomerLedgerEntry).where(
            CustomerLedgerEntry.tenant_id == tenant.id,
            CustomerLedgerEntry.source_type == SourceType.SALES_INVOICE,
            CustomerLedgerEntry.source_id == uuid.UUID(invoice_id),
        )
    )
    assert entry is not None
    assert entry.entry_type == CustomerLedgerEntryType.INVOICE
    assert entry.debit_amount == Decimal("200.0000")
    balance = await db_session.scalar(
        select(CustomerBalance).where(CustomerBalance.customer_id == setup.customer.id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("200.0000")


async def test_customer_payment_seed_permissions(
    db_session: AsyncSession,
) -> None:
    first = await _ensure_permissions(db_session)
    second = await _ensure_permissions(db_session)

    permission_codes = {
        code
        for (code,) in (
            await db_session.execute(
                select(Permission.code).where(Permission.module == "customer_payments")
            )
        ).all()
    }
    assert {
        "customer_payments.create",
        "customer_payments.read",
        "customer_payments.update",
        "customer_payments.delete",
    }.issubset(permission_codes)
    assert len(first) == len(second)


async def test_customer_payment_concurrent_post_only_applies_once(
    concurrent_sessions: tuple[AsyncSession, AsyncSession],
) -> None:
    session_a, session_b = concurrent_sessions
    tenant = await make_tenant(session_a, code="customer-payments-race-post")
    setup = await make_sales_setup(session_a, tenant_id=tenant.id)
    actor = await make_payment_actor(session_a, tenant=tenant)
    payment = CustomerPayment(
        tenant_id=tenant.id,
        document_no="CP-RACE",
        customer_id=setup.customer.id,
        payment_date=date(2026, 8, 8),
        amount=Decimal("500.0000"),
        status=DocumentStatus.DRAFT,
    )
    session_a.add(payment)
    await session_a.commit()

    results = await asyncio.gather(
        service.post_payment(session_a, tenant.id, payment.id, actor_user_id=actor.id),
        service.post_payment(session_b, tenant.id, payment.id, actor_user_id=actor.id),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], CustomerPaymentNotPostable)

    entries = (
        (
            await session_a.execute(
                select(CustomerLedgerEntry).where(
                    CustomerLedgerEntry.tenant_id == tenant.id,
                    CustomerLedgerEntry.customer_id == setup.customer.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    balance = await session_a.scalar(
        select(CustomerBalance).where(CustomerBalance.customer_id == setup.customer.id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("-500.0000")


async def test_customer_payment_concurrent_posted_allocations_do_not_over_apply(
    concurrent_sessions: tuple[AsyncSession, AsyncSession],
) -> None:
    session_a, session_b = concurrent_sessions
    tenant = await make_tenant(session_a, code="customer-payments-race-alloc")
    setup = await make_sales_setup(session_a, tenant_id=tenant.id)
    actor = await make_payment_actor(session_a, tenant=tenant)
    invoice = await make_posted_invoice(
        session_a,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-RACE-ALLOC",
        total_amount=Decimal("1000.0000"),
    )
    payment = CustomerPayment(
        tenant_id=tenant.id,
        document_no="CP-RACE-ALLOC",
        customer_id=setup.customer.id,
        payment_date=date(2026, 8, 8),
        amount=Decimal("300.0000"),
        status=DocumentStatus.POSTED,
        posted_at=datetime(2026, 8, 8, 6, 0, tzinfo=UTC),
        posted_by=actor.id,
    )
    session_a.add(payment)
    await session_a.commit()

    from src.modules.customer_payments.schemas import CustomerPaymentAllocationCreate

    allocation_data = CustomerPaymentAllocationCreate(
        sales_invoice_id=invoice.id,
        allocated_amount=Decimal("300.0000"),
    )
    results = await asyncio.gather(
        service.create_allocation(
            session_a, tenant.id, payment.id, allocation_data, actor_user_id=actor.id
        ),
        service.create_allocation(
            session_b, tenant.id, payment.id, allocation_data, actor_user_id=actor.id
        ),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1

    await session_a.refresh(invoice)
    assert invoice.paid_amount == Decimal("300.0000")
    assert invoice.balance_amount == Decimal("700.0000")


async def test_customer_payment_reverse_restores_ledger_and_invoice_balances(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-reverse")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    customer_id = setup.customer.id
    invoice = await make_posted_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=customer_id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-REVERSE",
        total_amount=Decimal("1000.0000"),
    )
    invoice_id = invoice.id
    actor = await make_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(customer_id),
            "payment_date": "2026-08-08",
            "amount": "800.0000",
            "allocations": [{"sales_invoice_id": str(invoice_id), "allocated_amount": "800.0000"}],
        },
        headers=headers,
    )
    payment_id = created.json()["id"]
    posted = await client.post(f"/api/v1/customer-payments/{payment_id}/post", headers=headers)
    assert posted.status_code == 200

    missing_reason = await client.post(
        f"/api/v1/customer-payments/{payment_id}/reverse",
        json={"reason": ""},
        headers=headers,
    )
    assert missing_reason.status_code == 422

    no_permission_user = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("customer_payments", ActionType.READ)],
    )
    forbidden = await client.post(
        f"/api/v1/customer-payments/{payment_id}/reverse",
        json={"reason": "customer disputed the charge"},
        headers=auth_headers(user_access_token(no_permission_user)),
    )
    assert forbidden.status_code == 403

    reversed_response = await client.post(
        f"/api/v1/customer-payments/{payment_id}/reverse",
        json={"reason": "customer disputed the charge"},
        headers=headers,
    )
    assert reversed_response.status_code == 200
    body = reversed_response.json()
    assert body["status"] == "reversed"
    assert body["reversed_by"] == str(actor.id)
    assert body["reversal_reason"] == "customer disputed the charge"

    await db_session.refresh(invoice)
    assert invoice.paid_amount == Decimal("0.0000")
    assert invoice.balance_amount == Decimal("1000.0000")

    balance = await db_session.scalar(
        select(CustomerBalance).where(CustomerBalance.customer_id == setup.customer.id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("1000.0000")

    entries = (
        (
            await db_session.execute(
                select(CustomerLedgerEntry)
                .where(
                    CustomerLedgerEntry.tenant_id == tenant.id,
                    CustomerLedgerEntry.customer_id == setup.customer.id,
                )
                .order_by(CustomerLedgerEntry.posted_at, CustomerLedgerEntry.id)
            )
        )
        .scalars()
        .all()
    )
    assert [entry.entry_type for entry in entries] == [
        CustomerLedgerEntryType.INVOICE,
        CustomerLedgerEntryType.PAYMENT,
        CustomerLedgerEntryType.REVERSAL,
    ]

    already_reversed = await client.post(
        f"/api/v1/customer-payments/{payment_id}/reverse",
        json={"reason": "second attempt"},
        headers=headers,
    )
    assert already_reversed.status_code == 400
    assert already_reversed.json()["error_code"] == "customer_payment_not_reversible"

    draft = await client.post(
        "/api/v1/customer-payments",
        json={
            "customer_id": str(customer_id),
            "payment_date": "2026-08-08",
            "amount": "100.0000",
        },
        headers=headers,
    )
    draft_reverse = await client.post(
        f"/api/v1/customer-payments/{draft.json()['id']}/reverse",
        json={"reason": "not postable"},
        headers=headers,
    )
    assert draft_reverse.status_code == 400
    assert draft_reverse.json()["error_code"] == "customer_payment_not_reversible"


async def test_customer_payment_idempotency_key_prevents_duplicate_create(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-idempotency")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    actor = await make_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor)) | {"Idempotency-Key": "retry-key-1"}
    body = {
        "customer_id": str(setup.customer.id),
        "payment_date": "2026-08-08",
        "amount": "250.0000",
    }

    first = await client.post("/api/v1/customer-payments", json=body, headers=headers)
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/customer-payments",
        json=body | {"amount": "999.0000"},
        headers=headers,
    )
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["document_no"] == first.json()["document_no"]

    payments = (
        (
            await db_session.execute(
                select(CustomerPayment).where(CustomerPayment.tenant_id == tenant.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(payments) == 1

    different_key_headers = auth_headers(user_access_token(actor)) | {
        "Idempotency-Key": "retry-key-2"
    }
    third = await client.post(
        "/api/v1/customer-payments",
        json=body,
        headers=different_key_headers,
    )
    assert third.status_code == 201
    assert third.json()["id"] != first.json()["id"]


async def test_customer_balance_reconciliation_detects_drift(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="customer-payments-reconciliation")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    actor = await make_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    clean = await client.get(
        f"/api/v1/customer-balances/reconciliation?customer_id={setup.customer.id}",
        headers=headers,
    )
    assert clean.status_code == 200
    assert clean.json() == []

    # No ledger entries exist for this customer yet, so a cached balance row
    # with a nonzero amount is pure drift (e.g. from the race in #1 before it
    # was fixed, or a manual data patch).
    db_session.add(
        CustomerBalance(
            tenant_id=tenant.id,
            customer_id=setup.customer.id,
            balance_amount=Decimal("50.0000"),
            updated_at=datetime(2026, 8, 8, 6, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    drifted = await client.get(
        f"/api/v1/customer-balances/reconciliation?customer_id={setup.customer.id}",
        headers=headers,
    )
    assert drifted.status_code == 200
    [entry] = drifted.json()
    assert entry["customer_id"] == str(setup.customer.id)
    assert Decimal(entry["cached_balance"]) == Decimal("50.0000")
    assert Decimal(entry["ledger_balance"]) == Decimal("0.0000")
    assert Decimal(entry["delta"]) == Decimal("50.0000")


async def make_payment_actor(db_session: AsyncSession, *, tenant):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("customer_payments", ActionType.CREATE),
            permission("customer_payments", ActionType.READ),
            permission("customer_payments", ActionType.UPDATE),
            permission("customer_payments", ActionType.DELETE),
            "customer_payments.reverse",
        ],
    )


async def make_posted_invoice(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    location_id: uuid.UUID,
    price_level_id: uuid.UUID,
    document_no: str,
    total_amount: Decimal,
    posted_at: datetime | None = None,
    status: DocumentStatus = DocumentStatus.POSTED,
) -> SalesInvoice:
    invoice = SalesInvoice(
        tenant_id=tenant_id,
        document_no=document_no,
        customer_id=customer_id,
        location_id=location_id,
        price_level_id=price_level_id,
        invoice_date=date(2026, 8, 8),
        status=status,
        subtotal_amount=total_amount,
        total_amount=total_amount,
        paid_amount=Decimal("0.0000"),
        balance_amount=total_amount,
        total_cost=Decimal("0.0000"),
        gross_profit=total_amount,
        posted_at=posted_at or datetime(2026, 8, 8, 6, 0, tzinfo=UTC),
    )
    db_session.add(invoice)
    await db_session.flush()
    return invoice
