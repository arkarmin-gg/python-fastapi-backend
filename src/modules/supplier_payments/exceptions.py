from src.exceptions import AppException, ConflictError, NotFoundError


class SupplierPaymentNotFound(NotFoundError):
    error_code = "supplier_payment_not_found"
    detail = "Supplier payment not found."


class SupplierPaymentDocumentNoConflict(ConflictError):
    error_code = "supplier_payment_document_no_conflict"
    detail = "Supplier payment document number already exists for this tenant."


class InvalidSupplierPaymentSupplier(AppException):
    status_code = 400
    error_code = "invalid_supplier_payment_supplier"
    detail = "Supplier payment supplier must be active and belong to the tenant."


class SupplierPaymentAllocationNotFound(NotFoundError):
    error_code = "supplier_payment_allocation_not_found"
    detail = "Supplier payment allocation not found."


class SupplierPaymentNotDraft(AppException):
    status_code = 400
    error_code = "supplier_payment_not_draft"
    detail = "Only draft supplier payments can be modified."


class SupplierPaymentNotPostable(AppException):
    status_code = 400
    error_code = "supplier_payment_not_postable"
    detail = "Only draft supplier payments can be posted."


class SupplierPaymentNotCancellable(AppException):
    status_code = 400
    error_code = "supplier_payment_not_cancellable"
    detail = "Only draft supplier payments can be cancelled."


class SupplierPaymentNotReversible(AppException):
    status_code = 400
    error_code = "supplier_payment_not_reversible"
    detail = "Only posted supplier payments can be reversed."


class SupplierPaymentAllocationNotEditable(AppException):
    status_code = 400
    error_code = "supplier_payment_allocation_not_editable"
    detail = "Allocations can only be modified on draft or posted supplier payments."


class SupplierPaymentAllocationInvoiceConflict(ConflictError):
    error_code = "supplier_payment_allocation_invoice_conflict"
    detail = "A supplier payment allocation for this purchase invoice already exists."


class InvalidSupplierPaymentAllocationInvoice(AppException):
    status_code = 400
    error_code = "invalid_supplier_payment_allocation_invoice"
    detail = "Allocation invoice must be posted and belong to the same supplier and tenant."


class SupplierPaymentOverAllocated(AppException):
    status_code = 400
    error_code = "supplier_payment_over_allocated"
    detail = "Supplier payment allocations cannot exceed the payment amount."


class SupplierPaymentInvoiceOverpaid(AppException):
    status_code = 400
    error_code = "supplier_payment_invoice_overpaid"
    detail = "Supplier payment allocation cannot overpay a purchase invoice."


class SupplierLedgerEntryNotFound(NotFoundError):
    error_code = "supplier_ledger_entry_not_found"
    detail = "Supplier ledger entry not found."


class SupplierBalanceNotFound(NotFoundError):
    error_code = "supplier_balance_not_found"
    detail = "Supplier balance not found."
