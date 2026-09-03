from src.exceptions import AppException, ConflictError, NotFoundError


class StockCountNotFound(NotFoundError):
    error_code = "stock_count_not_found"
    detail = "Stock count not found."


class StockCountDocumentNoConflict(ConflictError):
    error_code = "stock_count_document_no_conflict"
    detail = "A stock count with this document number already exists for the tenant."


class InvalidStockCountLocation(AppException):
    status_code = 400
    error_code = "invalid_stock_count_location"
    detail = "Location must be active and belong to the tenant."


class StockCountNotDraft(AppException):
    status_code = 400
    error_code = "stock_count_not_draft"
    detail = "Only draft stock counts can be modified."


class StockCountNotSubmittable(AppException):
    status_code = 400
    error_code = "stock_count_not_submittable"
    detail = "Only draft stock counts with at least one line can be submitted."


class StockCountNotPendingApproval(AppException):
    status_code = 400
    error_code = "stock_count_not_pending_approval"
    detail = "Only pending approval stock counts can be approved or rejected."


class StockCountNotApproved(AppException):
    status_code = 400
    error_code = "stock_count_not_approved"
    detail = "Only approved stock counts can be posted."


class StockCountNotCancellable(AppException):
    status_code = 400
    error_code = "stock_count_not_cancellable"
    detail = "Only draft or pending approval stock counts can be cancelled."


class StockCountHasNoLines(AppException):
    status_code = 400
    error_code = "stock_count_has_no_lines"
    detail = "Stock count must have at least one line."


class StockCountLineNotFound(NotFoundError):
    error_code = "stock_count_line_not_found"
    detail = "Stock count line not found."


class StockCountLineNoConflict(ConflictError):
    error_code = "stock_count_line_no_conflict"
    detail = "A stock count line with this line number already exists on the count."


class InvalidStockCountLineProduct(AppException):
    status_code = 400
    error_code = "invalid_stock_count_line_product"
    detail = "Product variant must be active, inventory-tracked, and belong to the tenant."


class InvalidStockCountLineBatch(AppException):
    status_code = 400
    error_code = "invalid_stock_count_line_batch"
    detail = "Stock batch must be active, belong to the tenant, and match the selected variant."


class StockCountNegativeBalance(AppException):
    status_code = 400
    error_code = "stock_count_negative_balance"
    detail = "Stock count posting would make a stock balance negative."
