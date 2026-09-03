# python-fastapi-backend

A FastAPI/SQLAlchemy/Postgres backend for the POS/ERP foundation slice described by
`POS_ERD.dbml`. The current implementation is not the old admin starter; it is the
foundation layer for tenant identity, employee records, tenant-scoped users, RBAC, auth,
and audit logging.
RBAC now includes explicit assignment lifecycles for Role Permission and User Role rows in
addition to replacement-style role/user updates.

Catalog development has started with **Units**. Units are a globally managed shared
reference catalog, not tenant-owned data. Tenant users with `units.*` permissions can
create, read, update, and deactivate units; deactivation sets `is_active=false`.
The next completed catalog slice is **Product Category**. Product categories are
tenant-owned setup data, may form a parent/child tree, and use `is_active` lifecycle.
The next completed pricing setup slice is **Price Level**. Price levels are tenant-owned
and maintain at most one default per tenant.
The catalog refactor now includes the full **Catalog** setup lifecycle. Catalog items are
tenant-owned item families, product variants are the sellable/scannable rows, variant
units replace product units for POS-facing unit conversions, and barcodes/POS/location
settings hang from the variant. Catalog options define variant-defining choices for item
families and link selected option values to product variants. Product and Product Unit are
removed legacy concepts; new behavior must use Catalog Item, Product Variant, Variant
Unit, and Catalog Option terms.
Customer master-data development has started with **Customer**. Customers are tenant-owned
party records, may reference an active tenant price level, and use `status` lifecycle
(`active`, `inactive`, `blocked`); deactivation sets `status=inactive`.
Supplier master-data development now includes **Supplier**. Suppliers are tenant-owned
vendor party records and use the same `status` lifecycle; deactivation sets
`status=inactive`.
Pricing management now includes **Price Rule**. Price rules are moving to tenant-owned
variant pricing rows for product-variant/variant-unit/price-level/customer scopes.
Operational location setup now includes **Location**. Locations are tenant-owned places
for stores, warehouses, counters, damaged stock, in-transit, or virtual inventory flows;
they may form a parent/child tree and use `is_active` lifecycle.
Location accountability now includes **Location Assignment**. Location assignments are
tenant-owned history rows that connect active employees to active locations by role and
date window.
Purchasing now includes **Purchase Invoice** draft workflow. Purchase invoices are
tenant-owned purchasing documents with draft-only product-variant line and landed-cost
mutation; this slice derives totals before explicit posting.
Inventory receiving has started with **Purchase Invoice Posting**. Posting a draft
purchase invoice creates stock batches, immutable stock movements, and stock balances.
Purchase posting writes variant-aware inventory rows. Posted purchase invoices are
read-only until a future reversal slice.
Inventory operations now include **Stock Adjustment** and **Stock Transfer** documents.
Stock adjustments now use a draft workflow with product-variant/variant-unit lines,
explicit posting that can create variant-aware opening-balance batches or adjust existing
variant batch balances, and draft cancellation.
Stock transfers now use a draft workflow with product-variant/variant-unit lines to move
existing variant stock batches between active locations; explicit posting writes paired
`transfer_out` and `transfer_in` stock movements while preserving batch identity.
Repacking now includes **Repack Order** documents. Repack orders use a draft workflow to
consume existing input variant stock batches at one active location, define new output
variant batches with manual cost allocation, and explicitly post variant-aware
`repack_input` and `repack_output` stock movements while recording waste cost.
Inventory counting now includes **Stock Count** documents. Stock counts are tenant-owned
physical count records for active locations; draft counts use product-variant batch
lines, capture expected quantities from current variant-aware stock balances, move
through submit-and-approve workflow, and post approved variances as variant-aware
`count_adjustment` stock movements.
Sales now includes **Sales Invoice** draft workflow. Sales invoices are tenant-owned
selling documents with draft-only product-variant line mutation, price-level defaulting,
variant price-rule resolution, server-derived totals, explicit FIFO inventory
issue/cost proof when posted, and draft cancellation. Sales posting consumes
variant-aware stock from each line's source location. Customer payment posting now collects and allocates posted
receivables, while reversals remain a future slice.
Receivables now include **Customer Payment** draft workflow. Draft payments own mutable
header fields and allocation rows to posted customer sales invoices; explicit posting
writes customer ledger credit entries, updates invoice paid/balance amounts, and
maintains cached customer balances with unapplied payment amount represented as customer
credit.
POS sales now include **POS Checkout** for selected customers. A checkout atomically
creates and posts the sales invoice, optionally creates/posts one allocated immediate
customer payment, enforces the resulting customer credit limit, and persists tender and
post-sale balance snapshots for durable receipts. Idempotency keys make ambiguous network
retries safe. Walk-in sales continue to use the sales-invoice workflow directly.
Payables now include **Supplier Payment** draft workflow. Draft payments own mutable
header fields and allocation rows to posted supplier purchase invoices; explicit posting
updates invoice paid/balance amounts, writes supplier ledger payment entries, and
maintains cached supplier balances with unapplied payment amount represented as supplier
credit.
Document numbers are server-owned across sales invoices, purchase invoices, customer
payments, supplier payments, stock adjustments, stock transfers, stock counts, and repack
orders. Clients must not submit `document_no` on create or update; the backend generates
tenant/type/month sequences in `{PREFIX}-{YYYYMM}-{000001}` format and returns the value
in responses.

