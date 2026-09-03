from src.exceptions import AppException, ConflictError, NotFoundError


class StockTransferNotFound(NotFoundError):
    error_code = "stock_transfer_not_found"
    detail = "Stock transfer not found."


class StockTransferDocumentNoConflict(ConflictError):
    error_code = "stock_transfer_document_no_conflict"
    detail = "A stock transfer with this document number already exists for the tenant."


class StockTransferLineNotFound(NotFoundError):
    error_code = "stock_transfer_line_not_found"
    detail = "Stock transfer line not found."


class StockTransferLineNoConflict(ConflictError):
    error_code = "stock_transfer_line_no_conflict"
    detail = "A stock transfer line with this line number already exists on the transfer."


class StockTransferNotDraft(AppException):
    status_code = 400
    error_code = "stock_transfer_not_draft"
    detail = "Only draft stock transfers can be changed."


class StockTransferHasNoLines(AppException):
    status_code = 400
    error_code = "stock_transfer_has_no_lines"
    detail = "Stock transfer must have at least one line before posting."


class StockTransferNotPostable(AppException):
    status_code = 400
    error_code = "stock_transfer_not_postable"
    detail = "Only draft stock transfers can be posted."


class StockTransferNotCancellable(AppException):
    status_code = 400
    error_code = "stock_transfer_not_cancellable"
    detail = "Only draft stock transfers can be cancelled."


class InvalidStockTransferLineProduct(AppException):
    status_code = 400
    error_code = "invalid_stock_transfer_line_product"
    detail = "Product variant must be active, inventory-tracked, and belong to the tenant."


class InvalidStockTransferLineUnit(AppException):
    status_code = 400
    error_code = "invalid_stock_transfer_line_unit"
    detail = "Variant unit must be active and belong to the selected product variant."


class InvalidStockTransferLineBatch(AppException):
    status_code = 400
    error_code = "invalid_stock_transfer_line_batch"
    detail = "Stock batch must be active, belong to the tenant, and match the selected variant."


class InvalidStockTransferLineLocation(AppException):
    status_code = 400
    error_code = "invalid_stock_transfer_line_location"
    detail = "Source and destination locations must be active, different, and belong to the tenant."


class StockTransferInsufficientBalance(AppException):
    status_code = 400
    error_code = "stock_transfer_insufficient_balance"
    detail = "Stock transfer would make the source stock balance negative."
