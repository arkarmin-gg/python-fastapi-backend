import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.modules.repack_orders import service
from src.modules.repack_orders.exceptions import (
    InvalidRepackOrderEmployee,
    InvalidRepackOrderInputBatch,
    InvalidRepackOrderInputProduct,
    InvalidRepackOrderInputUnit,
    InvalidRepackOrderLocation,
    InvalidRepackOrderOutputProduct,
    InvalidRepackOrderOutputUnit,
    RepackOrderDocumentNoConflict,
    RepackOrderHasNoInputs,
    RepackOrderHasNoOutputs,
    RepackOrderInputLineNoConflict,
    RepackOrderInputNotFound,
    RepackOrderInsufficientBalance,
    RepackOrderNotCancellable,
    RepackOrderNotDraft,
    RepackOrderNotFound,
    RepackOrderNotPostable,
    RepackOrderOutputCostExceedsInputCost,
    RepackOrderOutputLineNoConflict,
    RepackOrderOutputNotFound,
    RepackOrderOutputQuantityExceedsInputQuantity,
)
from src.modules.repack_orders.schemas import (
    RepackOrderCreate,
    RepackOrderDetailRead,
    RepackOrderFilters,
    RepackOrderInputCreate,
    RepackOrderInputFilters,
    RepackOrderInputListResponse,
    RepackOrderInputRead,
    RepackOrderInputUpdate,
    RepackOrderListResponse,
    RepackOrderOutputCreate,
    RepackOrderOutputFilters,
    RepackOrderOutputListResponse,
    RepackOrderOutputRead,
    RepackOrderOutputUpdate,
    RepackOrderUpdate,
    repack_order_filters,
    repack_order_input_filters,
    repack_order_output_filters,
)
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/repack-orders", tags=["Repack Orders"])

ORDER_SORT_FIELDS = {"document_no", "status", "created_at", "id"}
ORDER_DEFAULT_SORT = ("document_no", "id")
INPUT_SORT_FIELDS = {"line_no", "product_variant_id", "stock_batch_id", "id"}
INPUT_DEFAULT_SORT = ("line_no", "id")
OUTPUT_SORT_FIELDS = {"line_no", "product_variant_id", "created_stock_batch_id", "id"}
OUTPUT_DEFAULT_SORT = ("line_no", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
CREATE_VALIDATION_ERRORS = (
    RepackOrderDocumentNoConflict,
    InvalidRepackOrderLocation,
    InvalidRepackOrderEmployee,
    InvalidRepackOrderInputProduct,
    InvalidRepackOrderInputUnit,
    InvalidRepackOrderInputBatch,
    InvalidRepackOrderOutputProduct,
    InvalidRepackOrderOutputUnit,
    RepackOrderOutputCostExceedsInputCost,
    RepackOrderOutputQuantityExceedsInputQuantity,
)
INPUT_VALIDATION_ERRORS = (
    RepackOrderInputLineNoConflict,
    InvalidRepackOrderInputProduct,
    InvalidRepackOrderInputUnit,
    InvalidRepackOrderInputBatch,
    RepackOrderNotDraft,
    RepackOrderOutputCostExceedsInputCost,
    RepackOrderOutputQuantityExceedsInputQuantity,
)
OUTPUT_VALIDATION_ERRORS = (
    RepackOrderOutputLineNoConflict,
    InvalidRepackOrderOutputProduct,
    InvalidRepackOrderOutputUnit,
    RepackOrderNotDraft,
    RepackOrderOutputCostExceedsInputCost,
    RepackOrderOutputQuantityExceedsInputQuantity,
)
WORKFLOW_ERRORS = (
    RepackOrderHasNoInputs,
    RepackOrderHasNoOutputs,
    RepackOrderNotPostable,
    RepackOrderNotCancellable,
    InvalidRepackOrderLocation,
    InvalidRepackOrderEmployee,
    InvalidRepackOrderInputProduct,
    InvalidRepackOrderInputUnit,
    InvalidRepackOrderInputBatch,
    RepackOrderInsufficientBalance,
    InvalidRepackOrderOutputProduct,
    InvalidRepackOrderOutputUnit,
    RepackOrderOutputCostExceedsInputCost,
    RepackOrderOutputQuantityExceedsInputQuantity,
)


def repack_order_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=ORDER_SORT_FIELDS, default=ORDER_DEFAULT_SORT)


def repack_order_input_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=INPUT_SORT_FIELDS, default=INPUT_DEFAULT_SORT)


def repack_order_output_sort(
    sort: Annotated[str | None, Query()] = None,
) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=OUTPUT_SORT_FIELDS, default=OUTPUT_DEFAULT_SORT)


