import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class ProductCategoryRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    parent_category_id: uuid.UUID | None
    code: str | None
    name: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


ProductCategoryListResponse = Page[ProductCategoryRead]


class ProductCategoryFilters(RequestSchema):
    search: str | None = None
    parent_category_id: uuid.UUID | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def product_category_filters(
    search: Annotated[str | None, Query()] = None,
    parent_category_id: Annotated[uuid.UUID | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> ProductCategoryFilters:
    return build_query_model(
        ProductCategoryFilters,
        search=search,
        parent_category_id=parent_category_id,
        is_active=is_active,
    )


class ProductCategoryCreate(RequestSchema):
    parent_category_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    is_active: bool = True


class ProductCategoryUpdate(RequestSchema):
    parent_category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    is_active: bool | None = None
