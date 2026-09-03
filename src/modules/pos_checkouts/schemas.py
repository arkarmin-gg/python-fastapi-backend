import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field, model_validator

from src.foundation_enums import PaymentMethod
from src.modules.customer_payments.schemas import CustomerPaymentDetailRead
from src.modules.sales_invoices.schemas import SalesInvoiceCreate, SalesInvoiceDetailRead
from src.schemas import RequestSchema, ResponseSchema


class PosCheckoutCreate(RequestSchema):
    invoice: SalesInvoiceCreate
    expected_total: Decimal = Field(ge=0, max_digits=20, decimal_places=4)
    paid_now_amount: Decimal = Field(ge=0, max_digits=20, decimal_places=4)
    payment_method: PaymentMethod | None = None
    cash_tendered_amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=20,
        decimal_places=4,
    )

    @model_validator(mode="after")
    def _validate_tender(self) -> "PosCheckoutCreate":
        if self.invoice.customer_id is None:
            raise ValueError("invoice.customer_id is required for a POS customer checkout.")
        if self.paid_now_amount > self.expected_total:
            raise ValueError("paid_now_amount cannot exceed expected_total.")
        if self.paid_now_amount == 0:
            if self.payment_method is not None or self.cash_tendered_amount is not None:
                raise ValueError(
                    "payment_method and cash_tendered_amount must be omitted when nothing is paid."
                )
            return self
        if self.payment_method is None:
            raise ValueError("payment_method is required when paid_now_amount is positive.")
        if self.payment_method == PaymentMethod.CASH:
            if self.cash_tendered_amount is None:
                raise ValueError("cash_tendered_amount is required for a cash payment.")
            if self.cash_tendered_amount < self.paid_now_amount:
                raise ValueError("cash_tendered_amount cannot be less than paid_now_amount.")
        elif self.cash_tendered_amount is not None:
            raise ValueError("cash_tendered_amount is only valid for cash payments.")
        return self


class PosCheckoutRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    idempotency_key: str
    sales_invoice_id: uuid.UUID
    customer_payment_id: uuid.UUID | None
    payment_method: PaymentMethod | None
    paid_now_amount: Decimal
    cash_tendered_amount: Decimal | None
    change_due_amount: Decimal
    charged_to_account_amount: Decimal
    customer_balance_after: Decimal
    available_credit_after: Decimal | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    sales_invoice: SalesInvoiceDetailRead
    customer_payment: CustomerPaymentDetailRead | None


class PosCustomerCreditRead(ResponseSchema):
    customer_id: uuid.UUID
    balance_amount: Decimal
    credit_limit: Decimal | None
    available_credit: Decimal | None
