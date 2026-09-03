import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.location_assignments import service
from src.modules.location_assignments.exceptions import (
    InvalidLocationAssignmentEmployee,
    InvalidLocationAssignmentLocation,
    LocationAssignmentNotFound,
    LocationAssignmentOverlapConflict,
)
from src.modules.location_assignments.schemas import (
    LocationAssignmentCreate,
    LocationAssignmentFilters,
    LocationAssignmentListResponse,
    LocationAssignmentRead,
    LocationAssignmentUpdate,
    location_assignment_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/location-assignments", tags=["Location Assignments"])

SORT_FIELDS = {"location_id", "employee_id", "role", "start_date", "id"}
DEFAULT_SORT = ("location_id", "start_date", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)


def location_assignment_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=LocationAssignmentListResponse,
    dependencies=[Depends(require_permission("location_assignments.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_location_assignments(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[LocationAssignmentFilters, Depends(location_assignment_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(location_assignment_sort)],
):
    return await service.list_location_assignments(
        db,
        current.tenant_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "",
    response_model=LocationAssignmentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("location_assignments.create"))],
    responses=error_responses(
        *AUTH_ERRORS,
        InvalidLocationAssignmentLocation,
        InvalidLocationAssignmentEmployee,
        LocationAssignmentOverlapConflict,
    ),
)
async def create_location_assignment(
    db: DbSession,
    current: CurrentUser,
    body: LocationAssignmentCreate,
):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{assignment_id}",
    response_model=LocationAssignmentRead,
    dependencies=[Depends(require_permission("location_assignments.read"))],
    responses=error_responses(*AUTH_ERRORS, LocationAssignmentNotFound),
)
async def get_location_assignment(
    db: DbSession,
    current: CurrentUser,
    assignment_id: uuid.UUID,
):
    assignment = await service.get_by_id(db, current.tenant_id, assignment_id)
    if assignment is None:
        raise LocationAssignmentNotFound()
    return assignment


@router.patch(
    "/{assignment_id}",
    response_model=LocationAssignmentRead,
    dependencies=[Depends(require_permission("location_assignments.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        LocationAssignmentNotFound,
        InvalidLocationAssignmentLocation,
        InvalidLocationAssignmentEmployee,
        LocationAssignmentOverlapConflict,
    ),
)
async def update_location_assignment(
    db: DbSession,
    current: CurrentUser,
    assignment_id: uuid.UUID,
    body: LocationAssignmentUpdate,
):
    return await service.update(
        db,
        current.tenant_id,
        assignment_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("location_assignments.delete"))],
    responses=error_responses(*AUTH_ERRORS, LocationAssignmentNotFound),
)
async def delete_or_close_location_assignment(
    db: DbSession,
    current: CurrentUser,
    assignment_id: uuid.UUID,
) -> None:
    await service.delete_or_close(
        db,
        current.tenant_id,
        assignment_id,
        actor_user_id=current.user_id,
    )
