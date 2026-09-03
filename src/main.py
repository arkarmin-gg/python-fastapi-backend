import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import src.registry  # noqa: F401  -- register every ORM model so all FKs resolve
from src.api.routers import v1
from src.config import Environment, settings
from src.exceptions import AppException
from src.schemas import ErrorResponse

SHOW_DOCS_IN = {Environment.LOCAL, Environment.STAGING}

OPENAPI_TAGS = [
    {"name": "Auth", "description": "Tenant user authentication."},
    {"name": "Tenants", "description": "Tenant/company management."},
    {"name": "Employees", "description": "Tenant employee records."},
    {"name": "Users", "description": "Tenant user account management."},
    {
        "name": "RBAC",
        "description": "Tenant roles, global permissions, and RBAC assignments.",
    },
    {"name": "Units", "description": "Globally managed unit catalog for POS products."},
    {"name": "Product Categories", "description": "Tenant-scoped product category tree."},
    {
        "name": "Catalog",
        "description": (
            "Tenant-scoped item, variant, option, unit, barcode, POS profile, and location setup."
        ),
    },
    {"name": "Price Levels", "description": "Tenant-scoped customer pricing levels."},
    {"name": "Price Rules", "description": "Tenant-scoped variant/customer price rules."},
    {"name": "Customers", "description": "Tenant-scoped customer master data."},
    {
        "name": "Customer Payments",
        "description": "Tenant-scoped customer payment draft workflow and receivables posting.",
    },
    {"name": "Suppliers", "description": "Tenant-scoped supplier master data."},
    {
        "name": "Supplier Payments",
        "description": "Tenant-scoped supplier payment draft workflow and payables posting.",
    },
    {"name": "Locations", "description": "Tenant-scoped operational location master data."},
    {
        "name": "Location Assignments",
        "description": "Tenant-scoped employee responsibility history for locations.",
    },
    {
        "name": "Purchase Invoices",
        "description": "Tenant-scoped purchase invoice draft workflow and receiving posting.",
    },
    {
        "name": "Stock Adjustments",
        "description": "Tenant-scoped stock adjustment draft workflow and inventory posting.",
    },
    {
        "name": "Stock Counts",
        "description": "Tenant-scoped stock count approval and inventory variance posting.",
    },
    {
        "name": "Stock Transfers",
        "description": "Tenant-scoped stock transfer draft workflow and inventory posting.",
    },
    {
        "name": "Repack Orders",
        "description": "Tenant-scoped repack order draft workflow and inventory posting.",
    },
    {
        "name": "Sales Invoices",
        "description": "Tenant-scoped sales invoice draft workflow and FIFO posting.",
    },
    {
        "name": "POS Checkouts",
        "description": "Atomic customer checkout, credit control, and receipt snapshots.",
    },
    {"name": "Inventory", "description": "Tenant-scoped stock batches, movements, and balances."},
    {"name": "Audit Logs", "description": "Tenant-scoped audit trail."},
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Startup/shutdown hooks go here (warm caches, open clients, etc.).
    yield


def create_app() -> FastAPI:
    docs_enabled = settings.ENVIRONMENT in SHOW_DOCS_IN

    app_kwargs: dict = {
        "title": settings.PROJECT_NAME,
        "version": "0.1.0",
        "description": (
            "FastAPI backend for the POS/ERP foundation slice: tenants, "
            "employees, users, tenant RBAC, auth, audit logging, and catalog setup."
        ),
        "lifespan": lifespan,
        "openapi_url": "/openapi.json" if docs_enabled else None,
        "docs_url": "/docs" if docs_enabled else None,
        "redoc_url": "/redoc" if docs_enabled else None,
        "openapi_tags": OPENAPI_TAGS,
    }

    app = FastAPI(**app_kwargs)

    app.add_middleware(
        cast(Any, CORSMiddleware),
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppException)
    async def _handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error_code=exc.error_code,
                detail=exc.detail,
                details=exc.details,
            ).model_dump(exclude_none=True),
        )

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "environment": settings.ENVIRONMENT.value,
            "app_name": settings.PROJECT_NAME,
            "version": app.version,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    app.include_router(v1)

    return app


app = create_app()
