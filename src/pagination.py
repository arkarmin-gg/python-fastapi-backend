from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class PaginationParams(BaseModel):
    limit: int = Field(default=DEFAULT_PAGE_SIZE, description="Maximum number of items to return.")
    offset: int = Field(default=0, description="Number of items to skip before collecting results.")


class Page[ItemT](BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    items: list[ItemT] = Field(description="The page of results.")
    total: int = Field(description="Total number of items across all pages.")
    limit: int = Field(description="Maximum number of items requested per page.")
    offset: int = Field(description="Number of items skipped before this page.")


def pagination_params(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginationParams:
    return PaginationParams(limit=limit, offset=offset)


async def paginate[ItemT](
    db: AsyncSession,
    stmt: Select[tuple[ItemT]],
    count_stmt: Select[tuple[int]],
    pagination: PaginationParams,
) -> Page[ItemT]:
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))

    total = await db.scalar(count_stmt)

    return Page(
        items=list(result.scalars().all()),
        total=total or 0,
        limit=pagination.limit,
        offset=pagination.offset,
    )


async def get_all[ItemT](
    db: AsyncSession,
    stmt: Select[tuple[ItemT]],
) -> list[ItemT]:
    result = await db.execute(stmt)
    return list(result.scalars().all())
