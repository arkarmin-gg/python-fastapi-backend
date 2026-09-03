import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Date as SqlDate
from sqlalchemy import DateTime as SqlDateTime
from sqlalchemy import String, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.foundation_enums import DocumentStatus
from src.modules.analytics.schemas import (
    UNSPECIFIED_PAYMENT_METHOD,
    AnalyticsGroupBy,
    CashFlowFilters,
    CashFlowMethodRow,
    CashFlowRead,
    CustomerBalanceRow,
    LowStockFilters,
    LowStockRow,
    PartyBalanceFilters,
    PayablesRead,
    PaymentMethodBreakdownRow,
    ReceivablesRead,
    SalesRangeFilters,
    SalesSummaryRow,
    SalesTimeseriesPoint,
    SupplierBalanceRow,
    TimeseriesGranularity,
    TopProductRow,
    TopProductsFilters,
    TopProductsSortBy,
)
from src.modules.catalog.models import ProductVariant, VariantLocationSetting
from src.modules.customer_payments.models import CustomerBalance, CustomerPayment
from src.modules.customers.models import Customer
from src.modules.inventory.models import StockBalance
from src.modules.locations.models import Location
from src.modules.pos_checkouts.models import PosCheckout
from src.modules.sales_invoices.models import SalesInvoice, SalesInvoiceLine
from src.modules.supplier_payments.models import SupplierBalance, SupplierPayment
from src.modules.suppliers.models import Supplier
from src.pagination import Page, PaginationParams
from src.query_filters import SortSpec, apply_sort, normalize_search

ZERO = Decimal("0.0000")
ZERO_QUANTITY = Decimal("0.00000000")


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _average_basket(revenue: Decimal, invoice_count: int) -> Decimal:
    if invoice_count == 0:
        return ZERO
    return (revenue / invoice_count).quantize(Decimal("0.0001"))


# --- Sales -------------------------------------------------------------


async def get_sales_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: SalesRangeFilters,
    group_by: AnalyticsGroupBy | None,
) -> list[SalesSummaryRow]:
    by_location = group_by is AnalyticsGroupBy.LOCATION
    revenue_sum = func.coalesce(func.sum(SalesInvoice.total_amount), ZERO).label("revenue")
    invoice_count = func.count(SalesInvoice.id).label("invoice_count")

    columns: list[Any] = []
    group_columns: list[Any] = []
    if by_location:
        columns.append(SalesInvoice.location_id.label("location_id"))
        columns.append(Location.name.label("location_name"))
        group_columns.append(SalesInvoice.location_id)
        group_columns.append(Location.name)
    columns.append(revenue_sum)
    columns.append(invoice_count)

    stmt = select(*columns).where(
        SalesInvoice.tenant_id == tenant_id,
        SalesInvoice.status == DocumentStatus.POSTED,
        SalesInvoice.invoice_date >= filters.date_from,
        SalesInvoice.invoice_date <= filters.date_to,
    )
    if by_location:
        stmt = stmt.join(Location, SalesInvoice.location_id == Location.id)
    if filters.location_id is not None:
        stmt = stmt.where(SalesInvoice.location_id == filters.location_id)
    if by_location:
        stmt = stmt.group_by(*group_columns)

    rows = (await db.execute(stmt)).all() if by_location else [(await db.execute(stmt)).one()]

    return [
        SalesSummaryRow(
            location_id=getattr(row, "location_id", None),
            location_name=getattr(row, "location_name", None),
            revenue=row.revenue,
            invoice_count=row.invoice_count,
            average_basket=_average_basket(row.revenue, row.invoice_count),
        )
        for row in rows
    ]


