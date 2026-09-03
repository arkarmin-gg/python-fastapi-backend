import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from httpx import AsyncClient
from scripts.seed import _ensure_permissions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.foundation_enums import (
    DocumentStatus,
    LocationType,
    SourceType,
    StockAdjustmentReason,
    StockBatchStatus,
    StockMovementType,
    UnitKind,
)
from src.modules.audit_logs.models import AuditLog
from src.modules.catalog.models import CatalogItem, ProductVariant, VariantUnit
from src.modules.inventory.models import StockBalance, StockBatch, StockMovement
from src.modules.locations.models import Location
from src.modules.rbac.constants import ActionType
from src.modules.rbac.models import Permission
from src.modules.stock_adjustments.models import StockAdjustment
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_stock_adjustment_draft_then_post_is_atomic_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-adjustment-crud")
    other_tenant = await make_tenant(db_session, code="stock-adjustment-other")
    setup = await make_adjustment_setup(db_session, tenant_id=tenant.id, with_batch=False)
    other_setup = await make_adjustment_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="sa-other-unit",
        sku="SA-OTHER",
        location_code="SA-OTHER-WH",
    )
    other_adjustment = await make_stock_adjustment(
        db_session,
        tenant_id=other_tenant.id,
        location_id=other_setup.location.id,
        document_no="SA-001",
    )
    actor = await make_stock_adjustment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.post(
        "/api/v1/stock-adjustments",
        json={
            "location_id": str(setup.location.id),
            "reason": "opening_balance",
            "notes": "initial load",
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "quantity": "2.00000000",
                    "unit_cost_base": "100.00000000",
                    "lot_number": "OPEN-1",
                }
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    adjustment_id = body["id"]
    assert body["status"] == "draft"
    assert body["created_by"] == str(actor.id)
    assert len(body["lines"]) == 1
    line_id = body["lines"][0]["id"]
    assert body["lines"][0]["stock_batch_id"] is None
    assert body["lines"][0]["conversion_to_base"] == "12.00000000"
    assert body["lines"][0]["quantity_base"] == "24.00000000"
    assert await db_session.scalar(select(StockMovement.id)) is None

    listed = await client.get(
        (
            "/api/v1/stock-adjustments"
            "?search=initial"
            f"&location_id={setup.location.id}"
            "&reason=opening_balance"
            "&status=draft"
            "&created_at_gte=2026-08-08"
            "&sort=document_no,id"
        ),
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [adjustment_id]

    fetched = await client.get(f"/api/v1/stock-adjustments/{adjustment_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert len(fetched.json()["lines"]) == 1

    not_found = await client.get(
        f"/api/v1/stock-adjustments/{other_adjustment.id}",
        headers=headers,
    )
    assert not_found.status_code == 404

    posted = await client.post(f"/api/v1/stock-adjustments/{adjustment_id}/post", headers=headers)
    assert posted.status_code == 200
    body = posted.json()
    assert body["status"] == "posted"
    assert body["posted_by"] == str(actor.id)
    assert body["lines"][0]["stock_batch_id"] is not None

    listed_lines = await client.get(
        (
            f"/api/v1/stock-adjustments/{adjustment_id}/lines"
            f"?product_variant_id={setup.product_variant.id}"
            f"&variant_unit_id={setup.variant_unit.id}&sort=line_no,id"
        ),
        headers=headers,
    )
    assert listed_lines.status_code == 200
    assert [item["id"] for item in listed_lines.json()["items"]] == [line_id]

    fetched_line = await client.get(
        f"/api/v1/stock-adjustments/{adjustment_id}/lines/{line_id}", headers=headers
    )
    assert fetched_line.status_code == 200

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == uuid.UUID(adjustment_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert Counter(actions) == Counter(["stock_adjustments.create", "stock_adjustments.post"])


async def test_stock_adjustment_duplicate_document_no_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-adjustment-dup")
    other_tenant = await make_tenant(db_session, code="stock-adjustment-dup-other")
    setup = await make_adjustment_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_adjustment_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="dup-other-unit",
        sku="DUP-OTHER",
        location_code="DUP-OTHER-WH",
    )
    await make_stock_adjustment(
        db_session,
        tenant_id=tenant.id,
        location_id=setup.location.id,
        document_no="SA-DUP",
    )
    cross_tenant = await make_stock_adjustment(
        db_session,
        tenant_id=other_tenant.id,
        location_id=other_setup.location.id,
        document_no="SA-DUP",
    )
    actor = await make_stock_adjustment_actor(db_session, tenant=tenant)

    duplicate = await client.post(
        "/api/v1/stock-adjustments",
        json=adjustment_body(setup, document_no="SA-DUP"),
        headers=auth_headers(user_access_token(actor)),
    )

    assert duplicate.status_code == 201
    assert duplicate.json()["document_no"].startswith("SA-")
    assert cross_tenant.tenant_id == other_tenant.id


async def test_stock_adjustment_rejects_invalid_references_and_rolls_back(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-adjustment-invalid")
    tenant_id = tenant.id
    other_tenant = await make_tenant(db_session, code="stock-adjustment-invalid-other")
    setup = await make_adjustment_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_adjustment_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="invalid-other-unit",
        sku="INVALID-OTHER",
        location_code="INVALID-OTHER-WH",
    )
    inactive_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="SA-INACTIVE-WH",
        is_active=False,
    )
    inactive_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=setup.catalog_item.id,
        sku="SA-INACTIVE-V",
        base_unit_id=setup.unit.id,
        is_active=False,
    )
    service_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=setup.catalog_item.id,
        sku="SA-SERVICE-V",
        base_unit_id=setup.unit.id,
        track_inventory=False,
    )
    unmapped_unit = await make_unit(db_session, code="sa-unmapped-unit")
    unmapped_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_id=unmapped_unit.id,
        is_active=False,
    )
    other_batch = await make_stock_batch(
        db_session,
        tenant_id=other_tenant.id,
        product_variant_id=other_setup.product_variant.id,
    )
    actor = await make_stock_adjustment_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    invalid_location_body = {
        "location_id": str(inactive_location.id),
        "reason": "correction",
        "lines": [line_payload(setup)],
    }
    invalid_product_body = adjustment_body(
        setup,
        document_no="SA-BAD-PRODUCT",
        overrides={"product_variant_id": str(inactive_variant.id)},
    )
    service_line_body = adjustment_body(
        setup,
        document_no="SA-SERVICE-LINE",
        overrides={"product_variant_id": str(service_variant.id)},
    )
    invalid_unit_body = adjustment_body(
        setup,
        document_no="SA-BAD-UNIT",
        overrides={"variant_unit_id": str(unmapped_variant_unit.id)},
    )
    invalid_batch_body = adjustment_body(
        setup,
        document_no="SA-BAD-BATCH",
        overrides={"stock_batch_id": str(other_batch.id)},
    )
    missing_batch_body = adjustment_body(
        setup,
        document_no="SA-MISSING-BATCH",
        overrides={"stock_batch_id": None},
    )

    invalid_location = await client.post(
        "/api/v1/stock-adjustments", json=invalid_location_body, headers=headers
    )
    invalid_product = await client.post(
        "/api/v1/stock-adjustments", json=invalid_product_body, headers=headers
    )
    service_line = await client.post(
        "/api/v1/stock-adjustments", json=service_line_body, headers=headers
    )
    invalid_unit = await client.post(
        "/api/v1/stock-adjustments", json=invalid_unit_body, headers=headers
    )
    invalid_batch = await client.post(
        "/api/v1/stock-adjustments", json=invalid_batch_body, headers=headers
    )
    missing_batch = await client.post(
        "/api/v1/stock-adjustments", json=missing_batch_body, headers=headers
    )

    assert invalid_location.status_code == 400
    assert invalid_location.json()["error_code"] == "invalid_stock_adjustment_location"
    assert invalid_product.status_code == 400
    assert invalid_product.json()["error_code"] == "invalid_stock_adjustment_line_product"
    assert service_line.status_code == 400
    assert service_line.json()["error_code"] == "invalid_stock_adjustment_line_product"
    assert invalid_unit.status_code == 400
    assert invalid_unit.json()["error_code"] == "invalid_stock_adjustment_line_unit"
    assert invalid_batch.status_code == 400
    assert invalid_batch.json()["error_code"] == "invalid_stock_adjustment_line_batch"
    assert missing_batch.status_code == 400
    assert missing_batch.json()["error_code"] == "stock_adjustment_line_batch_required"

    persisted = (
        (
            await db_session.execute(
                select(StockAdjustment).where(StockAdjustment.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert persisted == []


async def test_opening_balance_create_creates_batch_movement_balance_and_audit(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-adjustment-opening")
    setup = await make_adjustment_setup(
        db_session,
        tenant_id=tenant.id,
        with_batch=False,
    )
    actor = await make_stock_adjustment_actor(
        db_session,
        tenant=tenant,
        extra_permissions=[permission("inventory", ActionType.READ)],
    )
    headers = auth_headers(user_access_token(actor))

    response = await client.post(
        "/api/v1/stock-adjustments",
        json={
            "location_id": str(setup.location.id),
            "reason": "opening_balance",
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "quantity": "5.00000000",
                    "unit_cost_base": "200.00000000",
                    "lot_number": "OPEN-LOT",
                    "manufactured_date": "2026-08-01",
                    "expiry_date": "2027-08-01",
                }
            ],
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["posted_by"] is None
    assert body["lines"][0]["stock_batch_id"] is None

    posted = await client.post(f"/api/v1/stock-adjustments/{body['id']}/post", headers=headers)
    assert posted.status_code == 200
    body = posted.json()
    assert body["status"] == "posted"
    assert body["posted_by"] == str(actor.id)
    line_row_id = uuid.UUID(body["lines"][0]["id"])
    stock_batch_id = uuid.UUID(body["lines"][0]["stock_batch_id"])
    assert stock_batch_id is not None

    batch = await db_session.scalar(select(StockBatch).where(StockBatch.id == stock_batch_id))
    movement = await db_session.scalar(
        select(StockMovement).where(StockMovement.source_line_id == line_row_id)
    )
    balance = await db_session.scalar(
        select(StockBalance).where(StockBalance.stock_batch_id == stock_batch_id)
    )
    assert batch is not None
    assert batch.product_variant_id == setup.product_variant.id
    assert batch.source_type == SourceType.STOCK_ADJUSTMENT
    assert batch.initial_quantity_base == Decimal("60.00000000")
    assert batch.unit_cost_base == Decimal("200.00000000")
    assert batch.lot_number == "OPEN-LOT"
    assert movement is not None
    assert movement.product_variant_id == setup.product_variant.id
    assert movement.movement_type == StockMovementType.ADJUSTMENT
    assert movement.quantity_base == Decimal("60.00000000")
    assert balance is not None
    assert balance.product_variant_id == setup.product_variant.id
    assert balance.quantity_base == Decimal("60.00000000")

    inventory = await client.get(
        f"/api/v1/stock-batches?source_type=stock_adjustment&source_id={body['id']}",
        headers=headers,
    )
    assert inventory.status_code == 200
    assert [item["id"] for item in inventory.json()["items"]] == [str(batch.id)]

    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant.id,
            AuditLog.action == "stock_adjustments.post",
            AuditLog.entity_id == uuid.UUID(body["id"]),
        )
    )
    assert audit is not None
    assert audit.after_json["posted_inventory"][0]["stock_batch_id"] == str(batch.id)


async def test_existing_batch_create_decreases_balance_and_maps_damage_loss(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-adjustment-damage")
    setup = await make_adjustment_setup(db_session, tenant_id=tenant.id)
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.location.id,
        stock_batch_id=setup.batch.id,
        quantity_base=Decimal("20.00000000"),
    )
    actor = await make_stock_adjustment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.post(
        "/api/v1/stock-adjustments",
        json={
            "location_id": str(setup.location.id),
            "reason": "damage",
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(setup.product_variant.id),
                    "stock_batch_id": str(setup.batch.id),
                    "variant_unit_id": str(setup.variant_unit.id),
                    "quantity": "-1.00000000",
                }
            ],
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"

    posted = await client.post(f"/api/v1/stock-adjustments/{body['id']}/post", headers=headers)
    assert posted.status_code == 200
    body = posted.json()
    assert body["status"] == "posted"
    assert body["lines"][0]["unit_cost_base"] == "10.00000000"

    balance = await db_session.scalar(
        select(StockBalance).where(
            StockBalance.tenant_id == tenant.id,
            StockBalance.stock_batch_id == setup.batch.id,
        )
    )
    movement = await db_session.scalar(
        select(StockMovement).where(
            StockMovement.source_line_id == uuid.UUID(body["lines"][0]["id"])
        )
    )
    assert balance is not None
    assert balance.quantity_base == Decimal("8.00000000")
    assert movement is not None
    assert movement.product_variant_id == setup.product_variant.id
    assert movement.movement_type == StockMovementType.DAMAGE_LOSS
    assert movement.quantity_base == Decimal("-12.00000000")


async def test_stock_adjustment_rejects_empty_lines_negative_balance_and_posted_mutations(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-adjustment-post-invalid")
    tenant_id = tenant.id
    setup = await make_adjustment_setup(db_session, tenant_id=tenant.id)
    location_id = setup.location.id
    posted_line_body = line_payload(setup)
    duplicate_line_body = {
        "location_id": str(location_id),
        "reason": "correction",
        "lines": [
            line_payload(setup, line_no=1),
            line_payload(setup, line_no=1),
        ],
    }
    negative_body = adjustment_body(
        setup,
        document_no="SA-NEG",
        overrides={"quantity": "-2.00000000"},
    )
    actor = await make_stock_adjustment_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    empty_lines = await client.post(
        "/api/v1/stock-adjustments",
        json={
            "location_id": str(setup.location.id),
            "reason": "correction",
            "lines": [],
        },
        headers=headers,
    )
    assert empty_lines.status_code == 201
    empty_post = await client.post(
        f"/api/v1/stock-adjustments/{empty_lines.json()['id']}/post",
        headers=headers,
    )
    assert empty_post.status_code == 400
    assert empty_post.json()["error_code"] == "stock_adjustment_has_no_lines"

    duplicate_line_no = await client.post(
        "/api/v1/stock-adjustments",
        json=duplicate_line_body,
        headers=headers,
    )
    assert duplicate_line_no.status_code == 422

    negative_create = await client.post(
        "/api/v1/stock-adjustments",
        json=negative_body,
        headers=headers,
    )
    assert negative_create.status_code == 201
    negative = await client.post(
        f"/api/v1/stock-adjustments/{negative_create.json()['id']}/post",
        headers=headers,
    )
    assert negative.status_code == 400
    assert negative.json()["error_code"] == "stock_adjustment_negative_balance"

    persisted = (
        (
            await db_session.execute(
                select(StockAdjustment).where(StockAdjustment.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(persisted) == 2
    assert {adjustment.status for adjustment in persisted} == {DocumentStatus.DRAFT}

    posted = await make_stock_adjustment(
        db_session,
        tenant_id=tenant_id,
        location_id=location_id,
        document_no="SA-POSTED",
        status=DocumentStatus.POSTED,
    )
    posted_id = posted.id
    await db_session.commit()
    update = await client.patch(
        f"/api/v1/stock-adjustments/{posted_id}",
        json={"notes": "nope"},
        headers=headers,
    )
    cancel = await client.delete(f"/api/v1/stock-adjustments/{posted_id}", headers=headers)
    repost = await client.post(f"/api/v1/stock-adjustments/{posted_id}/post", headers=headers)
    create_line = await client.post(
        f"/api/v1/stock-adjustments/{posted_id}/lines",
        json=posted_line_body,
        headers=headers,
    )
    assert update.status_code == 400
    assert update.json()["error_code"] == "stock_adjustment_not_draft"
    assert cancel.status_code == 400
    assert cancel.json()["error_code"] == "stock_adjustment_not_cancellable"
    assert repost.status_code == 400
    assert repost.json()["error_code"] == "stock_adjustment_not_postable"
    assert create_line.status_code == 400
    assert create_line.json()["error_code"] == "stock_adjustment_not_draft"


async def test_stock_adjustment_draft_header_line_crud_and_cancel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-adjustment-draft-crud")
    setup = await make_adjustment_setup(db_session, tenant_id=tenant.id)
    actor = await make_stock_adjustment_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/stock-adjustments",
        json={
            "location_id": str(setup.location.id),
            "reason": "correction",
            "notes": "draft",
        },
        headers=headers,
    )
    assert created.status_code == 201
    adjustment_id = created.json()["id"]
    assert created.json()["lines"] == []

    updated_header = await client.patch(
        f"/api/v1/stock-adjustments/{adjustment_id}",
        json={"notes": "updated"},
        headers=headers,
    )
    assert updated_header.status_code == 200
    assert updated_header.json()["document_no"].startswith("SA-2026")

    created_line = await client.post(
        f"/api/v1/stock-adjustments/{adjustment_id}/lines",
        json=line_payload(setup, line_no=1, quantity="1.00000000"),
        headers=headers,
    )
    assert created_line.status_code == 201
    line_id = created_line.json()["id"]
    assert created_line.json()["quantity_base"] == "12.00000000"

    duplicate_line = await client.post(
        f"/api/v1/stock-adjustments/{adjustment_id}/lines",
        json=line_payload(setup, line_no=1, quantity="1.00000000"),
        headers=headers,
    )
    assert duplicate_line.status_code == 409
    assert duplicate_line.json()["error_code"] == "stock_adjustment_line_no_conflict"

    updated_line = await client.patch(
        f"/api/v1/stock-adjustments/{adjustment_id}/lines/{line_id}",
        json={"line_no": 2, "quantity": "2.00000000", "notes": "count correction"},
        headers=headers,
    )
    assert updated_line.status_code == 200
    assert updated_line.json()["line_no"] == 2
    assert updated_line.json()["quantity_base"] == "24.00000000"

    deleted_line = await client.delete(
        f"/api/v1/stock-adjustments/{adjustment_id}/lines/{line_id}",
        headers=headers,
    )
    assert deleted_line.status_code == 204

    cancelled = await client.delete(f"/api/v1/stock-adjustments/{adjustment_id}", headers=headers)
    assert cancelled.status_code == 204
    cancelled_adjustment = await client.get(
        f"/api/v1/stock-adjustments/{adjustment_id}",
        headers=headers,
    )
    assert cancelled_adjustment.status_code == 200
    assert cancelled_adjustment.json()["status"] == "cancelled"
    assert cancelled_adjustment.json()["cancelled_by"] == str(actor.id)


async def test_stock_adjustment_permissions_and_seed(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-adjustment-permissions")
    setup = await make_adjustment_setup(db_session, tenant_id=tenant.id)
    read_only = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("stock_adjustments", ActionType.READ)],
    )
    headers = auth_headers(user_access_token(read_only))

    create_forbidden = await client.post(
        "/api/v1/stock-adjustments",
        json=adjustment_body(setup, document_no="SA-FORBIDDEN"),
        headers=headers,
    )
    assert create_forbidden.status_code == 403

    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)
    codes = (
        (
            await db_session.execute(
                select(Permission.code).where(Permission.module == "stock_adjustments")
            )
        )
        .scalars()
        .all()
    )
    assert sorted(codes) == [
        "stock_adjustments.create",
        "stock_adjustments.delete",
        "stock_adjustments.read",
        "stock_adjustments.update",
    ]


@dataclass
class AdjustmentSetup:
    unit: Unit
    catalog_item: CatalogItem
    product_variant: ProductVariant
    variant_unit: VariantUnit
    location: Location
    batch: StockBatch | None


def line_payload(
    setup: "AdjustmentSetup",
    *,
    quantity: str = "1.00000000",
    line_no: int = 1,
) -> dict[str, str | int | None]:
    return {
        "line_no": line_no,
        "product_variant_id": str(setup.product_variant.id),
        "stock_batch_id": str(setup.batch.id) if setup.batch else None,
        "variant_unit_id": str(setup.variant_unit.id),
        "quantity": quantity,
    }


def adjustment_body(
    setup: "AdjustmentSetup",
    *,
    document_no: str,
    reason: str = "correction",
    overrides: dict[str, str | None] | None = None,
) -> dict:
    line = line_payload(setup)
    line.update(overrides or {})
    return {
        "location_id": str(setup.location.id),
        "reason": reason,
        "lines": [line],
    }


async def make_adjustment_setup(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    unit_code: str = "stock-adjustment-unit",
    sku: str = "SA-SKU",
    location_code: str = "SA-WH",
    with_batch: bool = True,
) -> AdjustmentSetup:
    unit = await make_unit(db_session, code=unit_code)
    catalog_item = await make_catalog_item(db_session, tenant_id=tenant_id, name=sku.title())
    product_variant = await make_product_variant(
        db_session,
        tenant_id=tenant_id,
        catalog_item_id=catalog_item.id,
        sku=sku,
        base_unit_id=unit.id,
    )
    variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=product_variant.id,
        unit_id=unit.id,
        conversion_to_base=Decimal("12.00000000"),
    )
    location = await make_location(db_session, tenant_id=tenant_id, code=location_code)
    batch = None
    if with_batch:
        batch = await make_stock_batch(
            db_session,
            tenant_id=tenant_id,
            product_variant_id=product_variant.id,
            unit_cost_base=Decimal("10.00000000"),
        )
    return AdjustmentSetup(
        unit=unit,
        catalog_item=catalog_item,
        product_variant=product_variant,
        variant_unit=variant_unit,
        location=location,
        batch=batch,
    )


async def make_stock_adjustment_actor(
    db_session: AsyncSession,
    *,
    tenant,
    extra_permissions: list[str] | None = None,
):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("stock_adjustments", ActionType.CREATE),
            permission("stock_adjustments", ActionType.READ),
            permission("stock_adjustments", ActionType.UPDATE),
            permission("stock_adjustments", ActionType.DELETE),
            *(extra_permissions or []),
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
        track_inventory=track_inventory,
        is_active=is_active,
    )
    db_session.add(product_variant)
    await db_session.flush()
    return product_variant


async def make_variant_unit(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    unit_id: uuid.UUID,
    conversion_to_base: Decimal = Decimal("1.00000000"),
    is_active: bool = True,
) -> VariantUnit:
    variant_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        unit_id=unit_id,
        conversion_to_base=conversion_to_base,
        is_base_unit=True,
        is_purchase_unit=True,
        is_sales_unit=True,
        is_active=is_active,
    )
    db_session.add(variant_unit)
    await db_session.flush()
    return variant_unit


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


async def make_stock_adjustment(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    document_no: str = "SA-TEST",
    reason: StockAdjustmentReason = StockAdjustmentReason.CORRECTION,
    status: DocumentStatus = DocumentStatus.DRAFT,
) -> StockAdjustment:
    adjustment = StockAdjustment(
        tenant_id=tenant_id,
        document_no=document_no,
        location_id=location_id,
        reason=reason,
        status=status,
    )
    db_session.add(adjustment)
    await db_session.flush()
    return adjustment


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
