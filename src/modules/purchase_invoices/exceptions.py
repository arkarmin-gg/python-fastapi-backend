from src.exceptions import AppException, ConflictError, NotFoundError


class PurchaseInvoiceNotFound(NotFoundError):
    error_code = "purchase_invoice_not_found"
    detail = "Purchase invoice not found."


class PurchaseInvoiceDocumentNoConflict(ConflictError):
    error_code = "purchase_invoice_document_no_conflict"
    detail = "A purchase invoice with this document number already exists for the tenant."


class InvalidPurchaseInvoiceSupplier(AppException):
    status_code = 400
    error_code = "invalid_purchase_invoice_supplier"
    detail = "Supplier must be active and belong to the tenant."


class InvalidPurchaseInvoiceLocation(AppException):
    status_code = 400
    error_code = "invalid_purchase_invoice_location"
    detail = "Receiving location must be active and belong to the tenant."


class PurchaseInvoiceLineProductNotInventoryTracked(AppException):
    status_code = 400
    error_code = "purchase_invoice_line_product_not_inventory_tracked"
    detail = "Purchase invoice lines can only be posted for inventory-tracked variants."


class PurchaseInvoiceLineMissingLotNumber(AppException):
    status_code = 400
    error_code = "purchase_invoice_line_missing_lot_number"
    detail = "Batch-tracked variants require a lot number before posting."


class PurchaseInvoiceLineMissingExpiryDate(AppException):
    status_code = 400
    error_code = "purchase_invoice_line_missing_expiry_date"
    detail = "Expiry-tracked variants require an expiry date before posting."


class PurchaseInvoiceLineNotFound(NotFoundError):
    error_code = "purchase_invoice_line_not_found"
    detail = "Purchase invoice line not found."


class PurchaseInvoiceLineNoConflict(ConflictError):
    error_code = "purchase_invoice_line_no_conflict"
    detail = "A purchase invoice line with this line number already exists for the invoice."


class InvalidPurchaseInvoiceLineProduct(AppException):
    status_code = 400
    error_code = "invalid_purchase_invoice_line_product"
    detail = "Product variant must be active and belong to the tenant."


class InvalidPurchaseInvoiceLineUnit(AppException):
    status_code = 400
    error_code = "invalid_purchase_invoice_line_unit"
    detail = "Unit must be an active product unit for the selected product."


class PurchaseInvoiceLineMeasuredQuantityRequired(AppException):
    status_code = 400
    error_code = "purchase_invoice_line_measured_quantity_required"
    detail = "Measured quantity is required for this product's selected unit."


class PurchaseLandedCostNotFound(NotFoundError):
    error_code = "purchase_landed_cost_not_found"
    detail = "Purchase landed cost not found."


class InvalidPurchaseLandedCostAllocation(AppException):
    status_code = 400
    error_code = "invalid_purchase_landed_cost_allocation"
    detail = "Manual landed cost allocation is not supported yet."


class PurchaseInvoiceNotDraft(AppException):
    status_code = 400
    error_code = "purchase_invoice_not_draft"
    detail = "Purchase invoice can only be changed while it is draft."


class PurchaseInvoiceHasNoLines(AppException):
    status_code = 400
    error_code = "purchase_invoice_has_no_lines"
    detail = "Purchase invoice must have at least one line before posting."


class PurchaseInvoiceNotPostable(AppException):
    status_code = 400
    error_code = "purchase_invoice_not_postable"
    detail = "Only draft purchase invoices can be posted."


class PurchaseInvoiceNotCancellable(AppException):
    status_code = 400
    error_code = "purchase_invoice_not_cancellable"
    detail = "Only draft purchase invoices can be cancelled."
