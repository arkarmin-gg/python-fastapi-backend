import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.employees import service
from src.modules.employees.exceptions import EmployeeCodeConflict, EmployeeNotFound
from src.modules.employees.schemas import (
    EmployeeCreate,
    EmployeeFilters,
    EmployeeListResponse,
    EmployeeRead,
    EmployeeUpdate,
    employee_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/employees", tags=["Employees"])

SORT_FIELDS = {"code", "name", "created_at", "id"}
DEFAULT_SORT = ("code", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def employee_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=EmployeeListResponse,
    dependencies=[Depends(require_permission("employees.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_employees(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[EmployeeFilters, Depends(employee_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(employee_sort)],
):
    return await service.list_employees(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=EmployeeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("employees.create"))],
    responses=error_responses(*AUTH_ERRORS, EmployeeCodeConflict),
)
async def create_employee(db: DbSession, current: CurrentUser, body: EmployeeCreate):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{employee_id}",
    response_model=EmployeeRead,
    dependencies=[Depends(require_permission("employees.read"))],
    responses=error_responses(*AUTH_ERRORS, EmployeeNotFound),
)
async def get_employee(db: DbSession, current: CurrentUser, employee_id: uuid.UUID):
    employee = await service.get_by_id(db, current.tenant_id, employee_id)
    if employee is None:
        raise EmployeeNotFound()
    return employee


@router.patch(
    "/{employee_id}",
    response_model=EmployeeRead,
    dependencies=[Depends(require_permission("employees.update"))],
    responses=error_responses(*AUTH_ERRORS, EmployeeNotFound, EmployeeCodeConflict),
)
async def update_employee(
    db: DbSession,
    current: CurrentUser,
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
):
    return await service.update(
        db, current.tenant_id, employee_id, body, actor_user_id=current.user_id
    )


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("employees.delete"))],
    responses=error_responses(*AUTH_ERRORS, EmployeeNotFound),
)
async def deactivate_employee(db: DbSession, current: CurrentUser, employee_id: uuid.UUID):
    await service.deactivate(db, current.tenant_id, employee_id, actor_user_id=current.user_id)
