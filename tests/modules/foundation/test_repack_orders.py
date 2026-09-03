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
from src.modules.repack_orders.models import RepackOrder
from src.modules.units.models import Unit

from tests.conftest import (
    auth_headers,
    make_tenant,
    make_user_with_permissions,
    permission,
    user_access_token,
)


async def test_repack_order_draft_then_post_is_atomic_tenant_scoped_and_audited(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-crud")
    other_tenant = await make_tenant(db_session, code="repack-other")
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_repack_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="rp-other-unit",
        input_sku="RP-OTHER-IN",
        output_sku="RP-OTHER-OUT",
        location_code="RP-OTHER-WH",
    )
    other_order = await make_repack_order(
        db_session,
        tenant_id=other_tenant.id,
        location_id=other_setup.location.id,
        document_no="RP-001",
    )
    actor = await make_repack_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    response = await client.post(
        "/api/v1/repack-orders",
        json={
            "location_id": str(setup.location.id),
            "notes": "make retail packs",
            "inputs": [input_payload(setup, quantity="5.00000000")],
            "outputs": [output_payload(setup, quantity="4.00000000", allocated_cost="550.0000")],
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    order_id = body["id"]
    assert body["status"] == "draft"
    assert body["created_by"] == str(actor.id)
    assert body["total_input_cost"] == "600.0000"
    assert body["total_output_cost"] == "550.0000"
    assert body["waste_cost"] == "50.0000"
    assert body["total_input_quantity_base"] == "60.00000000"
    assert body["total_output_quantity_base"] == "48.00000000"
    assert len(body["inputs"]) == 1
    assert len(body["outputs"]) == 1
    output_id = body["outputs"][0]["id"]
    assert body["outputs"][0]["created_stock_batch_id"] is None
    assert await db_session.scalar(select(StockMovement.id)) is None

    listed = await client.get(
        (
            "/api/v1/repack-orders"
            "?search=retail"
            f"&location_id={setup.location.id}"
            "&status=draft"
            "&created_at_gte=2026-08-08"
            "&sort=document_no,id"
        ),
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [order_id]

    fetched = await client.get(f"/api/v1/repack-orders/{order_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["tenant_id"] == str(tenant.id)
    assert len(fetched.json()["inputs"]) == 1
    assert len(fetched.json()["outputs"]) == 1

    not_found = await client.get(f"/api/v1/repack-orders/{other_order.id}", headers=headers)
    assert not_found.status_code == 404

    posted = await client.post(f"/api/v1/repack-orders/{order_id}/post", headers=headers)
    assert posted.status_code == 200
    body = posted.json()
    assert body["status"] == "posted"
    assert body["posted_by"] == str(actor.id)
    assert body["outputs"][0]["created_stock_batch_id"] is not None

    listed_inputs = await client.get(
        (
            f"/api/v1/repack-orders/{order_id}/inputs"
            f"?product_variant_id={setup.input_variant.id}"
            f"&stock_batch_id={setup.batch.id}"
            f"&variant_unit_id={setup.input_variant_unit.id}"
            "&sort=line_no,id"
        ),
        headers=headers,
    )
    assert listed_inputs.status_code == 200
    assert len(listed_inputs.json()["items"]) == 1

    listed_outputs = await client.get(
        (
            f"/api/v1/repack-orders/{order_id}/outputs"
            f"?product_variant_id={setup.output_variant.id}"
            f"&variant_unit_id={setup.output_variant_unit.id}"
            "&sort=line_no,id"
        ),
        headers=headers,
    )
    assert listed_outputs.status_code == 200
    assert [item["id"] for item in listed_outputs.json()["items"]] == [output_id]

    input_balance = await db_session.scalar(
        select(StockBalance).where(StockBalance.id == setup.balance.id)
    )
    assert input_balance is not None
    assert input_balance.quantity_base == Decimal("40.00000000")

    output_batch_id = uuid.UUID(body["outputs"][0]["created_stock_batch_id"])
    output_batch = await db_session.scalar(
        select(StockBatch).where(StockBatch.id == output_batch_id)
    )
    assert output_batch is not None
    assert output_batch.source_type == SourceType.REPACK_ORDER
    assert output_batch.source_id == uuid.UUID(order_id)
    assert output_batch.initial_quantity_base == Decimal("48.00000000")
    assert output_batch.total_cost == Decimal("550.0000")
    assert output_batch.lot_number == "RP-LOT"

    output_balance = await db_session.scalar(
        select(StockBalance).where(
            StockBalance.tenant_id == tenant.id,
            StockBalance.product_variant_id == setup.output_variant.id,
            StockBalance.location_id == setup.location.id,
            StockBalance.stock_batch_id == output_batch.id,
        )
    )
    assert output_balance is not None
    assert output_balance.quantity_base == Decimal("48.00000000")

    movements = (
        (
            await db_session.execute(
                select(StockMovement).where(
                    StockMovement.tenant_id == tenant.id,
                    StockMovement.source_type == SourceType.REPACK_ORDER,
                    StockMovement.source_id == uuid.UUID(order_id),
                )
            )
        )
        .scalars()
        .all()
    )
    by_type = {movement.movement_type: movement for movement in movements}
    assert set(by_type) == {
        StockMovementType.REPACK_INPUT,
        StockMovementType.REPACK_OUTPUT,
    }
    assert by_type[StockMovementType.REPACK_INPUT].quantity_base == Decimal("-60.00000000")
    assert by_type[StockMovementType.REPACK_OUTPUT].quantity_base == Decimal("48.00000000")

    actions = (
        (
            await db_session.execute(
                select(AuditLog.action).where(
                    AuditLog.tenant_id == tenant.id,
                    AuditLog.entity_id == uuid.UUID(order_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert Counter(actions) == Counter(["repack_orders.create", "repack_orders.post"])


async def test_repack_order_draft_header_input_output_mutation_and_cancel(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-draft")
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    actor = await make_repack_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))

    created = await client.post(
        "/api/v1/repack-orders",
        json={
            "location_id": str(setup.location.id),
            "notes": "before update",
            "inputs": [],
            "outputs": [],
        },
        headers=headers,
    )
    assert created.status_code == 201
    order_id = created.json()["id"]
    assert created.json()["status"] == "draft"
    assert created.json()["total_input_cost"] == "0.0000"
    assert created.json()["total_input_quantity_base"] == "0.00000000"
    assert created.json()["outputs"] == []

    updated = await client.patch(
        f"/api/v1/repack-orders/{order_id}",
        json={"notes": "after update"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["document_no"].startswith("RP-2026")
    assert updated.json()["notes"] == "after update"

    input_line = await client.post(
        f"/api/v1/repack-orders/{order_id}/inputs",
        json=input_payload(setup, quantity="2.00000000"),
        headers=headers,
    )
    assert input_line.status_code == 201
    input_id = input_line.json()["id"]
    assert input_line.json()["total_cost"] == "240.0000"

    duplicate_input = await client.post(
        f"/api/v1/repack-orders/{order_id}/inputs",
        json=input_payload(setup, line_no=1),
        headers=headers,
    )
    assert duplicate_input.status_code == 409
    assert duplicate_input.json()["error_code"] == "repack_order_input_line_no_conflict"

    output_line = await client.post(
        f"/api/v1/repack-orders/{order_id}/outputs",
        json=output_payload(setup, quantity="1.00000000", allocated_cost="100.0000"),
        headers=headers,
    )
    assert output_line.status_code == 201
    output_id = output_line.json()["id"]
    assert output_line.json()["unit_cost_base"] == "8.33333333"

    duplicate_output = await client.post(
        f"/api/v1/repack-orders/{order_id}/outputs",
        json=output_payload(setup, line_no=1, allocated_cost="0.0000"),
        headers=headers,
    )
    assert duplicate_output.status_code == 409
    assert duplicate_output.json()["error_code"] == "repack_order_output_line_no_conflict"

    updated_input = await client.patch(
        f"/api/v1/repack-orders/{order_id}/inputs/{input_id}",
        json={"line_no": 2, "quantity": "3.00000000"},
        headers=headers,
    )
    assert updated_input.status_code == 200
    assert updated_input.json()["line_no"] == 2
    assert updated_input.json()["total_cost"] == "360.0000"

    updated_output = await client.patch(
        f"/api/v1/repack-orders/{order_id}/outputs/{output_id}",
        json={"line_no": 2, "allocated_cost": "120.0000"},
        headers=headers,
    )
    assert updated_output.status_code == 200
    assert updated_output.json()["line_no"] == 2
    assert updated_output.json()["allocated_cost"] == "120.0000"

    fetched = await client.get(f"/api/v1/repack-orders/{order_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["total_input_cost"] == "360.0000"
    assert fetched.json()["total_output_cost"] == "120.0000"
    assert fetched.json()["waste_cost"] == "240.0000"
    assert fetched.json()["total_input_quantity_base"] == "36.00000000"
    assert fetched.json()["total_output_quantity_base"] == "12.00000000"

    deleted_output = await client.delete(
        f"/api/v1/repack-orders/{order_id}/outputs/{output_id}",
        headers=headers,
    )
    assert deleted_output.status_code == 204
    deleted_input = await client.delete(
        f"/api/v1/repack-orders/{order_id}/inputs/{input_id}",
        headers=headers,
    )
    assert deleted_input.status_code == 204

    replacement_input = await client.post(
        f"/api/v1/repack-orders/{order_id}/inputs",
        json=input_payload(setup, line_no=1),
        headers=headers,
    )
    assert replacement_input.status_code == 201
    replacement_output = await client.post(
        f"/api/v1/repack-orders/{order_id}/outputs",
        json=output_payload(setup, line_no=1, allocated_cost="100.0000"),
        headers=headers,
    )
    assert replacement_output.status_code == 201

    cancelled = await client.delete(f"/api/v1/repack-orders/{order_id}", headers=headers)
    assert cancelled.status_code == 204
    fetched = await client.get(f"/api/v1/repack-orders/{order_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "cancelled"
    assert fetched.json()["cancelled_by"] == str(actor.id)

    after_cancel = await client.patch(
        f"/api/v1/repack-orders/{order_id}",
        json={"notes": "too late"},
        headers=headers,
    )
    assert after_cancel.status_code == 400
    assert after_cancel.json()["error_code"] == "repack_order_not_draft"


async def test_repack_order_duplicate_document_no_is_tenant_scoped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-dup")
    other_tenant = await make_tenant(db_session, code="repack-dup-other")
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    other_setup = await make_repack_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="rp-dup-other-unit",
        input_sku="RP-DUP-OTHER-IN",
        output_sku="RP-DUP-OTHER-OUT",
        location_code="RP-DUP-OTHER-WH",
    )
    await make_repack_order(
        db_session,
        tenant_id=tenant.id,
        location_id=setup.location.id,
        document_no="RP-DUP",
    )
    cross_tenant = await make_repack_order(
        db_session,
        tenant_id=other_tenant.id,
        location_id=other_setup.location.id,
        document_no="RP-DUP",
    )
    actor = await make_repack_actor(db_session, tenant=tenant)
    duplicate_body = order_body(setup, document_no="RP-DUP")
    tenant_id = tenant.id
    cross_tenant_id = cross_tenant.tenant_id
    other_tenant_id = other_tenant.id
    await db_session.commit()

    duplicate = await client.post(
        "/api/v1/repack-orders",
        json=duplicate_body,
        headers=auth_headers(user_access_token(actor)),
    )

    assert duplicate.status_code == 201
    assert duplicate.json()["document_no"].startswith("RP-")
    assert cross_tenant_id == other_tenant_id

    remaining = await db_session.scalar(
        select(RepackOrder).where(
            RepackOrder.tenant_id == tenant_id,
            RepackOrder.document_no == "RP-DUP",
        )
    )
    assert remaining is not None
    assert remaining.status == DocumentStatus.DRAFT


async def test_repack_order_rejects_invalid_references_rolls_back_and_checks_permissions(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-invalid")
    tenant_id = tenant.id
    other_tenant = await make_tenant(db_session, code="repack-invalid-other")
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    balance_id = setup.balance.id
    other_setup = await make_repack_setup(
        db_session,
        tenant_id=other_tenant.id,
        unit_code="rp-invalid-other-unit",
        input_sku="RP-INVALID-OTHER-IN",
        output_sku="RP-INVALID-OTHER-OUT",
        location_code="RP-INVALID-OTHER-WH",
    )
    inactive_variant = await make_catalog_variant(
        db_session,
        tenant_id=tenant.id,
        sku="RP-INACTIVE-VAR",
        base_unit_id=setup.unit.id,
        is_active=False,
    )
    service_variant = await make_catalog_variant(
        db_session,
        tenant_id=tenant.id,
        sku="RP-SERVICE-VAR",
        base_unit_id=setup.unit.id,
        track_inventory=False,
    )
    service_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=service_variant.id,
        unit_id=setup.unit.id,
        conversion_to_base=Decimal("12.00000000"),
    )
    unmapped_unit = await make_unit(db_session, code="rp-unmapped-unit")
    unmapped_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant.id,
        product_variant_id=setup.output_variant.id,
        unit_id=unmapped_unit.id,
        conversion_to_base=Decimal("1.00000000"),
        is_base_unit=False,
    )
    inactive_location = await make_location(
        db_session,
        tenant_id=tenant.id,
        code="RP-INACTIVE-LOC",
        is_active=False,
    )
    actor = await make_repack_actor(db_session, tenant=tenant)
    restricted = await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[permission("repack_orders", ActionType.READ)],
    )
    headers = auth_headers(user_access_token(actor))
    restricted_headers = auth_headers(user_access_token(restricted))

    # Build every request body up front, while all fixture objects are still
    # freshly loaded — a rollback triggered by one request would otherwise
    # expire the ORM objects the *next* request's body still needs to read.
    denied_body = order_body(setup, document_no="RP-DENIED")
    invalid_location_body = order_body(
        setup, document_no="RP-BAD-LOC", location_id=inactive_location.id
    )
    invalid_product_body = order_body(
        setup,
        document_no="RP-BAD-PRODUCT",
        input_overrides={"product_variant_id": str(inactive_variant.id)},
    )
    invalid_unit_body = order_body(
        setup,
        document_no="RP-BAD-UNIT",
        input_overrides={"variant_unit_id": str(unmapped_variant_unit.id)},
    )
    invalid_batch_body = order_body(
        setup,
        document_no="RP-BAD-BATCH",
        input_overrides={"stock_batch_id": str(other_setup.batch.id)},
    )
    invalid_output_product_body = order_body(
        setup,
        document_no="RP-BAD-OUT-PRODUCT",
        output_overrides={
            "product_variant_id": str(service_variant.id),
            "variant_unit_id": str(service_variant_unit.id),
        },
    )
    await db_session.commit()

    denied = await client.post(
        "/api/v1/repack-orders", json=denied_body, headers=restricted_headers
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "permission_denied"

    invalid_location = await client.post(
        "/api/v1/repack-orders", json=invalid_location_body, headers=headers
    )
    assert invalid_location.status_code == 400
    assert invalid_location.json()["error_code"] == "invalid_repack_order_location"

    invalid_product = await client.post(
        "/api/v1/repack-orders", json=invalid_product_body, headers=headers
    )
    assert invalid_product.status_code == 400
    assert invalid_product.json()["error_code"] == "invalid_repack_order_input_product"

    invalid_unit = await client.post(
        "/api/v1/repack-orders", json=invalid_unit_body, headers=headers
    )
    assert invalid_unit.status_code == 400
    assert invalid_unit.json()["error_code"] == "invalid_repack_order_input_unit"

    invalid_batch = await client.post(
        "/api/v1/repack-orders", json=invalid_batch_body, headers=headers
    )
    assert invalid_batch.status_code == 400
    assert invalid_batch.json()["error_code"] == "invalid_repack_order_input_batch"

    invalid_output_product = await client.post(
        "/api/v1/repack-orders", json=invalid_output_product_body, headers=headers
    )
    assert invalid_output_product.status_code == 400
    assert invalid_output_product.json()["error_code"] == "invalid_repack_order_output_product"

    # None of the rejected attempts should have persisted anything.
    persisted = (
        (await db_session.execute(select(RepackOrder).where(RepackOrder.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert persisted == []
    input_balance = await db_session.scalar(
        select(StockBalance).where(StockBalance.id == balance_id)
    )
    assert input_balance.quantity_base == Decimal("100.00000000")

    await _ensure_permissions(db_session)
    permission_row = await db_session.scalar(
        select(Permission).where(Permission.code == "repack_orders.create")
    )
    assert permission_row is not None


async def test_repack_order_rejects_output_cost_greater_than_input_cost_and_rolls_back(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-overcost")
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    actor = await make_repack_actor(db_session, tenant=tenant)
    tenant_id = tenant.id
    balance_id = setup.balance.id
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    response = await client.post(
        "/api/v1/repack-orders",
        json=order_body(
            setup,
            document_no="RP-OVER",
            input_overrides={"quantity": "1.00000000"},
            output_overrides={"quantity": "1.00000000", "allocated_cost": "999.0000"},
        ),
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "repack_order_output_cost_exceeds_input_cost"

    persisted = (
        (await db_session.execute(select(RepackOrder).where(RepackOrder.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert persisted == []
    input_balance = await db_session.scalar(
        select(StockBalance).where(StockBalance.id == balance_id)
    )
    assert input_balance.quantity_base == Decimal("100.00000000")


async def test_repack_order_rejects_output_quantity_greater_than_input_quantity_and_rolls_back(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-overqty")
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    actor = await make_repack_actor(db_session, tenant=tenant)
    tenant_id = tenant.id
    balance_id = setup.balance.id
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    response = await client.post(
        "/api/v1/repack-orders",
        json=order_body(
            setup,
            document_no="RP-OVERQTY",
            input_overrides={"quantity": "1.00000000"},
            output_overrides={"quantity": "2.00000000", "allocated_cost": "50.0000"},
        ),
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "repack_order_output_quantity_exceeds_input_quantity"

    persisted = (
        (await db_session.execute(select(RepackOrder).where(RepackOrder.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    assert persisted == []
    input_balance = await db_session.scalar(
        select(StockBalance).where(StockBalance.id == balance_id)
    )
    assert input_balance.quantity_base == Decimal("100.00000000")


async def test_repack_order_post_rejects_insufficient_balance_without_inventory_side_effects(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-insufficient")
    tenant_id = tenant.id
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    balance_id = setup.balance.id
    actor = await make_repack_actor(db_session, tenant=tenant)
    body = order_body(
        setup,
        document_no="RP-INSUFFICIENT",
        input_overrides={"quantity": "999.00000000"},
    )
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    created = await client.post("/api/v1/repack-orders", json=body, headers=headers)
    assert created.status_code == 201
    order_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    posted = await client.post(f"/api/v1/repack-orders/{order_id}/post", headers=headers)
    assert posted.status_code == 400
    assert posted.json()["error_code"] == "repack_order_insufficient_balance"

    order = await db_session.scalar(
        select(RepackOrder).where(
            RepackOrder.tenant_id == tenant_id,
            RepackOrder.id == order_id,
        )
    )
    assert order is not None
    assert order.status == DocumentStatus.DRAFT
    input_balance = await db_session.scalar(
        select(StockBalance).where(StockBalance.id == balance_id)
    )
    assert input_balance.quantity_base == Decimal("100.00000000")
    assert await db_session.scalar(select(StockMovement.id)) is None


async def test_repack_order_rejects_missing_lines_and_duplicate_line_numbers(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-shape")
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    actor = await make_repack_actor(db_session, tenant=tenant)
    headers = auth_headers(user_access_token(actor))
    no_inputs_body = {
        "location_id": str(setup.location.id),
        "inputs": [],
        "outputs": [],
    }
    no_outputs_body = {
        "location_id": str(setup.location.id),
        "inputs": [input_payload(setup)],
        "outputs": [],
    }
    duplicate_output_body = {
        "location_id": str(setup.location.id),
        "inputs": [input_payload(setup)],
        "outputs": [
            output_payload(setup, line_no=1),
            output_payload(setup, line_no=1),
        ],
    }

    no_inputs = await client.post(
        "/api/v1/repack-orders",
        json=no_inputs_body,
        headers=headers,
    )
    assert no_inputs.status_code == 201
    no_inputs_post = await client.post(
        f"/api/v1/repack-orders/{no_inputs.json()['id']}/post",
        headers=headers,
    )
    assert no_inputs_post.status_code == 400
    assert no_inputs_post.json()["error_code"] == "repack_order_has_no_inputs"

    no_outputs = await client.post(
        "/api/v1/repack-orders",
        json=no_outputs_body,
        headers=headers,
    )
    assert no_outputs.status_code == 201
    no_outputs_post = await client.post(
        f"/api/v1/repack-orders/{no_outputs.json()['id']}/post",
        headers=headers,
    )
    assert no_outputs_post.status_code == 400
    assert no_outputs_post.json()["error_code"] == "repack_order_has_no_outputs"

    duplicate_output_line_no = await client.post(
        "/api/v1/repack-orders",
        json=duplicate_output_body,
        headers=headers,
    )
    assert duplicate_output_line_no.status_code == 422


async def test_repack_order_posted_records_are_immutable_and_not_cancellable_or_postable(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    tenant = await make_tenant(db_session, code="repack-posted-lock")
    setup = await make_repack_setup(db_session, tenant_id=tenant.id)
    actor = await make_repack_actor(db_session, tenant=tenant)
    body = order_body(setup, document_no="RP-POSTED-LOCK")
    input_create_body = input_payload(setup, line_no=2)
    output_create_body = output_payload(setup, line_no=2, allocated_cost="0.0000")
    await db_session.commit()
    headers = auth_headers(user_access_token(actor))

    created = await client.post("/api/v1/repack-orders", json=body, headers=headers)
    assert created.status_code == 201
    posted = await client.post(
        f"/api/v1/repack-orders/{created.json()['id']}/post",
        headers=headers,
    )
    assert posted.status_code == 200
    order_id = posted.json()["id"]
    input_id = posted.json()["inputs"][0]["id"]
    output_id = posted.json()["outputs"][0]["id"]

    update = await client.patch(
        f"/api/v1/repack-orders/{order_id}",
        json={"notes": "no longer possible"},
        headers=headers,
    )
    cancel = await client.delete(f"/api/v1/repack-orders/{order_id}", headers=headers)
    post_again = await client.post(f"/api/v1/repack-orders/{order_id}/post", headers=headers)
    create_input = await client.post(
        f"/api/v1/repack-orders/{order_id}/inputs",
        json=input_create_body,
        headers=headers,
    )
    update_input = await client.patch(
        f"/api/v1/repack-orders/{order_id}/inputs/{input_id}",
        json={"quantity": "2.00000000"},
        headers=headers,
    )
    delete_input = await client.delete(
        f"/api/v1/repack-orders/{order_id}/inputs/{input_id}",
        headers=headers,
    )
    create_output = await client.post(
        f"/api/v1/repack-orders/{order_id}/outputs",
        json=output_create_body,
        headers=headers,
    )
    update_output = await client.patch(
        f"/api/v1/repack-orders/{order_id}/outputs/{output_id}",
        json={"allocated_cost": "0.0000"},
        headers=headers,
    )
    delete_output = await client.delete(
        f"/api/v1/repack-orders/{order_id}/outputs/{output_id}",
        headers=headers,
    )

    assert update.status_code == 400
    assert update.json()["error_code"] == "repack_order_not_draft"
    assert cancel.status_code == 400
    assert cancel.json()["error_code"] == "repack_order_not_cancellable"
    assert post_again.status_code == 400
    assert post_again.json()["error_code"] == "repack_order_not_postable"
    assert create_input.status_code == 400
    assert create_input.json()["error_code"] == "repack_order_not_draft"
    assert update_input.status_code == 400
    assert update_input.json()["error_code"] == "repack_order_not_draft"
    assert delete_input.status_code == 400
    assert delete_input.json()["error_code"] == "repack_order_not_draft"
    assert create_output.status_code == 400
    assert create_output.json()["error_code"] == "repack_order_not_draft"
    assert update_output.status_code == 400
    assert update_output.json()["error_code"] == "repack_order_not_draft"
    assert delete_output.status_code == 400
    assert delete_output.json()["error_code"] == "repack_order_not_draft"


@dataclass
class RepackSetup:
    unit: Unit
    location: Location
    input_variant: ProductVariant
    output_variant: ProductVariant
    input_variant_unit: VariantUnit
    output_variant_unit: VariantUnit
    batch: StockBatch
    balance: StockBalance


async def make_repack_actor(db_session: AsyncSession, *, tenant):
    return await make_user_with_permissions(
        db_session,
        tenant=tenant,
        permissions=[
            permission("repack_orders", ActionType.CREATE),
            permission("repack_orders", ActionType.READ),
            permission("repack_orders", ActionType.UPDATE),
            permission("repack_orders", ActionType.DELETE),
        ],
    )


def input_payload(
    setup: RepackSetup,
    *,
    product_variant_id: uuid.UUID | None = None,
    stock_batch_id: uuid.UUID | None = None,
    variant_unit_id: uuid.UUID | None = None,
    quantity: str = "1.00000000",
    line_no: int = 1,
) -> dict[str, str | int]:
    return {
        "line_no": line_no,
        "product_variant_id": str(product_variant_id or setup.input_variant.id),
        "stock_batch_id": str(stock_batch_id or setup.batch.id),
        "variant_unit_id": str(variant_unit_id or setup.input_variant_unit.id),
        "quantity": quantity,
    }


def output_payload(
    setup: RepackSetup,
    *,
    product_variant_id: uuid.UUID | None = None,
    variant_unit_id: uuid.UUID | None = None,
    quantity: str = "1.00000000",
    allocated_cost: str = "100.0000",
    line_no: int = 1,
) -> dict[str, str | int]:
    return {
        "line_no": line_no,
        "product_variant_id": str(product_variant_id or setup.output_variant.id),
        "variant_unit_id": str(variant_unit_id or setup.output_variant_unit.id),
        "quantity": quantity,
        "allocated_cost": allocated_cost,
        "lot_number": "RP-LOT",
    }


def order_body(
    setup: RepackSetup,
    *,
    document_no: str,
    location_id: uuid.UUID | None = None,
    input_overrides: dict[str, str] | None = None,
    output_overrides: dict[str, str] | None = None,
) -> dict:
    input_line = input_payload(setup)
    input_line.update(input_overrides or {})
    output_line = output_payload(setup)
    output_line.update(output_overrides or {})
    return {
        "location_id": str(location_id or setup.location.id),
        "inputs": [input_line],
        "outputs": [output_line],
    }


async def make_repack_setup(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    unit_code: str = "rp-carton",
    input_sku: str = "RP-BULK",
    output_sku: str = "RP-PACK",
    location_code: str = "RP-WH",
) -> RepackSetup:
    unit = await make_unit(db_session, code=unit_code)
    location = await make_location(db_session, tenant_id=tenant_id, code=location_code)
    input_variant = await make_catalog_variant(
        db_session,
        tenant_id=tenant_id,
        sku=f"{input_sku}-VAR",
        base_unit_id=unit.id,
    )
    output_variant = await make_catalog_variant(
        db_session,
        tenant_id=tenant_id,
        sku=f"{output_sku}-VAR",
        base_unit_id=unit.id,
    )
    input_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=input_variant.id,
        unit_id=unit.id,
        conversion_to_base=Decimal("12.00000000"),
    )
    output_variant_unit = await make_variant_unit(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=output_variant.id,
        unit_id=unit.id,
        conversion_to_base=Decimal("12.00000000"),
    )
    batch = await make_stock_batch(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=input_variant.id,
        quantity_base=Decimal("100.00000000"),
        unit_cost_base=Decimal("10.00000000"),
    )
    balance = await make_stock_balance(
        db_session,
        tenant_id=tenant_id,
        product_variant_id=input_variant.id,
        location_id=location.id,
        stock_batch_id=batch.id,
        quantity_base=Decimal("100.00000000"),
    )
    return RepackSetup(
        unit=unit,
        location=location,
        input_variant=input_variant,
        output_variant=output_variant,
        input_variant_unit=input_variant_unit,
        output_variant_unit=output_variant_unit,
        batch=batch,
        balance=balance,
    )


async def make_unit(db_session: AsyncSession, *, code: str) -> Unit:
    unit = Unit(code=code, name_en=code.title(), unit_kind=UnitKind.PACKAGE)
    db_session.add(unit)
    await db_session.flush()
    return unit


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
        name=f"{code} Location",
        location_type=LocationType.WAREHOUSE,
        is_active=is_active,
    )
    db_session.add(location)
    await db_session.flush()
    return location


async def make_catalog_variant(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    sku: str,
    base_unit_id: uuid.UUID,
    is_active: bool = True,
    track_inventory: bool = True,
) -> ProductVariant:
    item = CatalogItem(
        tenant_id=tenant_id,
        code=f"ITEM-{uuid.uuid4().hex[:8]}",
        name=f"{sku} Item",
    )
    db_session.add(item)
    await db_session.flush()
    variant = ProductVariant(
        tenant_id=tenant_id,
        catalog_item_id=item.id,
        sku=sku,
        name=f"{sku} Variant",
        base_unit_id=base_unit_id,
        default_sale_price=Decimal("0.0000"),
        default_purchase_cost=Decimal("0.0000"),
        track_inventory=track_inventory,
        track_batches=True,
        is_active=is_active,
    )
    db_session.add(variant)
    await db_session.flush()
    return variant


async def make_variant_unit(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    unit_id: uuid.UUID,
    conversion_to_base: Decimal,
    is_base_unit: bool = True,
) -> VariantUnit:
    variant_unit = VariantUnit(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        unit_id=unit_id,
        conversion_to_base=conversion_to_base,
        is_base_unit=is_base_unit,
        is_purchase_unit=True,
        is_sales_unit=True,
        allow_decimal_quantity=True,
        rounding_precision=Decimal("0.00000100"),
    )
    db_session.add(variant_unit)
    await db_session.flush()
    return variant_unit


async def make_stock_batch(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    quantity_base: Decimal,
    unit_cost_base: Decimal,
) -> StockBatch:
    batch = StockBatch(
        tenant_id=tenant_id,
        product_variant_id=product_variant_id,
        source_type=SourceType.MANUAL,
        source_id=uuid.uuid4(),
        received_at=datetime.now(UTC),
        initial_quantity_base=quantity_base,
        unit_cost_base=unit_cost_base,
        total_cost=quantity_base * unit_cost_base,
        conversion_to_base=Decimal("1.00000000"),
        status=StockBatchStatus.ACTIVE,
        created_at=datetime.now(UTC),
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


async def make_repack_order(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    location_id: uuid.UUID,
    document_no: str,
) -> RepackOrder:
    order = RepackOrder(
        tenant_id=tenant_id,
        document_no=document_no,
        location_id=location_id,
        status=DocumentStatus.DRAFT,
    )
    db_session.add(order)
    await db_session.flush()
    return order
