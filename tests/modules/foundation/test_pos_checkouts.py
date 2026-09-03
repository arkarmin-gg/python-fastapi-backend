from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.modules.customer_payments.models import (
    CustomerBalance,
    CustomerLedgerEntry,
    CustomerPayment,
)
from src.modules.customers.models import Customer
from src.modules.pos_checkouts.models import PosCheckout
from src.modules.sales_invoices.models import SalesInvoice

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    user_access_token,
)
from tests.modules.foundation.test_sales_invoices import make_sales_setup


async def _setup_checkout(db_session: AsyncSession, *, code: str):
    tenant = await make_tenant(db_session, code=code)
    setup = await make_sales_setup(
        db_session,
        tenant_id=tenant.id,
        unit_code=f"{code}-unit",
        sku=f"{code}-sku",
        price_level_code=f"{code}-retail",
        customer_code=f"{code}-customer",
        location_code=f"{code}-store",
    )
    setup.product_variant.track_inventory = False
    setup.customer.credit_limit = Decimal("5000.0000")
    await db_session.flush()
    return tenant, setup


def _body(setup, *, expected: str = "1000.0000", paid: str = "400.0000"):
    body = {
        "invoice": {
            "customer_id": str(setup.customer.id),
            "location_id": str(setup.location.id),
            "price_level_id": str(setup.customer_price_level.id),
            "invoice_date": "2026-08-29",
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "quantity": "1.00000000",
                    "unit_price": "1000.0000",
                }
            ],
        },
        "expected_total": expected,
        "paid_now_amount": paid,
    }
    if Decimal(paid) > 0:
        body |= {
            "payment_method": "cash",
            "cash_tendered_amount": "500.0000",
        }
    return body


async def _actor(db_session: AsyncSession, tenant, *, credit: bool = True, payment: bool = True):
    permissions = ["sales_invoices.create", "sales_invoices.read"]
    if credit:
        permissions.append("sales_invoices.create_credit")
    if payment:
        permissions.append("customer_payments.create")
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=permissions,
    )


async def test_partial_credit_checkout_is_atomic_idempotent_and_durable(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant, setup = await _setup_checkout(db_session, code="pos-partial")
    actor = await _actor(db_session, tenant)
    headers = auth_headers(user_access_token(actor)) | {"Idempotency-Key": "pos-partial-key"}
    body = _body(setup)

    credit = await client.get(
        f"/api/v1/pos-checkouts/customers/{setup.customer.id}/credit",
        headers=headers,
    )
    assert credit.status_code == 200
    assert credit.json()["balance_amount"] == "0.0000"
    assert credit.json()["available_credit"] == "5000.0000"

    created = await client.post("/api/v1/pos-checkouts", json=body, headers=headers)
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["paid_now_amount"] == "400.0000"
    assert result["cash_tendered_amount"] == "500.0000"
    assert result["change_due_amount"] == "100.0000"
    assert result["charged_to_account_amount"] == "600.0000"
    assert result["customer_balance_after"] == "600.0000"
    assert result["available_credit_after"] == "4400.0000"
    assert result["sales_invoice"]["status"] == "posted"
    assert result["sales_invoice"]["paid_amount"] == "400.0000"
    assert result["sales_invoice"]["balance_amount"] == "600.0000"
    assert result["customer_payment"]["status"] == "posted"
    assert result["customer_payment"]["amount"] == "400.0000"

    fetched = await client.get(
        f"/api/v1/pos-checkouts/sales-invoices/{result['sales_invoice_id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == result["id"]
    assert fetched.json()["cash_tendered_amount"] == "500.0000"

    replay = await client.post("/api/v1/pos-checkouts", json=body, headers=headers)
    assert replay.status_code == 201
    assert replay.json()["id"] == result["id"]

    changed = await client.post(
        "/api/v1/pos-checkouts",
        json=body | {"paid_now_amount": "300.0000", "cash_tendered_amount": "500.0000"},
        headers=headers,
    )
    assert changed.status_code == 409
    assert changed.json()["error_code"] == "pos_checkout_idempotency_conflict"
    assert await db_session.scalar(select(func.count(PosCheckout.id))) == 1
    assert await db_session.scalar(select(func.count(SalesInvoice.id))) == 1
    assert await db_session.scalar(select(func.count(CustomerPayment.id))) == 1
    assert await db_session.scalar(select(func.count(CustomerLedgerEntry.id))) == 2
    balance = await db_session.scalar(
        select(CustomerBalance).where(CustomerBalance.customer_id == setup.customer.id)
    )
    assert balance is not None
    assert balance.balance_amount == Decimal("600.0000")


async def test_fully_on_account_checkout_creates_no_zero_payment(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant, setup = await _setup_checkout(db_session, code="pos-credit")
    actor = await _actor(db_session, tenant, payment=False)
    headers = auth_headers(user_access_token(actor)) | {"Idempotency-Key": "pos-credit-key"}

    created = await client.post(
        "/api/v1/pos-checkouts",
        json=_body(setup, paid="0.0000"),
        headers=headers,
    )
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["customer_payment_id"] is None
    assert result["customer_payment"] is None
    assert result["payment_method"] is None
    assert result["charged_to_account_amount"] == "1000.0000"
    assert await db_session.scalar(select(func.count(CustomerPayment.id))) == 0


async def test_checkout_rejects_total_change_and_credit_limit_without_side_effects(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant, setup = await _setup_checkout(db_session, code="pos-reject")
    actor = await _actor(db_session, tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))
    normal_body = _body(setup)
    customer_id = setup.customer.id

    changed = await client.post(
        "/api/v1/pos-checkouts",
        json=normal_body | {"expected_total": "999.0000"},
        headers=headers | {"Idempotency-Key": "pos-total-key"},
    )
    assert changed.status_code == 409
    assert changed.json()["error_code"] == "pos_checkout_total_changed"
    assert changed.json()["details"]["authoritative_total"] == "1000.0000"

    customer = await db_session.get(Customer, customer_id)
    assert customer is not None
    customer.credit_limit = Decimal("500.0000")
    await db_session.flush()
    over_limit = await client.post(
        "/api/v1/pos-checkouts",
        json=normal_body,
        headers=headers | {"Idempotency-Key": "pos-limit-key"},
    )
    assert over_limit.status_code == 400
    assert over_limit.json()["error_code"] == "pos_checkout_credit_limit_exceeded"
    assert over_limit.json()["details"]["available_credit"] == "500.0000"
    assert await db_session.scalar(select(func.count(PosCheckout.id))) == 0
    assert await db_session.scalar(select(func.count(SalesInvoice.id))) == 0
    assert await db_session.scalar(select(func.count(CustomerPayment.id))) == 0


async def test_checkout_enforces_component_permissions(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant, setup = await _setup_checkout(db_session, code="pos-permissions")
    no_credit = await _actor(db_session, tenant, credit=False)
    denied_credit = await client.post(
        "/api/v1/pos-checkouts",
        json=_body(setup),
        headers=auth_headers(user_access_token(no_credit))
        | {"Idempotency-Key": "pos-denied-credit"},
    )
    assert denied_credit.status_code == 403

    no_payment = await _actor(db_session, tenant, payment=False)
    denied_payment = await client.post(
        "/api/v1/pos-checkouts",
        json=_body(setup, paid="1000.0000") | {"cash_tendered_amount": "1000.0000"},
        headers=auth_headers(user_access_token(no_payment))
        | {"Idempotency-Key": "pos-denied-payment"},
    )
    assert denied_payment.status_code == 403
