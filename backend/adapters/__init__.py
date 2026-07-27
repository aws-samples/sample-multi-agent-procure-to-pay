# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Canonical P2P adapter layer.

Provides an ERP-agnostic interface for Procure-to-Pay operations.
Each ERP system (ERPNext, SAP, Workday, Infor) implements the adapter
interface, translating canonical API calls to ERP-specific REST/BAPI calls.
"""