@router.get(
    "",
    response_model=RepackOrderListResponse,
    dependencies=[Depends(require_permission("repack_orders.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_repack_orders(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[RepackOrderFilters, Depends(repack_order_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(repack_order_sort)],
):
    return await service.list_repack_orders(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=RepackOrderDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("repack_orders.create"))],
    responses=error_responses(*AUTH_ERRORS, *CREATE_VALIDATION_ERRORS),
)
async def create_repack_order(
    db: DbSession,
    current: CurrentUser,
    body: RepackOrderCreate,
):
    return await service.create_order(
        db,
        current.tenant_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{repack_order_id}",
    response_model=RepackOrderDetailRead,
    dependencies=[Depends(require_permission("repack_orders.read"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound),
)
async def get_repack_order(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
):
    order = await service.get_order_detail_by_id(db, current.tenant_id, repack_order_id)
    if order is None:
        raise RepackOrderNotFound()
    return order


@router.patch(
    "/{repack_order_id}",
    response_model=RepackOrderDetailRead,
    dependencies=[Depends(require_permission("repack_orders.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        RepackOrderNotFound,
        RepackOrderNotDraft,
        *CREATE_VALIDATION_ERRORS,
    ),
)
async def update_repack_order(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    body: RepackOrderUpdate,
):
    return await service.update_order(
        db,
        current.tenant_id,
        repack_order_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{repack_order_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("repack_orders.delete"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound, RepackOrderNotCancellable),
)
async def cancel_repack_order(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
) -> None:
    await service.cancel_order(
        db,
        current.tenant_id,
        repack_order_id,
        actor_user_id=current.user_id,
    )


@router.post(
    "/{repack_order_id}/post",
    response_model=RepackOrderDetailRead,
    dependencies=[Depends(require_permission("repack_orders.update"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound, *WORKFLOW_ERRORS),
)
async def post_repack_order(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
):
    return await service.post_order(
        db,
        current.tenant_id,
        repack_order_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{repack_order_id}/inputs",
    response_model=RepackOrderInputListResponse,
    dependencies=[Depends(require_permission("repack_orders.read"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound),
)
async def list_repack_order_inputs(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[RepackOrderInputFilters, Depends(repack_order_input_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(repack_order_input_sort)],
):
    return await service.list_inputs(
        db,
        current.tenant_id,
        repack_order_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/{repack_order_id}/inputs",
    response_model=RepackOrderInputRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("repack_orders.create"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound, *INPUT_VALIDATION_ERRORS),
)
async def create_repack_order_input(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    body: RepackOrderInputCreate,
):
    return await service.create_input(
        db,
        current.tenant_id,
        repack_order_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{repack_order_id}/inputs/{input_id}",
    response_model=RepackOrderInputRead,
    dependencies=[Depends(require_permission("repack_orders.read"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound, RepackOrderInputNotFound),
)
async def get_repack_order_input(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    input_id: uuid.UUID,
):
    order = await service.get_by_id(db, current.tenant_id, repack_order_id)
    if order is None:
        raise RepackOrderNotFound()
    line = await service.get_input_by_id(db, current.tenant_id, repack_order_id, input_id)
    if line is None:
        raise RepackOrderInputNotFound()
    return line


@router.patch(
    "/{repack_order_id}/inputs/{input_id}",
    response_model=RepackOrderInputRead,
    dependencies=[Depends(require_permission("repack_orders.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        RepackOrderNotFound,
        RepackOrderInputNotFound,
        *INPUT_VALIDATION_ERRORS,
    ),
)
async def update_repack_order_input(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    input_id: uuid.UUID,
    body: RepackOrderInputUpdate,
):
    return await service.update_input(
        db,
        current.tenant_id,
        repack_order_id,
        input_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{repack_order_id}/inputs/{input_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("repack_orders.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        RepackOrderNotFound,
        RepackOrderInputNotFound,
        RepackOrderNotDraft,
        RepackOrderOutputCostExceedsInputCost,
        RepackOrderOutputQuantityExceedsInputQuantity,
    ),
)
async def delete_repack_order_input(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    input_id: uuid.UUID,
) -> None:
    await service.delete_input(
        db,
        current.tenant_id,
        repack_order_id,
        input_id,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{repack_order_id}/outputs",
    response_model=RepackOrderOutputListResponse,
    dependencies=[Depends(require_permission("repack_orders.read"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound),
)
async def list_repack_order_outputs(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[RepackOrderOutputFilters, Depends(repack_order_output_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(repack_order_output_sort)],
):
    return await service.list_outputs(
        db,
        current.tenant_id,
        repack_order_id,
        pagination,
        filters,
        sort,
    )


@router.post(
    "/{repack_order_id}/outputs",
    response_model=RepackOrderOutputRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("repack_orders.create"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound, *OUTPUT_VALIDATION_ERRORS),
)
async def create_repack_order_output(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    body: RepackOrderOutputCreate,
):
    return await service.create_output(
        db,
        current.tenant_id,
        repack_order_id,
        body,
        actor_user_id=current.user_id,
    )


@router.get(
    "/{repack_order_id}/outputs/{output_id}",
    response_model=RepackOrderOutputRead,
    dependencies=[Depends(require_permission("repack_orders.read"))],
    responses=error_responses(*AUTH_ERRORS, RepackOrderNotFound, RepackOrderOutputNotFound),
)
async def get_repack_order_output(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    output_id: uuid.UUID,
):
    order = await service.get_by_id(db, current.tenant_id, repack_order_id)
    if order is None:
        raise RepackOrderNotFound()
    line = await service.get_output_by_id(db, current.tenant_id, repack_order_id, output_id)
    if line is None:
        raise RepackOrderOutputNotFound()
    return line


@router.patch(
    "/{repack_order_id}/outputs/{output_id}",
    response_model=RepackOrderOutputRead,
    dependencies=[Depends(require_permission("repack_orders.update"))],
    responses=error_responses(
        *AUTH_ERRORS,
        RepackOrderNotFound,
        RepackOrderOutputNotFound,
        *OUTPUT_VALIDATION_ERRORS,
    ),
)
async def update_repack_order_output(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    output_id: uuid.UUID,
    body: RepackOrderOutputUpdate,
):
    return await service.update_output(
        db,
        current.tenant_id,
        repack_order_id,
        output_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{repack_order_id}/outputs/{output_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("repack_orders.delete"))],
    responses=error_responses(
        *AUTH_ERRORS,
        RepackOrderNotFound,
        RepackOrderOutputNotFound,
        RepackOrderNotDraft,
    ),
)
async def delete_repack_order_output(
    db: DbSession,
    current: CurrentUser,
    repack_order_id: uuid.UUID,
    output_id: uuid.UUID,
) -> None:
    await service.delete_output(
        db,
        current.tenant_id,
        repack_order_id,
        output_id,
        actor_user_id=current.user_id,
    )
