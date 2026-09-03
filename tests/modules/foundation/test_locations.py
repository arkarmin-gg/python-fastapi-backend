import uuid

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import LocationType
from src.modules.audit_logs.models import AuditLog
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


async def test_location_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="locations-crud")
    other_tenant = await make_tenant(db_session, code="locations-other")
    other_location = await make_location(
        db_session,
        tenant_id=other_tenant.id,
        code="OTHER-STORE",
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("locations", ActionType.CREATE),
            permission("locations", ActionType.READ),
            permission("locations", ActionType.UPDATE),
            permission("locations", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/locations",
        json={
            "name": "Main Store",
            "location_type": "store",
            "is_sellable": True,
        },
        headers=headers,
    )
    assert created.status_code == 201
    location_id = created.json()["id"]
    assert created.json()["code"].startswith("LOC-")

    listed = await client.get(
        "/api/v1/locations?search=Main&sort=code,id",
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [location_id]

    fetched = await client.get(f"/api/v1/locations/{location_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert fetched.json()["location_type"] == "store"
    assert fetched.json()["is_sellable"] is True

    not_found = await client.get(f"/api/v1/locations/{other_location.id}", headers=headers)
    assert not_found.status_code == 404

    updated = await client.patch(
        f"/api/v1/locations/{location_id}",
        json={"name": "Main Counter", "location_type": "counter"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Main Counter"
    assert updated.json()["location_type"] == "counter"

    deleted = await client.delete(f"/api/v1/locations/{location_id}", headers=headers)
    assert deleted.status_code == 204

    location = await db_session.scalar(
        select(Location).where(Location.id == uuid.UUID(location_id))
    )
    assert location is not None
    assert location.is_active is False

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == location.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["locations.create", "locations.update", "locations.deactivate"]


async def test_location_rejects_client_code(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="locations-conflict")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("locations", ActionType.CREATE)],
    )

    response = await client.post(
        "/api/v1/locations",
        json={"code": "DUP", "name": "Duplicate", "location_type": "warehouse"},
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 422


async def test_location_list_filters_and_sorting(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="locations-list")
    parent = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="MAIN",
        name="Main Warehouse",
        location_type=LocationType.WAREHOUSE,
    )
    match = await make_location(
        db_session,
        tenant_id=tenant.id,
        parent_location_id=parent.id,
        code="COUNTER-B",
        name="Fresh Counter",
        location_type=LocationType.COUNTER,
        is_sellable=True,
    )
    await make_location(
        db_session,
        tenant_id=tenant.id,
        parent_location_id=parent.id,
        code="COUNTER-A",
        name="Dry Counter",
        location_type=LocationType.COUNTER,
        is_sellable=False,
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("locations", ActionType.READ)],
    )

    response = await client.get(
        (
            "/api/v1/locations"
            "?search=Fresh"
            f"&parent_location_id={parent.id}"
            "&location_type=counter"
            "&is_sellable=true"
            "&is_active=true"
            "&sort=-name,id"
        ),
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(match.id)]


async def test_location_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="locations-denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/locations",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_location_parent_validation_rejects_invalid_parents(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="locations-tree")
    other_tenant = await make_tenant(db_session, code="locations-tree-other")
    parent = await make_location(db_session, tenant_id=tenant.id, code="PARENT")
    child = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="CHILD",
        parent_location_id=parent.id,
    )
    inactive_parent = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="INACTIVE",
        is_active=False,
    )
    other_parent = await make_location(
        db_session,
        tenant_id=other_tenant.id,
        code="OTHER-PARENT",
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("locations", ActionType.CREATE),
            permission("locations", ActionType.UPDATE),
            permission("locations", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    missing_parent = await client.post(
        "/api/v1/locations",
        json={
            "name": "Missing Parent",
            "location_type": "warehouse",
            "parent_location_id": str(uuid.uuid4()),
        },
        headers=headers,
    )
    cross_tenant_parent = await client.post(
        "/api/v1/locations",
        json={
            "name": "Cross Parent",
            "location_type": "warehouse",
            "parent_location_id": str(other_parent.id),
        },
        headers=headers,
    )
    inactive_parent_response = await client.post(
        "/api/v1/locations",
        json={
            "name": "Inactive Parent",
            "location_type": "warehouse",
            "parent_location_id": str(inactive_parent.id),
        },
        headers=headers,
    )
    self_parent = await client.patch(
        f"/api/v1/locations/{parent.id}",
        json={"parent_location_id": str(parent.id)},
        headers=headers,
    )
    cycle = await client.patch(
        f"/api/v1/locations/{parent.id}",
        json={"parent_location_id": str(child.id)},
        headers=headers,
    )

    for response in (
        missing_parent,
        cross_tenant_parent,
        inactive_parent_response,
        self_parent,
        cycle,
    ):
        assert response.status_code == 400
        assert response.json()["error_code"] == "invalid_parent_location"


async def test_location_deactivate_does_not_cascade_to_children(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="locations-delete-tree")
    parent = await make_location(db_session, tenant_id=tenant.id, code="PARENT")
    child = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="CHILD",
        parent_location_id=parent.id,
    )
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("locations", ActionType.DELETE)],
    )

    response = await client.delete(
        f"/api/v1/locations/{parent.id}",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 204
    await db_session.refresh(parent)
    await db_session.refresh(child)
    assert parent.is_active is False
    assert child.is_active is True
    assert child.parent_location_id == parent.id


async def test_seed_adds_location_permissions(db_session: AsyncSession) -> None:
    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)

    rows = await db_session.execute(
        select(Permission.code).where(Permission.module == "locations").order_by(Permission.code)
    )

    assert {code for (code,) in rows.all()} == {
        "locations.create",
        "locations.delete",
        "locations.read",
        "locations.update",
    }


async def make_location(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    name: str | None = None,
    parent_location_id: uuid.UUID | None = None,
    location_type: LocationType = LocationType.WAREHOUSE,
    is_sellable: bool = False,
    is_active: bool = True,
) -> Location:
    location = Location(
        tenant_id=tenant_id,
        parent_location_id=parent_location_id,
        code=code,
        name=name or code.title(),
        location_type=location_type,
        is_sellable=is_sellable,
        is_active=is_active,
    )
    db_session.add(location)
    await db_session.flush()
    return location
