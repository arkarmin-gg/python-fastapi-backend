from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
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


async def form_model[ModelT: BaseModel](request: Request, schema: type[ModelT]) -> ModelT:
    form = await request.form()

    raw_data = form.get("data")
    try:
        if isinstance(raw_data, str):
            return schema.model_validate_json(raw_data)

        values = {
            field_name: form[field_name] for field_name in schema.model_fields if field_name in form
        }

        return schema.model_validate(values)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
