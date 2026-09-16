from fastapi import APIRouter

from src.config import settings
from src.modules.audit_logs.router import router as audit_logs_router
from src.modules.auth.router import router as auth_router
from src.modules.organizations.router import router as organizations_router
from src.modules.rbac.router import router as rbac_router
from src.modules.users.router import router as users_router

foundation_router = APIRouter()
foundation_router.include_router(organizations_router)
foundation_router.include_router(users_router)
foundation_router.include_router(rbac_router)
foundation_router.include_router(audit_logs_router)


v1 = APIRouter(prefix=settings.API_V1_PREFIX)
v1.include_router(auth_router)
v1.include_router(foundation_router)
