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
    DocumentStatus,
    PartyStatus,
    SourceType,
    SupplierLedgerEntryType,
)
from src.modules.audit_logs.models import AuditLog
from src.modules.purchase_invoices.models import PurchaseInvoice
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.supplier_payments import service
from src.modules.supplier_payments.exceptions import SupplierPaymentNotPostable
from src.modules.supplier_payments.models import (
    SupplierBalance,
    SupplierLedgerEntry,
    SupplierPayment,
)

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)
from tests.modules.foundation.test_purchase_invoices import (
    make_purchase_actor,
    make_purchase_setup,
)


async def test_supplier_payment_draft_then_post_is_atomic_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-crud")
    other_tenant = await make_tenant(db_session, code="supplier-payments-other")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_purchase_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="sp-other-unit",
        sku="SP-OTHER",
        supplier_code="SP-OTHER-SUP",
        location_code="SP-OTHER-WH",
    )
    other_payment = SupplierPayment(
        tenant_id=other_tenant.id,
        document_no="SP-001",
        supplier_id=other_setup.supplier.id,
        payment_date=date(2026, 8, 8),
        amount=Decimal("1000.0000"),
        status=DocumentStatus.POSTED,
    )
    db_session.add(other_payment)
    await db_session.flush()
    posted_at = datetime(2026, 8, 8, 7, 0, tzinfo=UTC)
    invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-PAID",
        total_amount=Decimal("1000.0000"),
        posted_at=posted_at,
    )
    other_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-OPEN",
        total_amount=Decimal("300.0000"),
        posted_at=posted_at,
    )
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(setup.supplier.id),
            "payment_date": "2026-08-08",
            "payment_method": "cash",
            "amount": "1200.0000",
            "notes": "cash paid to vendor",
            "allocations": [
                {"purchase_invoice_id": str(invoice.id), "allocated_amount": "800.0000"}
            ],
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
            "/api/v1/supplier-payments?search=vendor"
            f"&supplier_id={setup.supplier.id}"
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

    fetched = await client.get(f"/api/v1/supplier-payments/{payment_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert len(fetched.json()["allocations"]) == 1

    not_found = await client.get(f"/api/v1/supplier-payments/{other_payment.id}", headers=headers)
    assert not_found.status_code == 404

    allocation_id = body["allocations"][0]["id"]
    await db_session.refresh(invoice)
    await db_session.refresh(other_invoice)
    assert invoice.paid_amount == Decimal("0.0000")
    assert invoice.balance_amount == Decimal("1000.0000")
    assert other_invoice.balance_amount == Decimal("300.0000")

    fetched_allocation = await client.get(
        f"/api/v1/supplier-payments/{payment_id}/allocations/{allocation_id}",
        headers=headers,
    )
    assert fetched_allocation.status_code == 200

    posted = await client.post(f"/api/v1/supplier-payments/{payment_id}/post", headers=headers)
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
                select(SupplierLedgerEntry)
                .where(
                    SupplierLedgerEntry.tenant_id == tenant.id,
                    SupplierLedgerEntry.supplier_id == setup.supplier.id,
                )
                .order_by(
                    SupplierLedgerEntry.posted_at,
                    SupplierLedgerEntry.balance_effect.desc(),
                    SupplierLedgerEntry.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(entry.entry_type, entry.source_type, entry.balance_effect) for entry in entries] == [
        (SupplierLedgerEntryType.INVOICE, SourceType.PURCHASE_INVOICE, Decimal("1000.0000")),
        (SupplierLedgerEntryType.PAYMENT, SourceType.SUPPLIER_PAYMENT, Decimal("-1200.0000")),
    ]
    balance = await db_session.scalar(
        select(SupplierBalance).where(SupplierBalance.supplier_id == setup.supplier.id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("-200.0000")

    ledger_list = await client.get(
        (
            f"/api/v1/supplier-ledger-entries?supplier_id={setup.supplier.id}"
            "&entry_type=payment&source_type=supplier_payment&sort=posted_at,id"
        ),
        headers=headers,
    )
    assert ledger_list.status_code == 200
    assert len(ledger_list.json()["items"]) == 1
    ledger_id = ledger_list.json()["items"][0]["id"]
    ledger_get = await client.get(f"/api/v1/supplier-ledger-entries/{ledger_id}", headers=headers)
    assert ledger_get.status_code == 200

    balance_list = await client.get(
        f"/api/v1/supplier-balances?supplier_id={setup.supplier.id}&sort=supplier_id,id",
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
    assert Counter(actions) == Counter(["supplier_payments.create", "supplier_payments.post"])
    assert other_setup.supplier.tenant_id == other_tenant.id


async def test_supplier_payment_draft_header_allocation_mutation_and_cancel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-draft")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-DRAFT-MUTATE",
        total_amount=Decimal("1000.0000"),
    )
    second_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-DRAFT-SECOND",
        total_amount=Decimal("1000.0000"),
    )
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(setup.supplier.id),
            "payment_date": "2026-08-08",
            "amount": "900.0000",
        },
        headers=headers,
    )
    assert created.status_code == 201
    payment_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/supplier-payments/{payment_id}",
        json={"amount": "1000.0000"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["document_no"].startswith("SP-2026")

    allocation = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/allocations",
        json={"purchase_invoice_id": str(invoice.id), "allocated_amount": "300.0000"},
        headers=headers,
    )
    assert allocation.status_code == 201
    allocation_id = allocation.json()["id"]

    duplicate = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/allocations",
        json={"purchase_invoice_id": str(invoice.id), "allocated_amount": "100.0000"},
        headers=headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "supplier_payment_allocation_invoice_conflict"

    changed = await client.patch(
        f"/api/v1/supplier-payments/{payment_id}/allocations/{allocation_id}",
        json={
            "purchase_invoice_id": str(second_invoice.id),
            "allocated_amount": "450.0000",
        },
        headers=headers,
    )
    assert changed.status_code == 200
    assert changed.json()["purchase_invoice_id"] == str(second_invoice.id)
    assert changed.json()["allocated_amount"] == "450.0000"

    deleted = await client.delete(
        f"/api/v1/supplier-payments/{payment_id}/allocations/{allocation_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    assert (
        await client.get(
            f"/api/v1/supplier-payments/{payment_id}/allocations/{allocation_id}",
            headers=headers,
        )
    ).status_code == 404

    cancelled = await client.delete(f"/api/v1/supplier-payments/{payment_id}", headers=headers)
    assert cancelled.status_code == 204
    fetched = await client.get(f"/api/v1/supplier-payments/{payment_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "cancelled"
    assert fetched.json()["cancelled_by"] == str(actor.id)

    after_cancel = await client.patch(
        f"/api/v1/supplier-payments/{payment_id}",
        json={"notes": "too late"},
        headers=headers,
    )
    assert after_cancel.status_code == 400
    assert after_cancel.json()["error_code"] == "supplier_payment_not_draft"


async def test_supplier_payment_duplicate_document_no_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-doc-conflict")
    other_tenant = await make_tenant(db_session, code="supplier-payments-doc-other")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_purchase_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="sp-doc-other-unit",
        sku="SP-DOC-OTHER",
        supplier_code="SP-DOC-OTHER-SUP",
        location_code="SP-DOC-OTHER-WH",
    )
    db_session.add(
        SupplierPayment(
            tenant_id=tenant.id,
            document_no="SP-DUP",
            supplier_id=setup.supplier.id,
            payment_date=date(2026, 8, 8),
            amount=Decimal("1000.0000"),
        )
    )
    cross_tenant_payment = SupplierPayment(
        tenant_id=other_tenant.id,
        document_no="SP-DUP",
        supplier_id=other_setup.supplier.id,
        payment_date=date(2026, 8, 8),
        amount=Decimal("1000.0000"),
    )
    db_session.add(cross_tenant_payment)
    await db_session.flush()
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)

    duplicate = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(setup.supplier.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
        },
        headers=auth_headers(user_access_token(actor)),
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["document_no"].startswith("SP-202608-")
    assert cross_tenant_payment.tenant_id == other_tenant.id


