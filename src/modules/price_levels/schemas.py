import uuid
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class PriceLevelRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_default: bool
    is_active: bool


PriceLevelListResponse = Page[PriceLevelRead]


class PriceLevelFilters(RequestSchema):
    search: str | None = None
    is_default: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def price_level_filters(
    search: Annotated[str | None, Query()] = None,
    is_default: Annotated[bool | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> PriceLevelFilters:
    return build_query_model(
        PriceLevelFilters,
        search=search,
        is_default=is_default,
        is_active=is_active,
    )


class PriceLevelCreate(RequestSchema):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    is_default: bool = False
    is_active: bool = True


class PriceLevelUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_default: bool | None = None
    is_active: bool | None = None
