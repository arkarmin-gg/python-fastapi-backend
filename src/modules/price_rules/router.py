import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.dependencies import DbSession
from src.exceptions import InvalidToken
from src.modules.auth.dependencies import CurrentUser
from src.modules.auth.exceptions import InactiveUser
from src.modules.price_rules import service
from src.modules.price_rules.exceptions import (
    InvalidPriceRuleCustomer,
    InvalidPriceRuleEffectivePeriod,
    InvalidPriceRulePriceLevel,
    InvalidPriceRuleVariant,
    InvalidPriceRuleVariantUnit,
    PriceRuleNotFound,
    PriceRuleOverlapConflict,
)
from src.modules.price_rules.schemas import (
    PriceRuleCreate,
    PriceRuleFilters,
    PriceRuleListResponse,
    PriceRuleRead,
    PriceRuleUpdate,
    price_rule_filters,
)
from src.modules.rbac.dependencies import require_permission
from src.modules.rbac.exceptions import PermissionDenied
from src.pagination import PaginationParams, pagination_params
from src.query_filters import SortSpec, parse_sort
from src.schemas import error_responses

router = APIRouter(prefix="/price-rules", tags=["Price Rules"])

SORT_FIELDS = {"effective_from", "unit_price", "product_variant_id", "id"}
DEFAULT_SORT = ("product_variant_id", "effective_from", "id")
AUTH_ERRORS = (InvalidToken, InactiveUser, PermissionDenied)
VALIDATION_ERRORS = (
    PriceRuleOverlapConflict,
    InvalidPriceRuleVariant,
    InvalidPriceRuleVariantUnit,
    InvalidPriceRulePriceLevel,
    InvalidPriceRuleCustomer,
    InvalidPriceRuleEffectivePeriod,
)


def price_rule_sort(sort: Annotated[str | None, Query()] = None) -> tuple[SortSpec, ...]:
    return parse_sort(sort, allowed_fields=SORT_FIELDS, default=DEFAULT_SORT)


@router.get(
    "",
    response_model=PriceRuleListResponse,
    dependencies=[Depends(require_permission("price_rules.read"))],
    responses=error_responses(*AUTH_ERRORS),
)
async def list_price_rules(
    db: DbSession,
    current: CurrentUser,
    pagination: Annotated[PaginationParams, Depends(pagination_params)],
    filters: Annotated[PriceRuleFilters, Depends(price_rule_filters)],
    sort: Annotated[tuple[SortSpec, ...], Depends(price_rule_sort)],
):
    return await service.list_price_rules(db, current.tenant_id, pagination, filters, sort)


@router.post(
    "",
    response_model=PriceRuleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("price_rules.create"))],
    responses=error_responses(*AUTH_ERRORS, *VALIDATION_ERRORS),
)
async def create_price_rule(
    db: DbSession,
    current: CurrentUser,
    body: PriceRuleCreate,
):
    return await service.create(db, current.tenant_id, body, actor_user_id=current.user_id)


@router.get(
    "/{price_rule_id}",
    response_model=PriceRuleRead,
    dependencies=[Depends(require_permission("price_rules.read"))],
    responses=error_responses(*AUTH_ERRORS, PriceRuleNotFound),
)
async def get_price_rule(
    db: DbSession,
    current: CurrentUser,
    price_rule_id: uuid.UUID,
):
    price_rule = await service.get_by_id(db, current.tenant_id, price_rule_id)
    if price_rule is None:
        raise PriceRuleNotFound()
    return price_rule


@router.patch(
    "/{price_rule_id}",
    response_model=PriceRuleRead,
    dependencies=[Depends(require_permission("price_rules.update"))],
    responses=error_responses(*AUTH_ERRORS, PriceRuleNotFound, *VALIDATION_ERRORS),
)
async def update_price_rule(
    db: DbSession,
    current: CurrentUser,
    price_rule_id: uuid.UUID,
    body: PriceRuleUpdate,
):
    return await service.update(
        db,
        current.tenant_id,
        price_rule_id,
        body,
        actor_user_id=current.user_id,
    )


@router.delete(
    "/{price_rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(require_permission("price_rules.delete"))],
    responses=error_responses(*AUTH_ERRORS, PriceRuleNotFound),
)
async def deactivate_price_rule(
    db: DbSession,
    current: CurrentUser,
    price_rule_id: uuid.UUID,
) -> None:
    await service.deactivate(db, current.tenant_id, price_rule_id, actor_user_id=current.user_id)
