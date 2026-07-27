# P2P Procurement Policy — Rules for Automated Reasoning

This document defines the formal procurement rules that govern the P2P agentic
system. Bedrock Automated Reasoning extracts these rules as formal logic and
uses them to verify that agent-generated recommendations are factually correct.

## 1. Three-Way Matching Rules

Rule 1.1: An invoice can only be approved for payment if a valid purchase order
exists for the referenced order ID. If an invoice has no PO reference, it must
be flagged for manual review.

Rule 1.2: The invoice unit price for each line item must not exceed the
purchase order unit price by more than 3 percent. If the invoice price exceeds
the PO price by more than 3 percent, the invoice must be flagged as a
DISCREPANCY.

Rule 1.3: The invoiced quantity for each line item must match the received
quantity from the goods receipt. If no goods receipt exists for the purchase
order, the invoice cannot be approved.

Rule 1.4: The total invoice amount must not exceed the total PO amount by more
than 50 USD. Differences up to 50 USD are acceptable as rounding tolerance.

Rule 1.5: Partial invoices are allowed. An invoice may cover a subset of PO
line items. At least 80 percent of the invoiced line items must match a
corresponding PO line item.

## 2. Approval Threshold Rules

Rule 2.1: A requisition with total amount up to 5,000 USD and risk level LOW
may be auto-approved without human intervention.

Rule 2.2: A requisition with total amount exceeding 50,000 USD must always be
escalated for human review regardless of risk level.

Rule 2.3: A requisition from a new supplier (a supplier with no prior purchase
order history) must never be auto-approved. It must always require human
review.

Rule 2.4: A requisition with risk level HIGH must always be escalated,
regardless of the total amount.

## 3. Payment Rules

Rule 3.1: A payment cannot be processed unless the corresponding invoice has
passed three-way matching (invoice matched to both PO and goods receipt).

Rule 3.2: A payment exceeding 50,000 USD requires approval from a manager or
higher-level approver before processing.

Rule 3.3: When an invoice has early payment discount terms (such as 2/10 Net
30) and the discount savings exceed 100 USD, the agent should recommend paying
within the discount window.

Rule 3.4: Duplicate payments for the same invoice must be prevented. If a
payment already exists for an invoice, a second payment for the same invoice
must be flagged.

## 4. Supplier Rules

Rule 4.1: Purchase orders must not be created for suppliers with status
BLOCKED. Only suppliers with status ACTIVE may receive new purchase orders.

Rule 4.2: Items should be sourced from suppliers whose specialization
categories include the item's group. A mismatch between the item group and
the supplier's categories should generate a warning.
