from src.exceptions import NotFoundError


class StockBatchNotFound(NotFoundError):
    error_code = "stock_batch_not_found"
    detail = "Stock batch not found."


class StockMovementNotFound(NotFoundError):
    error_code = "stock_movement_not_found"
    detail = "Stock movement not found."


class StockBalanceNotFound(NotFoundError):
    error_code = "stock_balance_not_found"
    detail = "Stock balance not found."
