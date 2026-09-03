from src.exceptions import AppException, ConflictError, NotFoundError


class CustomerPaymentNotFound(NotFoundError):
    error_code = "customer_payment_not_found"
    detail = "Customer payment not found."


class CustomerPaymentDocumentNoConflict(ConflictError):
    error_code = "customer_payment_document_no_conflict"
    detail = "Customer payment document number already exists for this tenant."


class InvalidCustomerPaymentCustomer(AppException):
    status_code = 400
    error_code = "invalid_customer_payment_customer"
    detail = "Customer payment customer must be active and belong to the tenant."


class CustomerPaymentAllocationNotFound(NotFoundError):
    error_code = "customer_payment_allocation_not_found"
    detail = "Customer payment allocation not found."


class CustomerPaymentNotDraft(AppException):
    status_code = 400
    error_code = "customer_payment_not_draft"
    detail = "Only draft customer payments can be modified."


class CustomerPaymentNotPostable(AppException):
    status_code = 400
    error_code = "customer_payment_not_postable"
    detail = "Only draft customer payments can be posted."


class CustomerPaymentNotCancellable(AppException):
    status_code = 400
    error_code = "customer_payment_not_cancellable"
    detail = "Only draft customer payments can be cancelled."


class CustomerPaymentNotReversible(AppException):
    status_code = 400
    error_code = "customer_payment_not_reversible"
    detail = "Only posted customer payments can be reversed."


class CustomerPaymentAllocationNotEditable(AppException):
    status_code = 400
    error_code = "customer_payment_allocation_not_editable"
    detail = "Allocations can only be modified on draft or posted customer payments."


class CustomerPaymentAllocationInvoiceConflict(ConflictError):
    error_code = "customer_payment_allocation_invoice_conflict"
    detail = "A customer payment allocation for this sales invoice already exists."


class InvalidCustomerPaymentAllocationInvoice(AppException):
    status_code = 400
    error_code = "invalid_customer_payment_allocation_invoice"
    detail = "Allocation invoice must be posted and belong to the same customer and tenant."


class CustomerPaymentOverAllocated(AppException):
    status_code = 400
    error_code = "customer_payment_over_allocated"
    detail = "Customer payment allocations cannot exceed the payment amount."


class CustomerPaymentInvoiceOverpaid(AppException):
    status_code = 400
    error_code = "customer_payment_invoice_overpaid"
    detail = "Customer payment allocation cannot overpay a sales invoice."


class CustomerLedgerEntryNotFound(NotFoundError):
    error_code = "customer_ledger_entry_not_found"
    detail = "Customer ledger entry not found."


class CustomerBalanceNotFound(NotFoundError):
    error_code = "customer_balance_not_found"
    detail = "Customer balance not found."