## Language

### Tenancy

**Tenant**:
A company or store operator using the POS system. Tenant-owned data carries `tenant_id`,
and authenticated requests derive tenant context from the JWT rather than from client
query parameters.
_Avoid_: organization, workspace, account

### People

**Employee**:
A person employed by a tenant. Employee records carry HR-style profile and lifecycle
fields from the ERD, including `status`.
_Avoid_: admin, staff account, operator account

**User**:
An authentication account inside a tenant. A user may optionally link to an employee and
is governed by tenant roles. Login accepts tenant code or tenant id, plus an email-or-phone
identifier and password.
_Avoid_: admin, member

### Access Control

**Role**:
A tenant-scoped named bundle of permissions assigned to users. System roles can be seeded
for baseline tenant ownership.
_Avoid_: group, tier

**Permission**:
A global read-only catalog entry identified by a stable code such as `users.read` or
`roles.update`. Permissions are granted to roles, never directly to users.
_Avoid_: grant, privilege, scope

**Role Permission**:
A tenant-owned assignment row connecting one role to one global permission. It can be
managed through role replacement payloads or explicit assign/revoke endpoints.
_Avoid_: permission grant, scope mapping

**User Role**:
A tenant-owned assignment row connecting one active user to one active role. It can be
managed through user replacement payloads or explicit assign/revoke endpoints.
_Avoid_: group membership, privilege assignment

### Catalog

**Code**:
A server-generated, tenant-scoped identifier for selected master-data records. Codes use a
stable entity prefix and six-digit sequence, such as `CUS-000001` or `ITEM-000001`; clients
cannot assign or change them. Existing codes remain unchanged during migration.
_Avoid_: document number, barcode, SKU

**Unit**:
A shared measurement or packaging reference such as `viss`, `tical`, `kg`, `g`, `piece`,
or `carton`. Units are global and permission-managed, then referenced by product catalog
records as the catalog grows module by module.
_Avoid_: tenant unit, measurement type

**Product Category**:
A tenant-owned grouping for catalog items, optionally nested under another category from the
same tenant. Categories use server-generated codes and
`is_active` for lifecycle.
_Avoid_: department, product group

**Price Level**:
A tenant-owned customer pricing tier such as retail, wholesale, or VIP. One price level
may be marked default per tenant, and future customers can reference a price level.
_Avoid_: price list, customer tier

**Catalog Item**:
A tenant-owned item family that holds shared catalog identity such as item name, local
name, description, category, kind, and lifecycle. Catalog items are not directly sold,
scanned, or stocked; their product variants are.
_Avoid_: SKU, stock item, POS tile

**Product Variant**:
A tenant-owned sellable/scannable catalog row under one catalog item. Variants carry SKU,
display name, base unit, default sale price, default purchase cost, inventory tracking
flags, and lifecycle.
_Avoid_: item family, unit conversion

