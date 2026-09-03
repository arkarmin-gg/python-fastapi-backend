import re
import uuid
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.document_numbers.models import DocumentSequence

DOCUMENT_NUMBER_PREFIXES = {
    "sales_invoice": "SI",
    "purchase_invoice": "PI",
    "customer_payment": "CP",
    "supplier_payment": "SP",
    "stock_adjustment": "SA",
    "stock_transfer": "ST",
    "stock_count": "SC",
    "repack_order": "RP",
    "lot_number": "LOT",
}

GENERATED_LOT_NUMBER_PATTERN = re.compile(r"^LOT-\d{6}-\d{6}$")


async def generate_document_no(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    document_type: str,
    document_date: date | datetime,
) -> str:
    prefix = DOCUMENT_NUMBER_PREFIXES[document_type]
    period = _period_for(document_date)
    stmt = (
        insert(DocumentSequence)
        .values(
            tenant_id=tenant_id,
            document_type=document_type,
            period=period,
            last_number=1,
        )
        .on_conflict_do_update(
            constraint="document_sequences_tenant_id_document_type_period_key",
            set_={
                "last_number": DocumentSequence.last_number + 1,
                "updated_at": func.now(),
            },
        )
        .returning(DocumentSequence.last_number)
    )
    next_number = await db.scalar(stmt)
    assert next_number is not None
    return f"{prefix}-{period}-{next_number:06d}"


async def generate_lot_number(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    allocated_at: datetime,
) -> str:
    """Allocate a tenant-wide, monthly lot number atomically."""
    return await generate_document_no(db, tenant_id, "lot_number", allocated_at)


def is_generated_lot_number(value: str) -> bool:
    return bool(GENERATED_LOT_NUMBER_PATTERN.fullmatch(value))


def _period_for(value: date | datetime) -> str:
    return f"{value.year:04d}{value.month:02d}"
