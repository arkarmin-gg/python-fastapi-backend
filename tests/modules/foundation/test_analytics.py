import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import (
    DocumentStatus,
    LocationType,
    PartyStatus,
    PaymentMethod,
    SourceType,
    UnitKind,
)
from src.modules.catalog.models import (
    CatalogItem,
    ProductVariant,
    VariantLocationSetting,
    VariantUnit,
)
from src.modules.customer_payments.models import CustomerBalance, CustomerPayment
from src.modules.customers.models import Customer
from src.modules.inventory.models import StockBalance, StockBatch
from src.modules.locations.models import Location
from src.modules.pos_checkouts.models import PosCheckout
from src.modules.price_levels.models import PriceLevel
from src.modules.rbac.constants import ActionType
from src.modules.sales_invoices.models import SalesInvoice, SalesInvoiceLine
from src.modules.supplier_payments.models import SupplierBalance, SupplierPayment
from src.modules.suppliers.models import Supplier
from src.modules.tenants.models import Tenant
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


async def make_reader(db_session: AsyncSession, *, tenant: Tenant):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("analytics", ActionType.READ)],
    )


async def make_unit(db_session: AsyncSession, *, code: str) -> Unit:
    unit = Unit(code=code, name_en=code.title(), unit_kind=UnitKind.COUNT)
    db_session.add(unit)
    await db_session.flush()
    return unit


async def make_location(
    db_session: AsyncSession, *, tenant_id: uuid.UUID, code: str, is_sellable: bool = True
) -> Location:
    location = Location(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        location_type=LocationType.STORE,
        is_sellable=is_sellable,
    )
    db_session.add(location)
    await db_session.flush()
    return location


async def make_variant(
    db_session: AsyncSession, *, tenant_id: uuid.UUID, sku: str, unit: Unit
) -> ProductVariant:
    catalog_item = CatalogItem(tenant_id=tenant_id, code=f"ITEM-{sku}", name=sku.title())
    db_session.add(catalog_item)
    await db_session.flush()
    variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=catalog_item.id,
        sku=sku,
        name=sku.title(),
        base_unit_id=unit.id,
    )
    db_session.add(variant)
    await db_session.flush()
    return variant


async def make_variant_unit(
    db_session: AsyncSession, *, tenant_id: uuid.UUID, product_variant_id: uuid.UUID, unit: Unit
) -> VariantUnit:
    variant_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        unit_id=unit.id,
        conversion_to_base=Decimal("1.00000000"),
        is_base_unit=True,
        is_sales_unit=True,
    )
    db_session.add(variant_unit)
    await db_session.flush()
    return variant_unit


async def make_price_level(
    db_session: AsyncSession, *, tenant_id: uuid.UUID, code: str
) -> PriceLevel:
    price_level = PriceLevel(tenant_id=tenant_id, code=code, name=code.title())
    db_session.add(price_level)
    await db_session.flush()
    return price_level


async def make_sales_invoice(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    price_level_id: uuid.UUID,
    document_no: str,
    invoice_date: date,
    total_amount: Decimal,
    status: DocumentStatus = DocumentStatus.POSTED,
    customer_id: uuid.UUID | None = None,
) -> SalesInvoice:
    invoice = SalesInvoice(
        tenant_id=tenant_id,
        document_no=document_no,
        customer_id=customer_id,
        location_id=location_id,
        price_level_id=price_level_id,
        invoice_date=invoice_date,
        status=status,
        total_amount=total_amount,
    )
    db_session.add(invoice)
    await db_session.flush()
    return invoice


