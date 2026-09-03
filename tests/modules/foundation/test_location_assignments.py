import uuid
from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import AssignmentRole, LocationType
from src.modules.audit_logs.models import AuditLog
from src.modules.employees.models import Employee
from src.modules.location_assignments.models import LocationAssignment
from src.modules.locations.models import Location
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_location_assignment_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-crud")
    other_tenant = await make_tenant(db_session, code="location-assignments-other")
    location = await make_location(db_session, tenant_id=tenant.id, code="MAIN")
    employee = await make_employee(db_session, tenant_id=tenant.id, code="EMP-001")
    other_assignment = await make_location_assignment(
        db_session,
        tenant_id=other_tenant.id,
        location_id=(await make_location(db_session, tenant_id=other_tenant.id, code="OTHER")).id,
        employee_id=(await make_employee(db_session, tenant_id=other_tenant.id, code="OTHER")).id,
        start_date=date(2026, 1, 1),
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("location_assignments", ActionType.CREATE),
            permission("location_assignments", ActionType.READ),
            permission("location_assignments", ActionType.UPDATE),
            permission("location_assignments", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/location-assignments",
        json={
            "location_id": str(location.id),
            "employee_id": str(employee.id),
            "role": "responsible",
            "start_date": "2026-01-01",
        },
        headers=headers,
    )
    assert created.status_code == 201
    assignment_id = created.json()["id"]

    listed = await client.get(
        f"/api/v1/location-assignments?location_id={location.id}&sort=location_id,start_date,id",
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [assignment_id]

    fetched = await client.get(
        f"/api/v1/location-assignments/{assignment_id}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert fetched.json()["role"] == "responsible"

    not_found = await client.get(
        f"/api/v1/location-assignments/{other_assignment.id}",
        headers=headers,
    )
    assert not_found.status_code == 404

    updated = await client.patch(
        f"/api/v1/location-assignments/{assignment_id}",
        json={"role": "checker", "end_date": "2026-12-31"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "checker"
    assert updated.json()["end_date"] == "2026-12-31"

    deleted = await client.delete(
        f"/api/v1/location-assignments/{assignment_id}",
        headers=headers,
    )
    assert deleted.status_code == 204

    assignment = await db_session.scalar(
        select(LocationAssignment).where(LocationAssignment.id == uuid.UUID(assignment_id))
    )
    assert assignment is not None
    assert assignment.end_date == datetime.now(UTC).date()

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == assignment.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == [
        "location_assignments.create",
        "location_assignments.update",
        "location_assignments.close",
    ]


async def test_location_assignment_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/location-assignments",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_location_assignment_invalid_references_are_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-invalid")
    other_tenant = await make_tenant(db_session, code="location-assignments-invalid-other")
    active_location = await make_location(db_session, tenant_id=tenant.id, code="ACTIVE")
    inactive_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="INACTIVE",
        is_active=False,
    )
    other_location = await make_location(db_session, tenant_id=other_tenant.id, code="OTHER")
    active_employee = await make_employee(db_session, tenant_id=tenant.id, code="ACTIVE")
    inactive_employee = await make_employee(
        db_session,
        tenant_id=tenant.id,
        code="INACTIVE",
        is_active=False,
    )
    other_employee = await make_employee(db_session, tenant_id=other_tenant.id, code="OTHER")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("location_assignments", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))

    async def create_assignment(location_id: uuid.UUID, employee_id: uuid.UUID):
        return await client.post(
            "/api/v1/location-assignments",
            json={
                "location_id": str(location_id),
                "employee_id": str(employee_id),
                "start_date": "2026-01-01",
            },
            headers=headers,
        )

    invalid_locations = [
        await create_assignment(uuid.uuid4(), active_employee.id),
        await create_assignment(inactive_location.id, active_employee.id),
        await create_assignment(other_location.id, active_employee.id),
    ]
    invalid_employees = [
        await create_assignment(active_location.id, uuid.uuid4()),
        await create_assignment(active_location.id, inactive_employee.id),
        await create_assignment(active_location.id, other_employee.id),
    ]

    for response in invalid_locations:
        assert response.status_code == 400
        assert response.json()["error_code"] == "invalid_location_assignment_location"
    for response in invalid_employees:
        assert response.status_code == 400
        assert response.json()["error_code"] == "invalid_location_assignment_employee"


async def test_location_assignment_date_validation_rejects_invalid_period(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-dates")
    location = await make_location(db_session, tenant_id=tenant.id, code="MAIN")
    employee = await make_employee(db_session, tenant_id=tenant.id, code="EMP")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("location_assignments", ActionType.CREATE)],
    )

    response = await client.post(
        "/api/v1/location-assignments",
        json={
            "location_id": str(location.id),
            "employee_id": str(employee.id),
            "start_date": "2026-02-01",
            "end_date": "2026-01-31",
        },
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 422


async def test_location_assignment_overlap_rules(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-overlap")
    other_tenant = await make_tenant(db_session, code="location-assignments-overlap-other")
    location = await make_location(db_session, tenant_id=tenant.id, code="MAIN")
    employee = await make_employee(db_session, tenant_id=tenant.id, code="EMP")
    other_employee = await make_employee(db_session, tenant_id=tenant.id, code="OTHER-EMP")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("location_assignments", ActionType.CREATE),
            permission("location_assignments", ActionType.UPDATE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    base = await client.post(
        "/api/v1/location-assignments",
        json={
            "location_id": str(location.id),
            "employee_id": str(employee.id),
            "role": "responsible",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
        headers=headers,
    )
    same_scope_overlap = await client.post(
        "/api/v1/location-assignments",
        json={
            "location_id": str(location.id),
            "employee_id": str(other_employee.id),
            "role": "responsible",
            "start_date": "2026-01-15",
            "end_date": "2026-02-15",
        },
        headers=headers,
    )
    different_role_overlap = await client.post(
        "/api/v1/location-assignments",
        json={
            "location_id": str(location.id),
            "employee_id": str(other_employee.id),
            "role": "assistant",
            "start_date": "2026-01-15",
            "end_date": "2026-02-15",
        },
        headers=headers,
    )
    non_overlapping = await client.post(
        "/api/v1/location-assignments",
        json={
            "location_id": str(location.id),
            "employee_id": str(other_employee.id),
            "role": "responsible",
            "start_date": "2026-02-01",
        },
        headers=headers,
    )

    other_location = await make_location(db_session, tenant_id=other_tenant.id, code="OTHER")
    other_tenant_employee = await make_employee(
        db_session,
        tenant_id=other_tenant.id,
        code="OTHER",
    )
    await make_location_assignment(
        db_session,
        tenant_id=other_tenant.id,
        location_id=other_location.id,
        employee_id=other_tenant_employee.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    same_dates_other_tenant = await client.post(
        "/api/v1/location-assignments",
        json={
            "location_id": str(location.id),
            "employee_id": str(employee.id),
            "role": "checker",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
        headers=headers,
    )

    assert base.status_code == 201
    assert same_scope_overlap.status_code == 409
    assert same_scope_overlap.json()["error_code"] == "location_assignment_overlap_conflict"
    assert different_role_overlap.status_code == 201
    assert non_overlapping.status_code == 201
    assert same_dates_other_tenant.status_code == 201

    overlap_update = await client.patch(
        f"/api/v1/location-assignments/{non_overlapping.json()['id']}",
        json={"start_date": "2026-01-31"},
        headers=headers,
    )
    assert overlap_update.status_code == 409
    assert overlap_update.json()["error_code"] == "location_assignment_overlap_conflict"


async def test_location_assignment_list_filters_and_sorting(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-list")
    location = await make_location(db_session, tenant_id=tenant.id, code="MAIN")
    employee = await make_employee(db_session, tenant_id=tenant.id, code="EMP")
    match = await make_location_assignment(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        employee_id=employee.id,
        role=AssignmentRole.CHECKER,
        start_date=date(2026, 3, 1),
    )
    await make_location_assignment(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        employee_id=employee.id,
        role=AssignmentRole.ASSISTANT,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("location_assignments", ActionType.READ)],
    )

    response = await client.get(
        (
            "/api/v1/location-assignments"
            f"?location_id={location.id}"
            f"&employee_id={employee.id}"
            "&role=checker"
            "&start_date_gte=2026-02-01"
            "&start_date_lte=2026-04-01"
            "&end_date_is_null=true"
            "&sort=-start_date,id"
        ),
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(match.id)]


async def test_location_assignment_delete_closes_started_assignment(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-delete-close")
    location = await make_location(db_session, tenant_id=tenant.id, code="MAIN")
    employee = await make_employee(db_session, tenant_id=tenant.id, code="EMP")
    assignment = await make_location_assignment(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        employee_id=employee.id,
        start_date=date(2026, 1, 1),
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("location_assignments", ActionType.DELETE)],
    )
    today = datetime.now(UTC).date()

    response = await client.delete(
        f"/api/v1/location-assignments/{assignment.id}",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 204
    await db_session.refresh(assignment)
    assert assignment.end_date == today


async def test_location_assignment_delete_hard_deletes_future_scheduled_assignment(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-delete-future")
    location = await make_location(db_session, tenant_id=tenant.id, code="MAIN")
    employee = await make_employee(db_session, tenant_id=tenant.id, code="EMP")
    assignment = await make_location_assignment(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        employee_id=employee.id,
        start_date=datetime.now(UTC).date() + timedelta(days=30),
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("location_assignments", ActionType.DELETE)],
    )

    response = await client.delete(
        f"/api/v1/location-assignments/{assignment.id}",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 204
    deleted = await db_session.scalar(
        select(LocationAssignment).where(LocationAssignment.id == assignment.id)
    )
    assert deleted is None


async def test_location_assignment_delete_leaves_already_ended_assignment_unchanged(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="location-assignments-delete-ended")
    location = await make_location(db_session, tenant_id=tenant.id, code="MAIN")
    employee = await make_employee(db_session, tenant_id=tenant.id, code="EMP")
    assignment = await make_location_assignment(
        db_session,
        tenant_id=tenant.id,
        location_id=location.id,
        employee_id=employee.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("location_assignments", ActionType.DELETE)],
    )

    response = await client.delete(
        f"/api/v1/location-assignments/{assignment.id}",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 204
    await db_session.refresh(assignment)
    assert assignment.end_date == date(2026, 1, 31)


async def test_seed_adds_location_assignment_permissions(db_session: AsyncSession) -> None:
    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)

    rows = await db_session.execute(
        select(Permission.code)
        .where(Permission.module == "location_assignments")
        .order_by(Permission.code)
    )

    assert {code for (code,) in rows.all()} == {
        "location_assignments.create",
        "location_assignments.delete",
        "location_assignments.read",
        "location_assignments.update",
    }


async def make_location(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    location_type: LocationType = LocationType.WAREHOUSE,
    is_active: bool = True,
) -> Location:
    location = Location(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        location_type=location_type,
        is_active=is_active,
    )
    db_session.add(location)
    await db_session.flush()
    return location


async def make_employee(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    is_active: bool = True,
) -> Employee:
    employee = Employee(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        is_active=is_active,
    )
    db_session.add(employee)
    await db_session.flush()
    return employee


async def make_location_assignment(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    employee_id: uuid.UUID,
    role: AssignmentRole = AssignmentRole.RESPONSIBLE,
    start_date: date,
    end_date: date | None = None,
) -> LocationAssignment:
    assignment = LocationAssignment(
        tenant_id=tenant_id,
        location_id=location_id,
        employee_id=employee_id,
        role=role,
        start_date=start_date,
        end_date=end_date,
    )
    db_session.add(assignment)
    await db_session.flush()
    return assignment
