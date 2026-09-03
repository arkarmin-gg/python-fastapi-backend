from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db

DbSession = Annotated[AsyncSession, Depends(get_db)]


@dataclass(frozen=True)
class RequestContext:
    ip_address: str | None
    user_agent: str | None


def get_request_context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


RequestCtx = Annotated[RequestContext, Depends(get_request_context)]
