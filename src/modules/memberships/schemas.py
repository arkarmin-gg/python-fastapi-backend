import uuid
from datetime import datetime
from typing import Annotated

from fastapi import Query

from src.foundation_enums import MembershipStatus
from src.pagination import Page
from src.query_filters import build_query_model
from src.schemas import RequestSchema, ResponseSchema


class MembershipRead(ResponseSchema):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    status: MembershipStatus
    invited_by_membership_id: uuid.UUID | None
    invited_by_user_name: str | None
    invited_at: datetime | None
    joined_at: datetime | None
    activated_at: datetime | None
    suspended_at: datetime | None
    removed_at: datetime | None
    created_at: datetime
    updated_at: datetime


MembershipListResponse = Page[MembershipRead]


class MembershipFilters(RequestSchema):
    user_id: uuid.UUID | None = None
    status: MembershipStatus | None = None


def membership_filters(
    user_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[MembershipStatus | None, Query()] = None,
) -> MembershipFilters:
    return build_query_model(MembershipFilters, user_id=user_id, status=status)


class MembershipInvite(RequestSchema):
    user_id: uuid.UUID


class MembershipUpdate(RequestSchema):
    status: MembershipStatus
