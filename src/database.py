from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

engine = create_async_engine(
    str(settings.DATABASE_URL),
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