async def test_sales_summary_filters_to_posted_invoices_in_range(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-sales-summary")
    other_tenant = await make_tenant(db_session, code="an-sales-summary-other")
    location = await make_location(db_session, tenant_id=tenant.id, code="AN-STORE")
    price_level = await make_price_level(db_session, tenant_id=tenant.id, code="AN-PL")

    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        price_level_id=price_level.id,
        document_no="SI-IN-RANGE",
        invoice_date=date(2026, 8, 15),
        total_amount=Decimal("1000.0000"),
    )
    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        price_level_id=price_level.id,
        document_no="SI-DRAFT",
        invoice_date=date(2026, 8, 15),
        total_amount=Decimal("5000.0000"),
        status=DocumentStatus.DRAFT,
    )
    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        price_level_id=price_level.id,
        document_no="SI-OUT-OF-RANGE",
        invoice_date=date(2026, 1, 1),
        total_amount=Decimal("2000.0000"),
    )
    other_location = await make_location(db_session, tenant_id=other_tenant.id, code="OTHER-STORE")
    other_price_level = await make_price_level(
        db_session, tenant_id=other_tenant.id, code="AN-PL-OTHER"
    )
    await make_sales_invoice(
        db_session,
        tenant_id=other_tenant.id,
        location_id=other_location.id,
        price_level_id=other_price_level.id,
        document_no="SI-OTHER-TENANT",
        invoice_date=date(2026, 8, 15),
        total_amount=Decimal("9999.0000"),
    )

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.get(
        "/api/v1/analytics/sales/summary",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["revenue"] == "1000.0000"
    assert body[0]["invoice_count"] == 1
    assert body[0]["average_basket"] == "1000.0000"
    assert body[0]["location_id"] is None


async def test_sales_summary_group_by_location_and_location_filter(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-sales-group")
    store_a = await make_location(db_session, tenant_id=tenant.id, code="AN-A")
    store_b = await make_location(db_session, tenant_id=tenant.id, code="AN-B")
    price_level = await make_price_level(db_session, tenant_id=tenant.id, code="AN-GROUP-PL")

    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=store_a.id,
        price_level_id=price_level.id,
        document_no="SI-A-1",
        invoice_date=date(2026, 8, 10),
        total_amount=Decimal("300.0000"),
    )
    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=store_b.id,
        price_level_id=price_level.id,
        document_no="SI-B-1",
        invoice_date=date(2026, 8, 11),
        total_amount=Decimal("700.0000"),
    )

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    grouped = await client.get(
        "/api/v1/analytics/sales/summary",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31", "group_by": "location"},
        headers=headers,
    )
    assert grouped.status_code == 200
    rows = {row["location_id"]: row for row in grouped.json()}
    assert rows[str(store_a.id)]["revenue"] == "300.0000"
    assert rows[str(store_b.id)]["revenue"] == "700.0000"

    filtered = await client.get(
        "/api/v1/analytics/sales/summary",
        params={
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "location_id": str(store_a.id),
        },
        headers=headers,
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert len(filtered_body) == 1
    assert filtered_body[0]["revenue"] == "300.0000"


async def test_sales_date_range_rejects_span_over_max_and_backwards_range(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-sales-range")
    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    too_wide = await client.get(
        "/api/v1/analytics/sales/summary",
        params={"date_from": "2020-01-01", "date_to": "2026-08-31"},
        headers=headers,
    )
    assert too_wide.status_code == 422

    backwards = await client.get(
        "/api/v1/analytics/sales/summary",
        params={"date_from": "2026-08-31", "date_to": "2026-08-01"},
        headers=headers,
    )
    assert backwards.status_code == 422


async def test_sales_timeseries_buckets_by_granularity(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-sales-ts")
    location = await make_location(db_session, tenant_id=tenant.id, code="AN-TS")
    price_level = await make_price_level(db_session, tenant_id=tenant.id, code="AN-TS-PL")

    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        price_level_id=price_level.id,
        document_no="SI-TS-1",
        invoice_date=date(2026, 8, 3),
        total_amount=Decimal("100.0000"),
    )
    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        price_level_id=price_level.id,
        document_no="SI-TS-2",
        invoice_date=date(2026, 8, 20),
        total_amount=Decimal("400.0000"),
    )

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.get(
        "/api/v1/analytics/sales/timeseries",
        params={
            "date_from": "2026-08-01",
            "date_to": "2026-08-31",
            "granularity": "month",
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["period_start"] == "2026-08-01"
    assert body[0]["revenue"] == "500.0000"
    assert body[0]["invoice_count"] == 2


async def test_sales_by_payment_method_buckets_unspecified_when_no_checkout(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-sales-pm")
    location = await make_location(db_session, tenant_id=tenant.id, code="AN-PM")
    price_level = await make_price_level(db_session, tenant_id=tenant.id, code="AN-PM-PL")

    cash_invoice = await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        price_level_id=price_level.id,
        document_no="SI-PM-CASH",
        invoice_date=date(2026, 8, 5),
        total_amount=Decimal("150.0000"),
    )
    db_session.add(
        PosCheckout(
            tenant_id=tenant.id,
            idempotency_key=f"idem-{uuid.uuid4().hex}",
            request_hash="hash",
            sales_invoice_id=cash_invoice.id,
            payment_method=PaymentMethod.CASH,
            paid_now_amount=Decimal("150.0000"),
            change_due_amount=Decimal("0.0000"),
            charged_to_account_amount=Decimal("0.0000"),
            customer_balance_after=Decimal("0.0000"),
        )
    )
    await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        price_level_id=price_level.id,
        document_no="SI-PM-NO-CHECKOUT",
        invoice_date=date(2026, 8, 6),
        total_amount=Decimal("50.0000"),
    )
    await db_session.flush()

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.get(
        "/api/v1/analytics/sales/by-payment-method",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31"},
        headers=headers,
    )
    assert response.status_code == 200
    rows = {row["payment_method"]: row for row in response.json()}
    assert rows["cash"]["revenue"] == "150.0000"
    assert rows["unspecified"]["revenue"] == "50.0000"


async def test_top_products_sorts_by_revenue_or_quantity(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-top-products")
    unit = await make_unit(db_session, code="an-top-unit")
    location = await make_location(db_session, tenant_id=tenant.id, code="AN-TOP")
    price_level = await make_price_level(db_session, tenant_id=tenant.id, code="AN-TOP-PL")
    high_revenue = await make_variant(db_session, tenant_id=tenant.id, sku="AN-HIGH-REV", unit=unit)
    high_qty = await make_variant(db_session, tenant_id=tenant.id, sku="AN-HIGH-QTY", unit=unit)
    high_revenue_unit = await make_variant_unit(
        db_session, tenant_id=tenant.id, product_variant_id=high_revenue.id, unit=unit
    )
    high_qty_unit = await make_variant_unit(
        db_session, tenant_id=tenant.id, product_variant_id=high_qty.id, unit=unit
    )

    invoice = await make_sales_invoice(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        price_level_id=price_level.id,
        document_no="SI-TOP-1",
        invoice_date=date(2026, 8, 12),
        total_amount=Decimal("1300.0000"),
    )
    db_session.add_all(
        [
            SalesInvoiceLine(
                tenant_id=tenant.id,
                sales_invoice_id=invoice.id,
                line_no=1,
                product_variant_id=high_revenue.id,
                variant_unit_id=high_revenue_unit.id,
                quantity=Decimal("1.00000000"),
                conversion_to_base=Decimal("1.00000000"),
                quantity_base=Decimal("1.00000000"),
                unit_price=Decimal("1000.0000"),
                line_total=Decimal("1000.0000"),
            ),
            SalesInvoiceLine(
                tenant_id=tenant.id,
                sales_invoice_id=invoice.id,
                line_no=2,
                product_variant_id=high_qty.id,
                variant_unit_id=high_qty_unit.id,
                quantity=Decimal("50.00000000"),
                conversion_to_base=Decimal("1.00000000"),
                quantity_base=Decimal("50.00000000"),
                unit_price=Decimal("6.0000"),
                line_total=Decimal("300.0000"),
            ),
        ]
    )
    await db_session.flush()

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    by_revenue = await client.get(
        "/api/v1/analytics/inventory/top-products",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31", "sort_by": "revenue"},
        headers=headers,
    )
    assert by_revenue.status_code == 200
    assert by_revenue.json()[0]["product_variant_sku"] == "AN-HIGH-REV"

    by_quantity = await client.get(
        "/api/v1/analytics/inventory/top-products",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31", "sort_by": "quantity"},
        headers=headers,
    )
    assert by_quantity.status_code == 200
    assert by_quantity.json()[0]["product_variant_sku"] == "AN-HIGH-QTY"


async def test_low_stock_reports_only_variants_under_threshold(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-low-stock")
    unit = await make_unit(db_session, code="an-ls-unit")
    location = await make_location(db_session, tenant_id=tenant.id, code="AN-LS")
    low_variant = await make_variant(db_session, tenant_id=tenant.id, sku="AN-LOW", unit=unit)
    healthy_variant = await make_variant(
        db_session, tenant_id=tenant.id, sku="AN-HEALTHY", unit=unit
    )
    untracked_variant = await make_variant(
        db_session, tenant_id=tenant.id, sku="AN-UNTRACKED", unit=unit
    )

    db_session.add_all(
        [
            VariantLocationSetting(
                tenant_id=tenant.id,
                product_variant_id=low_variant.id,
                location_id=location.id,
                low_stock_quantity_base=Decimal("10.00000000"),
            ),
            VariantLocationSetting(
                tenant_id=tenant.id,
                product_variant_id=healthy_variant.id,
                location_id=location.id,
                low_stock_quantity_base=Decimal("10.00000000"),
            ),
            VariantLocationSetting(
                tenant_id=tenant.id,
                product_variant_id=untracked_variant.id,
                location_id=location.id,
                low_stock_quantity_base=None,
            ),
        ]
    )
    low_batch = StockBatch(
        tenant_id=tenant.id,
        product_variant_id=low_variant.id,
        source_type=SourceType.MANUAL,
        source_id=uuid.uuid4(),
        received_at=utc_now(),
        initial_quantity_base=Decimal("0"),
        unit_cost_base=Decimal("1.00000000"),
        total_cost=Decimal("0.0000"),
        created_at=utc_now(),
    )
    healthy_batch = StockBatch(
        tenant_id=tenant.id,
        product_variant_id=healthy_variant.id,
        source_type=SourceType.MANUAL,
        source_id=uuid.uuid4(),
        received_at=utc_now(),
        initial_quantity_base=Decimal("0"),
        unit_cost_base=Decimal("1.00000000"),
        total_cost=Decimal("0.0000"),
        created_at=utc_now(),
    )
    db_session.add_all([low_batch, healthy_batch])
    await db_session.flush()
    db_session.add_all(
        [
            StockBalance(
                tenant_id=tenant.id,
                product_variant_id=low_variant.id,
                location_id=location.id,
                stock_batch_id=low_batch.id,
                quantity_base=Decimal("3.00000000"),
                updated_at=utc_now(),
            ),
            StockBalance(
                tenant_id=tenant.id,
                product_variant_id=healthy_variant.id,
                location_id=location.id,
                stock_batch_id=healthy_batch.id,
                quantity_base=Decimal("50.00000000"),
                updated_at=utc_now(),
            ),
        ]
    )
    await db_session.flush()

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.get("/api/v1/analytics/inventory/low-stock", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert [item["product_variant_sku"] for item in body["items"]] == ["AN-LOW"]
    assert body["items"][0]["shortage_quantity_base"] == "7.00000000"


async def test_receivables_and_payables_report_outstanding_balances(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-financials")
    customer = Customer(
        tenant_id=tenant.id,
        code="AN-CUST",
        name="Analytics Customer",
        status=PartyStatus.ACTIVE,
    )
    second_customer = Customer(
        tenant_id=tenant.id,
        code="AN-CUST-2",
        name="Second Customer",
        status=PartyStatus.ACTIVE,
    )
    settled_customer = Customer(
        tenant_id=tenant.id,
        code="AN-CUST-SETTLED",
        name="Settled Customer",
        status=PartyStatus.ACTIVE,
    )
    supplier = Supplier(tenant_id=tenant.id, code="AN-SUPP", name="Analytics Supplier")
    second_supplier = Supplier(tenant_id=tenant.id, code="AN-SUPP-2", name="Second Supplier")
    db_session.add_all([customer, second_customer, settled_customer, supplier, second_supplier])
    await db_session.flush()
    db_session.add_all(
        [
            CustomerBalance(
                tenant_id=tenant.id,
                customer_id=customer.id,
                balance_amount=Decimal("2500.0000"),
                updated_at=utc_now(),
            ),
            CustomerBalance(
                tenant_id=tenant.id,
                customer_id=second_customer.id,
                balance_amount=Decimal("1000.0000"),
                updated_at=utc_now(),
            ),
            CustomerBalance(
                tenant_id=tenant.id,
                customer_id=settled_customer.id,
                balance_amount=Decimal("0.0000"),
                updated_at=utc_now(),
            ),
            SupplierBalance(
                tenant_id=tenant.id,
                supplier_id=supplier.id,
                balance_amount=Decimal("900.0000"),
                updated_at=utc_now(),
            ),
            SupplierBalance(
                tenant_id=tenant.id,
                supplier_id=second_supplier.id,
                balance_amount=Decimal("100.0000"),
                updated_at=utc_now(),
            ),
        ]
    )
    await db_session.flush()

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    receivables = await client.get("/api/v1/analytics/financials/receivables", headers=headers)
    assert receivables.status_code == 200
    receivables_body = receivables.json()
    assert receivables_body["total_outstanding"] == "3500.0000"
    assert {item["customer_code"] for item in receivables_body["items"]} == {
        "AN-CUST",
        "AN-CUST-2",
    }

    payables = await client.get("/api/v1/analytics/financials/payables", headers=headers)
    assert payables.status_code == 200
    payables_body = payables.json()
    assert payables_body["total_outstanding"] == "1000.0000"
    assert {item["supplier_code"] for item in payables_body["items"]} == {
        "AN-SUPP",
        "AN-SUPP-2",
    }


async def test_cash_flow_nets_customer_and_supplier_payments_by_method(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-cash-flow")
    customer = Customer(tenant_id=tenant.id, code="AN-CF-CUST", name="Cash Flow Customer")
    supplier = Supplier(tenant_id=tenant.id, code="AN-CF-SUPP", name="Cash Flow Supplier")
    db_session.add_all([customer, supplier])
    await db_session.flush()

    db_session.add(
        CustomerPayment(
            tenant_id=tenant.id,
            document_no="CP-CF-1",
            customer_id=customer.id,
            payment_date=date(2026, 8, 10),
            payment_method=PaymentMethod.CASH,
            amount=Decimal("1000.0000"),
            status=DocumentStatus.POSTED,
        )
    )
    db_session.add(
        CustomerPayment(
            tenant_id=tenant.id,
            document_no="CP-CF-DRAFT",
            customer_id=customer.id,
            payment_date=date(2026, 8, 10),
            payment_method=PaymentMethod.CASH,
            amount=Decimal("5000.0000"),
            status=DocumentStatus.DRAFT,
        )
    )
    db_session.add(
        SupplierPayment(
            tenant_id=tenant.id,
            document_no="SP-CF-1",
            supplier_id=supplier.id,
            payment_date=date(2026, 8, 11),
            payment_method=PaymentMethod.BANK,
            amount=Decimal("400.0000"),
            status=DocumentStatus.POSTED,
        )
    )
    await db_session.flush()

    actor = await make_reader(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.get(
        "/api/v1/analytics/financials/cash-flow",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_cash_in"] == "1000.0000"
    assert body["total_cash_out"] == "400.0000"
    assert body["net_cash_flow"] == "600.0000"
    by_method = {row["payment_method"]: row for row in body["by_payment_method"]}
    assert by_method["cash"]["cash_in"] == "1000.0000"
    assert by_method["cash"]["cash_out"] == "0.0000"
    assert by_method["bank"]["cash_out"] == "400.0000"


async def test_analytics_requires_permission_and_authentication(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="an-permissions")
    unauthorized = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])
    headers = auth_headers(user_access_token(unauthorized))

    forbidden = await client.get(
        "/api/v1/analytics/sales/summary",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31"},
        headers=headers,
    )
    assert forbidden.status_code == 403

    unauthenticated = await client.get(
        "/api/v1/analytics/sales/summary",
        params={"date_from": "2026-08-01", "date_to": "2026-08-31"},
    )
    assert unauthenticated.status_code == 401
