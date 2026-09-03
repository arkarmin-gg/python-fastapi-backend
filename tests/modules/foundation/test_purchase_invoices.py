import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import (
    DocumentStatus,
    LocationType,
    PartyStatus,
    SourceType,
    StockBatchStatus,
    StockMovementType,
    SupplierLedgerEntryType,
    SupplierType,
    UnitKind,
)
from src.modules.audit_logs.models import AuditLog
from src.modules.catalog.models import CatalogItem, ProductVariant, VariantUnit
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.purchase_invoices import service as purchase_invoice_service
from src.modules.purchase_invoices.models import PurchaseInvoice
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.supplier_payments.models import SupplierLedgerEntry
from src.modules.suppliers.models import Supplier
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


def test_purchase_invoice_by_id_stmt_can_lock_invoice_row() -> None:
    tenant_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    dialect = postgresql.dialect()

    unlocked_stmt = purchase_invoice_service._purchase_invoice_by_id_stmt(tenant_id, invoice_id)
    locked_stmt = purchase_invoice_service._purchase_invoice_by_id_stmt(
        tenant_id,
        invoice_id,
        for_update=True,
    )

    assert "FOR UPDATE" not in str(unlocked_stmt.compile(dialect=dialect))
    assert "FOR UPDATE" in str(locked_stmt.compile(dialect=dialect))


