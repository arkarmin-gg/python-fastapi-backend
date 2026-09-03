import uuid
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import UnitKind
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class UnitRead(ResponseSchema):
    id: uuid.UUID
    code: str
    name_en: str
    name_my: str | None
    unit_kind: UnitKind
    is_global: bool
    is_active: bool


UnitListResponse = Page[UnitRead]


class UnitFilters(RequestSchema):
    search: str | None = None
    unit_kind: UnitKind | None = None
    is_global: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def unit_filters(
    search: Annotated[str | None, Query()] = None,
    unit_kind: Annotated[UnitKind | None, Query()] = None,
    is_global: Annotated[bool | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> UnitFilters:
    return build_query_model(
        UnitFilters,
        search=search,
        unit_kind=unit_kind,
        is_global=is_global,
        is_active=is_active,
    )


class UnitCreate(RequestSchema):
    code: str = Field(min_length=1, max_length=50)
    name_en: str = Field(min_length=1, max_length=120)
    name_my: str | None = Field(default=None, max_length=120)
    unit_kind: UnitKind
    is_global: bool = True
    is_active: bool = True


class UnitUpdate(RequestSchema):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    name_my: str | None = Field(default=None, max_length=120)
    unit_kind: UnitKind | None = None
    is_global: bool | None = None
    is_active: bool | None = None
