from src.exceptions import AppException, ConflictError, NotFoundError


class SalesInvoiceNotFound(NotFoundError):
    error_code = "sales_invoice_not_found"
    detail = "Sales invoice not found."


class SalesInvoiceDocumentNoConflict(ConflictError):
    error_code = "sales_invoice_document_no_conflict"
    detail = "A sales invoice with this document number already exists for the tenant."


class SalesInvoiceLineNoConflict(ConflictError):
    error_code = "sales_invoice_line_no_conflict"
    detail = "A sales invoice line with this line number already exists for the invoice."


class SalesInvoiceNotDraft(AppException):
    status_code = 400
    error_code = "sales_invoice_not_draft"
    detail = "Only draft sales invoices can be mutated."


class SalesInvoiceHasNoLines(AppException):
    status_code = 400
    error_code = "sales_invoice_has_no_lines"
    detail = "Sales invoice must have at least one line before posting."


class SalesInvoiceNotPostable(AppException):
    status_code = 400
    error_code = "sales_invoice_not_postable"
    detail = "Only draft sales invoices can be posted."


class SalesInvoiceNotCancellable(AppException):
    status_code = 400
    error_code = "sales_invoice_not_cancellable"
    detail = "Only draft sales invoices can be cancelled."


class InvalidSalesInvoiceCustomer(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_customer"
    detail = "Customer must be active and belong to the tenant."


class InvalidSalesInvoicePriceLevel(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_price_level"
    detail = "Price level must be active and belong to the tenant."


class MissingSalesInvoicePriceLevel(AppException):
    status_code = 400
    error_code = "missing_sales_invoice_price_level"
    detail = "An active price level is required for the sales invoice."


class InvalidSalesInvoiceLocation(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_location"
    detail = "Location must be active, sellable, and belong to the tenant."


class SalesInvoiceInsufficientStock(AppException):
    status_code = 400
    error_code = "sales_invoice_insufficient_stock"
    detail = "Insufficient stock is available to post the sales invoice."


class InvalidSalesInvoiceDiscount(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_discount"
    detail = "Discount amount cannot make the sales invoice total negative."


class SalesInvoiceLineNotFound(NotFoundError):
    error_code = "sales_invoice_line_not_found"
    detail = "Sales invoice line not found."


class InvalidSalesInvoiceLineProduct(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_line_product"
    detail = "Product variant must be active and belong to the tenant."


class InvalidSalesInvoiceLineUnit(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_line_unit"
    detail = "Unit must be an active sales product unit for the selected product."


class InvalidSalesInvoiceLineSourceLocation(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_line_source_location"
    detail = (
        "Source location must be active, available for the product variant, "
        "and belong to the tenant."
    )


class SalesInvoiceLineMeasuredQuantityRequired(AppException):
    status_code = 400
    error_code = "sales_invoice_line_measured_quantity_required"
    detail = "Measured quantity is required for this product's selected unit."


class MissingSalesInvoiceLinePrice(AppException):
    status_code = 400
    error_code = "missing_sales_invoice_line_price"
    detail = "A unit price or matching active price rule is required for the sales invoice line."


class InvalidSalesInvoiceLineDiscount(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_line_discount"
    detail = "Discount amount cannot make the sales invoice line total negative."


class SalesInvoiceLineCostNotFound(NotFoundError):
    error_code = "sales_invoice_line_cost_not_found"
    detail = "Sales invoice line cost not found."


class InvalidSalesInvoiceLineLocations(AppException):
    status_code = 400
    error_code = "invalid_sales_invoice_line_locations"
    detail = (
        "Line locations must be unique and active, with the variant available "
        "at each location, and their quantities must sum to the line quantity."
    )
