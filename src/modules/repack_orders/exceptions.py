from src.exceptions import AppException, ConflictError, NotFoundError


class RepackOrderNotFound(NotFoundError):
    error_code = "repack_order_not_found"
    detail = "Repack order not found."


class RepackOrderDocumentNoConflict(ConflictError):
    error_code = "repack_order_document_no_conflict"
    detail = "A repack order with this document number already exists for the tenant."


class RepackOrderNotDraft(AppException):
    status_code = 400
    error_code = "repack_order_not_draft"
    detail = "Only draft repack orders can be changed."


class RepackOrderHasNoInputs(AppException):
    status_code = 400
    error_code = "repack_order_has_no_inputs"
    detail = "Repack order must have at least one input line before posting."


class RepackOrderHasNoOutputs(AppException):
    status_code = 400
    error_code = "repack_order_has_no_outputs"
    detail = "Repack order must have at least one output line before posting."


class RepackOrderNotPostable(AppException):
    status_code = 400
    error_code = "repack_order_not_postable"
    detail = "Only draft repack orders can be posted."


class RepackOrderNotCancellable(AppException):
    status_code = 400
    error_code = "repack_order_not_cancellable"
    detail = "Only draft repack orders can be cancelled."


class RepackOrderOutputCostExceedsInputCost(AppException):
    status_code = 400
    error_code = "repack_order_output_cost_exceeds_input_cost"
    detail = "Total output allocated cost cannot exceed total input cost."


class RepackOrderOutputQuantityExceedsInputQuantity(AppException):
    status_code = 400
    error_code = "repack_order_output_quantity_exceeds_input_quantity"
    detail = "Total output quantity cannot exceed total input quantity."


class RepackOrderInputNotFound(NotFoundError):
    error_code = "repack_order_input_not_found"
    detail = "Repack order input line not found."


class RepackOrderInputLineNoConflict(ConflictError):
    error_code = "repack_order_input_line_no_conflict"
    detail = "A repack order input line with this line number already exists on the order."


class RepackOrderOutputNotFound(NotFoundError):
    error_code = "repack_order_output_not_found"
    detail = "Repack order output line not found."


class RepackOrderOutputLineNoConflict(ConflictError):
    error_code = "repack_order_output_line_no_conflict"
    detail = "A repack order output line with this line number already exists on the order."


class InvalidRepackOrderLocation(AppException):
    status_code = 400
    error_code = "invalid_repack_order_location"
    detail = "Location must be active and belong to the tenant."


class InvalidRepackOrderEmployee(AppException):
    status_code = 400
    error_code = "invalid_repack_order_employee"
    detail = "Employee must be active and belong to the tenant."


class InvalidRepackOrderInputProduct(AppException):
    status_code = 400
    error_code = "invalid_repack_order_input_product"
    detail = (
        "Input product variant must be active, inventory-tracked, bridged, "
        "and belong to the tenant."
    )


class InvalidRepackOrderInputUnit(AppException):
    status_code = 400
    error_code = "invalid_repack_order_input_unit"
    detail = "Input variant unit must be active and belong to the selected product variant."


class InvalidRepackOrderInputBatch(AppException):
    status_code = 400
    error_code = "invalid_repack_order_input_batch"
    detail = "Input stock batch must be active, belong to the tenant, and match the variant."


class RepackOrderInsufficientBalance(AppException):
    status_code = 400
    error_code = "repack_order_insufficient_balance"
    detail = "Repack order would make the input stock balance negative."


class InvalidRepackOrderOutputProduct(AppException):
    status_code = 400
    error_code = "invalid_repack_order_output_product"
    detail = (
        "Output product variant must be active, inventory-tracked, bridged, "
        "and belong to the tenant."
    )


class InvalidRepackOrderOutputUnit(AppException):
    status_code = 400
    error_code = "invalid_repack_order_output_unit"
    detail = "Output variant unit must be active and belong to the selected product variant."
