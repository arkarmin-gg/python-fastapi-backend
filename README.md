# python-fastapi-backend

FastAPI + SQLAlchemy + Postgres backend for the POS/ERP foundation slice from
`POS_ERD.dbml`.

Implemented foundation modules:

- tenants
- employees
- users
- tenant-scoped RBAC with a global permission catalog
- tenant user auth with refresh-token rotation
- tenant-scoped audit logs
- explicit RBAC role-permission and user-role assignment lifecycle
- catalog units as a globally managed shared reference catalog
- tenant-scoped product categories
- tenant-scoped catalog items, variants, variant units, barcodes, POS profiles, and
  location settings
- tenant-scoped catalog option groups, option values, and variant option links
- tenant-scoped price levels
- tenant-scoped customers
- tenant-scoped suppliers
- server-generated tenant-scoped codes for employees, locations, categories, price levels,
  suppliers, customers, catalog items, and product variants
- tenant-scoped variant price rules
- tenant-scoped locations
- tenant-scoped location assignments
- tenant-scoped draft purchase invoices with variant lines
- tenant-scoped purchase invoice posting into inventory
- tenant-scoped supplier payment draft workflow and payables
- tenant-scoped customer payment draft workflow and receivables
- transactional selected-customer POS checkout with partial payment, credit-limit
  enforcement, idempotent retry, and durable receipt snapshots
- tenant-scoped stock adjustment draft workflow with explicit opening-balance posting
- tenant-scoped stock counts with approval and variance posting
- tenant-scoped stock transfers with paired movement posting
- tenant-scoped repack orders with input consumption and output batch posting
- tenant-scoped sales invoice draft workflow with variant lines, line-level stock sources, explicit FIFO posting, and cost proof
- server-owned document number generation for invoices, payments, stock operations,
  counts, and repack orders
- tenant-scoped inventory visibility for stock batches, movements, and balances

The previous starter API, generic settings table, soft-delete behavior, and activity log
schema have been replaced.

## Stack

Python 3.13 · uv · FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic · Pydantic v2 ·
PyJWT · argon2-cffi · ruff · pytest

## Layout

```text
src/
├── api/routers.py
├── config.py        database.py      models.py
├── dependencies.py  exceptions.py    main.py     registry.py
├── modules/
│   ├── auth/        login/logout/refresh/me and user_refresh_tokens
│   ├── tenants/     tenant/company records
│   ├── employees/   tenant employee records
│   ├── users/       user accounts and user_roles
│   ├── rbac/        roles, permissions, role_permissions, user_role assignments
│   ├── units/       globally managed unit catalog
│   ├── product_categories/ tenant product category tree
│   ├── catalog/     item/variant catalog, options, and POS-facing setup
│   ├── price_levels/ tenant customer pricing levels
│   ├── customers/   tenant customer master data
│   ├── suppliers/   tenant supplier master data
│   ├── supplier_payments/ supplier payment drafts, allocations, and payables posting
│   ├── price_rules/ tenant variant/customer price rules
│   ├── locations/   tenant operational location master data
│   ├── location_assignments/ employee location responsibility history
│   ├── document_numbers/ tenant/type/month document number sequences
│   ├── purchase_invoices/ draft purchase invoices and receiving posting
│   ├── stock_adjustments/ stock adjustment drafts and explicit posting
│   ├── stock_counts/ approved stock counts and variance posting
│   ├── stock_transfers/ stock transfer drafts and explicit posting
│   ├── repack_orders/ repack order drafts and explicit posting
│   ├── sales_invoices/ sales invoice drafts, price resolution, and FIFO posting
│   ├── inventory/   read-only stock batches, movements, and balances
│   └── audit_logs/  ERD-style audit_logs
├── pagination.py
└── query_filters.py
migrations/          one POS foundation baseline migration
scripts/seed.py      demo tenant + owner role/user seed
scripts/clear_database.py destructive local data reset helper
tests/               auth and foundation CRUD/RBAC/audit tests
```

`src/registry.py` imports every active model module so `Base.metadata` is complete for
the app, Alembic, tests, and seed.

## Quick Start

```bash
uv sync
cp .env.example .env
createdb grocery_pos
make migrate
make seed
make seed-catalog
make run
```

If an existing local database was already stamped with the old starter baseline revision,
recreate or reset that database before running `make migrate`. The baseline migration was
intentionally replaced for the POS foundation refactor.

