import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import OrganizationStatus
from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class OrganizationRead(ResponseSchema):
    id: uuid.UUID
    code: str
    name: str
    status: OrganizationStatus
    suspended_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


OrganizationListResponse = Page[OrganizationRead]


class OrganizationFilters(RequestSchema):
    search: str | None = None
    status: OrganizationStatus | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def organization_filters(
    search: Annotated[str | None, Query()] = None,
    status: Annotated[OrganizationStatus | None, Query()] = None,
) -> OrganizationFilters:
    return build_query_model(OrganizationFilters, search=search, status=status)


class OrganizationCreate(RequestSchema):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)


class OrganizationUpdate(RequestSchema):
    code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: OrganizationStatus | None = None
