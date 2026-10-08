// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
//
// Role checks key on the `p2p_role` JWT claim. That claim is asserted
// server-side by the Cognito Pre Token Generation trigger
// (infra/lambda/pre_token_generation/handler.py) from Cognito Group
// membership, which only operators can change. Never key a permit on a
// user-writable attribute such as `custom:role`: users can set those
// themselves via UpdateUserAttributes.
//
// IAM agents (AgentCore Runtimes) — unrestricted access to all tools
permit(
  principal is AgentCore::IamEntity,
  action in [
    AgentCore::Action::"erp___list_suppliers",
    AgentCore::Action::"erp___get_supplier",
    AgentCore::Action::"erp___list_items",
    AgentCore::Action::"erp___get_item",
    AgentCore::Action::"erp___list_requisitions",
    AgentCore::Action::"erp___get_requisition",
    AgentCore::Action::"erp___create_requisition",
    AgentCore::Action::"erp___list_purchase_orders",
    AgentCore::Action::"erp___get_purchase_order",
    AgentCore::Action::"erp___create_purchase_order",
    AgentCore::Action::"erp___list_receipts",
    AgentCore::Action::"erp___get_receipt",
    AgentCore::Action::"erp___create_receipt",
    AgentCore::Action::"erp___list_invoices",
    AgentCore::Action::"erp___get_invoice",
    AgentCore::Action::"erp___create_invoice",
    AgentCore::Action::"erp___list_payments",
    AgentCore::Action::"erp___create_payment",
    AgentCore::Action::"erp___get_spend_summary",
    AgentCore::Action::"erp___get_supplier_performance"
  ],
  resource is AgentCore::Gateway
);

// All OAuth users — read-only access
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"erp___list_suppliers",
    AgentCore::Action::"erp___get_supplier",
    AgentCore::Action::"erp___list_items",
    AgentCore::Action::"erp___get_item",
    AgentCore::Action::"erp___list_requisitions",
    AgentCore::Action::"erp___get_requisition",
    AgentCore::Action::"erp___list_purchase_orders",
    AgentCore::Action::"erp___get_purchase_order",
    AgentCore::Action::"erp___list_receipts",
    AgentCore::Action::"erp___get_receipt",
    AgentCore::Action::"erp___list_invoices",
    AgentCore::Action::"erp___get_invoice",
    AgentCore::Action::"erp___list_payments",
    AgentCore::Action::"erp___get_spend_summary",
    AgentCore::Action::"erp___get_supplier_performance"
  ],
  resource is AgentCore::Gateway
);

// Requisition creation — requester, procurement, admin
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"erp___create_requisition",
  resource is AgentCore::Gateway
) when {
  principal.hasTag("p2p_role") &&
  (principal.getTag("p2p_role") == "requester" ||
   principal.getTag("p2p_role") == "procurement" ||
   principal.getTag("p2p_role") == "admin")
};

// PO and receipt creation — procurement, admin
permit(
  principal is AgentCore::OAuthUser,
  action in [
    AgentCore::Action::"erp___create_purchase_order",
    AgentCore::Action::"erp___create_receipt"
  ],
  resource is AgentCore::Gateway
) when {
  principal.hasTag("p2p_role") &&
  (principal.getTag("p2p_role") == "procurement" ||
   principal.getTag("p2p_role") == "admin")
};

// Invoice creation — ap_clerk, procurement, admin
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"erp___create_invoice",
  resource is AgentCore::Gateway
) when {
  principal.hasTag("p2p_role") &&
  (principal.getTag("p2p_role") == "ap_clerk" ||
   principal.getTag("p2p_role") == "procurement" ||
   principal.getTag("p2p_role") == "admin")
};

// Payment creation — ap_clerk, approver, admin
permit(
  principal is AgentCore::OAuthUser,
  action == AgentCore::Action::"erp___create_payment",
  resource is AgentCore::Gateway
) when {
  principal.hasTag("p2p_role") &&
  (principal.getTag("p2p_role") == "ap_clerk" ||
   principal.getTag("p2p_role") == "approver" ||
   principal.getTag("p2p_role") == "admin")
};
