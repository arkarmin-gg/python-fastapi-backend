import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.codes.models import CodeSequence

CODE_PREFIXES = {
    "employee": "EMP",
    "location": "LOC",
    "product_category": "CAT",
    "price_level": "PL",
    "supplier": "SUP",
    "customer": "CUS",
    "catalog_item": "ITEM",
    "product_variant": "VAR",
}


async def generate_code(db: AsyncSession, tenant_id: uuid.UUID, entity_type: str) -> str:
    prefix = CODE_PREFIXES[entity_type]
    stmt = (
        insert(CodeSequence)
        .values(
            tenant_id=tenant_id,
            entity_type=entity_type,
            last_number=1,
        )
        .on_conflict_do_update(
            constraint="code_sequences_tenant_id_entity_type_key",
            set_={
                "last_number": CodeSequence.last_number + 1,
                "updated_at": func.now(),
            },
        )
        .returning(CodeSequence.last_number)
    )
    next_number = await db.scalar(stmt)
    assert next_number is not None
    return f"{prefix}-{next_number:06d}"