async def test_supplier_payment_rejects_invalid_supplier_and_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-validation")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    read_only = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("supplier_payments", ActionType.READ)],
    )

    no_permission = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(setup.supplier.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
        },
        headers=auth_headers(user_access_token(read_only)),
    )
    assert no_permission.status_code == 403

    setup.supplier.status = PartyStatus.INACTIVE
    await db_session.flush()
    invalid_supplier = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(setup.supplier.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
        },
        headers=auth_headers(user_access_token(actor)),
    )
    assert invalid_supplier.status_code == 400
    assert invalid_supplier.json()["error_code"] == "invalid_supplier_payment_supplier"


async def test_supplier_payment_rejects_invalid_allocation_invoice_and_rolls_back(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-alloc-invalid")
    tenant_id = tenant.id
    other_tenant = await make_tenant(db_session, code="supplier-payments-alloc-other")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_purchase_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="sp-alloc-other-unit",
        sku="SP-ALLOC-OTHER",
        supplier_code="SP-ALLOC-OTHER-SUP",
        location_code="SP-ALLOC-OTHER-WH",
    )
    other_supplier_setup = await make_purchase_setup(
        db_session,
        tenant_id=tenant.id,
        unit_code="sp-other-supplier-unit",
        sku="SP-OTHER-SUPPLIER",
        supplier_code="SP-OTHER-SUPPLIER-SUP",
        location_code="SP-OTHER-SUPPLIER-WH",
    )
    posted_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-ALLOC",
        total_amount=Decimal("1000.0000"),
    )
    draft_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-DRAFT",
        total_amount=Decimal("1000.0000"),
        status=DocumentStatus.DRAFT,
    )
    other_tenant_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=other_tenant.id,
        supplier_id=other_setup.supplier.id,
        document_no="PI-OTHER",
        total_amount=Decimal("1000.0000"),
    )
    other_supplier_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=other_supplier_setup.supplier.id,
        document_no="PI-OTHER-SUP",
        total_amount=Decimal("1000.0000"),
    )
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    def allocation_body(document_no: str, invoice_id: uuid.UUID) -> dict:
        return {
            "supplier_id": str(setup.supplier.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
            "allocations": [
                {"purchase_invoice_id": str(invoice_id), "allocated_amount": "100.0000"}
            ],
        }

    draft_body = allocation_body("SP-BAD-INVOICE", draft_invoice.id)
    cross_tenant_body = allocation_body("SP-CROSS-TENANT", other_tenant_invoice.id)
    other_supplier_body = allocation_body("SP-OTHER-SUP-INVOICE", other_supplier_invoice.id)
    duplicate_allocation_body = {
        "supplier_id": str(setup.supplier.id),
        "payment_date": "2026-08-08",
        "amount": "500.0000",
        "allocations": [
            {"purchase_invoice_id": str(posted_invoice.id), "allocated_amount": "100.0000"},
            {"purchase_invoice_id": str(posted_invoice.id), "allocated_amount": "200.0000"},
        ],
    }

    invalid_invoice = await client.post(
        "/api/v1/supplier-payments", json=draft_body, headers=headers
    )
    cross_tenant = await client.post(
        "/api/v1/supplier-payments", json=cross_tenant_body, headers=headers
    )
    other_supplier = await client.post(
        "/api/v1/supplier-payments", json=other_supplier_body, headers=headers
    )
    duplicate_allocation = await client.post(
        "/api/v1/supplier-payments", json=duplicate_allocation_body, headers=headers
    )

    assert invalid_invoice.status_code == 400
    assert invalid_invoice.json()["error_code"] == "invalid_supplier_payment_allocation_invoice"
    assert cross_tenant.status_code == 400
    assert cross_tenant.json()["error_code"] == "invalid_supplier_payment_allocation_invoice"
    assert other_supplier.status_code == 400
    assert other_supplier.json()["error_code"] == "invalid_supplier_payment_allocation_invoice"
    assert duplicate_allocation.status_code == 422

    persisted = (
        (
            await db_session.execute(
                select(SupplierPayment).where(SupplierPayment.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert persisted == []


async def test_supplier_payment_rejects_over_allocation_and_invoice_overpayment_atomically(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-over")
    tenant_id = tenant.id
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    over_allocation_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-OVER",
        total_amount=Decimal("1000.0000"),
    )
    partially_paid_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-PARTIAL",
        total_amount=Decimal("1000.0000"),
    )
    partially_paid_invoice.balance_amount = Decimal("700.0000")
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    over_allocated_body = {
        "supplier_id": str(setup.supplier.id),
        "payment_date": "2026-08-08",
        "amount": "900.0000",
        "allocations": [
            {"purchase_invoice_id": str(over_allocation_invoice.id), "allocated_amount": "950.0000"}
        ],
    }
    overpay_body = {
        "supplier_id": str(setup.supplier.id),
        "payment_date": "2026-08-08",
        "amount": "1200.0000",
        "allocations": [
            {"purchase_invoice_id": str(partially_paid_invoice.id), "allocated_amount": "800.0000"}
        ],
    }

    over_allocated = await client.post(
        "/api/v1/supplier-payments", json=over_allocated_body, headers=headers
    )
    overpay = await client.post("/api/v1/supplier-payments", json=overpay_body, headers=headers)

    assert over_allocated.status_code == 400
    assert over_allocated.json()["error_code"] == "supplier_payment_over_allocated"
    assert overpay.status_code == 400
    assert overpay.json()["error_code"] == "supplier_payment_invoice_overpaid"

    persisted = (
        (
            await db_session.execute(
                select(SupplierPayment).where(SupplierPayment.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert persisted == []


async def test_supplier_payment_posted_documents_are_immutable(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-immutable")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-IMMUTABLE",
        total_amount=Decimal("1000.0000"),
    )
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    invoice_id = invoice.id
    created = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(setup.supplier.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
            "allocations": [
                {"purchase_invoice_id": str(invoice_id), "allocated_amount": "500.0000"}
            ],
        },
        headers=headers,
    )
    assert created.status_code == 201
    payment_id = created.json()["id"]
    immutable_post = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/post",
        headers=headers,
    )
    assert immutable_post.status_code == 200

    header_update = await client.patch(
        f"/api/v1/supplier-payments/{payment_id}",
        json={"notes": "nope"},
        headers=headers,
    )
    post_again = await client.post(f"/api/v1/supplier-payments/{payment_id}/post", headers=headers)
    cancel = await client.delete(f"/api/v1/supplier-payments/{payment_id}", headers=headers)
    # Posted payments allow allocation edits (advance-credit application, see the
    # dedicated posted-allocation test below) but re-allocating the SAME invoice
    # a posted payment already covers still conflicts.
    allocation_create = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/allocations",
        json={"purchase_invoice_id": str(invoice_id), "allocated_amount": "1.0000"},
        headers=headers,
    )

    assert header_update.status_code == 400
    assert header_update.json()["error_code"] == "supplier_payment_not_draft"
    assert post_again.status_code == 400
    assert post_again.json()["error_code"] == "supplier_payment_not_postable"
    assert cancel.status_code == 400
    assert cancel.json()["error_code"] == "supplier_payment_not_cancellable"
    assert allocation_create.status_code == 409
    assert allocation_create.json()["error_code"] == "supplier_payment_allocation_invoice_conflict"


async def test_supplier_payment_allocations_editable_while_posted(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-posted-alloc")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-POSTED-ALLOC",
        total_amount=Decimal("1000.0000"),
    )
    second_invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-POSTED-ALLOC-2",
        total_amount=Decimal("1000.0000"),
    )
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(setup.supplier.id),
            "payment_date": "2026-08-08",
            "amount": "500.0000",
            "allocations": [
                {"purchase_invoice_id": str(invoice.id), "allocated_amount": "300.0000"}
            ],
        },
        headers=headers,
    )
    payment_id = created.json()["id"]
    allocation_id = created.json()["allocations"][0]["id"]
    posted = await client.post(f"/api/v1/supplier-payments/{payment_id}/post", headers=headers)
    assert posted.status_code == 200

    applied = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/allocations",
        json={"purchase_invoice_id": str(second_invoice.id), "allocated_amount": "200.0000"},
        headers=headers,
    )
    assert applied.status_code == 201
    second_allocation_id = applied.json()["id"]

    await db_session.refresh(second_invoice)
    assert second_invoice.paid_amount == Decimal("200.0000")
    assert second_invoice.balance_amount == Decimal("800.0000")

    over_applied = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/allocations",
        json={"purchase_invoice_id": str(second_invoice.id), "allocated_amount": "1.0000"},
        headers=headers,
    )
    assert over_applied.status_code == 409

    updated = await client.patch(
        f"/api/v1/supplier-payments/{payment_id}/allocations/{allocation_id}",
        json={"allocated_amount": "1.0000"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["allocated_amount"] == "1.0000"
    await db_session.refresh(invoice)
    assert invoice.paid_amount == Decimal("1.0000")
    assert invoice.balance_amount == Decimal("999.0000")

    deleted = await client.delete(
        f"/api/v1/supplier-payments/{payment_id}/allocations/{second_allocation_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    await db_session.refresh(second_invoice)
    assert second_invoice.paid_amount == Decimal("0.0000")
    assert second_invoice.balance_amount == Decimal("1000.0000")


async def test_purchase_invoice_posting_creates_supplier_ledger_entry(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-purchase-ledger")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    setup.product_variant.track_batches = False
    supplier_id = setup.supplier.id
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    invoice_response = await client.post(
        "/api/v1/purchase-invoices",
        json={
            "supplier_id": str(supplier_id),
            "invoice_date": "2026-08-08",
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "location_id": str(setup.location.id),
                    "quantity": "2.00000000",
                    "unit_cost": "100.0000",
                }
            ],
        },
        headers=headers,
    )
    assert invoice_response.status_code == 201
    invoice_id = invoice_response.json()["id"]
    post_response = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/post",
        headers=headers,
    )
    assert post_response.status_code == 200

    entry = await db_session.scalar(
        select(SupplierLedgerEntry).where(
            SupplierLedgerEntry.tenant_id == tenant.id,
            SupplierLedgerEntry.source_type == SourceType.PURCHASE_INVOICE,
            SupplierLedgerEntry.source_id == uuid.UUID(invoice_id),
        )
    )
    assert entry is not None
    assert entry.entry_type == SupplierLedgerEntryType.INVOICE
    assert entry.credit_amount == Decimal("200.0000")
    assert entry.balance_effect == Decimal("200.0000")
    balance = await db_session.scalar(
        select(SupplierBalance).where(SupplierBalance.supplier_id == supplier_id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("200.0000")


async def test_supplier_payment_seed_permissions(
    db_session: AsyncSession,
) -> None:
    first = await _ensure_permissions(db_session)
    second = await _ensure_permissions(db_session)

    permission_codes = {
        code
        for (code,) in (
            await db_session.execute(
                select(Permission.code).where(Permission.module == "supplier_payments")
            )
        ).all()
    }
    assert {
        "supplier_payments.create",
        "supplier_payments.read",
        "supplier_payments.update",
        "supplier_payments.delete",
    }.issubset(permission_codes)
    assert len(first) == len(second)


async def test_supplier_payment_concurrent_post_only_applies_once(
    concurrent_sessions: tuple[AsyncSession, AsyncSession],
) -> None:
    session_a, session_b = concurrent_sessions
    tenant = await make_tenant(session_a, code="supplier-payments-race-post")
    setup = await make_purchase_setup(session_a, tenant_id=tenant.id)
    actor = await make_supplier_payment_actor(session_a, tenant=tenant)
    payment = SupplierPayment(
        tenant_id=tenant.id,
        document_no="SP-RACE",
        supplier_id=setup.supplier.id,
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
    assert isinstance(failures[0], SupplierPaymentNotPostable)

    entries = (
        (
            await session_a.execute(
                select(SupplierLedgerEntry).where(
                    SupplierLedgerEntry.tenant_id == tenant.id,
                    SupplierLedgerEntry.supplier_id == setup.supplier.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    balance = await session_a.scalar(
        select(SupplierBalance).where(SupplierBalance.supplier_id == setup.supplier.id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("-500.0000")


async def test_supplier_payment_concurrent_posted_allocations_do_not_over_apply(
    concurrent_sessions: tuple[AsyncSession, AsyncSession],
) -> None:
    session_a, session_b = concurrent_sessions
    tenant = await make_tenant(session_a, code="supplier-payments-race-alloc")
    setup = await make_purchase_setup(session_a, tenant_id=tenant.id)
    actor = await make_supplier_payment_actor(session_a, tenant=tenant)
    invoice = await make_posted_purchase_invoice(
        session_a,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-RACE-ALLOC",
        total_amount=Decimal("1000.0000"),
    )
    payment = SupplierPayment(
        tenant_id=tenant.id,
        document_no="SP-RACE-ALLOC",
        supplier_id=setup.supplier.id,
        payment_date=date(2026, 8, 8),
        amount=Decimal("300.0000"),
        status=DocumentStatus.POSTED,
        posted_at=datetime(2026, 8, 8, 6, 0, tzinfo=UTC),
        posted_by=actor.id,
    )
    session_a.add(payment)
    await session_a.commit()

    from src.modules.supplier_payments.schemas import SupplierPaymentAllocationCreate

    allocation_data = SupplierPaymentAllocationCreate(
        purchase_invoice_id=invoice.id,
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


async def test_supplier_payment_reverse_restores_ledger_and_invoice_balances(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-reverse")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    supplier_id = setup.supplier.id
    invoice = await make_posted_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=supplier_id,
        document_no="PI-REVERSE",
        total_amount=Decimal("1000.0000"),
    )
    invoice_id = invoice.id
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(supplier_id),
            "payment_date": "2026-08-08",
            "amount": "800.0000",
            "allocations": [
                {"purchase_invoice_id": str(invoice_id), "allocated_amount": "800.0000"}
            ],
        },
        headers=headers,
    )
    payment_id = created.json()["id"]
    posted = await client.post(f"/api/v1/supplier-payments/{payment_id}/post", headers=headers)
    assert posted.status_code == 200

    missing_reason = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/reverse",
        json={"reason": ""},
        headers=headers,
    )
    assert missing_reason.status_code == 422

    no_permission_user = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("supplier_payments", ActionType.READ)],
    )
    forbidden = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/reverse",
        json={"reason": "duplicate payment"},
        headers=auth_headers(user_access_token(no_permission_user)),
    )
    assert forbidden.status_code == 403

    reversed_response = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/reverse",
        json={"reason": "duplicate payment"},
        headers=headers,
    )
    assert reversed_response.status_code == 200
    body = reversed_response.json()
    assert body["status"] == "reversed"
    assert body["reversed_by"] == str(actor.id)
    assert body["reversal_reason"] == "duplicate payment"

    await db_session.refresh(invoice)
    assert invoice.paid_amount == Decimal("0.0000")
    assert invoice.balance_amount == Decimal("1000.0000")

    balance = await db_session.scalar(
        select(SupplierBalance).where(SupplierBalance.supplier_id == supplier_id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("1000.0000")

    entries = (
        (
            await db_session.execute(
                select(SupplierLedgerEntry)
                .where(
                    SupplierLedgerEntry.tenant_id == tenant.id,
                    SupplierLedgerEntry.supplier_id == supplier_id,
                )
                .order_by(SupplierLedgerEntry.posted_at, SupplierLedgerEntry.id)
            )
        )
        .scalars()
        .all()
    )
    assert [entry.entry_type for entry in entries] == [
        SupplierLedgerEntryType.INVOICE,
        SupplierLedgerEntryType.PAYMENT,
        SupplierLedgerEntryType.REVERSAL,
    ]

    already_reversed = await client.post(
        f"/api/v1/supplier-payments/{payment_id}/reverse",
        json={"reason": "second attempt"},
        headers=headers,
    )
    assert already_reversed.status_code == 400
    assert already_reversed.json()["error_code"] == "supplier_payment_not_reversible"

    draft = await client.post(
        "/api/v1/supplier-payments",
        json={
            "supplier_id": str(supplier_id),
            "payment_date": "2026-08-08",
            "amount": "100.0000",
        },
        headers=headers,
    )
    draft_reverse = await client.post(
        f"/api/v1/supplier-payments/{draft.json()['id']}/reverse",
        json={"reason": "not postable"},
        headers=headers,
    )
    assert draft_reverse.status_code == 400
    assert draft_reverse.json()["error_code"] == "supplier_payment_not_reversible"


async def test_supplier_payment_idempotency_key_prevents_duplicate_create(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-idempotency")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor)) | {"Idempotency-Key": "retry-key-1"}
    body = {
        "supplier_id": str(setup.supplier.id),
        "payment_date": "2026-08-08",
        "amount": "250.0000",
    }

    first = await client.post("/api/v1/supplier-payments", json=body, headers=headers)
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/supplier-payments",
        json=body | {"amount": "999.0000"},
        headers=headers,
    )
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["document_no"] == first.json()["document_no"]

    payments = (
        (
            await db_session.execute(
                select(SupplierPayment).where(SupplierPayment.tenant_id == tenant.id)
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
        "/api/v1/supplier-payments",
        json=body,
        headers=different_key_headers,
    )
    assert third.status_code == 201
    assert third.json()["id"] != first.json()["id"]


async def test_supplier_balance_reconciliation_detects_drift(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="supplier-payments-reconciliation")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    actor = await make_supplier_payment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    clean = await client.get(
        f"/api/v1/supplier-balances/reconciliation?supplier_id={setup.supplier.id}",
        headers=headers,
    )
    assert clean.status_code == 200
    assert clean.json() == []

    db_session.add(
        SupplierBalance(
            tenant_id=tenant.id,
            supplier_id=setup.supplier.id,
            balance_amount=Decimal("50.0000"),
            updated_at=datetime(2026, 8, 8, 6, 0, tzinfo=UTC),
        )
    )
    await db_session.commit()

    drifted = await client.get(
        f"/api/v1/supplier-balances/reconciliation?supplier_id={setup.supplier.id}",
        headers=headers,
    )
    assert drifted.status_code == 200
    [entry] = drifted.json()
    assert entry["supplier_id"] == str(setup.supplier.id)
    assert Decimal(entry["cached_balance"]) == Decimal("50.0000")
    assert Decimal(entry["ledger_balance"]) == Decimal("0.0000")
    assert Decimal(entry["delta"]) == Decimal("50.0000")


async def make_supplier_payment_actor(db_session: AsyncSession, *, tenant):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("supplier_payments", ActionType.CREATE),
            permission("supplier_payments", ActionType.READ),
            permission("supplier_payments", ActionType.UPDATE),
            permission("supplier_payments", ActionType.DELETE),
            "supplier_payments.reverse",
        ],
    )


async def make_posted_purchase_invoice(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    document_no: str,
    total_amount: Decimal,
    posted_at: datetime | None = None,
    status: DocumentStatus = DocumentStatus.POSTED,
) -> PurchaseInvoice:
    invoice = PurchaseInvoice(
        tenant_id=tenant_id,
        document_no=document_no,
        supplier_id=supplier_id,
        invoice_date=date(2026, 8, 8),
        status=status,
        subtotal_amount=total_amount,
        total_amount=total_amount,
        paid_amount=Decimal("0.0000"),
        balance_amount=total_amount,
        posted_at=posted_at or datetime(2026, 8, 8, 6, 0, tzinfo=UTC),
    )
    db_session.add(invoice)
    await db_session.flush()
    return invoice
