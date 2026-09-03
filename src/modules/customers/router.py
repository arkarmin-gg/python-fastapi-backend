import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.customers import service
from src.modules.customers.exceptions import (
    CustomerCodeConflict,
    CustomerNotFound,
    InvalidCustomerPriceLevel,
)
from src.modules.customers.schemas import (
    CustomerCreate,
    CustomerFilters,
    CustomerListResponse,
    CustomerRead,
    CustomerUpdate,
    customer_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/customers", tags=["Customers"])

SORT_FIELDS = {"code", "name", "customer_type", "status", "created_at", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def customer_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=CustomerListResponse,
    dependencies=[Depends(require_permission("customers.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_customers(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[CustomerFilters, Depends(customer_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(customer_sort)],
):
    return await service.list_customers(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=CustomerRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("customers.create"))],
    responses=error_responses(*AUTH_ERRORS, CustomerCodeConflict, InvalidCustomerPriceLevel),
)
async def create_customer(
    db: DbSession,
    current: CurrentUser,
    body: CustomerCreate,
):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{customer_id}",
    response_model=CustomerRead,
    dependencies=[Depends(require_permission("customers.read"))],
    responses=error_responses(*AUTH_ERRORS, CustomerNotFound),
)
async def get_customer(
    db: DbSession,
    current: CurrentUser,
    customer_id: uuid.UUID,
):
    customer = await service.get_by_id(db, current.tenant_id, customer_id)
    if customer is None:
        raise CustomerNotFound()
    return customer


@router.patch(
    "/{customer_id}",
    response_model=CustomerRead,
    dependencies=[Depends(require_permission("customers.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        CustomerNotFound,
        CustomerCodeConflict,
        InvalidCustomerPriceLevel,
    ),
)
async def update_customer(
    db: DbSession,
    current: CurrentUser,
    customer_id: uuid.UUID,
    body: CustomerUpdate,
):
    return await service.update(
        db,
        current.tenant_id,
        customer_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("customers.delete"))],
    responses=error_responses(*AUTH_ERRORS, CustomerNotFound),
)
async def deactivate_customer(
    db: DbSession,
    current: CurrentUser,
    customer_id: uuid.UUID,
) -> None:
    await service.deactivate(db, current.tenant_id, customer_id, actor_user_id=current.user_id)