async def get_sales_timeseries(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: SalesRangeFilters,
    granularity: TimeseriesGranularity,
    group_by: AnalyticsGroupBy | None,
) -> list[SalesTimeseriesPoint]:
    by_location = group_by is AnalyticsGroupBy.LOCATION
    period_expr = cast(
        func.date_trunc(granularity.value, cast(SalesInvoice.invoice_date, SqlDateTime)),
        SqlDate,
    ).label("period_start")
    revenue_sum = func.coalesce(func.sum(SalesInvoice.total_amount), ZERO).label("revenue")
    invoice_count = func.count(SalesInvoice.id).label("invoice_count")

    columns: list[Any] = [period_expr]
    group_columns: list[Any] = [period_expr]
    if by_location:
        columns.append(SalesInvoice.location_id.label("location_id"))
        columns.append(Location.name.label("location_name"))
        group_columns.append(SalesInvoice.location_id)
        group_columns.append(Location.name)
    columns.append(revenue_sum)
    columns.append(invoice_count)

    stmt = select(*columns).where(
        SalesInvoice.tenant_id == tenant_id,
        SalesInvoice.status == DocumentStatus.POSTED,
        SalesInvoice.invoice_date >= filters.date_from,
        SalesInvoice.invoice_date <= filters.date_to,
    )
    if by_location:
        stmt = stmt.join(Location, SalesInvoice.location_id == Location.id)
    if filters.location_id is not None:
        stmt = stmt.where(SalesInvoice.location_id == filters.location_id)
    stmt = stmt.group_by(*group_columns).order_by(period_expr)

    rows = (await db.execute(stmt)).all()
    return [
        SalesTimeseriesPoint(
            period_start=row.period_start,
            location_id=getattr(row, "location_id", None),
            location_name=getattr(row, "location_name", None),
            revenue=row.revenue,
            invoice_count=row.invoice_count,
        )
        for row in rows
    ]


async def get_sales_by_payment_method(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: SalesRangeFilters,
) -> list[PaymentMethodBreakdownRow]:
    method_expr = func.coalesce(
        cast(PosCheckout.payment_method, String), literal(UNSPECIFIED_PAYMENT_METHOD)
    ).label("payment_method")
    revenue_sum = func.coalesce(func.sum(SalesInvoice.total_amount), ZERO).label("revenue")
    transaction_count = func.count(SalesInvoice.id).label("transaction_count")

    stmt = (
        select(method_expr, revenue_sum, transaction_count)
        .select_from(SalesInvoice)
        .outerjoin(
            PosCheckout,
            (PosCheckout.sales_invoice_id == SalesInvoice.id)
            & (PosCheckout.tenant_id == SalesInvoice.tenant_id),
        )
        .where(
            SalesInvoice.tenant_id == tenant_id,
            SalesInvoice.status == DocumentStatus.POSTED,
            SalesInvoice.invoice_date >= filters.date_from,
            SalesInvoice.invoice_date <= filters.date_to,
        )
        .group_by(method_expr)
        .order_by(revenue_sum.desc())
    )
    if filters.location_id is not None:
        stmt = stmt.where(SalesInvoice.location_id == filters.location_id)

    rows = (await db.execute(stmt)).all()
    return [
        PaymentMethodBreakdownRow(
            payment_method=row.payment_method,
            revenue=row.revenue,
            transaction_count=row.transaction_count,
        )
        for row in rows
    ]


# --- Inventory -----------------------------------------------------------


async def get_top_products(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: TopProductsFilters,
) -> list[TopProductRow]:
    quantity_sum = func.coalesce(func.sum(SalesInvoiceLine.quantity_base), ZERO_QUANTITY).label(
        "quantity_sold_base"
    )
    revenue_sum = func.coalesce(func.sum(SalesInvoiceLine.line_total), ZERO).label("revenue")

    stmt = (
        select(
            SalesInvoiceLine.product_variant_id.label("product_variant_id"),
            ProductVariant.sku.label("product_variant_sku"),
            ProductVariant.name.label("product_variant_name"),
            quantity_sum,
            revenue_sum,
        )
        .join(SalesInvoice, SalesInvoiceLine.sales_invoice_id == SalesInvoice.id)
        .join(ProductVariant, SalesInvoiceLine.product_variant_id == ProductVariant.id)
        .where(
            SalesInvoiceLine.tenant_id == tenant_id,
            SalesInvoice.status == DocumentStatus.POSTED,
            SalesInvoice.invoice_date >= filters.date_from,
            SalesInvoice.invoice_date <= filters.date_to,
        )
        .group_by(SalesInvoiceLine.product_variant_id, ProductVariant.sku, ProductVariant.name)
    )
    if filters.location_id is not None:
        stmt = stmt.where(SalesInvoice.location_id == filters.location_id)

    order_col = revenue_sum if filters.sort_by is TopProductsSortBy.REVENUE else quantity_sum
    stmt = stmt.order_by(order_col.desc()).limit(filters.limit)

    rows = (await db.execute(stmt)).all()
    return [
        TopProductRow(
            product_variant_id=row.product_variant_id,
            product_variant_sku=row.product_variant_sku,
            product_variant_name=row.product_variant_name,
            quantity_sold_base=row.quantity_sold_base,
            revenue=row.revenue,
        )
        for row in rows
    ]


