from contextvars import ContextVar, Token
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
    request_id: str | None
    trace_id: str | None


_request_context: ContextVar[RequestContext | None] = ContextVar(
    "request_context",
    default=None,
)


def get_request_context(request: Request) -> RequestContext:
    return RequestContext(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        request_id=request.headers.get("x-request-id"),
        trace_id=request.headers.get("x-trace-id"),
    )


def set_request_context(context: RequestContext) -> Token[RequestContext | None]:
    return _request_context.set(context)


def reset_request_context(token: Token[RequestContext | None]) -> None:
    _request_context.reset(token)


def current_request_context() -> RequestContext | None:
    return _request_context.get()


RequestCtx = Annotated[RequestContext, Depends(get_request_context)]
