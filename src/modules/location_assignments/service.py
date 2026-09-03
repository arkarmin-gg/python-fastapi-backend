import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.foundation_enums import AssignmentRole
from src.modules.audit_logs.service import record_audit_log
from src.modules.employees.models import Employee
from src.modules.location_assignments.exceptions import (
    InvalidLocationAssignmentEmployee,
    InvalidLocationAssignmentLocation,
    InvalidLocationAssignmentPeriod,
    LocationAssignmentNotFound,
    LocationAssignmentOverlapConflict,
)
from src.modules.location_assignments.models import LocationAssignment
from src.modules.location_assignments.schemas import (
    LocationAssignmentCreate,
    LocationAssignmentFilters,
    LocationAssignmentUpdate,
)
from src.modules.locations.models import Location
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort

LOCATION_ASSIGNMENT_SORT_COLUMNS = {
    "location_id": LocationAssignment.location_id,
    "employee_id": LocationAssignment.employee_id,
    "role": LocationAssignment.role,
    "start_date": LocationAssignment.start_date,
    "id": LocationAssignment.id,
}


async def get_by_id(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> LocationAssignment | None:
    return await db.scalar(
        select(LocationAssignment).where(
            LocationAssignment.tenant_id == tenant_id,
            LocationAssignment.id == assignment_id,
        )
    )


async def list_location_assignments(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: LocationAssignmentFilters,
    sort: tuple[SortSpec, ...],
) -> Page[LocationAssignment]:
    stmt = _apply_filters(
        select(LocationAssignment).where(LocationAssignment.tenant_id == tenant_id),
        filters,
    )
    stmt = apply_sort(stmt, sort, LOCATION_ASSIGNMENT_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(LocationAssignment.id)).where(LocationAssignment.tenant_id == tenant_id),
        filters,
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: LocationAssignmentCreate,
    *,
    actor_user_id: uuid.UUID,
) -> LocationAssignment:
    await _ensure_active_location(db, tenant_id, data.location_id)
    await _ensure_active_employee(db, tenant_id, data.employee_id)
    _ensure_valid_period(data.start_date, data.end_date)
    await _ensure_no_overlap(
        db,
        tenant_id=tenant_id,
        location_id=data.location_id,
        role=data.role,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    assignment = LocationAssignment(tenant_id=tenant_id, **data.model_dump())
    db.add(assignment)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="location_assignments.create",
        entity_type="location_assignment",
        entity_id=assignment.id,
        after_json=_loggable(assignment),
    )
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    data: LocationAssignmentUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> LocationAssignment:
    assignment = await get_by_id(db, tenant_id, assignment_id)
    if assignment is None:
        raise LocationAssignmentNotFound()
    before = _loggable(assignment)
    fields = data.model_dump(exclude_unset=True)
    new_location_id = fields.get("location_id", assignment.location_id)
    new_employee_id = fields.get("employee_id", assignment.employee_id)
    new_role = fields.get("role", assignment.role)
    new_start_date = fields.get("start_date", assignment.start_date)
    new_end_date = fields.get("end_date", assignment.end_date)

    if "location_id" in fields:
        await _ensure_active_location(db, tenant_id, new_location_id)
    if "employee_id" in fields:
        await _ensure_active_employee(db, tenant_id, new_employee_id)
    _ensure_valid_period(new_start_date, new_end_date)
    await _ensure_no_overlap(
        db,
        tenant_id=tenant_id,
        location_id=new_location_id,
        role=new_role,
        start_date=new_start_date,
        end_date=new_end_date,
        assignment_id=assignment.id,
    )
    for key, value in fields.items():
        setattr(assignment, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="location_assignments.update",
        entity_type="location_assignment",
        entity_id=assignment.id,
        before_json=before,
        after_json=_loggable(assignment),
    )
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def delete_or_close(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    today: date | None = None,
) -> None:
    assignment = await get_by_id(db, tenant_id, assignment_id)
    if assignment is None:
        raise LocationAssignmentNotFound()
    today = today or datetime.now(UTC).date()
    before = _loggable(assignment)
    if assignment.start_date > today:
        await db.delete(assignment)
        await db.flush()
        await record_audit_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="location_assignments.delete_scheduled",
            entity_type="location_assignment",
            entity_id=assignment.id,
            before_json=before,
        )
        await db.commit()
        return
    if assignment.end_date is None or assignment.end_date > today:
        assignment.end_date = today
        await db.flush()
        await record_audit_log(
            db,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="location_assignments.close",
            entity_type="location_assignment",
            entity_id=assignment.id,
            before_json=before,
            after_json=_loggable(assignment),
        )
        await db.commit()
        return
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="location_assignments.close",
        entity_type="location_assignment",
        entity_id=assignment.id,
        before_json=before,
        after_json=_loggable(assignment),
    )
    await db.commit()


async def _ensure_active_location(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
) -> None:
    location = await db.scalar(
        select(Location).where(Location.tenant_id == tenant_id, Location.id == location_id)
    )
    if location is None or not location.is_active:
        raise InvalidLocationAssignmentLocation()


async def _ensure_active_employee(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> None:
    employee = await db.scalar(
        select(Employee).where(Employee.tenant_id == tenant_id, Employee.id == employee_id)
    )
    if employee is None or not employee.is_active:
        raise InvalidLocationAssignmentEmployee()


async def _ensure_no_overlap(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    role: AssignmentRole,
    start_date: date,
    end_date: date | None,
    assignment_id: uuid.UUID | None = None,
) -> None:
    stmt = select(LocationAssignment).where(
        LocationAssignment.tenant_id == tenant_id,
        LocationAssignment.location_id == location_id,
        LocationAssignment.role == role,
        LocationAssignment.start_date <= (end_date or date.max),
        or_(
            LocationAssignment.end_date.is_(None),
            LocationAssignment.end_date >= start_date,
        ),
    )
    if assignment_id is not None:
        stmt = stmt.where(LocationAssignment.id != assignment_id)
    existing = await db.scalar(stmt.limit(1))
    if existing is not None:
        raise LocationAssignmentOverlapConflict()


def _ensure_valid_period(start_date: date, end_date: date | None) -> None:
    if end_date is not None and end_date < start_date:
        raise InvalidLocationAssignmentPeriod()


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: LocationAssignmentFilters) -> StmtT:
    if filters.location_id is not None:
        stmt = stmt.where(LocationAssignment.location_id == filters.location_id)
    if filters.employee_id is not None:
        stmt = stmt.where(LocationAssignment.employee_id == filters.employee_id)
    if filters.role is not None:
        stmt = stmt.where(LocationAssignment.role == filters.role)
    if filters.start_date_gte is not None:
        stmt = stmt.where(LocationAssignment.start_date >= filters.start_date_gte)
    if filters.start_date_lte is not None:
        stmt = stmt.where(LocationAssignment.start_date <= filters.start_date_lte)
    if filters.end_date_is_null is True:
        stmt = stmt.where(LocationAssignment.end_date.is_(None))
    elif filters.end_date_is_null is False:
        stmt = stmt.where(LocationAssignment.end_date.is_not(None))
    return stmt


def _loggable(assignment: LocationAssignment) -> dict[str, Any]:
    return {
        "location_id": str(assignment.location_id),
        "employee_id": str(assignment.employee_id),
        "role": assignment.role.value,
        "start_date": assignment.start_date.isoformat(),
        "end_date": assignment.end_date.isoformat() if assignment.end_date is not None else None,
    }
