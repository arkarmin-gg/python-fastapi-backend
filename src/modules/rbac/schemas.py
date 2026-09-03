import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.pagination import Page
from src.query_filters import build_query_model, normalize_search
from src.schemas import RequestSchema, ResponseSchema


class PermissionRead(ResponseSchema):
    id: uuid.UUID
    code: str
    name: str
    module: str
    description: str | None


class RoleRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_system: bool
    is_active: bool
    permissions: list[PermissionRead]
    created_at: datetime
    updated_at: datetime


class RolePermissionRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    role_id: uuid.UUID
    permission_id: uuid.UUID


class UserRoleRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID


RoleListResponse = Page[RoleRead]
RolePermissionListResponse = Page[RolePermissionRead]
UserRoleListResponse = Page[UserRoleRead]


class RoleFilters(RequestSchema):
    search: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def normalize(self):
        self.search = normalize_search(self.search)
        return self


def role_filters(
    search: Annotated[str | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> RoleFilters:
    return build_query_model(RoleFilters, search=search, is_active=is_active)


class RolePermissionFilters(RequestSchema):
    role_id: uuid.UUID | None = None
    permission_id: uuid.UUID | None = None


def role_permission_filters(
    role_id: Annotated[uuid.UUID | None, Query()] = None,
    permission_id: Annotated[uuid.UUID | None, Query()] = None,
) -> RolePermissionFilters:
    return build_query_model(
        RolePermissionFilters,
        role_id=role_id,
        permission_id=permission_id,
    )


class UserRoleFilters(RequestSchema):
    user_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None


def user_role_filters(
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    role_id: Annotated[uuid.UUID | None, Query()] = None,
) -> UserRoleFilters:
    return build_query_model(UserRoleFilters, user_id=user_id, role_id=role_id)


class RoleCreate(RequestSchema):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    is_active: bool = True
    permission_ids: list[uuid.UUID] = Field(default_factory=list)


class RoleUpdate(RequestSchema):
    code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_active: bool | None = None
    permission_ids: list[uuid.UUID] | None = None


class RolePermissionCreate(RequestSchema):
    role_id: uuid.UUID
    permission_id: uuid.UUID


class UserRoleCreate(RequestSchema):
    user_id: uuid.UUID
    role_id: uuid.UUID
