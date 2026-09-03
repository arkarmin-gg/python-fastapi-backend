import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.audit_logs.service import record_audit_log
from src.modules.codes.service import generate_code
from src.modules.employees.exceptions import EmployeeCodeConflict, EmployeeNotFound
from src.modules.employees.models import Employee
from src.modules.employees.schemas import EmployeeCreate, EmployeeFilters, EmployeeUpdate
from src.pagination import Page, PaginationParams, paginate
from src.query_filters import SortSpec, apply_sort, search_clause

EMPLOYEE_SORT_COLUMNS = {
    "code": Employee.code,
    "name": Employee.name,
    "created_at": Employee.created_at,
    "id": Employee.id,
}


async def get_by_id(
    db: AsyncSession, tenant_id: uuid.UUID, employee_id: uuid.UUID
) -> Employee | None:
    return await db.scalar(
        select(Employee).where(Employee.tenant_id == tenant_id, Employee.id == employee_id)
    )


async def list_employees(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    pagination: PaginationParams,
    filters: EmployeeFilters,
    sort: tuple[SortSpec, ...],
) -> Page[Employee]:
    stmt = _apply_filters(select(Employee).where(Employee.tenant_id == tenant_id), filters)
    stmt = apply_sort(stmt, sort, EMPLOYEE_SORT_COLUMNS)
    count_stmt = _apply_filters(
        select(func.count(Employee.id)).where(Employee.tenant_id == tenant_id), filters
    )
    return await paginate(db, stmt, count_stmt, pagination)


async def create(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    data: EmployeeCreate,
    *,
    actor_user_id: uuid.UUID,
) -> Employee:
    employee = Employee(
        tenant_id=tenant_id,
        code=await generate_code(db, tenant_id, "employee"),
        **data.model_dump(),
    )
    db.add(employee)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="employees.create",
        entity_type="employee",
        entity_id=employee.id,
        after_json=_loggable(employee),
    )
    await db.commit()
    await db.refresh(employee)
    return employee


async def update(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    data: EmployeeUpdate,
    *,
    actor_user_id: uuid.UUID,
) -> Employee:
    employee = await get_by_id(db, tenant_id, employee_id)
    if employee is None:
        raise EmployeeNotFound()
    before = _loggable(employee)
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(employee, key, value)
    await db.flush()
    await record_audit_log(
        db,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        action="employees.update",
        entity_type="employee",
        entity_id=employee.id,
        before_json=before,
        after_json=_loggable(employee),
    )
    await db.commit()
    await db.refresh(employee)
    return employee


async def deactivate(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    employee_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> None:
    await update(
        db, tenant_id, employee_id, EmployeeUpdate(is_active=False), actor_user_id=actor_user_id
    )


async def _ensure_code_available(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    code: str,
    *,
    employee_id: uuid.UUID | None = None,
) -> None:
    existing = await db.scalar(
        select(Employee).where(Employee.tenant_id == tenant_id, Employee.code == code)
    )
    if existing is not None and existing.id != employee_id:
        raise EmployeeCodeConflict()


def _apply_filters[StmtT: Select[Any]](stmt: StmtT, filters: EmployeeFilters) -> StmtT:
    search = search_clause(
        [Employee.code, Employee.name, Employee.phone, Employee.position], filters.search
    )
    if search is not None:
        stmt = stmt.where(search)
    if filters.is_active is not None:
        stmt = stmt.where(Employee.is_active == filters.is_active)
    return stmt


def _loggable(employee: Employee) -> dict[str, Any]:
    return {
        "code": employee.code,
        "name": employee.name,
        "phone": employee.phone,
        "position": employee.position,
        "is_active": employee.is_active,
    }
