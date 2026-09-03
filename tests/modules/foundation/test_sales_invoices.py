import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import (
    CustomerLedgerEntryType,
    CustomerType,
    DocumentStatus,
    LocationType,
    PartyStatus,
    SourceType,
    StockBatchStatus,
    StockMovementType,
    UnitKind,
)
from src.modules.audit_logs.models import AuditLog
from src.modules.catalog.models import (
    CatalogItem,
    ProductVariant,
    VariantLocationSetting,
    VariantUnit,
)
from src.modules.customer_payments.models import CustomerLedgerEntry
from src.modules.customers.models import Customer
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.price_levels.models import PriceLevel
from src.modules.price_rules.models import PriceRule
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.sales_invoices.models import SalesInvoice
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_sales_invoice_draft_then_post_is_atomic_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-crud")
    other_tenant = await make_tenant(db_session, code="sales-crud-other")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_sales_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="sales-other-unit",
        sku="SALES-OTHER",
        price_level_code="other-retail",
        customer_code="OTHER-CUST",
        location_code="OTHER-STORE",
    )
    other_invoice = await make_sales_invoice(
        db_session,
        tenant_id=other_tenant.id,
        customer_id=other_setup.customer.id,
        location_id=other_setup.location.id,
        price_level_id=other_setup.price_level.id,
        document_no="SI-001",
    )
    service_catalog_item = await make_catalog_item(
        db_session, tenant_id=tenant.id, name="Sales Service"
    )
    service_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=service_catalog_item.id,
        sku="SALES-SERVICE",
        base_unit_id=setup.unit.id,
        track_inventory=False,
    )
    service_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=service_variant.id,
        unit_id=setup.unit.id,
    )
    customer_rule = await make_price_rule(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        variant_unit_id=setup.variant_unit.id,
        price_level_id=setup.price_level.id,
        customer_id=setup.customer.id,
        min_quantity=Decimal("1.00000000"),
        unit_price=Decimal("850.0000"),
    )
    first_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_cost_base=Decimal("10.00000000"),
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_cost_base=Decimal("12.00000000"),
        received_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    first_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=first_batch.id,
        quantity_base=Decimal("5.00000000"),
    )
    second_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=second_batch.id,
        quantity_base=Decimal("10.00000000"),
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.post(
        "/api/v1/sales-invoices",
        json={
            "customer_id": str(setup.customer.id),
            "location_id": str(setup.location.id),
            "price_level_id": str(setup.price_level.id),
            "invoice_date": "2026-08-08",
            "notes": "walk-in sale",
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "quantity": "8.00000000",
                },
                {
                    "line_no": 2,
                    "product_variant_id": str(service_variant.id),
                    "variant_unit_id": str(service_variant_unit.id),
                    "quantity": "1.00000000",
                    "unit_price": "50.0000",
                },
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    invoice_id = body["id"]
    assert body["status"] == "draft"
    assert body["created_by"] == str(actor.id)
    assert body["posted_by"] is None
    assert len(body["lines"]) == 2
    inventory_line = next(line for line in body["lines"] if line["line_no"] == 1)
    service_line = next(line for line in body["lines"] if line["line_no"] == 2)
    assert inventory_line["source_location_id"] == str(setup.location.id)
    assert service_line["source_location_id"] is None
    assert inventory_line["unit_price"] == "850.0000"
    assert inventory_line["price_rule_id"] == str(customer_rule.id)
    assert inventory_line["line_total"] == "6800.0000"
    assert inventory_line["total_cost"] == "0.0000"
    assert service_line["total_cost"] == "0.0000"
    assert body["subtotal_amount"] == "6850.0000"
    assert body["total_amount"] == "6850.0000"
    assert body["total_cost"] == "0.0000"
    assert body["gross_profit"] == "6850.0000"
    await db_session.refresh(first_balance)
    await db_session.refresh(second_balance)
    assert first_balance.quantity_base == Decimal("5.00000000")
    assert second_balance.quantity_base == Decimal("10.00000000")
    assert await db_session.scalar(select(func.count(StockMovement.id))) == 0

    listed = await client.get(
        (
            "/api/v1/sales-invoices"
            "?search=walk-in"
            f"&customer_id={setup.customer.id}"
            f"&location_id={setup.location.id}"
            f"&price_level_id={setup.price_level.id}"
            "&status=draft"
            "&invoice_date_gte=2026-08-08"
            "&invoice_date_lte=2026-08-08"
            "&sort=invoice_date,document_no,id"
        ),
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [invoice_id]

    fetched = await client.get(f"/api/v1/sales-invoices/{invoice_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert len(fetched.json()["lines"]) == 2

    not_found = await client.get(f"/api/v1/sales-invoices/{other_invoice.id}", headers=headers)
    assert not_found.status_code == 404

    posted = await client.post(f"/api/v1/sales-invoices/{invoice_id}/post", headers=headers)
    assert posted.status_code == 200
    posted_body = posted.json()
    assert posted_body["status"] == "posted"
    assert posted_body["posted_by"] == str(actor.id)
    assert posted_body["posted_by_name"] == "Test User"
    inventory_line = next(line for line in posted_body["lines"] if line["line_no"] == 1)
    service_line = next(line for line in posted_body["lines"] if line["line_no"] == 2)
    assert inventory_line["total_cost"] == "86.0000"
    assert service_line["total_cost"] == "0.0000"
    assert posted_body["total_cost"] == "86.0000"
    assert posted_body["gross_profit"] == "6764.0000"

    inventory_line_id = inventory_line["id"]
    costs = await client.get(
        f"/api/v1/sales-invoices/{invoice_id}/lines/{inventory_line_id}/costs?sort=stock_batch_id,id",
        headers=headers,
    )
    assert costs.status_code == 200
    cost_items = sorted(costs.json()["items"], key=lambda item: item["quantity_base"])
    assert [item["total_cost"] for item in cost_items] == ["36.0000", "50.0000"]
    fetched_cost = await client.get(
        f"/api/v1/sales-invoices/{invoice_id}/lines/{inventory_line_id}/costs/{cost_items[0]['id']}",
        headers=headers,
    )
    assert fetched_cost.status_code == 200

    service_line_id = service_line["id"]
    service_costs = await client.get(
        f"/api/v1/sales-invoices/{invoice_id}/lines/{service_line_id}/costs",
        headers=headers,
    )
    assert service_costs.status_code == 200
    assert service_costs.json()["items"] == []

    await db_session.refresh(first_balance)
    await db_session.refresh(second_balance)
    await db_session.refresh(first_batch)
    await db_session.refresh(second_batch)
    assert first_balance.quantity_base == Decimal("0E-8")
    assert second_balance.quantity_base == Decimal("7.00000000")
    assert first_batch.status == StockBatchStatus.DEPLETED
    assert second_batch.status == StockBatchStatus.ACTIVE

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
        StockMovementType.SALE_ISSUE,
        StockMovementType.SALE_ISSUE,
    ]
    assert sorted(movement.quantity_base for movement in movements) == [
        Decimal("-5.00000000"),
        Decimal("-3.00000000"),
    ]
    assert {movement.location_id for movement in movements} == {setup.location.id}

    ledger_entry = await db_session.scalar(
        select(CustomerLedgerEntry).where(
            CustomerLedgerEntry.tenant_id == tenant.id,
            CustomerLedgerEntry.source_type == SourceType.SALES_INVOICE,
            CustomerLedgerEntry.source_id == uuid.UUID(invoice_id),
        )
    )
    assert ledger_entry is not None
    assert ledger_entry.entry_type == CustomerLedgerEntryType.INVOICE
    assert ledger_entry.debit_amount == Decimal("6850.0000")

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
    assert Counter(actions) == Counter(["sales_invoices.create", "sales_invoices.post"])
    assert other_setup.customer.tenant_id == other_tenant.id


async def test_sales_invoice_duplicate_document_no_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-doc-conflict")
    other_tenant = await make_tenant(db_session, code="sales-doc-other")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_sales_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="sales-doc-other-unit",
        sku="SALES-DOC-OTHER",
        price_level_code="other-doc-retail",
        customer_code="OTHER-DOC-CUST",
        location_code="OTHER-DOC-STORE",
    )
    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-DUP",
    )
    cross_tenant = await make_sales_invoice(
        db_session,
        tenant_id=other_tenant.id,
        customer_id=other_setup.customer.id,
        location_id=other_setup.location.id,
        price_level_id=other_setup.price_level.id,
        document_no="SI-DUP",
    )
    actor = await make_sales_actor(db_session, tenant=tenant)

    response = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(
            setup,
            document_no="SI-DUP",
            line_overrides={"unit_price": "1000.0000"},
        ),
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 201, response.text
    assert response.json()["document_no"].startswith("SI-202608-")
    assert cross_tenant.tenant_id == other_tenant.id