async def test_purchase_invoice_create_is_atomic_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-crud")
    other_tenant = await make_tenant(db_session, code="purchase-crud-other")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_purchase_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="pi-other-unit",
        sku="PI-OTHER",
        supplier_code="PI-OTHER-SUP",
        location_code="PI-OTHER-WH",
    )
    other_invoice = await make_purchase_invoice(
        db_session,
        tenant_id=other_tenant.id,
        supplier_id=other_setup.supplier.id,
        document_no="PI-001",
    )
    unit_two = await make_unit(db_session, code="purchase-crud-each")
    catalog_item_two = await make_catalog_item(db_session, tenant_id=tenant.id, name="Landed 2")
    product_variant_two = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=catalog_item_two.id,
        sku="LANDED-2",
        base_unit_id=unit_two.id,
    )
    variant_unit_two = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=product_variant_two.id,
        unit_id=unit_two.id,
    )
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.post(
        "/api/v1/purchase-invoices",
        json={
            "supplier_id": str(setup.supplier.id),
            "invoice_date": "2026-08-08",
            "supplier_invoice_no": "SUP-INV-1",
            "notes": "first receipt",
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "location_id": str(setup.location.id),
                    "quantity": "1.00000000",
                    "unit_cost": "1000.0000",
                    "lot_number": "LOT-A",
                },
                {
                    "line_no": 2,
                    "product_variant_id": str(product_variant_two.id),
                    "variant_unit_id": str(variant_unit_two.id),
                    "location_id": str(setup.location.id),
                    "quantity": "10.00000000",
                    "unit_cost": "100.0000",
                    "lot_number": "LOT-B",
                },
            ],
            "landed_costs": [
                {"cost_type": "transport", "amount": "200.0000", "allocation_method": "by_value"},
                {
                    "cost_type": "loading",
                    "amount": "220.0000",
                    "allocation_method": "by_base_quantity",
                },
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    invoice_id = body["id"]
    assert body["status"] == "draft"
    assert body["created_by"] == str(actor.id)
    assert body["posted_by"] is None
    assert len(body["lines"]) == 2
    assert len(body["landed_costs"]) == 2
    line_one = next(line for line in body["lines"] if line["line_no"] == 1)
    line_two = next(line for line in body["lines"] if line["line_no"] == 2)
    assert line_one["allocated_landed_cost"] == "220.0000"
    assert line_one["total_line_cost"] == "1220.0000"
    assert line_one["unit_cost_base"] == "101.66666667"
    assert line_two["allocated_landed_cost"] == "200.0000"
    assert line_two["total_line_cost"] == "1200.0000"
    assert line_two["unit_cost_base"] == "120.00000000"
    assert body["subtotal_amount"] == "2000.0000"
    assert body["landed_cost_amount"] == "420.0000"
    assert body["total_amount"] == "2420.0000"

    assert not (
        (
            await db_session.execute(
                select(StockBatch).where(
                    StockBatch.tenant_id == tenant.id,
                    StockBatch.source_id == uuid.UUID(invoice_id),
                )
            )
        )
        .scalars()
        .all()
    )

    post_response = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/post",
        headers=headers,
    )
    assert post_response.status_code == 200
    body = post_response.json()
    assert body["status"] == "posted"
    assert body["posted_by"] == str(actor.id)
    assert body["posted_by_name"] == "Test User"
    line_one = next(line for line in body["lines"] if line["line_no"] == 1)

    listed = await client.get(
        (
            "/api/v1/purchase-invoices"
            "?search=SUP-INV"
            f"&supplier_id={setup.supplier.id}"
            f"&location_id={setup.location.id}"
            "&status=posted"
            "&invoice_date_gte=2026-08-08"
            "&invoice_date_lte=2026-08-08"
            "&sort=invoice_date,document_no,id"
        ),
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [invoice_id]

    fetched = await client.get(f"/api/v1/purchase-invoices/{invoice_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert len(fetched.json()["lines"]) == 2

    not_found = await client.get(f"/api/v1/purchase-invoices/{other_invoice.id}", headers=headers)
    assert not_found.status_code == 404

    fetched_line = await client.get(
        f"/api/v1/purchase-invoices/{invoice_id}/lines/{line_one['id']}",
        headers=headers,
    )
    assert fetched_line.status_code == 200

    fetched_cost = await client.get(
        f"/api/v1/purchase-invoices/{invoice_id}/landed-costs/{body['landed_costs'][0]['id']}",
        headers=headers,
    )
    assert fetched_cost.status_code == 200

    batches = (
        (
            await db_session.execute(
                select(StockBatch).where(
                    StockBatch.tenant_id == tenant.id,
                    StockBatch.source_id == uuid.UUID(invoice_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(batches) == 2
    assert {batch.status for batch in batches} == {StockBatchStatus.ACTIVE}
    assert all(batch.source_type == SourceType.PURCHASE_INVOICE for batch in batches)

    movements = (
        (
            await db_session.execute(
                select(StockMovement).where(
                    StockMovement.tenant_id == tenant.id,
                    StockMovement.source_id == uuid.UUID(invoice_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert [movement.movement_type for movement in movements] == [
        StockMovementType.PURCHASE_RECEIVE,
        StockMovementType.PURCHASE_RECEIVE,
    ]

    balances = (
        (
            await db_session.execute(
                select(StockBalance).where(
                    StockBalance.tenant_id == tenant.id,
                    StockBalance.location_id == setup.location.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(balance.quantity_base for balance in balances) == [
        Decimal("10.00000000"),
        Decimal("12.00000000"),
    ]

    ledger_entry = await db_session.scalar(
        select(SupplierLedgerEntry).where(
            SupplierLedgerEntry.tenant_id == tenant.id,
            SupplierLedgerEntry.source_type == SourceType.PURCHASE_INVOICE,
            SupplierLedgerEntry.source_id == uuid.UUID(invoice_id),
        )
    )
    assert ledger_entry is not None
    assert ledger_entry.entry_type == SupplierLedgerEntryType.INVOICE
    assert ledger_entry.credit_amount == Decimal("2420.0000")

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == uuid.UUID(invoice_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert Counter(actions) == Counter(["purchase_invoices.create", "purchase_invoices.post"])
    assert other_setup.supplier.tenant_id == other_tenant.id


async def test_purchase_invoice_duplicate_document_no_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-doc-conflict")
    other_tenant = await make_tenant(db_session, code="purchase-doc-other")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_purchase_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="doc-other-unit",
        sku="DOC-OTHER",
        supplier_code="DOC-OTHER-SUP",
        location_code="DOC-OTHER-WH",
    )
    await make_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-DUP",
    )
    cross_tenant = await make_purchase_invoice(
        db_session,
        tenant_id=other_tenant.id,
        supplier_id=other_setup.supplier.id,
        document_no="PI-DUP",
    )
    actor = await make_purchase_actor(db_session, tenant=tenant)

    duplicate = await client.post(
        "/api/v1/purchase-invoices",
        json=invoice_body(setup, document_no="PI-DUP"),
        headers=auth_headers(user_access_token(actor)),
    )

    assert duplicate.status_code == 201
    assert duplicate.json()["document_no"].startswith("PI-202608-")
    assert cross_tenant.tenant_id == other_tenant.id


async def test_purchase_invoice_rejects_invalid_references_and_rolls_back(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-invalid-refs")
    tenant_id = tenant.id
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    inactive_supplier = await make_supplier(
        db_session,
        tenant_id=tenant.id,
        code="INACTIVE-SUP",
        status=PartyStatus.INACTIVE,
    )
    inactive_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="INACTIVE-WH",
        is_active=False,
    )
    inactive_catalog_item = await make_catalog_item(
        db_session, tenant_id=tenant.id, name="Purchase Inactive"
    )
    inactive_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=inactive_catalog_item.id,
        sku="PURCHASE-INACTIVE",
        base_unit_id=setup.unit.id,
        is_active=False,
    )
    other_unit = await make_unit(db_session, code="line-invalid-other")
    invalid_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_id=other_unit.id,
        is_base_unit=False,
        is_purchase_unit=False,
    )
    actor = await make_purchase_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    invalid_supplier_body = invoice_body(
        setup, document_no="PI-REF-1", overrides={"supplier_id": str(inactive_supplier.id)}
    )
    invalid_location_body = invoice_body(
        setup,
        document_no="PI-REF-2",
        line_overrides={"location_id": str(inactive_location.id)},
    )
    invalid_product_body = invoice_body(
        setup,
        document_no="PI-REF-3",
        line_overrides={"product_variant_id": str(inactive_variant.id)},
    )
    invalid_unit_body = invoice_body(
        setup,
        document_no="PI-REF-4",
        line_overrides={"variant_unit_id": str(invalid_variant_unit.id)},
    )
    manual_allocation_body = invoice_body(
        setup,
        document_no="PI-REF-5",
        landed_costs=[{"cost_type": "other", "amount": "1.0000", "allocation_method": "manual"}],
    )

    invalid_supplier = await client.post(
        "/api/v1/purchase-invoices", json=invalid_supplier_body, headers=headers
    )
    invalid_location = await client.post(
        "/api/v1/purchase-invoices", json=invalid_location_body, headers=headers
    )
    invalid_product = await client.post(
        "/api/v1/purchase-invoices", json=invalid_product_body, headers=headers
    )
    invalid_unit = await client.post(
        "/api/v1/purchase-invoices", json=invalid_unit_body, headers=headers
    )
    manual_allocation = await client.post(
        "/api/v1/purchase-invoices", json=manual_allocation_body, headers=headers
    )

    assert invalid_supplier.status_code == 400
    assert invalid_supplier.json()["error_code"] == "invalid_purchase_invoice_supplier"
    assert invalid_location.status_code == 400
    assert invalid_location.json()["error_code"] == "invalid_purchase_invoice_location"
    assert invalid_product.status_code == 400
    assert invalid_product.json()["error_code"] == "invalid_purchase_invoice_line_product"
    assert invalid_unit.status_code == 400
    assert invalid_unit.json()["error_code"] == "invalid_purchase_invoice_line_unit"
    assert manual_allocation.status_code == 400
    assert manual_allocation.json()["error_code"] == "invalid_purchase_landed_cost_allocation"

    persisted = (
        (
            await db_session.execute(
                select(PurchaseInvoice).where(PurchaseInvoice.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert persisted == []


async def test_purchase_invoice_rejects_post_without_lines_and_duplicate_line_numbers(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-empty-dup")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    duplicate_lines = [
        line_payload(setup, line_no=1, lot_number="LOT-X"),
        line_payload(setup, line_no=1, lot_number="LOT-Y"),
    ]
    duplicate_body = invoice_body(
        setup,
        document_no="PI-DUP-LINE",
        lines=duplicate_lines,
    )
    await db_session.commit()

    draft = await client.post(
        "/api/v1/purchase-invoices",
        json={
            "supplier_id": str(setup.supplier.id),
            "invoice_date": "2026-08-08",
            "lines": [],
        },
        headers=headers,
    )
    assert draft.status_code == 201
    empty_post = await client.post(
        f"/api/v1/purchase-invoices/{draft.json()['id']}/post",
        headers=headers,
    )
    assert empty_post.status_code == 400
    assert empty_post.json()["error_code"] == "purchase_invoice_has_no_lines"

    duplicate_line_no = await client.post(
        "/api/v1/purchase-invoices",
        json=duplicate_body,
        headers=headers,
    )
    assert duplicate_line_no.status_code == 422


async def test_purchase_invoice_rejects_unpostable_lines_atomically(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-post-invalid")
    tenant_id = tenant.id
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    expiry_catalog_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Expiry")
    expiry_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=expiry_catalog_item.id,
        sku="POST-EXPIRY",
        base_unit_id=setup.unit.id,
        track_expiry=True,
    )
    expiry_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=expiry_variant.id,
        unit_id=setup.unit.id,
    )
    service_catalog_item = await make_catalog_item(db_session, tenant_id=tenant.id, name="Service")
    service_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=service_catalog_item.id,
        sku="POST-SERVICE",
        base_unit_id=setup.unit.id,
        track_inventory=False,
    )
    service_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=service_variant.id,
        unit_id=setup.unit.id,
    )
    actor = await make_purchase_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    no_lot_body = invoice_body(setup, document_no="PI-NO-LOT", line_overrides={"lot_number": None})
    no_expiry_body = invoice_body(
        setup,
        document_no="PI-NO-EXPIRY",
        line_overrides={
            "product_variant_id": str(expiry_variant.id),
            "variant_unit_id": str(expiry_variant_unit.id),
            "lot_number": "LOT-NO-EXPIRY",
        },
    )
    service_body = invoice_body(
        setup,
        document_no="PI-SERVICE",
        line_overrides={
            "product_variant_id": str(service_variant.id),
            "variant_unit_id": str(service_variant_unit.id),
            "lot_number": "LOT-SERVICE",
        },
    )

    no_lot_draft = await client.post("/api/v1/purchase-invoices", json=no_lot_body, headers=headers)
    no_expiry_draft = await client.post(
        "/api/v1/purchase-invoices", json=no_expiry_body, headers=headers
    )
    service_draft = await client.post(
        "/api/v1/purchase-invoices", json=service_body, headers=headers
    )

    assert no_lot_draft.status_code == 201
    assert no_lot_draft.json()["lines"][0]["lot_number"] == "LOT-202608-000001"
    assert no_expiry_draft.status_code == 201
    assert service_draft.status_code == 201
    no_lot_response = await client.post(
        f"/api/v1/purchase-invoices/{no_lot_draft.json()['id']}/post",
        headers=headers,
    )
    no_expiry_response = await client.post(
        f"/api/v1/purchase-invoices/{no_expiry_draft.json()['id']}/post",
        headers=headers,
    )
    service_response = await client.post(
        f"/api/v1/purchase-invoices/{service_draft.json()['id']}/post",
        headers=headers,
    )

    assert no_lot_response.status_code == 200
    assert no_expiry_response.status_code == 400
    assert no_expiry_response.json()["error_code"] == "purchase_invoice_line_missing_expiry_date"
    assert service_response.status_code == 400
    assert service_response.json()["error_code"] == (
        "purchase_invoice_line_product_not_inventory_tracked"
    )

    persisted = (
        (
            await db_session.execute(
                select(PurchaseInvoice).where(PurchaseInvoice.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert {invoice.document_no for invoice in persisted} == {
        "PI-202608-000001",
        "PI-202608-000002",
        "PI-202608-000003",
    }
    assert {invoice.status for invoice in persisted} == {
        DocumentStatus.DRAFT,
        DocumentStatus.POSTED,
    }
    movements = (
        (
            await db_session.execute(
                select(StockMovement).where(StockMovement.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(movements) == 1


async def test_purchase_invoice_posted_documents_reject_draft_mutations(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-gone")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    invoice = await make_purchase_invoice(
        db_session,
        tenant_id=tenant.id,
        supplier_id=setup.supplier.id,
        document_no="PI-GONE",
        status=DocumentStatus.POSTED,
    )
    invoice_id = invoice.id
    line_body = line_payload(setup, lot_number="LOT-Z")
    landed_cost_body = {"cost_type": "transport", "amount": "100.0000"}
    await db_session.commit()

    assert (
        await client.patch(
            f"/api/v1/purchase-invoices/{invoice_id}",
            json={"notes": "nope"},
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.delete(f"/api/v1/purchase-invoices/{invoice_id}", headers=headers)
    ).status_code == 400
    repost = await client.post(f"/api/v1/purchase-invoices/{invoice_id}/post", headers=headers)
    assert repost.status_code == 400
    assert repost.json()["error_code"] == "purchase_invoice_not_postable"
    assert (
        await client.post(
            f"/api/v1/purchase-invoices/{invoice_id}/lines",
            json=line_body,
            headers=headers,
        )
    ).status_code == 400
    assert (
        await client.post(
            f"/api/v1/purchase-invoices/{invoice_id}/landed-costs",
            json=landed_cost_body,
            headers=headers,
        )
    ).status_code == 400


async def test_purchase_invoice_draft_header_child_crud_and_cancel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-workflow")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    create_response = await client.post(
        "/api/v1/purchase-invoices",
        json=invoice_body(setup, document_no="PI-WF", lines=[], landed_costs=[]),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/purchase-invoices/{invoice_id}",
        json={"supplier_invoice_no": "SUP-WF-1", "notes": "patched draft"},
        headers=headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["supplier_invoice_no"] == "SUP-WF-1"

    line_response = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/lines",
        json=line_payload(setup, quantity="2.00000000", unit_cost="100.0000"),
        headers=headers,
    )
    assert line_response.status_code == 201
    line_id = line_response.json()["id"]

    duplicate_line = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/lines",
        json=line_payload(setup, quantity="1.00000000", unit_cost="100.0000"),
        headers=headers,
    )
    assert duplicate_line.status_code == 409
    assert duplicate_line.json()["error_code"] == "purchase_invoice_line_no_conflict"

    updated_line = await client.patch(
        f"/api/v1/purchase-invoices/{invoice_id}/lines/{line_id}",
        json={"quantity": "3.00000000", "unit_cost": "120.0000"},
        headers=headers,
    )
    assert updated_line.status_code == 200
    assert updated_line.json()["line_amount"] == "360.0000"

    landed_cost_response = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/landed-costs",
        json={"cost_type": "transport", "amount": "60.0000", "allocation_method": "by_value"},
        headers=headers,
    )
    assert landed_cost_response.status_code == 201
    cost_id = landed_cost_response.json()["id"]

    updated_cost = await client.patch(
        f"/api/v1/purchase-invoices/{invoice_id}/landed-costs/{cost_id}",
        json={"amount": "30.0000"},
        headers=headers,
    )
    assert updated_cost.status_code == 200
    assert updated_cost.json()["amount"] == "30.0000"

    detail = await client.get(f"/api/v1/purchase-invoices/{invoice_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["subtotal_amount"] == "360.0000"
    assert detail.json()["landed_cost_amount"] == "30.0000"
    assert detail.json()["total_amount"] == "390.0000"

    delete_cost = await client.delete(
        f"/api/v1/purchase-invoices/{invoice_id}/landed-costs/{cost_id}",
        headers=headers,
    )
    assert delete_cost.status_code == 204
    delete_line = await client.delete(
        f"/api/v1/purchase-invoices/{invoice_id}/lines/{line_id}",
        headers=headers,
    )
    assert delete_line.status_code == 204

    cancel_response = await client.delete(
        f"/api/v1/purchase-invoices/{invoice_id}",
        headers=headers,
    )
    assert cancel_response.status_code == 204
    cancelled = await client.get(f"/api/v1/purchase-invoices/{invoice_id}", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_by"] == str(actor.id)


async def test_purchase_invoice_line_requires_measured_quantity_when_flagged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-measured-required")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    bag_unit = await make_unit(db_session, code="purchase-unit-bag")
    pack_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_id=bag_unit.id,
        conversion_to_base=Decimal("25.00000000"),
        is_base_unit=False,
        is_purchase_unit=True,
        requires_measured_quantity=True,
    )
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/purchase-invoices",
        json=invoice_body(setup, document_no="PI-MQ-REQ", lines=[], landed_costs=[]),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]

    missing_measured = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/lines",
        json=line_payload(
            setup,
            quantity="3.00000000",
            unit_cost="26840.0000",
            variant_unit_id=str(pack_unit.id),
        ),
        headers=headers,
    )
    assert missing_measured.status_code == 400
    assert (
        missing_measured.json()["error_code"] == "purchase_invoice_line_measured_quantity_required"
    )

    with_measured = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/lines",
        json=line_payload(
            setup,
            quantity="3.00000000",
            unit_cost="26840.0000",
            variant_unit_id=str(pack_unit.id),
            measured_quantity="24.40000000",
        ),
        headers=headers,
    )
    assert with_measured.status_code == 201
    body = with_measured.json()
    assert body["line_amount"] == "80520.0000"
    assert body["measured_quantity"] == "24.40000000"
    assert body["conversion_to_base"] == "24.40000000"
    assert body["quantity_base"] == "73.20000000"


async def test_purchase_invoice_line_measured_quantity_honored_when_not_required(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-measured-optional")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/purchase-invoices",
        json=invoice_body(setup, document_no="PI-MQ-OPT", lines=[], landed_costs=[]),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]

    with_measured = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/lines",
        json=line_payload(
            setup,
            quantity="2.00000000",
            unit_cost="100.0000",
            measured_quantity="19.00000000",
        ),
        headers=headers,
    )
    assert with_measured.status_code == 201
    assert with_measured.json()["measured_quantity"] == "19.00000000"
    assert with_measured.json()["conversion_to_base"] == "19.00000000"
    assert with_measured.json()["quantity_base"] == "38.00000000"

    without_measured = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/lines",
        json=line_payload(setup, line_no=2, quantity="2.00000000", unit_cost="100.0000"),
        headers=headers,
    )
    assert without_measured.status_code == 201
    assert without_measured.json()["measured_quantity"] is None
    assert without_measured.json()["quantity_base"] == "24.00000000"


async def test_purchase_invoice_lines_receive_into_per_line_locations(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-multi-loc")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    warehouse = await make_location(db_session, tenant_id=tenant.id, code="PURCHASE-WH-2")
    empty_location = await make_location(db_session, tenant_id=tenant.id, code="PURCHASE-WH-3")
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/purchase-invoices",
        json=invoice_body(
            setup,
            document_no="PI-MULTI-LOC",
            lines=[
                line_payload(setup, line_no=1, quantity="3.00000000", unit_cost="100.0000"),
                line_payload(
                    setup,
                    line_no=2,
                    quantity="10.00000000",
                    unit_cost="100.0000",
                    location_id=str(warehouse.id),
                ),
            ],
        ),
        headers=headers,
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["lines"][0]["location_id"] == str(setup.location.id)
    assert body["lines"][1]["location_id"] == str(warehouse.id)
    invoice_id = body["id"]

    posted = await client.post(f"/api/v1/purchase-invoices/{invoice_id}/post", headers=headers)
    assert posted.status_code == 200

    movements = (
        (
            await db_session.execute(
                select(StockMovement).where(
                    StockMovement.tenant_id == tenant.id,
                    StockMovement.source_id == uuid.UUID(invoice_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert {movement.location_id for movement in movements} == {setup.location.id, warehouse.id}
    movement_by_location = {movement.location_id: movement for movement in movements}
    assert movement_by_location[setup.location.id].quantity_base == Decimal("36.00000000")
    assert movement_by_location[warehouse.id].quantity_base == Decimal("120.00000000")

    balances = (
        (await db_session.execute(select(StockBalance).where(StockBalance.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert {(balance.location_id, balance.quantity_base) for balance in balances} == {
        (setup.location.id, Decimal("36.00000000")),
        (warehouse.id, Decimal("120.00000000")),
    }

    for location_id in (setup.location.id, warehouse.id):
        listed = await client.get(
            f"/api/v1/purchase-invoices?location_id={location_id}",
            headers=headers,
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [invoice_id]

    not_received = await client.get(
        f"/api/v1/purchase-invoices?location_id={empty_location.id}",
        headers=headers,
    )
    assert not_received.status_code == 200
    assert not_received.json()["items"] == []


async def test_purchase_invoice_post_rejects_inactive_line_location(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-loc-deactivated")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/purchase-invoices",
        json=invoice_body(setup, document_no="PI-LOC-GONE"),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]

    location = await db_session.scalar(
        select(Location).where(
            Location.tenant_id == tenant.id,
            Location.id == setup.location.id,
        )
    )
    assert location is not None
    location.is_active = False
    await db_session.commit()

    posted = await client.post(f"/api/v1/purchase-invoices/{invoice_id}/post", headers=headers)
    assert posted.status_code == 400
    assert posted.json()["error_code"] == "invalid_purchase_invoice_location"

    await db_session.refresh(location)
    assert location.is_active is False


async def test_purchase_invoice_update_line_requires_measured_quantity_on_unit_switch(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-measured-switch")
    setup = await make_purchase_setup(db_session, tenant_id=tenant.id)
    bag_unit = await make_unit(db_session, code="purchase-unit-bag-switch")
    pack_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_id=bag_unit.id,
        conversion_to_base=Decimal("25.00000000"),
        is_base_unit=False,
        is_purchase_unit=True,
        requires_measured_quantity=True,
    )
    actor = await make_purchase_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/purchase-invoices",
        json=invoice_body(setup, document_no="PI-MQ-SWITCH", lines=[], landed_costs=[]),
        headers=headers,
    )
    invoice_id = create_response.json()["id"]
    line_response = await client.post(
        f"/api/v1/purchase-invoices/{invoice_id}/lines",
        json=line_payload(setup, quantity="2.00000000", unit_cost="100.0000"),
        headers=headers,
    )
    line_id = line_response.json()["id"]

    switch_response = await client.patch(
        f"/api/v1/purchase-invoices/{invoice_id}/lines/{line_id}",
        json={"variant_unit_id": str(pack_unit.id)},
        headers=headers,
    )
    assert switch_response.status_code == 400
    assert (
        switch_response.json()["error_code"] == "purchase_invoice_line_measured_quantity_required"
    )

    switch_with_measured = await client.patch(
        f"/api/v1/purchase-invoices/{invoice_id}/lines/{line_id}",
        json={"variant_unit_id": str(pack_unit.id), "measured_quantity": "24.40000000"},
        headers=headers,
    )
    assert switch_with_measured.status_code == 200
    assert switch_with_measured.json()["conversion_to_base"] == "24.40000000"
    assert switch_with_measured.json()["quantity_base"] == "48.80000000"


async def test_purchase_invoice_permissions_and_seed_idempotently(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="purchase-permissions")
    forbidden_actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/purchase-invoices",
        headers=auth_headers(user_access_token(forbidden_actor)),
    )
    assert response.status_code == 403

    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)
    codes = (
        (
            await db_session.execute(
                select(Permission.code).where(Permission.module == "purchase_invoices")
            )
        )
        .scalars()
        .all()
    )
    assert sorted(codes) == [
        "purchase_invoices.create",
        "purchase_invoices.delete",
        "purchase_invoices.read",
        "purchase_invoices.update",
    ]
    inventory_codes = (
        (await db_session.execute(select(Permission.code).where(Permission.module == "inventory")))
        .scalars()
        .all()
    )
    assert sorted(inventory_codes) == [
        "inventory.create",
        "inventory.delete",
        "inventory.read",
        "inventory.update",
    ]


@dataclass
class PurchaseSetup:
    unit: Unit
    catalog_item: CatalogItem
    product_variant: ProductVariant
    variant_unit: VariantUnit
    supplier: Supplier
    location: Location


def line_payload(
    setup: "PurchaseSetup",
    *,
    line_no: int = 1,
    quantity: str = "1.00000000",
    unit_cost: str = "1000.0000",
    lot_number: str = "LOT-DEFAULT",
    **overrides: str,
) -> dict:
    payload: dict = {
        "line_no": line_no,
        "product_variant_id": str(setup.product_variant.id),
        "variant_unit_id": str(setup.variant_unit.id),
        "location_id": str(setup.location.id),
        "quantity": quantity,
        "unit_cost": unit_cost,
        "lot_number": lot_number,
    }
    payload.update(overrides)
    return payload


def invoice_body(
    setup: "PurchaseSetup",
    *,
    document_no: str,
    overrides: dict | None = None,
    line_overrides: dict | None = None,
    lines: list[dict] | None = None,
    landed_costs: list[dict] | None = None,
) -> dict:
    body: dict = {
        "supplier_id": str(setup.supplier.id),
        "invoice_date": "2026-08-08",
        "lines": lines if lines is not None else [line_payload(setup, **(line_overrides or {}))],
        "landed_costs": landed_costs if landed_costs is not None else [],
    }
    body.update(overrides or {})
    return body


async def make_purchase_setup(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    unit_code: str = "purchase-unit",
    sku: str = "PURCHASE-SKU",
    supplier_code: str = "PURCHASE-SUP",
    location_code: str = "PURCHASE-WH",
) -> PurchaseSetup:
    unit = await make_unit(db_session, code=unit_code)
    catalog_item = await make_catalog_item(db_session, tenant_id=tenant_id, name=sku.title())
    product_variant = await make_product_variant(
        db_session,
        tenant_id=tenant_id,
        catalog_item_id=catalog_item.id,
        sku=sku,
        base_unit_id=unit.id,
    )
    variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=product_variant.id,
        unit_id=unit.id,
        conversion_to_base=Decimal("12.00000000"),
    )
    supplier = await make_supplier(db_session, tenant_id=tenant_id, code=supplier_code)
    location = await make_location(db_session, tenant_id=tenant_id, code=location_code)
    return PurchaseSetup(
        unit=unit,
        catalog_item=catalog_item,
        product_variant=product_variant,
        variant_unit=variant_unit,
        supplier=supplier,
        location=location,
    )


async def make_purchase_actor(
    db_session: AsyncSession,
    *,
    tenant,
    extra_permissions: list[str] | None = None,
):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("purchase_invoices", ActionType.CREATE),
            permission("purchase_invoices", ActionType.READ),
            permission("purchase_invoices", ActionType.UPDATE),
            permission("purchase_invoices", ActionType.DELETE),
            *(extra_permissions or []),
        ],
    )


async def make_unit(db_session: AsyncSession, *, code: str) -> Unit:
    unit = Unit(code=code, name_en=code.title(), unit_kind=UnitKind.COUNT)
    db_session.add(unit)
    await db_session.flush()
    return unit


async def make_catalog_item(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    is_active: bool = True,
) -> CatalogItem:
    catalog_item = CatalogItem(
        tenant_id=tenant_id,
        code=f"ITEM-{uuid.uuid4().hex[:8]}",
        name=name,
        is_active=is_active,
    )
    db_session.add(catalog_item)
    await db_session.flush()
    return catalog_item


async def make_product_variant(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    sku: str,
    base_unit_id: uuid.UUID,
    is_active: bool = True,
    track_inventory: bool = True,
    track_batches: bool = True,
    track_expiry: bool = False,
) -> ProductVariant:
    product_variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=catalog_item_id,
        sku=sku,
        name=sku.title(),
        base_unit_id=base_unit_id,
        track_inventory=track_inventory,
        track_batches=track_batches,
        track_expiry=track_expiry,
        is_active=is_active,
    )
    db_session.add(product_variant)
    await db_session.flush()
    return product_variant


async def make_variant_unit(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    unit_id: uuid.UUID,
    conversion_to_base: Decimal = Decimal("1.00000000"),
    is_base_unit: bool = True,
    is_purchase_unit: bool = True,
    is_active: bool = True,
    requires_measured_quantity: bool = False,
) -> VariantUnit:
    variant_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        unit_id=unit_id,
        conversion_to_base=conversion_to_base,
        is_base_unit=is_base_unit,
        is_purchase_unit=is_purchase_unit,
        is_active=is_active,
        requires_measured_quantity=requires_measured_quantity,
    )
    db_session.add(variant_unit)
    await db_session.flush()
    return variant_unit


async def make_supplier(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    status: PartyStatus = PartyStatus.ACTIVE,
) -> Supplier:
    supplier = Supplier(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        supplier_type=SupplierType.LOCAL,
        status=status,
    )
    db_session.add(supplier)
    await db_session.flush()
    return supplier


async def make_location(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    is_active: bool = True,
) -> Location:
    location = Location(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        location_type=LocationType.WAREHOUSE,
        is_active=is_active,
    )
    db_session.add(location)
    await db_session.flush()
    return location


async def make_purchase_invoice(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    supplier_id: uuid.UUID,
    document_no: str = "PI-TEST",
    status: DocumentStatus = DocumentStatus.DRAFT,
) -> PurchaseInvoice:
    invoice = PurchaseInvoice(
        tenant_id=tenant_id,
        document_no=document_no,
        supplier_id=supplier_id,
        invoice_date=date(2026, 8, 8),
        status=status,
    )
    db_session.add(invoice)
    await db_session.flush()
    return invoice