async def get_low_stock(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: LowStockFilters,
    sort: tuple[SortSpec, ...],
) -> Page[LowStockRow]:
    balance_subq = (
        select(
            StockBalance.product_variant_id.label("product_variant_id"),
            StockBalance.location_id.label("location_id"),
            func.sum(StockBalance.quantity_base).label("quantity_base"),
        )
        .where(StockBalance.tenant_id == tenant_id)
        .group_by(StockBalance.product_variant_id, StockBalance.location_id)
        .subquery()
    )
    quantity_expr = func.coalesce(balance_subq.c.quantity_base, ZERO_QUANTITY).label(
        "quantity_base"
    )
    shortage_expr = (VariantLocationSetting.low_stock_quantity_base - quantity_expr).label(
        "shortage_quantity_base"
    )

    base_stmt = (
        select(
            VariantLocationSetting.id.label("id"),
            VariantLocationSetting.product_variant_id.label("product_variant_id"),
            ProductVariant.sku.label("product_variant_sku"),
            ProductVariant.name.label("product_variant_name"),
            VariantLocationSetting.location_id.label("location_id"),
            Location.name.label("location_name"),
            quantity_expr,
            VariantLocationSetting.low_stock_quantity_base.label("low_stock_quantity_base"),
            shortage_expr,
        )
        .join(ProductVariant, VariantLocationSetting.product_variant_id == ProductVariant.id)
        .join(Location, VariantLocationSetting.location_id == Location.id)
        .outerjoin(
            balance_subq,
            (balance_subq.c.product_variant_id == VariantLocationSetting.product_variant_id)
            & (balance_subq.c.location_id == VariantLocationSetting.location_id),
        )
        .where(
            VariantLocationSetting.tenant_id == tenant_id,
            VariantLocationSetting.low_stock_quantity_base.is_not(None),
            shortage_expr > ZERO_QUANTITY,
        )
    )
    if filters.location_id is not None:
        base_stmt = base_stmt.where(VariantLocationSetting.location_id == filters.location_id)
    search = normalize_search(filters.search)
    if search is not None:
        pattern = _like_pattern(search)
        base_stmt = base_stmt.where(
            or_(
                ProductVariant.sku.ilike(pattern, escape="\\"),
                ProductVariant.name.ilike(pattern, escape="\\"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0

    sort_columns: dict[str, Any] = {
        "shortage_quantity_base": shortage_expr,
        "quantity_base": quantity_expr,
        "product_variant_name": ProductVariant.name,
        "id": VariantLocationSetting.id,
    }
    sorted_stmt = apply_sort(base_stmt, sort, sort_columns)
    result = await db.execute(sorted_stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.all()
    items = [
        LowStockRow(
            product_variant_id=row.product_variant_id,
            product_variant_sku=row.product_variant_sku,
            product_variant_name=row.product_variant_name,
            location_id=row.location_id,
            location_name=row.location_name,
            quantity_base=row.quantity_base,
            low_stock_quantity_base=row.low_stock_quantity_base,
            shortage_quantity_base=row.shortage_quantity_base,
        )
        for row in rows
    ]
    return Page[LowStockRow](
        items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


# --- Financials ------------------------------------------------------------


async def get_receivables(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: PartyBalanceFilters,
    sort: tuple[SortSpec, ...],
) -> ReceivablesRead:
    base_stmt = (
        select(
            CustomerBalance.id.label("id"),
            CustomerBalance.customer_id.label("customer_id"),
            Customer.code.label("customer_code"),
            Customer.name.label("customer_name"),
            CustomerBalance.balance_amount.label("balance_amount"),
        )
        .join(Customer, CustomerBalance.customer_id == Customer.id)
        .where(CustomerBalance.tenant_id == tenant_id, CustomerBalance.balance_amount != ZERO)
    )
    search = normalize_search(filters.search)
    if search is not None:
        pattern = _like_pattern(search)
        base_stmt = base_stmt.where(
            or_(
                Customer.code.ilike(pattern, escape="\\"),
                Customer.name.ilike(pattern, escape="\\"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
    balance_only = base_stmt.with_only_columns(CustomerBalance.balance_amount).subquery()
    total_outstanding = (
        await db.scalar(select(func.coalesce(func.sum(balance_only.c.balance_amount), ZERO)))
        or ZERO
    )

    sort_columns: dict[str, Any] = {
        "balance_amount": CustomerBalance.balance_amount,
        "customer_name": Customer.name,
        "id": CustomerBalance.id,
    }
    sorted_stmt = apply_sort(base_stmt, sort, sort_columns)
    result = await db.execute(sorted_stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.all()
    items = [
        CustomerBalanceRow(
            customer_id=row.customer_id,
            customer_code=row.customer_code,
            customer_name=row.customer_name,
            balance_amount=row.balance_amount,
        )
        for row in rows
    ]
    return ReceivablesRead(
        items=items,
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
        total_outstanding=total_outstanding,
    )


async def get_payables(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: PartyBalanceFilters,
    sort: tuple[SortSpec, ...],
) -> PayablesRead:
    base_stmt = (
        select(
            SupplierBalance.id.label("id"),
            SupplierBalance.supplier_id.label("supplier_id"),
            Supplier.code.label("supplier_code"),
            Supplier.name.label("supplier_name"),
            SupplierBalance.balance_amount.label("balance_amount"),
        )
        .join(Supplier, SupplierBalance.supplier_id == Supplier.id)
        .where(SupplierBalance.tenant_id == tenant_id, SupplierBalance.balance_amount != ZERO)
    )
    search = normalize_search(filters.search)
    if search is not None:
        pattern = _like_pattern(search)
        base_stmt = base_stmt.where(
            or_(
                Supplier.code.ilike(pattern, escape="\\"),
                Supplier.name.ilike(pattern, escape="\\"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
    balance_only = base_stmt.with_only_columns(SupplierBalance.balance_amount).subquery()
    total_outstanding = (
        await db.scalar(select(func.coalesce(func.sum(balance_only.c.balance_amount), ZERO)))
        or ZERO
    )

    sort_columns: dict[str, Any] = {
        "balance_amount": SupplierBalance.balance_amount,
        "supplier_name": Supplier.name,
        "id": SupplierBalance.id,
    }
    sorted_stmt = apply_sort(base_stmt, sort, sort_columns)
    result = await db.execute(sorted_stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.all()
    items = [
        SupplierBalanceRow(
            supplier_id=row.supplier_id,
            supplier_code=row.supplier_code,
            supplier_name=row.supplier_name,
            balance_amount=row.balance_amount,
        )
        for row in rows
    ]
    return PayablesRead(
        items=items,
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
        total_outstanding=total_outstanding,
    )


async def get_cash_flow(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: CashFlowFilters,
) -> CashFlowRead:
    in_stmt = (
        select(
            CustomerPayment.payment_method.label("payment_method"),
            func.coalesce(func.sum(CustomerPayment.amount), ZERO).label("total"),
        )
        .where(
            CustomerPayment.tenant_id == tenant_id,
            CustomerPayment.status == DocumentStatus.POSTED,
            CustomerPayment.payment_date >= filters.date_from,
            CustomerPayment.payment_date <= filters.date_to,
        )
        .group_by(CustomerPayment.payment_method)
    )
    out_stmt = (
        select(
            SupplierPayment.payment_method.label("payment_method"),
            func.coalesce(func.sum(SupplierPayment.amount), ZERO).label("total"),
        )
        .where(
            SupplierPayment.tenant_id == tenant_id,
            SupplierPayment.status == DocumentStatus.POSTED,
            SupplierPayment.payment_date >= filters.date_from,
            SupplierPayment.payment_date <= filters.date_to,
        )
        .group_by(SupplierPayment.payment_method)
    )
    in_rows = {row.payment_method: row.total for row in (await db.execute(in_stmt)).all()}
    out_rows = {row.payment_method: row.total for row in (await db.execute(out_stmt)).all()}

    methods = sorted({*in_rows, *out_rows}, key=lambda method: method.value)
    by_method = [
        CashFlowMethodRow(
            payment_method=method,
            cash_in=in_rows.get(method, ZERO),
            cash_out=out_rows.get(method, ZERO),
        )
        for method in methods
    ]
    total_in = sum(in_rows.values(), ZERO)
    total_out = sum(out_rows.values(), ZERO)
    return CashFlowRead(
        date_from=filters.date_from,
        date_to=filters.date_to,
        total_cash_in=total_in,
        total_cash_out=total_out,
        net_cash_flow=total_in - total_out,
        by_payment_method=by_method,
    )
