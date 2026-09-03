import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import Query
from pydantic import Field, model_validator

from src.foundation_enums import AssignmentRole
from src.pagination import Page
from src.query_filters import build_query_model
from src.schemas import RequestSchema, ResponseSchema


class LocationAssignmentRead(ResponseSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    location_id: uuid.UUID
    employee_id: uuid.UUID
    role: AssignmentRole
    start_date: date
    end_date: date | None
    created_at: datetime


LocationAssignmentListResponse = Page[LocationAssignmentRead]


class LocationAssignmentFilters(RequestSchema):
    location_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    role: AssignmentRole | None = None
    start_date_gte: date | None = None
    start_date_lte: date | None = None
    end_date_is_null: bool | None = None


def location_assignment_filters(
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    employee_id: Annotated[uuid.UUID | None, Query()] = None,
    role: Annotated[AssignmentRole | None, Query()] = None,
    start_date_gte: Annotated[date | None, Query()] = None,
    start_date_lte: Annotated[date | None, Query()] = None,
    end_date_is_null: Annotated[bool | None, Query()] = None,
) -> LocationAssignmentFilters:
    return build_query_model(
        LocationAssignmentFilters,
        location_id=location_id,
        employee_id=employee_id,
        role=role,
        start_date_gte=start_date_gte,
        start_date_lte=start_date_lte,
        end_date_is_null=end_date_is_null,
    )


class LocationAssignmentCreate(RequestSchema):
    location_id: uuid.UUID
    employee_id: uuid.UUID
    role: AssignmentRole = AssignmentRole.RESPONSIBLE
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class LocationAssignmentUpdate(RequestSchema):
    location_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    role: AssignmentRole | None = None
    start_date: date | None = None
    end_date: date | None = Field(default=None)

    @model_validator(mode="after")
    def validate_period(self):
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("end_date must be on or after start_date")
        return self
