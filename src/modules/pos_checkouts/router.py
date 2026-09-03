import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.customer_payments.exceptions import (
    CustomerPaymentInvoiceOverpaid,
    CustomerPaymentOverAllocated,
    InvalidCustomerPaymentAllocationInvoice,
    InvalidCustomerPaymentCustomer,
)
from src.modules.pos_checkouts import service
from src.modules.pos_checkouts.exceptions import (
    PosCheckoutCreditLimitExceeded,
    PosCheckoutIdempotencyConflict,
    PosCheckoutNotFound,
    PosCheckoutTotalChanged,
)
from src.modules.pos_checkouts.schemas import (
    PosCheckoutCreate,
    PosCheckoutRead,
    PosCustomerCreditRead,
)
from src.modules.rbac import service as rbac_service
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.sales_invoices.router import CREATE_VALIDATION_ERRORS, WORKFLOW_ERRORS
from src.schemas import error_responses

router = APIRouter(prefix="/pos-checkouts", tags=["POS Checkouts"])

AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CHECKOUT_ERRORS = (
    PosCheckoutTotalChanged,
    PosCheckoutCreditLimitExceeded,
    PosCheckoutIdempotencyConflict,
    InvalidCustomerPaymentCustomer,
    InvalidCustomerPaymentAllocationInvoice,
    CustomerPaymentOverAllocated,
    CustomerPaymentInvoiceOverpaid,
    *CREATE_VALIDATION_ERRORS,
    *WORKFLOW_ERRORS,
)


@router.get(
    "/customers/{customer_id}/credit",
    response_model=PosCustomerCreditRead,
    dependencies=[Depends(require_permission("sales_invoices.create_credit"))],
    responses=error_responses(*AUTH_ERRORS, InvalidCustomerPaymentCustomer),
)
async def get_pos_customer_credit(
    db: DbSession,
    current: CurrentUser,
    customer_id: uuid.UUID,
):
    credit = await service.get_customer_credit(db, current.tenant_id, customer_id)
    if credit is None:
        raise InvalidCustomerPaymentCustomer()
    return credit


@router.post(
    "",
    response_model=PosCheckoutRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sales_invoices.create"))],
    responses=error_responses(*AUTH_ERRORS, *CHECKOUT_ERRORS),
)
async def create_pos_checkout(
    db: DbSession,
    current: CurrentUser,
    body: PosCheckoutCreate,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ],
):
    if body.paid_now_amount > 0 and not await rbac_service.user_has_permission(
        db, current.user, "customer_payments.create"
    ):
        raise PermissionDenied()
    if body.paid_now_amount < body.expected_total and not await rbac_service.user_has_permission(
        db, current.user, "sales_invoices.create_credit"
    ):
        raise PermissionDenied()
    return await service.create_checkout(
        db,
        current.tenant_id,
        body,
        idempotency_key=idempotency_key,
        actor_user_id=current.user_id,
    )


@router.get(
    "/sales-invoices/{sales_invoice_id}",
    response_model=PosCheckoutRead,
    dependencies=[Depends(require_permission("sales_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, PosCheckoutNotFound),
)
async def get_pos_checkout_by_sales_invoice(
    db: DbSession,
    current: CurrentUser,
    sales_invoice_id: uuid.UUID,
):
    checkout = await service.get_by_sales_invoice_id(db, current.tenant_id, sales_invoice_id)
    if checkout is None:
        raise PosCheckoutNotFound()
    return checkout


@router.get(
    "/{pos_checkout_id}",
    response_model=PosCheckoutRead,
    dependencies=[Depends(require_permission("sales_invoices.read"))],
    responses=error_responses(*AUTH_ERRORS, PosCheckoutNotFound),
)
async def get_pos_checkout(
    db: DbSession,
    current: CurrentUser,
    pos_checkout_id: uuid.UUID,
):
    checkout = await service.get_by_id(db, current.tenant_id, pos_checkout_id)
    if checkout is None:
        raise PosCheckoutNotFound()
    return checkout