async def test_sales_invoice_rejects_invalid_references_and_rolls_back(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-invalid")
    tenant_id = tenant.id
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    inactive_customer = await make_customer(
        db_session,
        tenant_id=tenant.id,
        code="INACTIVE-CUST",
        price_level_id=setup.price_level.id,
        status=PartyStatus.INACTIVE,
    )
    inactive_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="INACTIVE-STORE",
        is_active=False,
    )
    not_sellable_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="NOT-SELLABLE",
        is_sellable=False,
    )
    inactive_price_level = await make_price_level(
        db_session,
        tenant_id=tenant.id,
        code="inactive-price",
        is_active=False,
    )
    inactive_catalog_item = await make_catalog_item(
        db_session, tenant_id=tenant.id, name="Sales Inactive"
    )
    inactive_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=inactive_catalog_item.id,
        sku="SALES-INACTIVE",
        base_unit_id=setup.unit.id,
        is_active=False,
    )
    no_sales_unit_catalog_item = await make_catalog_item(
        db_session, tenant_id=tenant.id, name="Sales No Unit"
    )
    no_sales_unit_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=no_sales_unit_catalog_item.id,
        sku="SALES-NO-UNIT",
        base_unit_id=setup.unit.id,
    )
    no_sales_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=no_sales_unit_variant.id,
        unit_id=setup.unit.id,
        is_sales_unit=False,
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    invalid_customer_body = invoice_body(
        setup, document_no="SI-REF-1", overrides={"customer_id": str(inactive_customer.id)}
    )
    invalid_location_body = invoice_body(
        setup, document_no="SI-REF-2", overrides={"location_id": str(inactive_location.id)}
    )
    not_sellable_body = invoice_body(
        setup, document_no="SI-REF-3", overrides={"location_id": str(not_sellable_location.id)}
    )
    invalid_price_level_body = invoice_body(
        setup,
        document_no="SI-REF-4",
        overrides={"price_level_id": str(inactive_price_level.id)},
    )
    invalid_product_body = invoice_body(
        setup,
        document_no="SI-REF-5",
        line_overrides={"product_variant_id": str(inactive_variant.id)},
    )
    invalid_unit_body = invoice_body(
        setup,
        document_no="SI-REF-6",
        line_overrides={
            "product_variant_id": str(no_sales_unit_variant.id),
            "variant_unit_id": str(no_sales_variant_unit.id),
        },
    )
    missing_price_body = invoice_body(setup, document_no="SI-REF-7")
    invalid_line_discount_body = invoice_body(
        setup,
        document_no="SI-REF-8",
        line_overrides={"unit_price": "100.0000", "discount_amount": "101.0000"},
    )
    invalid_header_discount_body = invoice_body(
        setup,
        document_no="SI-REF-9",
        overrides={"discount_amount": "999999.0000"},
        line_overrides={"unit_price": "100.0000"},
    )

    invalid_customer = await client.post(
        "/api/v1/sales-invoices", json=invalid_customer_body, headers=headers
    )
    invalid_location = await client.post(
        "/api/v1/sales-invoices", json=invalid_location_body, headers=headers
    )
    not_sellable = await client.post(
        "/api/v1/sales-invoices", json=not_sellable_body, headers=headers
    )
    invalid_price_level = await client.post(
        "/api/v1/sales-invoices", json=invalid_price_level_body, headers=headers
    )
    invalid_product = await client.post(
        "/api/v1/sales-invoices", json=invalid_product_body, headers=headers
    )
    invalid_unit = await client.post(
        "/api/v1/sales-invoices", json=invalid_unit_body, headers=headers
    )
    missing_price = await client.post(
        "/api/v1/sales-invoices", json=missing_price_body, headers=headers
    )
    invalid_line_discount = await client.post(
        "/api/v1/sales-invoices", json=invalid_line_discount_body, headers=headers
    )
    invalid_header_discount = await client.post(
        "/api/v1/sales-invoices", json=invalid_header_discount_body, headers=headers
    )

    assert invalid_customer.status_code == 400
    assert invalid_customer.json()["error_code"] == "invalid_sales_invoice_customer"
    assert invalid_location.status_code == 400
    assert invalid_location.json()["error_code"] == "invalid_sales_invoice_location"
    assert not_sellable.status_code == 400
    assert not_sellable.json()["error_code"] == "invalid_sales_invoice_location"
    assert invalid_price_level.status_code == 400
    assert invalid_price_level.json()["error_code"] == "invalid_sales_invoice_price_level"
    assert invalid_product.status_code == 400
    assert invalid_product.json()["error_code"] == "invalid_sales_invoice_line_product"
    assert invalid_unit.status_code == 400
    assert invalid_unit.json()["error_code"] == "invalid_sales_invoice_line_unit"
    assert missing_price.status_code == 400
    assert missing_price.json()["error_code"] == "missing_sales_invoice_line_price"
    assert invalid_line_discount.status_code == 400
    assert invalid_line_discount.json()["error_code"] == "invalid_sales_invoice_line_discount"
    assert invalid_header_discount.status_code == 400
    assert invalid_header_discount.json()["error_code"] == "invalid_sales_invoice_discount"

    persisted = (
        (await db_session.execute(select(SalesInvoice).where(SalesInvoice.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert persisted == []


async def test_sales_invoice_rejects_insufficient_stock_atomically(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-post-short")
    tenant_id = tenant.id
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
    )
    balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=batch.id,
        quantity_base=Decimal("2.00000000"),
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(
            setup,
            document_no="SI-SHORT",
            line_overrides={"quantity": "3.00000000", "unit_price": "100.0000"},
        ),
        headers=headers,
    )
    assert created.status_code == 201
    invoice_id = created.json()["id"]

    response = await client.post(f"/api/v1/sales-invoices/{invoice_id}/post", headers=headers)
    assert response.status_code == 400
    assert response.json()["error_code"] == "sales_invoice_insufficient_stock"

    await db_session.refresh(balance)
    assert balance.quantity_base == Decimal("2.00000000")
    assert await db_session.scalar(select(func.count(StockMovement.id))) == 0
    persisted = (
        (await db_session.execute(select(SalesInvoice).where(SalesInvoice.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert len(persisted) == 1
    assert persisted[0].status == DocumentStatus.DRAFT


async def test_sales_invoice_posts_lines_from_different_source_locations(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-multi-source")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    warehouse = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="SALES-WAREHOUSE",
        is_sellable=False,
    )
    second_item = await make_catalog_item(
        db_session,
        tenant_id=tenant.id,
        name="Sales Warehouse Item",
    )
    second_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=second_item.id,
        sku="SALES-WH-SKU",
        base_unit_id=setup.unit.id,
    )
    second_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=second_variant.id,
        unit_id=setup.unit.id,
    )
    store_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_cost_base=Decimal("10.00000000"),
    )
    warehouse_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=second_variant.id,
        unit_cost_base=Decimal("20.00000000"),
    )
    store_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=store_batch.id,
        quantity_base=Decimal("4.00000000"),
    )
    warehouse_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=second_variant.id,
        location_id=warehouse.id,
        stock_batch_id=warehouse_batch.id,
        quantity_base=Decimal("6.00000000"),
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(
            setup,
            document_no="SI-MULTI-SOURCE",
            lines=[
                line_payload(
                    setup,
                    line_no=1,
                    quantity="2.00000000",
                    unit_price="100.0000",
                ),
                {
                    "line_no": 2,
                    "product_variant_id": str(second_variant.id),
                    "variant_unit_id": str(second_unit.id),
                    "locations": [{"location_id": str(warehouse.id), "quantity": "3.00000000"}],
                    "quantity": "3.00000000",
                    "unit_price": "200.0000",
                },
            ],
        ),
        headers=headers,
    )
    assert created.status_code == 201
    lines_by_no = {line["line_no"]: line for line in created.json()["lines"]}
    assert lines_by_no[1]["source_location_id"] == str(setup.location.id)
    assert lines_by_no[2]["source_location_id"] == str(warehouse.id)

    posted = await client.post(
        f"/api/v1/sales-invoices/{created.json()['id']}/post",
        headers=headers,
    )
    assert posted.status_code == 200
    posted_lines_by_no = {line["line_no"]: line for line in posted.json()["lines"]}
    assert posted_lines_by_no[1]["total_cost"] == "20.0000"
    assert posted_lines_by_no[2]["total_cost"] == "60.0000"
    assert posted.json()["total_cost"] == "80.0000"

    await db_session.refresh(store_balance)
    await db_session.refresh(warehouse_balance)
    assert store_balance.quantity_base == Decimal("2.00000000")
    assert warehouse_balance.quantity_base == Decimal("3.00000000")
    movement_locations = (
        (
            await db_session.execute(
                select(StockMovement.location_id).where(
                    StockMovement.tenant_id == tenant.id,
                    StockMovement.source_id == uuid.UUID(created.json()["id"]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(movement_locations) == {setup.location.id, warehouse.id}


async def test_sales_invoice_source_location_rules_are_enforced_at_post(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-source-rules")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
    )
    balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=batch.id,
        quantity_base=Decimal("5.00000000"),
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(
            setup,
            document_no="SI-SOURCE-UNAVAILABLE",
            line_overrides={"quantity": "2.00000000", "unit_price": "100.0000"},
        ),
        headers=headers,
    )
    assert created.status_code == 201
    setting = VariantLocationSetting(
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        is_available=False,
    )
    db_session.add(setting)
    await db_session.commit()

    posted = await client.post(
        f"/api/v1/sales-invoices/{created.json()['id']}/post",
        headers=headers,
    )
    assert posted.status_code == 400
    assert posted.json()["error_code"] == "invalid_sales_invoice_line_source_location"

    await db_session.refresh(balance)
    assert balance.quantity_base == Decimal("5.00000000")
    assert await db_session.scalar(select(func.count(StockMovement.id))) == 0


async def test_sales_invoice_rejects_missing_lines_and_duplicate_line_numbers(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-empty-dup")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    duplicate_line_body = invoice_body(
        setup,
        document_no="SI-DUP-LINE",
        lines=[
            line_payload(setup, line_no=1, unit_price="100.0000"),
            line_payload(setup, line_no=1, unit_price="100.0000"),
        ],
    )

    empty_lines = await client.post(
        "/api/v1/sales-invoices",
        json={
            "location_id": str(setup.location.id),
            "invoice_date": "2026-08-08",
            "lines": [],
        },
        headers=headers,
    )
    assert empty_lines.status_code == 201
    empty_post = await client.post(
        f"/api/v1/sales-invoices/{empty_lines.json()['id']}/post",
        headers=headers,
    )
    assert empty_post.status_code == 400
    assert empty_post.json()["error_code"] == "sales_invoice_has_no_lines"

    duplicate_line_no = await client.post(
        "/api/v1/sales-invoices",
        json=duplicate_line_body,
        headers=headers,
    )
    assert duplicate_line_no.status_code == 422


async def test_sales_invoice_single_line_fulfilled_from_multiple_locations(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POS scenario: one customer line of 10 stacks, split 3 from the main
    store and 7 from a non-sellable warehouse."""
    tenant = await make_tenant(db_session, code="sales-split-loc")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    warehouse = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="SALES-SPLIT-WH",
        is_sellable=False,
    )
    store_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_cost_base=Decimal("10.00000000"),
    )
    warehouse_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_cost_base=Decimal("20.00000000"),
    )
    store_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=store_batch.id,
        quantity_base=Decimal("100.00000000"),
    )
    warehouse_balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=warehouse.id,
        stock_batch_id=warehouse_batch.id,
        quantity_base=Decimal("200.00000000"),
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    created = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(
            setup,
            document_no="SI-SPLIT",
            lines=[
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "quantity": "10.00000000",
                    "unit_price": "100.0000",
                    "locations": [
                        {"location_id": str(setup.location.id), "quantity": "3.00000000"},
                        {"location_id": str(warehouse.id), "quantity": "7.00000000"},
                    ],
                }
            ],
        ),
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    line = body["lines"][0]
    assert len(line["locations"]) == 2
    splits_by_location = {split["location_id"]: split for split in line["locations"]}
    assert splits_by_location[str(setup.location.id)]["quantity"] == "3.00000000"
    assert splits_by_location[str(warehouse.id)]["quantity"] == "7.00000000"
    # Multi-split lines clear the mirrored single-source column.
    assert line["source_location_id"] is None
    invoice_id = body["id"]

    posted = await client.post(f"/api/v1/sales-invoices/{invoice_id}/post", headers=headers)
    assert posted.status_code == 200

    await db_session.refresh(store_balance)
    await db_session.refresh(warehouse_balance)
    assert store_balance.quantity_base == Decimal("97.00000000")
    assert warehouse_balance.quantity_base == Decimal("193.00000000")

    movements = (
        await db_session.execute(
            select(StockMovement.location_id, StockMovement.quantity_base).where(
                StockMovement.tenant_id == tenant.id,
                StockMovement.source_id == uuid.UUID(invoice_id),
            )
        )
    ).all()
    totals_by_location = {}
    for location_id, quantity_base in movements:
        totals_by_location[location_id] = (
            totals_by_location.get(location_id, Decimal("0")) + quantity_base
        )
    assert totals_by_location[setup.location.id] == Decimal("-3.00000000")
    assert totals_by_location[warehouse.id] == Decimal("-7.00000000")


async def test_sales_invoice_line_rejects_invalid_location_splits(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-split-invalid")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    other_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="SALES-SPLIT-OTHER",
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(setup, document_no="SI-SPLIT-BAD", lines=[]),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]

    mismatch = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json={
            **line_payload(setup, line_no=1, quantity="10.00000000", unit_price="100.0000"),
            "locations": [
                {"location_id": str(setup.location.id), "quantity": "3.00000000"},
                {"location_id": str(other_location.id), "quantity": "5.00000000"},
            ],
        },
        headers=headers,
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error_code"] == "invalid_sales_invoice_line_locations"

    duplicate = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json={
            **line_payload(setup, line_no=2, quantity="10.00000000", unit_price="100.0000"),
            "locations": [
                {"location_id": str(setup.location.id), "quantity": "6.00000000"},
                {"location_id": str(setup.location.id), "quantity": "4.00000000"},
            ],
        },
        headers=headers,
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["error_code"] == "invalid_sales_invoice_line_locations"


async def test_sales_invoice_post_reports_insufficient_split_location(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-split-short")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    warehouse = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="SALES-SPLIT-SHORT-WH",
        is_sellable=False,
    )
    store_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
    )
    warehouse_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
    )
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=store_batch.id,
        quantity_base=Decimal("500.00000000"),
    )
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=warehouse.id,
        stock_batch_id=warehouse_batch.id,
        quantity_base=Decimal("5.00000000"),
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    created = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(
            setup,
            document_no="SI-SPLIT-SHORT",
            lines=[
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "quantity": "10.00000000",
                    "unit_price": "100.0000",
                    "locations": [
                        {"location_id": str(warehouse.id), "quantity": "10.00000000"},
                    ],
                }
            ],
        ),
        headers=headers,
    )
    assert created.status_code == 201

    warehouse_code_title = warehouse.code.title()
    store_code_title = setup.location.code.title()
    invoice_id = created.json()["id"]
    posted = await client.post(f"/api/v1/sales-invoices/{invoice_id}/post", headers=headers)
    assert posted.status_code == 400
    assert posted.json()["error_code"] == "sales_invoice_insufficient_stock"
    assert store_code_title not in posted.json()["detail"]
    assert warehouse_code_title in posted.json()["detail"]


async def test_sales_invoice_line_requires_measured_quantity_when_flagged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-measured-required")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    bag_unit = await make_unit(db_session, code="sales-unit-bag-req")
    pack_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_id=bag_unit.id,
        conversion_to_base=Decimal("25.00000000"),
        is_base_unit=False,
        is_sales_unit=True,
        requires_measured_quantity=True,
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(setup, document_no="SI-MQ-REQ", lines=[]),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]

    missing_measured = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json=line_payload(
            setup,
            quantity="3.00000000",
            unit_price="26840.0000",
            variant_unit_id=str(pack_unit.id),
        ),
        headers=headers,
    )
    assert missing_measured.status_code == 400
    assert missing_measured.json()["error_code"] == "sales_invoice_line_measured_quantity_required"

    with_measured = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json=line_payload(
            setup,
            quantity="3.00000000",
            unit_price="26840.0000",
            variant_unit_id=str(pack_unit.id),
            measured_quantity="24.40000000",
        ),
        headers=headers,
    )
    assert with_measured.status_code == 201
    body = with_measured.json()
    assert body["line_total"] == "80520.0000"
    assert body["measured_quantity"] == "24.40000000"
    assert body["conversion_to_base"] == "24.40000000"
    assert body["quantity_base"] == "73.20000000"


async def test_sales_invoice_line_measured_quantity_optional_when_not_required(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-measured-optional")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(setup, document_no="SI-MQ-OPT", lines=[]),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]

    with_measured = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json=line_payload(
            setup,
            quantity="2.00000000",
            unit_price="100.0000",
            measured_quantity="1.90000000",
        ),
        headers=headers,
    )
    assert with_measured.status_code == 201
    assert with_measured.json()["measured_quantity"] == "1.90000000"
    assert with_measured.json()["quantity_base"] == "3.80000000"

    without_measured = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json=line_payload(setup, line_no=2, quantity="2.00000000", unit_price="100.0000"),
        headers=headers,
    )
    assert without_measured.status_code == 201
    assert without_measured.json()["measured_quantity"] is None
    assert without_measured.json()["quantity_base"] == "2.00000000"


async def test_sales_invoice_measured_quantity_drives_fifo_consumption(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-measured-fifo")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    bag_unit = await make_unit(db_session, code="sales-unit-bag-fifo")
    pack_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_id=bag_unit.id,
        conversion_to_base=Decimal("25.00000000"),
        is_base_unit=False,
        is_sales_unit=True,
        requires_measured_quantity=True,
    )
    batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_cost_base=Decimal("10.00000000"),
    )
    balance = await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=batch.id,
        quantity_base=Decimal("100.00000000"),
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(
            setup,
            document_no="SI-MQ-FIFO",
            lines=[
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(pack_unit.id),
                    "quantity": "3.00000000",
                    "unit_price": "26840.0000",
                    "measured_quantity": "24.40000000",
                }
            ],
        ),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]
    assert create_response.json()["lines"][0]["quantity_base"] == "73.20000000"

    posted = await client.post(f"/api/v1/sales-invoices/{invoice_id}/post", headers=headers)
    assert posted.status_code == 200

    await db_session.refresh(balance)
    assert balance.quantity_base == Decimal("26.80000000")

    movement = await db_session.scalar(
        select(StockMovement).where(StockMovement.stock_batch_id == batch.id)
    )
    assert movement is not None
    assert movement.quantity_base == Decimal("-73.20000000")


async def test_sales_invoice_header_update_preserves_measured_quantity(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-measured-header")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    bag_unit = await make_unit(db_session, code="sales-unit-bag-header")
    pack_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_id=bag_unit.id,
        conversion_to_base=Decimal("25.00000000"),
        is_base_unit=False,
        is_sales_unit=True,
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await db_session.commit()

    create_response = await client.post(
        "/api/v1/sales-invoices",
        json=invoice_body(
            setup,
            document_no="SI-MQ-HDR",
            lines=[
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(pack_unit.id),
                    "quantity": "3.00000000",
                    "unit_price": "26840.0000",
                    "measured_quantity": "24.40000000",
                }
            ],
        ),
        headers=headers,
    )
    assert create_response.status_code == 201
    invoice_id = create_response.json()["id"]
    assert create_response.json()["lines"][0]["quantity_base"] == "73.20000000"

    update_response = await client.patch(
        f"/api/v1/sales-invoices/{invoice_id}",
        json={"notes": "adjust notes only"},
        headers=headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["lines"][0]["quantity_base"] == "73.20000000"


async def test_sales_invoice_posted_documents_reject_draft_mutations(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-gone")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    invoice = await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        customer_id=setup.customer.id,
        location_id=setup.location.id,
        price_level_id=setup.price_level.id,
        document_no="SI-GONE",
        status=DocumentStatus.POSTED,
    )
    invoice_id = invoice.id
    line_body = line_payload(setup, unit_price="100.0000")
    await db_session.commit()

    update = await client.patch(
        f"/api/v1/sales-invoices/{invoice_id}",
        json={"notes": "nope"},
        headers=headers,
    )
    cancel = await client.delete(f"/api/v1/sales-invoices/{invoice_id}", headers=headers)
    repost = await client.post(f"/api/v1/sales-invoices/{invoice_id}/post", headers=headers)
    create_line = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json=line_body,
        headers=headers,
    )

    assert update.status_code == 400
    assert update.json()["error_code"] == "sales_invoice_not_draft"
    assert cancel.status_code == 400
    assert cancel.json()["error_code"] == "sales_invoice_not_cancellable"
    assert repost.status_code == 400
    assert repost.json()["error_code"] == "sales_invoice_not_postable"
    assert create_line.status_code == 400
    assert create_line.json()["error_code"] == "sales_invoice_not_draft"


async def test_sales_invoice_draft_header_line_crud_and_cancel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-draft-crud")
    setup = await make_sales_setup(db_session, tenant_id=tenant.id)
    other_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="SALES-DRAFT-OTHER",
    )
    actor = await make_sales_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/sales-invoices",
        json={
            "customer_id": str(setup.customer.id),
            "location_id": str(setup.location.id),
            "price_level_id": str(setup.price_level.id),
            "invoice_date": "2026-08-08",
            "notes": "draft",
        },
        headers=headers,
    )
    assert created.status_code == 201
    invoice_id = created.json()["id"]
    assert created.json()["lines"] == []

    updated_header = await client.patch(
        f"/api/v1/sales-invoices/{invoice_id}",
        json={"notes": "updated"},
        headers=headers,
    )
    assert updated_header.status_code == 200
    assert updated_header.json()["document_no"].startswith("SI-2026")

    created_line = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json=line_payload(setup, line_no=1, quantity="2.00000000", unit_price="100.0000"),
        headers=headers,
    )
    assert created_line.status_code == 201
    line_id = created_line.json()["id"]
    assert created_line.json()["line_total"] == "200.0000"
    assert created_line.json()["source_location_id"] == str(setup.location.id)

    listed_lines = await client.get(
        f"/api/v1/sales-invoices/{invoice_id}/lines?limit=100&offset=0&sort=line_no",
        headers=headers,
    )
    assert listed_lines.status_code == 200
    assert len(listed_lines.json()["items"]) == 1
    assert listed_lines.json()["items"][0]["locations"][0]["location_id"] == str(setup.location.id)

    updated_location = await client.patch(
        f"/api/v1/sales-invoices/{invoice_id}",
        json={"location_id": str(other_location.id)},
        headers=headers,
    )
    assert updated_location.status_code == 200
    preserved_source_line = next(
        line for line in updated_location.json()["lines"] if line["id"] == line_id
    )
    assert updated_location.json()["location_id"] == str(other_location.id)
    assert preserved_source_line["source_location_id"] == str(setup.location.id)

    duplicate_line = await client.post(
        f"/api/v1/sales-invoices/{invoice_id}/lines",
        json=line_payload(setup, line_no=1, quantity="1.00000000", unit_price="100.0000"),
        headers=headers,
    )
    assert duplicate_line.status_code == 409
    assert duplicate_line.json()["error_code"] == "sales_invoice_line_no_conflict"

    updated_line = await client.patch(
        f"/api/v1/sales-invoices/{invoice_id}/lines/{line_id}",
        json={"line_no": 2, "quantity": "3.00000000", "discount_amount": "10.0000"},
        headers=headers,
    )
    assert updated_line.status_code == 200
    assert updated_line.json()["line_no"] == 2
    assert updated_line.json()["line_total"] == "290.0000"

    discounted_header = await client.patch(
        f"/api/v1/sales-invoices/{invoice_id}",
        json={"discount_amount": "5.0000"},
        headers=headers,
    )
    assert discounted_header.status_code == 200

    fetched = await client.get(f"/api/v1/sales-invoices/{invoice_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["subtotal_amount"] == "290.0000"
    assert fetched.json()["total_amount"] == "285.0000"

    reset_discount = await client.patch(
        f"/api/v1/sales-invoices/{invoice_id}",
        json={"discount_amount": "0.0000"},
        headers=headers,
    )
    assert reset_discount.status_code == 200

    deleted_line = await client.delete(
        f"/api/v1/sales-invoices/{invoice_id}/lines/{line_id}",
        headers=headers,
    )
    assert deleted_line.status_code == 204

    cancelled = await client.delete(f"/api/v1/sales-invoices/{invoice_id}", headers=headers)
    assert cancelled.status_code == 204
    cancelled_invoice = await client.get(f"/api/v1/sales-invoices/{invoice_id}", headers=headers)
    assert cancelled_invoice.status_code == 200
    assert cancelled_invoice.json()["status"] == "cancelled"
    assert cancelled_invoice.json()["cancelled_by"] == str(actor.id)


async def test_sales_invoice_permissions_and_seed_idempotently(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="sales-permissions")
    forbidden_actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/sales-invoices",
        headers=auth_headers(user_access_token(forbidden_actor)),
    )
    assert response.status_code == 403

    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)
    codes = (
        (
            await db_session.execute(
                select(Permission.code).where(Permission.module == "sales_invoices")
            )
        )
        .scalars()
        .all()
    )
    assert sorted(codes) == [
        "sales_invoices.create",
        "sales_invoices.create_credit",
        "sales_invoices.delete",
        "sales_invoices.read",
        "sales_invoices.update",
    ]


@dataclass
class SalesSetup:
    unit: Unit
    catalog_item: CatalogItem
    product_variant: ProductVariant
    variant_unit: VariantUnit
    price_level: PriceLevel
    customer_price_level: PriceLevel
    customer: Customer
    location: Location


def line_payload(
    setup: "SalesSetup",
    *,
    line_no: int = 1,
    quantity: str = "1.00000000",
    unit_price: str | None = None,
    **overrides: str,
) -> dict:
    payload: dict = {
        "line_no": line_no,
        "product_variant_id": str(setup.product_variant.id),
        "variant_unit_id": str(setup.variant_unit.id),
        "quantity": quantity,
    }
    if unit_price is not None:
        payload["unit_price"] = unit_price
    payload.update(overrides)
    return payload


def invoice_body(
    setup: "SalesSetup",
    *,
    document_no: str,
    overrides: dict | None = None,
    line_overrides: dict | None = None,
    lines: list[dict] | None = None,
) -> dict:
    body: dict = {
        "customer_id": str(setup.customer.id),
        "location_id": str(setup.location.id),
        "price_level_id": str(setup.price_level.id),
        "invoice_date": "2026-08-08",
        "lines": lines if lines is not None else [line_payload(setup, **(line_overrides or {}))],
    }
    body.update(overrides or {})
    return body


async def make_sales_setup(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    unit_code: str = "sales-unit",
    sku: str = "SALES-SKU",
    price_level_code: str = "retail",
    customer_code: str = "SALES-CUST",
    location_code: str = "SALES-STORE",
) -> SalesSetup:
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
        conversion_to_base=Decimal("1.00000000"),
        is_sales_unit=True,
    )
    price_level = await make_price_level(
        db_session,
        tenant_id=tenant_id,
        code=price_level_code,
        is_default=True,
    )
    customer_price_level = await make_price_level(
        db_session,
        tenant_id=tenant_id,
        code=f"{price_level_code}-customer",
    )
    customer = await make_customer(
        db_session,
        tenant_id=tenant_id,
        code=customer_code,
        price_level_id=customer_price_level.id,
    )
    location = await make_location(db_session, tenant_id=tenant_id, code=location_code)
    return SalesSetup(
        unit=unit,
        catalog_item=catalog_item,
        product_variant=product_variant,
        variant_unit=variant_unit,
        price_level=price_level,
        customer_price_level=customer_price_level,
        customer=customer,
        location=location,
    )


async def make_sales_actor(db_session: AsyncSession, *, tenant):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("sales_invoices", ActionType.CREATE),
            permission("sales_invoices", ActionType.READ),
            permission("sales_invoices", ActionType.UPDATE),
            permission("sales_invoices", ActionType.DELETE),
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
) -> ProductVariant:
    product_variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=catalog_item_id,
        sku=sku,
        name=sku.title(),
        base_unit_id=base_unit_id,
        track_inventory=track_inventory,
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
    is_sales_unit: bool = True,
    is_active: bool = True,
    requires_measured_quantity: bool = False,
) -> VariantUnit:
    variant_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        unit_id=unit_id,
        conversion_to_base=conversion_to_base,
        is_base_unit=is_base_unit,
        is_sales_unit=is_sales_unit,
        is_active=is_active,
        requires_measured_quantity=requires_measured_quantity,
    )
    db_session.add(variant_unit)
    await db_session.flush()
    return variant_unit


async def make_price_level(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    is_default: bool = False,
    is_active: bool = True,
) -> PriceLevel:
    price_level = PriceLevel(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        is_default=is_default,
        is_active=is_active,
    )
    db_session.add(price_level)
    await db_session.flush()
    return price_level


async def make_customer(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    price_level_id: uuid.UUID | None,
    status: PartyStatus = PartyStatus.ACTIVE,
) -> Customer:
    customer = Customer(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        customer_type=CustomerType.RETAIL,
        price_level_id=price_level_id,
        status=status,
    )
    db_session.add(customer)
    await db_session.flush()
    return customer


async def make_location(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    is_active: bool = True,
    is_sellable: bool = True,
) -> Location:
    location = Location(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        location_type=LocationType.STORE,
        is_sellable=is_sellable,
        is_active=is_active,
    )
    db_session.add(location)
    await db_session.flush()
    return location


async def make_price_rule(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    variant_unit_id: uuid.UUID,
    price_level_id: uuid.UUID,
    customer_id: uuid.UUID | None = None,
    min_quantity: Decimal | None = None,
    unit_price: Decimal = Decimal("1000.0000"),
    effective_from: datetime = datetime(2026, 1, 1, tzinfo=UTC),
) -> PriceRule:
    price_rule = PriceRule(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        variant_unit_id=variant_unit_id,
        price_level_id=price_level_id,
        customer_id=customer_id,
        min_quantity=min_quantity,
        currency_code="MMK",
        unit_price=unit_price,
        effective_from=effective_from,
    )
    db_session.add(price_rule)
    await db_session.flush()
    return price_rule


async def make_sales_invoice(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    location_id: uuid.UUID,
    price_level_id: uuid.UUID,
    document_no: str = "SI-TEST",
    discount_amount: Decimal = Decimal("0.0000"),
    status: DocumentStatus = DocumentStatus.DRAFT,
) -> SalesInvoice:
    invoice = SalesInvoice(
        tenant_id=tenant_id,
        document_no=document_no,
        customer_id=customer_id,
        location_id=location_id,
        price_level_id=price_level_id,
        invoice_date=date(2026, 8, 8),
        discount_amount=discount_amount,
        status=status,
    )
    db_session.add(invoice)
    await db_session.flush()
    return invoice


async def make_stock_batch(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    unit_cost_base: Decimal = Decimal("10.00000000"),
    received_at: datetime | None = None,
    status: StockBatchStatus = StockBatchStatus.ACTIVE,
) -> StockBatch:
    now = received_at or datetime.now(UTC)
    batch = StockBatch(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        source_type=SourceType.MANUAL,
        source_id=uuid.uuid4(),
        received_at=now,
        initial_quantity_base=Decimal("0.00000000"),
        unit_cost_base=unit_cost_base,
        total_cost=Decimal("0.0000"),
        conversion_to_base=Decimal("1.00000000"),
        status=status,
        created_at=now,
    )
    db_session.add(batch)
    await db_session.flush()
    return batch


async def make_stock_balance(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
    quantity_base: Decimal,
) -> StockBalance:
    balance = StockBalance(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        location_id=location_id,
        stock_batch_id=stock_batch_id,
        quantity_base=quantity_base,
        updated_at=datetime.now(UTC),
    )
    db_session.add(balance)
    await db_session.flush()
    return balance