**Variant Unit**:
A tenant-owned conversion row that defines an allowed sale or purchase unit for one
product variant. The active base variant unit must match the variant base unit and use
conversion value `1`; inactive rows can preserve conversion history.
_Avoid_: price rule, barcode

**Variant Barcode**:
A tenant-owned scan alias for a product variant. A barcode may optionally point to a
specific variant unit so scanning can imply both the variant and unit, such as carton
instead of piece.
_Avoid_: SKU

**Variant POS Profile**:
Optional POS tile metadata for one product variant, such as label, color, shape, image,
sort order, and visibility.
_Avoid_: catalog identity

**Variant Location Setting**:
A tenant-owned per-location row for a product variant's availability and low-stock
threshold in the variant base unit.
_Avoid_: location price

**Catalog Item Option Group**:
A tenant-owned option dimension under one catalog item, such as size, color, or pack.
Option groups own ordered option values and are used to define product variants.
_Avoid_: modifier group, POS add-on

**Catalog Item Option Value**:
A tenant-owned selectable value under one catalog item option group, such as small, red,
or carton. Option values can be linked to product variants from the same catalog item.
_Avoid_: attribute text, arbitrary tag

**Product Variant Option Value**:
A tenant-owned link assigning one catalog item option value to one product variant. A
variant may only use option values from its own catalog item, and only one value from
each option group.
_Avoid_: variant tag, product property

**Customer**:
A tenant-owned buyer/party record for sales, credit control, and future customer ledger
workflows. Customers carry a server-generated tenant-unique code, type, optional active price level, contact
details, credit limit, and lifecycle via `status`.
_Avoid_: client, account

**Supplier**:
A tenant-owned vendor/party record for purchasing, stock sourcing, and future supplier
ledger workflows. Suppliers carry a server-generated tenant-unique code, type, contact details, and
lifecycle via `status`.
_Avoid_: vendor account, purchase account

**Supplier Payment**:
A tenant-owned payables document for paying a supplier. Draft payments own mutable header
fields and allocation rows to posted purchase invoices; explicit posting writes a payment
ledger entry, updates allocated invoice paid/balance amounts, and maintains supplier
balance cache. Draft cancellation has no ledger or invoice side effects. Unallocated
amount is supplier credit.
_Avoid_: bank reconciliation, cash drawer entry, vendor payment

**Document Number**:
A server-owned, immutable identifier generated per tenant, document type, and month in
`{PREFIX}-{YYYYMM}-{000001}` format. Frontend clients display returned values but do not
submit or edit them.
_Avoid_: manual document number, frontend-generated invoice number

**Price Rule**:
A tenant-owned pricing row for a product variant, supported variant unit, price level,
optional customer, optional quantity threshold, currency, and effective period. Variant
default sale price is the fallback when no active rule matches.
_Avoid_: price list item, product price

**Location**:
A tenant-owned operational place where stock can be sold, stored, damaged, in transit, or
virtually represented. Locations carry tenant-unique codes, optional active parent
locations, sellable metadata, and lifecycle via `is_active`.
_Avoid_: branch, outlet, warehouse when the specific location type is not known

**Location Assignment**:
A tenant-owned historical responsibility row assigning an employee to a location as
responsible, assistant, or checker for a date window. Open-ended rows represent current
assignments; closing an assignment sets `end_date`.
_Avoid_: staff schedule, shift, roster

**Purchase Invoice**:
A tenant-owned draft purchasing document from a supplier into a receiving location.
Headers own product-variant invoice lines and landed costs; draft mutations recalculate
totals, explicit posting receives stock and writes supplier payable proof, and
cancellation changes document status without inventory posting. Public line responses
expose variant identity.
_Avoid_: receiving note, supplier bill when no stock posting has happened yet

