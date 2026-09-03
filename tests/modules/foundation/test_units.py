from httpx import AsyncClient
from scripts.seed import _ensure_default_units, _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import UnitKind
from src.modules.audit_logs.models import AuditLog
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.units.constants import DEFAULT_UNITS
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_units_crud_is_permission_gated_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="units-crud")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("units", ActionType.CREATE),
            permission("units", ActionType.READ),
            permission("units", ActionType.UPDATE),
            permission("units", ActionType.DELETE),
        ],
    )
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/units",
        json={
            "code": "dozen",
            "name_en": "Dozen",
            "unit_kind": UnitKind.COUNT.value,
        },
        headers=headers,
    )
    assert created.status_code == 201
    unit_id = created.json()["id"]

    listed = await client.get("/api/v1/units?search=doz&sort=-name_en", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [unit_id]

    fetched = await client.get(f"/api/v1/units/{unit_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["code"] == "dozen"

    updated = await client.patch(
        f"/api/v1/units/{unit_id}",
        json={"name_my": "တစ်ဒါဇင်", "is_global": False},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name_my"] == "တစ်ဒါဇင်"
    assert updated.json()["is_global"] is False

    deleted = await client.delete(f"/api/v1/units/{unit_id}", headers=headers)
    assert deleted.status_code == 204

    unit = await db_session.scalar(select(Unit).where(Unit.id == unit_id))
    assert unit is not None
    assert unit.is_active is False

    audit_actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == unit.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert audit_actions == ["units.create", "units.update", "units.deactivate"]


async def test_units_duplicate_code_returns_conflict(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="units-conflict")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("units", ActionType.CREATE)],
    )
    headers = auth_headers(user_access_token(actor))

    payload = {
        "code": "box",
        "name_en": "Box",
        "unit_kind": UnitKind.PACKAGE.value,
    }
    first = await client.post("/api/v1/units", json=payload, headers=headers)
    second = await client.post("/api/v1/units", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error_code"] == "unit_code_conflict"


async def test_units_list_filters_and_sorting(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="units-list")
    actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("units", ActionType.READ)],
    )
    db_session.add_all(
        [
            Unit(code="kg", name_en="Kilogram", unit_kind=UnitKind.WEIGHT, is_active=True),
            Unit(code="box", name_en="Box", unit_kind=UnitKind.PACKAGE, is_active=False),
            Unit(code="pc", name_en="Piece", unit_kind=UnitKind.COUNT, is_active=True),
        ]
    )
    await db_session.flush()

    response = await client.get(
        "/api/v1/units?unit_kind=weight&is_active=true&sort=-code",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["code"] == "kg"


async def test_units_permission_denied_without_required_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="units-denied")
    actor = await make_user_with_permissions(db_session, tenant=tenant, permissions=[])

    response = await client.get(
        "/api/v1/units",
        headers=auth_headers(user_access_token(actor)),
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "permission_denied"


async def test_seed_adds_units_and_permissions_idempotently(db_session: AsyncSession) -> None:
    permissions_first = await _ensure_permissions(db_session)
    units_first = await _ensure_default_units(db_session)
    permissions_second = await _ensure_permissions(db_session)
    units_second = await _ensure_default_units(db_session)

    unit_rows = await db_session.execute(select(Unit.code).order_by(Unit.code))
    unit_codes = {code for (code,) in unit_rows.all()}
    unit_permission_codes = {
        code
        for (code,) in (
            await db_session.execute(
                select(Permission.code)
                .where(Permission.module == "units")
                .order_by(Permission.code)
            )
        ).all()
    }

    assert len(units_first) == len(DEFAULT_UNITS)
    assert len(units_second) == len(DEFAULT_UNITS)
    assert {unit["code"] for unit in DEFAULT_UNITS} <= unit_codes
    assert len(permissions_first) == len(permissions_second)
    assert unit_permission_codes == {
        "units.create",
        "units.delete",
        "units.read",
        "units.update",
    }