The base seed creates one tenant and owner user. `make seed-catalog` adds demo Myanmar
grocery categories, catalog items, product variants, and variant units. Defaults:

- `TENANT_CODE=demo`
- `TENANT_NAME="Demo Grocery"`
- `USER_EMAIL=owner@example.com`
- `USER_PASSWORD=ChangeMe123!`

Log in with:

```http
POST /api/v1/auth/login
{
  "tenant_code": "demo",
  "identifier": "owner@example.com",
  "password": "ChangeMe123!"
}
```

Use the returned bearer token for `/api/v1/users`, `/api/v1/roles`,
`/api/v1/role-permissions`, `/api/v1/user-roles`,
`/api/v1/employees`, `/api/v1/tenants`, `/api/v1/permissions`,
`/api/v1/units`, `/api/v1/product-categories`, `/api/v1/price-levels`,
`/api/v1/catalog-items`, `/api/v1/product-variants`, `/api/v1/variant-units`,
`/api/v1/variant-barcodes`, `/api/v1/variant-pos-profiles`,
`/api/v1/variant-location-settings`, `/api/v1/catalog/barcode-lookup`,
`/api/v1/catalog-item-option-groups`, `/api/v1/catalog-item-option-values`,
`/api/v1/product-variant-option-values`,
`/api/v1/suppliers`, `/api/v1/supplier-payments`,
`/api/v1/supplier-ledger-entries`, `/api/v1/supplier-balances`,
`/api/v1/price-rules`, `/api/v1/locations`, `/api/v1/location-assignments`,
`/api/v1/purchase-invoices`, `/api/v1/stock-adjustments`, `/api/v1/stock-counts`,
`/api/v1/stock-transfers`, `/api/v1/repack-orders`, `/api/v1/sales-invoices`,
`/api/v1/stock-batches`, `/api/v1/stock-movements`, `/api/v1/stock-balances`, and
`/api/v1/audit-logs`.

The Bruno collection in `bruno/` mirrors these current endpoints and includes a local
environment example for the seeded tenant/user.

## Make Targets

| Command                      | What it does                         |
| ---------------------------- | ------------------------------------ |
| `make run`                   | API with autoreload                  |
| `make migrate`               | `alembic upgrade head`               |
| `make makemigration m="msg"` | autogenerate a migration             |
| `make downgrade`             | revert the last migration            |
| `make seed`                  | seed demo tenant + owner user        |
| `make seed-catalog`          | seed demo grocery catalog            |
| `make clear-db confirm=yes`  | truncate app tables, keep migrations |
| `make test`                  | run tests                            |
| `make lint` / `make format`  | ruff check + format                  |

## Conventions

- UUID primary keys with server-side `gen_random_uuid()`.
- Tenant-owned foundation tables carry `tenant_id`; protected routes derive tenant
  context from the JWT.
- Login requires `tenant_code` or `tenant_id`, plus an email-or-phone identifier.
- Enums are varchar-backed `StrEnum` values.
- Lifecycle uses ERD state fields like `status` and `is_active`, not soft delete.
- Refresh tokens are opaque, stored hashed, rotated on use, and revoked on logout or
  password change.
- RBAC role permissions and user roles can be managed either through full role/user
  replacement payloads or explicit assignment endpoints. Assignment endpoints validate
  active tenant-owned users/roles, reject duplicates, and audit assign/revoke actions.
- Catalog development starts with globally managed units. Units are shared across tenants,
  permission-gated through RBAC, seeded with Myanmar grocery defaults, and deactivated
  rather than hard deleted.
- Product categories are tenant-scoped, optionally hierarchical, permission-gated through
  RBAC, and deactivated rather than hard deleted.
- Price levels are tenant-scoped, permission-gated through RBAC, and maintain at most one
  default level per tenant for future customer pricing.
- Catalog items and product variants are the public catalog contract. Product variants
  are sellable/scannable rows, variant units hold allowed sales and purchase conversions,
  variant barcodes support scan aliases, POS profiles hold tile presentation, and variant
  location settings hold availability and low-stock thresholds. Catalog option groups
  and values define variant-defining choices such as size or color; product variant
  option links assign one value per option group to a variant. Catalog item, variant,
  variant unit, barcode, POS profile, location setting, and option endpoints now expose
  the full create/list/read/update/deactivate-or-delete lifecycle matching their ERD
  state fields.
- Legacy Product and Product Unit tables/modules have been removed. New catalog,
  pricing, document, and inventory behavior must use Catalog Item, Product Variant, and
  Variant Unit.
