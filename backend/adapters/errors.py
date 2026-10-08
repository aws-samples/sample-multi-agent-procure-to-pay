# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Adapter-level errors for operations that move money or change ERP state.

These exist so a caller can never mistake "the ERP did not do it" or "nobody
knows whether the ERP did it" for "done". A normal return from a write method
means the document is posted; anything else raises one of these.
"""


class ERPWriteError(RuntimeError):
    """Base class for ERP write failures."""


class DuplicatePaymentError(ERPWriteError):
    """A Payment Entry already exists for this invoice.

    Raised before anything is inserted. `existing_payment_id` names the entry;
    `existing_status` is its canonical status ("draft" or "submitted").
    A draft means an earlier attempt did not post: submit or cancel it rather
    than creating another. A submitted entry means the invoice is already paid.
    """

    def __init__(self, invoice_id: str, existing_payment_id: str, existing_status: str):
        self.invoice_id = invoice_id
        self.existing_payment_id = existing_payment_id
        self.existing_status = existing_status
        if existing_status == "submitted":
            hint = "the invoice is already paid"
        else:
            hint = "an earlier attempt left an unposted draft; submit or cancel it instead of creating another"
        super().__init__(
            f"Payment Entry {existing_payment_id} ({existing_status}) already references "
            f"invoice {invoice_id}: {hint}"
        )


class PaymentNotPostedError(ERPWriteError):
    """A Payment Entry was created but is not posted.

    `outcome` distinguishes the two cases a caller must treat differently:

    - "rejected": ERPNext refused the submit (validation error). The entry is
      definitely still a draft. Fix the data or cancel the draft.
    - "unknown": the submit call failed in a way that says nothing about
      whether ERPNext applied it (timeout, dropped connection, 5xx) and the
      follow-up read could not confirm a posted state. Do NOT retry by
      creating a new payment; reconcile `payment_id` in the ERP first.
    """

    def __init__(self, payment_id: str, outcome: str, detail: str):
        if outcome not in ("rejected", "unknown"):
            raise ValueError(f"outcome must be 'rejected' or 'unknown', got {outcome!r}")
        self.payment_id = payment_id
        self.outcome = outcome
        self.detail = detail
        super().__init__(
            f"Payment Entry {payment_id} is not posted (outcome={outcome}): {detail}"
        )
