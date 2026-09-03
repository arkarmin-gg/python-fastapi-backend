import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class EmployeeRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    phone: str | None
    position: str | None
    joined_date: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


EmployeeListResponse = Page[EmployeeRead]


class EmployeeFilters(RequestSchema):
    search: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def employee_filters(
    search: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> EmployeeFilters:
    return build_query_model(EmployeeFilters, search=search, is_active=is_active)


class EmployeeCreate(RequestSchema):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    position: str | None = Field(default=None, max_length=120)
    joined_date: date | None = None
    is_active: bool = True


class EmployeeUpdate(RequestSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    position: str | None = Field(default=None, max_length=120)
    joined_date: date | None = None
    is_active: bool | None = None
