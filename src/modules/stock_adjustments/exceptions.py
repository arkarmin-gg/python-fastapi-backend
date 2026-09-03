from src.exceptions import AppException, ConflictError, NotFoundError


class StockAdjustmentNotFound(NotFoundError):
    error_code = "stock_adjustment_not_found"
    detail = "Stock adjustment not found."


class StockAdjustmentDocumentNoConflict(ConflictError):
    error_code = "stock_adjustment_document_no_conflict"
    detail = "A stock adjustment with this document number already exists for the tenant."


class StockAdjustmentLineNoConflict(ConflictError):
    error_code = "stock_adjustment_line_no_conflict"
    detail = "A stock adjustment line with this line number already exists for the adjustment."


class StockAdjustmentNotDraft(AppException):
    status_code = 400
    error_code = "stock_adjustment_not_draft"
    detail = "Only draft stock adjustments can be mutated."


class StockAdjustmentHasNoLines(AppException):
    status_code = 400
    error_code = "stock_adjustment_has_no_lines"
    detail = "Stock adjustment must have at least one line before posting."


class StockAdjustmentNotPostable(AppException):
    status_code = 400
    error_code = "stock_adjustment_not_postable"
    detail = "Only draft stock adjustments can be posted."


class StockAdjustmentNotCancellable(AppException):
    status_code = 400
    error_code = "stock_adjustment_not_cancellable"
    detail = "Only draft stock adjustments can be cancelled."


class InvalidStockAdjustmentLocation(AppException):
    status_code = 400
    error_code = "invalid_stock_adjustment_location"
    detail = "Location must be active and belong to the tenant."


class StockAdjustmentLineNotFound(NotFoundError):
    error_code = "stock_adjustment_line_not_found"
    detail = "Stock adjustment line not found."


class InvalidStockAdjustmentLineProduct(AppException):
    status_code = 400
    error_code = "invalid_stock_adjustment_line_product"
    detail = "Product variant must be active, inventory-tracked, and belong to the tenant."


class InvalidStockAdjustmentLineUnit(AppException):
    status_code = 400
    error_code = "invalid_stock_adjustment_line_unit"
    detail = "Unit must be an active product unit for the selected product."


class InvalidStockAdjustmentLineBatch(AppException):
    status_code = 400
    error_code = "invalid_stock_adjustment_line_batch"
    detail = "Stock batch must be active, belong to the tenant, and match the selected product."


class StockAdjustmentLineBatchRequired(AppException):
    status_code = 400
    error_code = "stock_adjustment_line_batch_required"
    detail = "Non-opening balance adjustment lines must reference an existing stock batch."


class StockAdjustmentLineBatchNotAllowed(AppException):
    status_code = 400
    error_code = "stock_adjustment_line_batch_not_allowed"
    detail = "Only opening balance lines may omit a stock batch to create one during posting."


class StockAdjustmentLineCostRequired(AppException):
    status_code = 400
    error_code = "stock_adjustment_line_cost_required"
    detail = "Opening balance lines that create a stock batch require a positive base unit cost."


class StockAdjustmentNegativeBalance(AppException):
    status_code = 400
    error_code = "stock_adjustment_negative_balance"
    detail = "Stock adjustment would make a stock balance negative."
