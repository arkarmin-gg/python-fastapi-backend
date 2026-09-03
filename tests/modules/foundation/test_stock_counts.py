import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import (
    DocumentStatus,
    LocationType,
    SourceType,
    StockBatchStatus,
    StockMovementType,
    UnitKind,
)
from src.modules.audit_logs.models import AuditLog
from src.modules.catalog.models import CatalogItem, ProductVariant
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.rbac.constants import ActionType
from src.modules.stock_counts import service
from src.modules.stock_counts.models import StockCount, StockCountLine
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_stock_count_header_and_line_crud_is_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-count-crud")
    other_tenant = await make_tenant(db_session, code="stock-count-other")
    setup = await make_count_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_count_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="sc-other-unit",
        sku="SC-OTHER",
        location_code="SC-OTHER-WH",
    )
    other_count = await make_stock_count(
        db_session,
        tenant_id=other_tenant.id,
        location_id=other_setup.location.id,
        counted_by=(await make_stock_count_actor(db_session, tenant=other_tenant)).id,
        document_no="SC-001",
    )
    actor = await make_stock_count_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/stock-counts",
        json={
            "location_id": str(setup.location.id),
            "counted_at": "2026-08-09T09:00:00+00:00",
            "notes": "monthly count",
        },
        headers=headers,
    )
    assert created.status_code == 201
    count_id = created.json()["id"]
    assert created.json()["status"] == "draft"
    assert created.json()["counted_by"] == str(actor.id)

    listed = await client.get(
        (
            "/api/v1/stock-counts"
            "?search=monthly"
            f"&location_id={setup.location.id}"
            "&status=draft"
            "&counted_at_gte=2026-08-09"
            "&sort=document_no,id"
        ),
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [count_id]

    fetched = await client.get(f"/api/v1/stock-counts/{count_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert fetched.json()["lines"] == []

    not_found = await client.get(f"/api/v1/stock-counts/{other_count.id}", headers=headers)
    assert not_found.status_code == 404

    line = await client.post(
        f"/api/v1/stock-counts/{count_id}/lines",
        json={
            "line_no": 1,
            "product_variant_id": str(setup.product_variant.id),
            "stock_batch_id": str(setup.batch.id),
            "counted_quantity_base": "12.00000000",
            "notes": "front shelf",
        },
        headers=headers,
    )
    assert line.status_code == 201
    line_id = line.json()["id"]
    assert line.json()["expected_quantity_base"] == "10.00000000"
    assert line.json()["variance_quantity_base"] == "2.00000000"
    assert "product_id" not in line.json()

    fetched_with_line = await client.get(f"/api/v1/stock-counts/{count_id}", headers=headers)
    assert fetched_with_line.status_code == 200
    assert len(fetched_with_line.json()["lines"]) == 1
    assert fetched_with_line.json()["lines"][0]["id"] == line_id
    assert fetched_with_line.json()["lines"][0]["variance_quantity_base"] == "2.00000000"

    listed_lines = await client.get(
        (
            f"/api/v1/stock-counts/{count_id}/lines"
            f"?product_variant_id={setup.product_variant.id}"
            f"&stock_batch_id={setup.batch.id}&sort=line_no,id"
        ),
        headers=headers,
    )
    assert listed_lines.status_code == 200
    assert [item["id"] for item in listed_lines.json()["items"]] == [line_id]

    updated_line = await client.patch(
        f"/api/v1/stock-counts/{count_id}/lines/{line_id}",
        json={"counted_quantity_base": "8.00000000", "notes": "back shelf"},
        headers=headers,
    )
    assert updated_line.status_code == 200
    assert updated_line.json()["variance_quantity_base"] == "-2.00000000"

    deleted_line = await client.delete(
        f"/api/v1/stock-counts/{count_id}/lines/{line_id}",
        headers=headers,
    )
    assert deleted_line.status_code == 204
    assert (
        await db_session.scalar(
            select(StockCountLine).where(StockCountLine.id == uuid.UUID(line_id))
        )
    ) is None

    updated = await client.patch(
        f"/api/v1/stock-counts/{count_id}",
        json={"notes": "updated draft"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["notes"] == "updated draft"

    cancelled = await client.delete(f"/api/v1/stock-counts/{count_id}", headers=headers)
    assert cancelled.status_code == 204
    count = await db_session.scalar(select(StockCount).where(StockCount.id == uuid.UUID(count_id)))
    assert count is not None
    assert count.status == DocumentStatus.CANCELLED

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id.in_([count.id, uuid.UUID(line_id)]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert Counter(actions) == Counter(
        [
            "stock_counts.create",
            "stock_count_lines.create",
            "stock_count_lines.update",
            "stock_count_lines.delete",
            "stock_counts.update",
            "stock_counts.cancel",
        ]
    )


async def test_stock_count_detail_read_returns_nested_lines(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-count-detail")
    setup = await make_count_setup(db_session, tenant_id=tenant.id)
    actor = await make_stock_count_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    count = await create_count_via_api(client, headers, setup, document_no="SC-DETAIL")
    line_one = await create_line_via_api(
        client,
        headers,
        count_id=count["id"],
        setup=setup,
        counted_quantity_base="12.00000000",
    )
    line_two = await client.post(
        f"/api/v1/stock-counts/{count['id']}/lines",
        json={
            "line_no": 2,
            "product_variant_id": str(setup.product_variant.id),
            "stock_batch_id": str(setup.batch.id),
            "counted_quantity_base": "9.00000000",
        },
        headers=headers,
    )
    assert line_two.status_code == 201

    detail = await client.get(f"/api/v1/stock-counts/{count['id']}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["document_no"].startswith("SC-2026")
    assert body["status"] == "draft"
    assert {line["id"] for line in body["lines"]} == {line_one["id"], line_two.json()["id"]}

    listed_lines = await client.get(
        f"/api/v1/stock-counts/{count['id']}/lines",
        headers=headers,
    )
    assert listed_lines.status_code == 200
    assert {item["id"] for item in listed_lines.json()["items"]} == {
        line_one["id"],
        line_two.json()["id"],
    }


async def test_stock_count_rejects_duplicates_permissions_and_invalid_references(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-count-invalid")
    other_tenant = await make_tenant(db_session, code="stock-count-invalid-other")
    setup = await make_count_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_count_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="sc-invalid-other-unit",
        sku="SC-INVALID-OTHER",
        location_code="SC-INVALID-OTHER-WH",
    )
    inactive_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="SC-INACTIVE-WH",
        is_active=False,
    )
    inactive_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=setup.catalog_item.id,
        sku="SC-INACTIVE-V",
        base_unit_id=setup.unit.id,
        is_active=False,
    )
    other_batch = await make_stock_batch(
        db_session,
        tenant_id=other_tenant.id,
        product_variant_id=other_setup.product_variant.id,
    )
    actor = await make_stock_count_actor(db_session, tenant=tenant)
    await make_stock_count(
        db_session,
        tenant_id=tenant.id,
        location_id=setup.location.id,
        counted_by=actor.id,
        document_no="SC-DUP",
    )
    headers = auth_headers(user_access_token(actor))

    duplicate = await client.post(
        "/api/v1/stock-counts",
        json={"location_id": str(setup.location.id)},
        headers=headers,
    )
    invalid_location = await client.post(
        "/api/v1/stock-counts",
        json={"location_id": str(inactive_location.id)},
        headers=headers,
    )
    restricted_actor = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("stock_counts", ActionType.READ)],
    )
    denied = await client.post(
        "/api/v1/stock-counts",
        json={"location_id": str(setup.location.id)},
        headers=auth_headers(user_access_token(restricted_actor)),
    )
    count = await create_count_via_api(client, headers, setup)
    invalid_product = await client.post(
        f"/api/v1/stock-counts/{count['id']}/lines",
        json={
            "line_no": 1,
            "product_variant_id": str(inactive_variant.id),
            "stock_batch_id": str(setup.batch.id),
            "counted_quantity_base": "1.00000000",
        },
        headers=headers,
    )
    invalid_batch = await client.post(
        f"/api/v1/stock-counts/{count['id']}/lines",
        json={
            "line_no": 1,
            "product_variant_id": str(setup.product_variant.id),
            "stock_batch_id": str(other_batch.id),
            "counted_quantity_base": "1.00000000",
        },
        headers=headers,
    )
    invalid_quantity = await client.post(
        f"/api/v1/stock-counts/{count['id']}/lines",
        json={
            "line_no": 1,
            "product_variant_id": str(setup.product_variant.id),
            "stock_batch_id": str(setup.batch.id),
            "counted_quantity_base": "-1.00000000",
        },
        headers=headers,
    )

    assert duplicate.status_code == 201
    assert duplicate.json()["document_no"].startswith("SC-")
    assert invalid_location.status_code == 400
    assert invalid_location.json()["error_code"] == "invalid_stock_count_location"
    assert denied.status_code == 403
    assert invalid_product.status_code == 400
    assert invalid_product.json()["error_code"] == "invalid_stock_count_line_product"
    assert invalid_batch.status_code == 400
    assert invalid_batch.json()["error_code"] == "invalid_stock_count_line_batch"
    assert invalid_quantity.status_code == 422


async def test_stock_count_approval_workflow_and_posting_side_effects(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-count-post")
    setup = await make_count_setup(db_session, tenant_id=tenant.id)
    actor = await make_stock_count_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    empty_count = await create_count_via_api(client, headers, setup, document_no="SC-EMPTY")
    empty_submit = await client.post(
        f"/api/v1/stock-counts/{empty_count['id']}/submit",
        headers=headers,
    )
    assert empty_submit.status_code == 400
    assert empty_submit.json()["error_code"] == "stock_count_has_no_lines"

    count = await create_count_via_api(client, headers, setup, document_no="SC-WORKFLOW")
    line = await create_line_via_api(
        client,
        headers,
        count_id=count["id"],
        setup=setup,
        counted_quantity_base="12.00000000",
    )
    assert line["variance_quantity_base"] == "2.00000000"

    submit = await client.post(f"/api/v1/stock-counts/{count['id']}/submit", headers=headers)
    assert submit.status_code == 200
    assert submit.json()["status"] == "pending_approval"

    pending_update = await client.patch(
        f"/api/v1/stock-counts/{count['id']}",
        json={"notes": "blocked"},
        headers=headers,
    )
    pending_line_update = await client.patch(
        f"/api/v1/stock-counts/{count['id']}/lines/{line['id']}",
        json={"counted_quantity_base": "11.00000000"},
        headers=headers,
    )
    assert pending_update.status_code == 400
    assert pending_update.json()["error_code"] == "stock_count_not_draft"
    assert pending_line_update.status_code == 400
    assert pending_line_update.json()["error_code"] == "stock_count_not_draft"

    reject = await client.post(f"/api/v1/stock-counts/{count['id']}/reject", headers=headers)
    assert reject.status_code == 200
    assert reject.json()["status"] == "draft"

    resubmit = await client.post(f"/api/v1/stock-counts/{count['id']}/submit", headers=headers)
    approve = await client.post(f"/api/v1/stock-counts/{count['id']}/approve", headers=headers)
    assert resubmit.status_code == 200
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"
    assert approve.json()["approved_by"] == str(actor.id)

    approved_update = await client.patch(
        f"/api/v1/stock-counts/{count['id']}",
        json={"notes": "blocked"},
        headers=headers,
    )
    assert approved_update.status_code == 400
    assert approved_update.json()["error_code"] == "stock_count_not_draft"

    post = await client.post(f"/api/v1/stock-counts/{count['id']}/post", headers=headers)
    assert post.status_code == 200
    assert post.json()["status"] == "posted"
    assert post.json()["posted_by"] == str(actor.id)

    balance = await db_session.scalar(
        select(StockBalance).where(
            StockBalance.tenant_id == tenant.id,
            StockBalance.product_variant_id == setup.product_variant.id,
            StockBalance.location_id == setup.location.id,
            StockBalance.stock_batch_id == setup.batch.id,
        )
    )
    assert balance is not None
    assert balance.quantity_base == Decimal("12.00000000")
    movement = await db_session.scalar(
        select(StockMovement).where(
            StockMovement.tenant_id == tenant.id,
            StockMovement.source_type == SourceType.STOCK_COUNT,
            StockMovement.source_id == uuid.UUID(count["id"]),
        )
    )
    assert movement is not None
    assert movement.product_variant_id == setup.product_variant.id
    assert movement.movement_type == StockMovementType.COUNT_ADJUSTMENT
    assert movement.quantity_base == Decimal("2.00000000")
    posted_line = await db_session.scalar(
        select(StockCountLine).where(StockCountLine.id == uuid.UUID(line["id"]))
    )
    assert posted_line is not None
    assert posted_line.adjustment_movement_id == movement.id

    posted_update = await client.patch(
        f"/api/v1/stock-counts/{count['id']}",
        json={"notes": "blocked"},
        headers=headers,
    )
    assert posted_update.status_code == 400
    assert posted_update.json()["error_code"] == "stock_count_not_draft"


async def test_stock_count_zero_variance_and_negative_balance_rules(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-count-zero-negative")
    setup = await make_count_setup(db_session, tenant_id=tenant.id)
    actor = await make_stock_count_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    zero_count = await create_count_via_api(client, headers, setup, document_no="SC-ZERO")
    zero_line = await create_line_via_api(
        client,
        headers,
        count_id=zero_count["id"],
        setup=setup,
        counted_quantity_base="10.00000000",
    )
    assert zero_line["variance_quantity_base"] == "0.00000000"
    await client.post(f"/api/v1/stock-counts/{zero_count['id']}/submit", headers=headers)
    await client.post(f"/api/v1/stock-counts/{zero_count['id']}/approve", headers=headers)
    zero_post = await client.post(f"/api/v1/stock-counts/{zero_count['id']}/post", headers=headers)
    movement_count = await db_session.scalar(
        select(func.count(StockMovement.id)).where(
            StockMovement.tenant_id == tenant.id,
            StockMovement.source_id == uuid.UUID(zero_count["id"]),
        )
    )
    assert zero_post.status_code == 200
    assert movement_count == 0

    negative_count = await create_count_via_api(client, headers, setup, document_no="SC-NEG")
    await create_line_via_api(
        client,
        headers,
        count_id=negative_count["id"],
        setup=setup,
        counted_quantity_base="0.00000000",
    )
    setup.balance.quantity_base = Decimal("5.00000000")
    await db_session.flush()
    await client.post(f"/api/v1/stock-counts/{negative_count['id']}/submit", headers=headers)
    await client.post(f"/api/v1/stock-counts/{negative_count['id']}/approve", headers=headers)
    negative_post = await client.post(
        f"/api/v1/stock-counts/{negative_count['id']}/post",
        headers=headers,
    )
    assert negative_post.status_code == 400
    assert negative_post.json()["error_code"] == "stock_count_negative_balance"


async def test_stock_count_post_rolls_back_and_reraises_on_unexpected_error(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = await make_tenant(db_session, code="stock-count-post-rollback")
    setup = await make_count_setup(db_session, tenant_id=tenant.id)
    actor = await make_stock_count_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    count = await create_count_via_api(client, headers, setup, document_no="SC-ROLLBACK")
    line = await create_line_via_api(
        client,
        headers,
        count_id=count["id"],
        setup=setup,
        counted_quantity_base="12.00000000",
    )
    await client.post(f"/api/v1/stock-counts/{count['id']}/submit", headers=headers)
    await client.post(f"/api/v1/stock-counts/{count['id']}/approve", headers=headers)

    tenant_id = tenant.id
    actor_id = actor.id
    count_id = uuid.UUID(count["id"])
    line_id = uuid.UUID(line["id"])

    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "record_audit_log", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        await service.post_count(
            db_session,
            tenant_id,
            count_id,
            actor_user_id=actor_id,
        )

    reloaded = await db_session.scalar(select(StockCount).where(StockCount.id == count_id))
    assert reloaded is not None
    assert reloaded.status == DocumentStatus.APPROVED
    assert reloaded.posted_at is None
    assert reloaded.posted_by is None

    movement = await db_session.scalar(
        select(StockMovement).where(
            StockMovement.tenant_id == tenant_id,
            StockMovement.source_type == SourceType.STOCK_COUNT,
            StockMovement.source_id == count_id,
        )
    )
    assert movement is None

    reloaded_line = await db_session.scalar(
        select(StockCountLine).where(StockCountLine.id == line_id)
    )
    assert reloaded_line is not None
    assert reloaded_line.adjustment_movement_id is None


@dataclass
class CountSetup:
    unit: Unit
    catalog_item: CatalogItem
    product_variant: ProductVariant
    location: Location
    batch: StockBatch
    balance: StockBalance


async def create_count_via_api(
    client: AsyncClient,
    headers: dict[str, str],
    setup: CountSetup,
    *,
    document_no: str = "SC-API",
) -> dict:
    response = await client.post(
        "/api/v1/stock-counts",
        json={"location_id": str(setup.location.id)},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


async def create_line_via_api(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    count_id: str,
    setup: CountSetup,
    counted_quantity_base: str,
) -> dict:
    response = await client.post(
        f"/api/v1/stock-counts/{count_id}/lines",
        json={
            "line_no": 1,
            "product_variant_id": str(setup.product_variant.id),
            "stock_batch_id": str(setup.batch.id),
            "counted_quantity_base": counted_quantity_base,
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


async def make_count_setup(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    unit_code: str = "sc-piece",
    sku: str = "SC-SKU",
    location_code: str = "SC-WH",
) -> CountSetup:
    unit = await make_unit(db_session, code=unit_code)
    catalog_item = await make_catalog_item(db_session, tenant_id=tenant_id, name=sku.title())
    product_variant = await make_product_variant(
        db_session,
        tenant_id=tenant_id,
        catalog_item_id=catalog_item.id,
        sku=sku,
        base_unit_id=unit.id,
    )
    location = await make_location(db_session, tenant_id=tenant_id, code=location_code)
    batch = await make_stock_batch(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=product_variant.id,
    )
    balance = await make_stock_balance(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=product_variant.id,
        location_id=location.id,
        stock_batch_id=batch.id,
        quantity_base=Decimal("10.00000000"),
    )
    return CountSetup(
        unit=unit,
        catalog_item=catalog_item,
        product_variant=product_variant,
        location=location,
        batch=batch,
        balance=balance,
    )


async def make_stock_count_actor(db_session: AsyncSession, *, tenant):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("stock_counts", ActionType.CREATE),
            permission("stock_counts", ActionType.READ),
            permission("stock_counts", ActionType.UPDATE),
            permission("stock_counts", ActionType.DELETE),
        ],
    )


async def make_unit(db_session: AsyncSession, *, code: str) -> Unit:
    unit = Unit(code=code, name_en=code.title(), unit_kind=UnitKind.COUNT)
    db_session.add(unit)
    await db_session.flush()
    return unit


async def make_catalog_item(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    is_active: bool = True,
) -> CatalogItem:
    catalog_item = CatalogItem(
        tenant_id=tenant_id,
        code=f"ITEM-{uuid.uuid4().hex[:8]}",
        name=name,
        is_active=is_active,
    )
    db_session.add(catalog_item)
    await db_session.flush()
    return catalog_item


async def make_product_variant(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    catalog_item_id: uuid.UUID,
    sku: str,
    base_unit_id: uuid.UUID,
    is_active: bool = True,
    track_inventory: bool = True,
) -> ProductVariant:
    product_variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=catalog_item_id,
        sku=sku,
        name=sku.title(),
        base_unit_id=base_unit_id,
        is_active=is_active,
        track_inventory=track_inventory,
    )
    db_session.add(product_variant)
    await db_session.flush()
    return product_variant


async def make_location(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    code: str,
    is_active: bool = True,
) -> Location:
    location = Location(
        tenant_id=tenant_id,
        code=code,
        name=code.title(),
        location_type=LocationType.WAREHOUSE,
        is_active=is_active,
    )
    db_session.add(location)
    await db_session.flush()
    return location


async def make_stock_count(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    counted_by: uuid.UUID,
    document_no: str = "SC-TEST",
    status: DocumentStatus = DocumentStatus.DRAFT,
) -> StockCount:
    count = StockCount(
        tenant_id=tenant_id,
        document_no=document_no,
        location_id=location_id,
        counted_at=datetime.now(UTC),
        counted_by=counted_by,
        status=status,
    )
    db_session.add(count)
    await db_session.flush()
    return count


async def make_stock_batch(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    unit_cost_base: Decimal = Decimal("10.00000000"),
    status: StockBatchStatus = StockBatchStatus.ACTIVE,
) -> StockBatch:
    now = datetime.now(UTC)
    batch = StockBatch(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        source_type=SourceType.MANUAL,
        source_id=uuid.uuid4(),
        received_at=now,
        initial_quantity_base=Decimal("0.00000000"),
        unit_cost_base=unit_cost_base,
        total_cost=Decimal("0.0000"),
        conversion_to_base=Decimal("1.00000000"),
        status=status,
        created_at=now,
    )
    db_session.add(batch)
    await db_session.flush()
    return batch


async def make_stock_balance(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    location_id: uuid.UUID,
    stock_batch_id: uuid.UUID,
    quantity_base: Decimal,
) -> StockBalance:
    balance = StockBalance(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        location_id=location_id,
        stock_batch_id=stock_batch_id,
        quantity_base=quantity_base,
        updated_at=datetime.now(UTC),
    )
    db_session.add(balance)
    await db_session.flush()
    return balance