**Sales Invoice**:
A tenant-owned selling document for a customer or walk-in sale at a sellable location.
Headers own product-variant sales lines, derive totals, default price levels, and
preserve final line prices. The header location is the sale/register location; each
inventory-tracked line may carry a source location that supplies stock. Draft mutations
recalculate totals, explicit posting consumes variant-aware stock by FIFO, writes `sale_issue` movements and
`sales_invoice_line_costs`, calculates cost/gross profit, and writes customer receivable
ledger debit entries when the invoice has a customer. Draft cancellation changes document
status without stock issue or receivable proof. Public line responses expose variant
identity.
_Avoid_: sales order, receipt when no payment or stock issue has happened yet

**Customer Payment**:
A tenant-owned receivables document for collecting money from a customer. Draft payments
own mutable header fields and allocation rows to posted sales invoices; explicit posting
writes a payment ledger credit, updates allocated invoice paid/balance amounts, and
maintains customer balance cache. Draft cancellation has no ledger or invoice side
effects. Unallocated amount is customer credit.
_Avoid_: cash drawer entry, bank reconciliation, refund

**POS Checkout**:
A tenant-owned, idempotent customer sale transaction that atomically posts one sales
invoice and an optional immediate customer payment. Its durable tender snapshot records
paid-now, cash tendered/change, charged-to-account, and post-sale customer credit values.
_Avoid_: split tender, sales invoice, customer payment

**Stock Adjustment**:
A tenant-owned draft inventory correction document for opening balances, count variance,
damage, loss, expiry, correction, or other stock changes. Posting writes immutable stock
movements, updates balances, and may create opening-balance stock batches. Draft
header/line mutations are allowed until posting or cancellation. Public line responses
expose variant identity.
_Avoid_: stock count, transfer, purchase receiving

**Stock Transfer**:
A tenant-owned draft inventory movement document that moves existing variant stock batches
between two active locations. Draft header/line mutations are allowed until posting or
cancellation; posting writes paired `transfer_out` and `transfer_in` stock movements,
updates cached balances, and preserves the original stock batch identity.
_Avoid_: stock adjustment, receiving, sale issue

**Stock Count**:
A tenant-owned physical count document for an active location. Draft count lines reference
existing variant stock batches, snapshot expected base quantities from stock balances, store
counted quantities and variances, require submission and approval before posting, and
write `count_adjustment` stock movements when approved variances are posted.
Public line responses expose variant identity.
_Avoid_: stock adjustment, generated count sheet

**Repack Order**:
A tenant-owned inventory transformation document at one active location. Draft input
lines reference existing variant stock batches to consume; draft output lines define new
variant stock batches with manually allocated cost. Draft header/input/output mutations
are allowed until posting or cancellation. Posting writes variant-aware `repack_input`
and `repack_output` stock movements, updates balances, creates output stock batches, and
derives waste cost. Public input/output responses expose variant identity.
_Avoid_: manufacturing order, production order

**Stock Batch**:
A tenant-owned source-traceable quantity of stock keyed by product variant, location, and
source batch identity.
_Avoid_: product unit, inventory item

**Stock Movement**:
An immutable tenant-owned inventory ledger row. Purchase invoice posting writes positive
`purchase_receive` movements; stock adjustment posting writes signed `adjustment` or
`damage_loss` movements; stock count posting writes `count_adjustment` variance
movements; stock transfers write paired `transfer_out` and `transfer_in` movements;
repack orders write negative `repack_input` and positive `repack_output` movements; sales
invoice posting writes negative `sale_issue` movements.
_Avoid_: stock transaction when the ledger row is meant

**Stock Balance**:
A tenant-owned cached quantity by product variant, location, and stock batch, updated from
stock movements and rebuildable from the inventory ledger. Public inventory reads expose
variant identity.
_Avoid_: source of truth inventory ledger

**User Role**:
The assignment joining a user to a tenant role.
_Avoid_: membership, direct permission

### Auth Credentials

**Refresh Token**:
A long-lived opaque credential held by a user, exchanged to mint new short-lived access
tokens. Stored only as a hash in `user_refresh_tokens`, rotated on refresh, and revoked on
logout or password change.
_Avoid_: session, access token

### Observability

**Audit Log**:
An append-only tenant-scoped record of a management or auth action. Audit rows reference
the acting user when one exists and may capture before/after JSON state for changed
entities.
_Avoid_: activity log, history, change log