- Customers are tenant-scoped party records, permission-gated through RBAC, may reference
  an active tenant price level, and are deactivated by setting `status=inactive`.
- Suppliers are tenant-scoped vendor party records, permission-gated through RBAC, and
  are deactivated by setting `status=inactive`.
- Price rules are tenant-scoped variant/customer pricing rows, require active variant
  units for the selected product-variant/variant-unit pair, and are deactivated by
  setting `is_active=false`.
- Locations are tenant-scoped operational places, may form an active parent/child tree,
  and are deactivated by setting `is_active=false` without cascading to children.
- Location assignments are tenant-scoped employee responsibility history rows for
  locations; date windows define current versus historical assignment state.
- Purchase invoices are tenant-scoped draft purchasing documents. Headers own
  product-variant lines and landed costs through draft-only child CRUD; the API derives
  totals after each mutation and cancellation uses `status=cancelled` without posting
  stock.
- Purchase invoice posting receives draft invoices into inventory by creating one
  variant-aware stock batch and one purchase-receive movement per line, updating stock
  balances, and setting the invoice to `status=posted`; it also records supplier payable
  ledger and balance rows. Inventory rows are keyed by product variant. Posted invoices
  are read-only until a reversal slice is implemented.
- Inventory read endpoints expose stock batches, movements, and balances by
  `product_variant_id`.
- Variant-native document line APIs expose `product_variant_id` and `variant_unit_id`
  where applicable.
- Supplier payments are tenant-scoped payables documents. Draft payments own mutable
  header fields and allocation rows to posted supplier purchase invoices; explicit
  posting updates invoice paid/balance amounts, writes supplier ledger payment entries,
  and maintains cached supplier balances. Draft cancellation changes document status
  without payable side effects. Unapplied payment amount is represented as supplier
  credit.
- Stock adjustments are tenant-scoped draft inventory correction documents. Draft headers
  own mutable product-variant lines with variant units; explicit posting writes
  variant-aware adjustment or damage/loss stock movements, updates balances, and can
  create opening-balance stock batches at post time. Draft cancellation changes document
  status without inventory side effects.
- Stock counts are tenant-scoped physical count documents for active locations. Draft
  counts own manual product-variant/batch lines, capture expected base quantities from
  variant-aware stock balances, require submit-and-approve workflow, and posting writes
  variant-aware count-adjustment movements plus stock balance updates. Rejection returns
  a count to draft.
- Stock transfers are tenant-scoped draft inventory movement documents. Draft lines use
  product variants and variant units against existing stock batches; draft header/line
  mutations are allowed until posting or cancellation. Explicit posting preserves batch
  identity, moves variant-aware balances between active locations, and writes paired
  `transfer_out` and `transfer_in` stock movements.
- Repack orders are tenant-scoped draft inventory transformation documents for active
  locations. Draft header/input/output mutations are allowed until posting or
  cancellation; input cost is derived from existing variant stock batches, and draft
  outputs carry manual allocated cost for new variant batches. Explicit posting writes
  variant-aware repack input/output stock movements, creates new output stock batches,
  updates stock balances, and records waste cost.
- Sales invoices are tenant-scoped selling documents. Draft headers own mutable
  product-variant lines, default active price levels from customer or tenant setup, and
  resolve active variant price rules when line prices are omitted. The header location is
  the sale/register location, while each tracked line can issue stock from its own active
  source location. Explicit posting consumes variant-aware stock by FIFO, writes `sale_issue` movements and FIFO cost
  proof rows, and customer payment posting collects and allocates posted receivables while
  reversals remain a future slice. Draft cancellation changes document status without
  inventory or receivable side effects.
- Customer payments are tenant-scoped receivables documents. Draft payments own mutable
  header fields and allocation rows to posted customer sales invoices; explicit posting
  writes customer ledger credit entries, updates invoice paid/balance amounts, and
  maintains cached customer balances. Draft cancellation changes document status without
  receivable side effects. Unapplied payment amount is represented as customer credit.
- POS checkouts atomically create/post one selected-customer sales invoice and optionally
  create/post one allocated immediate payment. They enforce the resulting net credit
  balance against the customer limit and persist paid-now, cash tendered/change,
  charged-to-account, and post-sale balance snapshots for historical receipts.
- Inventory visibility is read-only for now and exposes tenant-scoped stock batches,
  immutable stock movements, and cached stock balances through `inventory.read`.
