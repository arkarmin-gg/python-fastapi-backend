from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from src.modules.customer_payments.schemas import CustomerPaymentUpdate
from src.modules.document_numbers.service import generate_document_no
from src.modules.purchase_invoices.schemas import PurchaseInvoiceUpdate
from src.modules.repack_orders.schemas import RepackOrderUpdate
from src.modules.sales_invoices.schemas import SalesInvoiceUpdate
from src.modules.stock_adjustments.schemas import StockAdjustmentUpdate
from src.modules.stock_counts.schemas import StockCountUpdate
from src.modules.stock_transfers.schemas import StockTransferUpdate
from src.modules.supplier_payments.schemas import SupplierPaymentUpdate

from tests.conftest import make_tenant


async def test_document_numbers_increment_per_tenant_type_and_period(
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="doc-number-sequence")
    other_tenant = await make_tenant(db_session, code="doc-number-other")

    first = await generate_document_no(db_session, tenant.id, "sales_invoice", date(2026, 8, 8))
    second = await generate_document_no(db_session, tenant.id, "sales_invoice", date(2026, 8, 9))
    next_month = await generate_document_no(
        db_session, tenant.id, "sales_invoice", date(2026, 9, 1)
    )
    other_type = await generate_document_no(
        db_session, tenant.id, "purchase_invoice", date(2026, 8, 8)
    )
    other_tenant_first = await generate_document_no(
        db_session, other_tenant.id, "sales_invoice", date(2026, 8, 8)
    )

    assert first == "SI-202608-000001"
    assert second == "SI-202608-000002"
    assert next_month == "SI-202609-000001"
    assert other_type == "PI-202608-000001"
    assert other_tenant_first == "SI-202608-000001"


@pytest.mark.parametrize(
    "schema",
    [
        SalesInvoiceUpdate,
        PurchaseInvoiceUpdate,
        CustomerPaymentUpdate,
        SupplierPaymentUpdate,
        StockAdjustmentUpdate,
        StockTransferUpdate,
        StockCountUpdate,
        RepackOrderUpdate,
    ],
)
def test_document_no_is_rejected_on_update_payloads(schema: type) -> None:
    with pytest.raises(ValidationError) as exc_info:
        schema.model_validate({"document_no": "MANUAL-001"})

    assert any(error["type"] == "extra_forbidden" for error in exc_info.value.errors())
