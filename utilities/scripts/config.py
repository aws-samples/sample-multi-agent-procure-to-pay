# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Configuration for ERPNext data loading scripts.
"""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ERPNext connection
ERPNEXT_URL = os.getenv("ERPNEXT_URL", "http://localhost:8080")
ERPNEXT_API_KEY = os.getenv("ERPNEXT_API_KEY", "")
ERPNEXT_API_SECRET = os.getenv("ERPNEXT_API_SECRET", "")

# Fallback to basic auth if no API keys
ERPNEXT_USER = os.getenv("ERPNEXT_USER", "Administrator")
ERPNEXT_PASSWORD = os.getenv("ERPNEXT_PASSWORD", "")
if not ERPNEXT_PASSWORD and not (ERPNEXT_API_KEY and ERPNEXT_API_SECRET):
    raise RuntimeError(
        "Set ERPNEXT_PASSWORD (or ERPNEXT_API_KEY + ERPNEXT_API_SECRET) in your "
        "environment or in utilities/.env. See utilities/.env.example."
    )

# ERPNext company settings
COMPANY_NAME = "Apex Manufacturing Group"
COMPANY_ABBR = "AMG"
DEFAULT_CURRENCY = "USD"
COUNTRY = "United States"
FISCAL_YEAR_START = "2025-01-01"
FISCAL_YEAR_END = "2025-12-31"
DEFAULT_WAREHOUSE = "Stores - AMG"
COST_CENTER = "Main - AMG"

# Data generation settings
NUM_SUPPLIERS = 15
NUM_ITEMS = 40
NUM_PURCHASE_ORDERS = 50
NUM_PURCHASE_RECEIPTS = 35
NUM_PURCHASE_INVOICES = 30
NUM_MATERIAL_REQUESTS = 20
NUM_PAYMENT_ENTRIES = 15
