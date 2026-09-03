from fastapi import APIRouter

from src.config import settings
from src.modules.analytics.router import router as analytics_router
from src.modules.audit_logs.router import router as audit_logs_router
from src.modules.auth.router import router as auth_router
from src.modules.catalog.router import router as catalog_router
from src.modules.customer_payments.router import router as customer_payments_router
from src.modules.customers.router import router as customers_router
from src.modules.employees.router import router as employees_router
from src.modules.inventory.router import router as inventory_router
from src.modules.location_assignments.router import router as location_assignments_router
from src.modules.locations.router import router as locations_router
from src.modules.pos_checkouts.router import router as pos_checkouts_router
from src.modules.price_levels.router import router as price_levels_router
from src.modules.price_rules.router import router as price_rules_router
from src.modules.product_categories.router import router as product_categories_router
from src.modules.purchase_invoices.router import router as purchase_invoices_router
from src.modules.rbac.router import router as rbac_router
from src.modules.repack_orders.router import router as repack_orders_router
from src.modules.sales_invoices.router import router as sales_invoices_router
from src.modules.stock_adjustments.router import router as stock_adjustments_router
from src.modules.stock_counts.router import router as stock_counts_router
from src.modules.stock_transfers.router import router as stock_transfers_router
from src.modules.supplier_payments.router import router as supplier_payments_router
from src.modules.suppliers.router import router as suppliers_router
from src.modules.tenants.router import router as tenants_router
from src.modules.units.router import router as units_router
from src.modules.users.router import router as users_router

foundation_router = APIRouter()
foundation_router.include_router(tenants_router)
foundation_router.include_router(employees_router)
foundation_router.include_router(users_router)
foundation_router.include_router(rbac_router)
foundation_router.include_router(units_router)
foundation_router.include_router(product_categories_router)
foundation_router.include_router(catalog_router)
foundation_router.include_router(price_levels_router)
foundation_router.include_router(price_rules_router)
foundation_router.include_router(customers_router)
foundation_router.include_router(customer_payments_router)
foundation_router.include_router(suppliers_router)
foundation_router.include_router(supplier_payments_router)
foundation_router.include_router(locations_router)
foundation_router.include_router(location_assignments_router)
foundation_router.include_router(purchase_invoices_router)
foundation_router.include_router(stock_adjustments_router)
foundation_router.include_router(stock_counts_router)
foundation_router.include_router(stock_transfers_router)
foundation_router.include_router(repack_orders_router)
foundation_router.include_router(sales_invoices_router)
foundation_router.include_router(pos_checkouts_router)
foundation_router.include_router(inventory_router)
foundation_router.include_router(audit_logs_router)
foundation_router.include_router(analytics_router)


v1 = APIRouter(prefix=settings.API_V1_PREFIX)
v1.include_router(auth_router)
v1.include_router(foundation_router)
