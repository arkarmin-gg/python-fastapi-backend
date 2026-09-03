import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.suppliers import service
from src.modules.suppliers.exceptions import SupplierCodeConflict, SupplierNotFound
from src.modules.suppliers.schemas import (
    SupplierCreate,
    SupplierFilters,
    SupplierListResponse,
    SupplierRead,
    SupplierUpdate,
    supplier_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])

SORT_FIELDS = {"code", "name", "supplier_type", "status", "created_at", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def supplier_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=SupplierListResponse,
    dependencies=[Depends(require_permission("suppliers.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_suppliers(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[SupplierFilters, Depends(supplier_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(supplier_sort)],
):
    return await service.list_suppliers(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("suppliers.create"))],
    responses=error_responses(*AUTH_ERRORS, SupplierCodeConflict),
)
async def create_supplier(
    db: DbSession,
    current: CurrentUser,
    body: SupplierCreate,
):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{supplier_id}",
    response_model=SupplierRead,
    dependencies=[Depends(require_permission("suppliers.read"))],
    responses=error_responses(*AUTH_ERRORS, SupplierNotFound),
)
async def get_supplier(
    db: DbSession,
    current: CurrentUser,
    supplier_id: uuid.UUID,
):
    supplier = await service.get_by_id(db, current.tenant_id, supplier_id)
    if supplier is None:
        raise SupplierNotFound()
    return supplier


@router.patch(
    "/{supplier_id}",
    response_model=SupplierRead,
    dependencies=[Depends(require_permission("suppliers.update"))],
    responses=error_responses(*AUTH_ERRORS, SupplierNotFound, SupplierCodeConflict),
)
async def update_supplier(
    db: DbSession,
    current: CurrentUser,
    supplier_id: uuid.UUID,
    body: SupplierUpdate,
):
    return await service.update(
        db,
        current.tenant_id,
        supplier_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{supplier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("suppliers.delete"))],
    responses=error_responses(*AUTH_ERRORS, SupplierNotFound),
)
async def deactivate_supplier(
    db: DbSession,
    current: CurrentUser,
    supplier_id: uuid.UUID,
) -> None:
    await service.deactivate(db, current.tenant_id, supplier_id, actor_user_id=current.user_id)
