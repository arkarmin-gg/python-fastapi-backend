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
from src.modules.stock_transfers.models import StockTransfer, StockTransferLine
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_stock_transfer_draft_then_post_is_atomic_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-transfer-crud")
    other_tenant = await make_tenant(db_session, code="stock-transfer-other")
    setup = await make_transfer_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_transfer_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="st-other-unit",
        sku="ST-OTHER",
        from_location_code="ST-OTHER-FROM",
        to_location_code="ST-OTHER-TO",
    )
    other_transfer = await make_stock_transfer(
        db_session,
        tenant_id=other_tenant.id,
        document_no="ST-001",
    )
    actor = await make_stock_transfer_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.from_location.id,
        stock_batch_id=setup.batch.id,
        quantity_base=Decimal("100.00000000"),
    )

    response = await client.post(
        "/api/v1/stock-transfers",
        json={
            "notes": "move to shop",
            "lines": [line_payload(setup, quantity="2.00000000")],
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    transfer_id = body["id"]
    assert body["status"] == "draft"
    assert body["requested_by"] == str(actor.id)
    assert len(body["lines"]) == 1
    line_id = body["lines"][0]["id"]
    assert body["lines"][0]["conversion_to_base"] == "12.00000000"
    assert body["lines"][0]["quantity_base"] == "24.00000000"
    assert await db_session.scalar(select(StockMovement.id)) is None

    listed = await client.get(
        (
            "/api/v1/stock-transfers"
            "?search=shop"
            "&status=draft"
            f"&requested_by={actor.id}"
            "&created_at_gte=2026-08-08"
            "&sort=document_no,id"
        ),
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [transfer_id]

    fetched = await client.get(f"/api/v1/stock-transfers/{transfer_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert len(fetched.json()["lines"]) == 1

    not_found = await client.get(f"/api/v1/stock-transfers/{other_transfer.id}", headers=headers)
    assert not_found.status_code == 404

    posted = await client.post(f"/api/v1/stock-transfers/{transfer_id}/post", headers=headers)
    assert posted.status_code == 200
    body = posted.json()
    assert body["status"] == "posted"
    assert body["posted_by"] == str(actor.id)

    listed_lines = await client.get(
        (
            f"/api/v1/stock-transfers/{transfer_id}/lines"
            f"?product_variant_id={setup.product_variant.id}"
            f"&stock_batch_id={setup.batch.id}"
            f"&variant_unit_id={setup.variant_unit.id}"
            f"&from_location_id={setup.from_location.id}"
            f"&to_location_id={setup.to_location.id}"
            "&sort=line_no,id"
        ),
        headers=headers,
    )
    assert listed_lines.status_code == 200
    assert [item["id"] for item in listed_lines.json()["items"]] == [line_id]

    fetched_line = await client.get(
        f"/api/v1/stock-transfers/{transfer_id}/lines/{line_id}", headers=headers
    )
    assert fetched_line.status_code == 200

    source_balance = await db_session.scalar(
        select(StockBalance).where(
            StockBalance.tenant_id == tenant.id,
            StockBalance.product_variant_id == setup.product_variant.id,
            StockBalance.location_id == setup.from_location.id,
            StockBalance.stock_batch_id == setup.batch.id,
        )
    )
    destination_balance = await db_session.scalar(
        select(StockBalance).where(
            StockBalance.tenant_id == tenant.id,
            StockBalance.product_variant_id == setup.product_variant.id,
            StockBalance.location_id == setup.to_location.id,
            StockBalance.stock_batch_id == setup.batch.id,
        )
    )
    assert source_balance is not None
    assert source_balance.quantity_base == Decimal("76.00000000")
    assert destination_balance is not None
    assert destination_balance.quantity_base == Decimal("24.00000000")

    movements = (
        (
            await db_session.execute(
                select(StockMovement)
                .where(
                    StockMovement.tenant_id == tenant.id,
                    StockMovement.source_type == SourceType.STOCK_TRANSFER,
                    StockMovement.source_id == uuid.UUID(transfer_id),
                )
                .order_by(StockMovement.quantity_base)
            )
        )
        .scalars()
        .all()
    )
    assert [movement.movement_type for movement in movements] == [
        StockMovementType.TRANSFER_OUT,
        StockMovementType.TRANSFER_IN,
    ]
    assert [movement.quantity_base for movement in movements] == [
        Decimal("-24.00000000"),
        Decimal("24.00000000"),
    ]

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == uuid.UUID(transfer_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert Counter(actions) == Counter(["stock_transfers.create", "stock_transfers.post"])
    assert other_setup.batch.tenant_id == other_tenant.id


async def test_stock_transfer_draft_header_line_mutation_and_cancel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-transfer-draft")
    setup = await make_transfer_setup(db_session, tenant_id=tenant.id)
    actor = await make_stock_transfer_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/stock-transfers",
        json={
            "notes": "before update",
            "lines": [],
        },
        headers=headers,
    )
    assert created.status_code == 201
    transfer_id = created.json()["id"]
    assert created.json()["status"] == "draft"
    assert created.json()["lines"] == []

    updated = await client.patch(
        f"/api/v1/stock-transfers/{transfer_id}",
        json={"notes": "after update"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["document_no"].startswith("ST-2026")
    assert updated.json()["notes"] == "after update"

    line = await client.post(
        f"/api/v1/stock-transfers/{transfer_id}/lines",
        json=line_payload(setup, quantity="2.00000000"),
        headers=headers,
    )
    assert line.status_code == 201
    line_id = line.json()["id"]
    assert line.json()["quantity_base"] == "24.00000000"

    duplicate_line_no = await client.post(
        f"/api/v1/stock-transfers/{transfer_id}/lines",
        json=line_payload(setup, line_no=1),
        headers=headers,
    )
    assert duplicate_line_no.status_code == 409
    assert duplicate_line_no.json()["error_code"] == "stock_transfer_line_no_conflict"

    updated_line = await client.patch(
        f"/api/v1/stock-transfers/{transfer_id}/lines/{line_id}",
        json={"line_no": 2, "quantity": "3.00000000"},
        headers=headers,
    )
    assert updated_line.status_code == 200
    assert updated_line.json()["line_no"] == 2
    assert updated_line.json()["quantity_base"] == "36.00000000"

    deleted_line = await client.delete(
        f"/api/v1/stock-transfers/{transfer_id}/lines/{line_id}",
        headers=headers,
    )
    assert deleted_line.status_code == 204

    replacement = await client.post(
        f"/api/v1/stock-transfers/{transfer_id}/lines",
        json=line_payload(setup, line_no=1),
        headers=headers,
    )
    assert replacement.status_code == 201

    cancelled = await client.delete(f"/api/v1/stock-transfers/{transfer_id}", headers=headers)
    assert cancelled.status_code == 204
    fetched = await client.get(f"/api/v1/stock-transfers/{transfer_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "cancelled"
    assert fetched.json()["cancelled_by"] == str(actor.id)

    after_cancel = await client.patch(
        f"/api/v1/stock-transfers/{transfer_id}",
        json={"notes": "too late"},
        headers=headers,
    )
    assert after_cancel.status_code == 400
    assert after_cancel.json()["error_code"] == "stock_transfer_not_draft"


async def test_stock_transfer_duplicate_document_no_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-transfer-dup")
    other_tenant = await make_tenant(db_session, code="stock-transfer-dup-other")
    setup = await make_transfer_setup(db_session, tenant_id=tenant.id)
    await make_stock_transfer(db_session, tenant_id=tenant.id, document_no="ST-DUP")
    cross_tenant = await make_stock_transfer(
        db_session,
        tenant_id=other_tenant.id,
        document_no="ST-DUP",
    )
    actor = await make_stock_transfer_actor(db_session, tenant=tenant)

    duplicate = await client.post(
        "/api/v1/stock-transfers",
        json={
            "lines": [line_payload(setup)],
        },
        headers=auth_headers(user_access_token(actor)),
    )

    assert duplicate.status_code == 201
    assert duplicate.json()["document_no"].startswith("ST-")
    assert cross_tenant.tenant_id == other_tenant.id


async def test_stock_transfer_rejects_invalid_line_references_and_rolls_back(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-transfer-invalid")
    tenant_id = tenant.id
    other_tenant = await make_tenant(db_session, code="stock-transfer-invalid-other")
    setup = await make_transfer_setup(db_session, tenant_id=tenant.id)
    await make_stock_balance(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        location_id=setup.from_location.id,
        stock_batch_id=setup.batch.id,
        quantity_base=Decimal("20.00000000"),
    )
    other_setup = await make_transfer_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="st-invalid-other-unit",
        sku="ST-INVALID-OTHER",
        from_location_code="ST-INVALID-OTHER-FROM",
        to_location_code="ST-INVALID-OTHER-TO",
    )
    inactive_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=setup.catalog_item.id,
        sku="ST-INACTIVE-V",
        base_unit_id=setup.unit.id,
        is_active=False,
    )
    service_variant = await make_product_variant(
        db_session,
        tenant_id=tenant.id,
        catalog_item_id=setup.catalog_item.id,
        sku="ST-SERVICE-V",
        base_unit_id=setup.unit.id,
        track_inventory=False,
    )
    unmapped_unit = await make_unit(db_session, code="st-unmapped-unit")
    inactive_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        unit_id=unmapped_unit.id,
        is_active=False,
    )
    inactive_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="ST-INACTIVE-LOC",
        is_active=False,
    )
    inactive_batch = await make_stock_batch(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.product_variant.id,
        status=StockBatchStatus.CANCELLED,
    )
    actor = await make_stock_transfer_actor(db_session, tenant=tenant)
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    invalid_product_body = order_body(
        setup,
        document_no="ST-BAD-PRODUCT",
        overrides={"product_variant_id": str(inactive_variant.id)},
    )
    service_line_body = order_body(
        setup,
        document_no="ST-SERVICE-LINE",
        overrides={"product_variant_id": str(service_variant.id)},
    )
    invalid_unit_body = order_body(
        setup,
        document_no="ST-BAD-UNIT",
        overrides={"variant_unit_id": str(inactive_variant_unit.id)},
    )
    invalid_batch_body = order_body(
        setup, document_no="ST-BAD-BATCH", overrides={"stock_batch_id": str(other_setup.batch.id)}
    )
    inactive_batch_body = order_body(
        setup, document_no="ST-INACTIVE-BATCH", overrides={"stock_batch_id": str(inactive_batch.id)}
    )
    inactive_location_body = order_body(
        setup,
        document_no="ST-INACTIVE-LOC-LINE",
        overrides={"from_location_id": str(inactive_location.id)},
    )
    same_location_body = order_body(
        setup,
        document_no="ST-SAME-LOC",
        overrides={"to_location_id": str(setup.from_location.id)},
    )

    invalid_product = await client.post(
        "/api/v1/stock-transfers", json=invalid_product_body, headers=headers
    )
    service_line = await client.post(
        "/api/v1/stock-transfers", json=service_line_body, headers=headers
    )
    invalid_unit = await client.post(
        "/api/v1/stock-transfers", json=invalid_unit_body, headers=headers
    )
    invalid_batch = await client.post(
        "/api/v1/stock-transfers", json=invalid_batch_body, headers=headers
    )
    inactive_batch_line = await client.post(
        "/api/v1/stock-transfers", json=inactive_batch_body, headers=headers
    )
    inactive_location_line = await client.post(
        "/api/v1/stock-transfers", json=inactive_location_body, headers=headers
    )
    same_location_line = await client.post(
        "/api/v1/stock-transfers", json=same_location_body, headers=headers
    )

    assert invalid_product.status_code == 400
    assert invalid_product.json()["error_code"] == "invalid_stock_transfer_line_product"
    assert service_line.status_code == 400
    assert service_line.json()["error_code"] == "invalid_stock_transfer_line_product"
    assert invalid_unit.status_code == 400
    assert invalid_unit.json()["error_code"] == "invalid_stock_transfer_line_unit"
    assert invalid_batch.status_code == 400
    assert invalid_batch.json()["error_code"] == "invalid_stock_transfer_line_batch"
    assert inactive_batch_line.status_code == 400
    assert inactive_batch_line.json()["error_code"] == "invalid_stock_transfer_line_batch"
    assert inactive_location_line.status_code == 400
    assert inactive_location_line.json()["error_code"] == "invalid_stock_transfer_line_location"
    assert same_location_line.status_code == 400
    assert same_location_line.json()["error_code"] == "invalid_stock_transfer_line_location"

    persisted = (
        (
            await db_session.execute(
                select(StockTransfer).where(StockTransfer.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert persisted == []


async def test_stock_transfer_rejects_empty_lines_duplicate_line_numbers_and_insufficient_balance(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-transfer-post-invalid")
    tenant_id = tenant.id
    setup = await make_transfer_setup(db_session, tenant_id=tenant.id)
    actor = await make_stock_transfer_actor(db_session, tenant=tenant)
    line = line_payload(setup, quantity="2.00000000")
    duplicate_lines = [line_payload(setup, line_no=1), line_payload(setup, line_no=1)]
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    empty_lines = await client.post(
        "/api/v1/stock-transfers",
        json={"lines": []},
        headers=headers,
    )
    assert empty_lines.status_code == 201
    empty_post = await client.post(
        f"/api/v1/stock-transfers/{empty_lines.json()['id']}/post",
        headers=headers,
    )
    assert empty_post.status_code == 400
    assert empty_post.json()["error_code"] == "stock_transfer_has_no_lines"

    duplicate_line_no = await client.post(
        "/api/v1/stock-transfers",
        json={
            "lines": duplicate_lines,
        },
        headers=headers,
    )
    assert duplicate_line_no.status_code == 422

    insufficient_draft = await client.post(
        "/api/v1/stock-transfers",
        json={
            "lines": [line],
        },
        headers=headers,
    )
    assert insufficient_draft.status_code == 201
    insufficient = await client.post(
        f"/api/v1/stock-transfers/{insufficient_draft.json()['id']}/post",
        headers=headers,
    )
    assert insufficient.status_code == 400
    assert insufficient.json()["error_code"] == "stock_transfer_insufficient_balance"

    persisted = (
        (
            await db_session.execute(
                select(StockTransfer).where(StockTransfer.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert Counter((row.document_no.startswith("ST-"), row.status) for row in persisted) == Counter(
        [
            (True, DocumentStatus.DRAFT),
            (True, DocumentStatus.DRAFT),
        ]
    )


async def test_stock_transfer_posted_records_are_immutable_and_not_cancellable_or_postable(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-transfer-posted-lock")
    setup = await make_transfer_setup(db_session, tenant_id=tenant.id)
    actor = await make_stock_transfer_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    transfer = await make_stock_transfer(
        db_session,
        tenant_id=tenant.id,
        document_no="ST-GONE",
        status=DocumentStatus.POSTED,
    )
    line = await make_stock_transfer_line(
        db_session,
        tenant_id=tenant.id,
        stock_transfer_id=transfer.id,
        setup=setup,
    )
    create_line_payload = line_payload(setup, line_no=2)
    transfer_id = transfer.id
    line_id = line.id
    await db_session.commit()

    update = await client.patch(
        f"/api/v1/stock-transfers/{transfer_id}",
        json={"notes": "nope"},
        headers=headers,
    )
    cancel = await client.delete(f"/api/v1/stock-transfers/{transfer_id}", headers=headers)
    post = await client.post(f"/api/v1/stock-transfers/{transfer_id}/post", headers=headers)
    create_line = await client.post(
        f"/api/v1/stock-transfers/{transfer_id}/lines",
        json=create_line_payload,
        headers=headers,
    )
    update_line = await client.patch(
        f"/api/v1/stock-transfers/{transfer_id}/lines/{line_id}",
        json={"quantity": "2.00000000"},
        headers=headers,
    )
    delete_line = await client.delete(
        f"/api/v1/stock-transfers/{transfer_id}/lines/{line_id}",
        headers=headers,
    )

    assert update.status_code == 400
    assert update.json()["error_code"] == "stock_transfer_not_draft"
    assert cancel.status_code == 400
    assert cancel.json()["error_code"] == "stock_transfer_not_cancellable"
    assert post.status_code == 400
    assert post.json()["error_code"] == "stock_transfer_not_postable"
    assert create_line.status_code == 400
    assert create_line.json()["error_code"] == "stock_transfer_not_draft"
    assert update_line.status_code == 400
    assert update_line.json()["error_code"] == "stock_transfer_not_draft"
    assert delete_line.status_code == 400
    assert delete_line.json()["error_code"] == "stock_transfer_not_draft"


async def test_stock_transfer_permissions_and_seed(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="stock-transfer-permissions")
    read_only = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("stock_transfers", ActionType.READ)],
    )
    headers = auth_headers(user_access_token(read_only))

    create_forbidden = await client.post(
        "/api/v1/stock-transfers",
        json={
            "lines": [
                {
                    "line_no": 1,
                    "product_variant_id": str(uuid.uuid4()),
                    "stock_batch_id": str(uuid.uuid4()),
                    "variant_unit_id": str(uuid.uuid4()),
                    "quantity": "1.00000000",
                    "from_location_id": str(uuid.uuid4()),
                    "to_location_id": str(uuid.uuid4()),
                }
            ],
        },
        headers=headers,
    )
    assert create_forbidden.status_code == 403

    await _ensure_permissions(db_session)
    await _ensure_permissions(db_session)
    codes = (
        (
            await db_session.execute(
                select(Permission.code).where(Permission.module == "stock_transfers")
            )
        )
        .scalars()
        .all()
    )
    assert sorted(codes) == [
        "stock_transfers.create",
        "stock_transfers.delete",
        "stock_transfers.read",
        "stock_transfers.update",
    ]


@dataclass
class TransferSetup:
    unit: Unit
    catalog_item: CatalogItem
    product_variant: ProductVariant
    variant_unit: VariantUnit
    from_location: Location
    to_location: Location
    batch: StockBatch


def line_payload(
    setup: "TransferSetup",
    *,
    quantity: str = "1.00000000",
    line_no: int = 1,
) -> dict[str, str | int]:
    return {
        "line_no": line_no,
        "product_variant_id": str(setup.product_variant.id),
        "stock_batch_id": str(setup.batch.id),
        "variant_unit_id": str(setup.variant_unit.id),
        "quantity": quantity,
        "from_location_id": str(setup.from_location.id),
        "to_location_id": str(setup.to_location.id),
    }


def order_body(
    setup: "TransferSetup",
    *,
    document_no: str,
    overrides: dict[str, str] | None = None,
) -> dict:
    line = line_payload(setup)
    line.update(overrides or {})
    return {"lines": [line]}


async def make_transfer_setup(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    unit_code: str = "stock-transfer-unit",
    sku: str = "ST-SKU",
    from_location_code: str = "ST-FROM",
    to_location_code: str = "ST-TO",
) -> TransferSetup:
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
    from_location = await make_location(db_session, tenant_id=tenant_id, code=from_location_code)
    to_location = await make_location(db_session, tenant_id=tenant_id, code=to_location_code)
    batch = await make_stock_batch(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=product_variant.id,
        unit_cost_base=Decimal("10.00000000"),
    )
    return TransferSetup(
        unit=unit,
        catalog_item=catalog_item,
        product_variant=product_variant,
        variant_unit=variant_unit,
        from_location=from_location,
        to_location=to_location,
        batch=batch,
    )


async def make_stock_transfer_actor(
    db_session: AsyncSession,
    *,
    tenant,
    extra_permissions: list[str] | None = None,
):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("stock_transfers", ActionType.CREATE),
            permission("stock_transfers", ActionType.READ),
            permission("stock_transfers", ActionType.UPDATE),
            permission("stock_transfers", ActionType.DELETE),
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
        is_active=is_active,
        track_inventory=track_inventory,
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


async def make_stock_transfer(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_no: str = "ST-TEST",
    status: DocumentStatus = DocumentStatus.DRAFT,
) -> StockTransfer:
    transfer = StockTransfer(
        tenant_id=tenant_id,
        document_no=document_no,
        status=status,
    )
    db_session.add(transfer)
    await db_session.flush()
    return transfer


async def make_stock_transfer_line(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    stock_transfer_id: uuid.UUID,
    setup: TransferSetup,
    line_no: int = 1,
    quantity: Decimal = Decimal("1.00000000"),
) -> StockTransferLine:
    line = StockTransferLine(
        tenant_id=tenant_id,
        stock_transfer_id=stock_transfer_id,
        line_no=line_no,
        product_variant_id=setup.product_variant.id,
        stock_batch_id=setup.batch.id,
        variant_unit_id=setup.variant_unit.id,
        quantity=quantity,
        conversion_to_base=setup.variant_unit.conversion_to_base,
        quantity_base=quantity * setup.variant_unit.conversion_to_base,
        from_location_id=setup.from_location.id,
        to_location_id=setup.to_location.id,
    )
    db_session.add(line)
    await db_session.flush()
    return line


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
