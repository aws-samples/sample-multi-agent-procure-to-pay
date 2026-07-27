# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# Local development harness for aria-p2p-agent. See local/README.md.
#
#   cp local/env.example local/.env      # fill in AWS creds (real Bedrock)
#   make -C local erpnext                 # start local ERPNext (compose)
#   make -C local up                      # emulators + shims + agents + backend
#   make -C local ui                      # SPA (Vite) in another terminal
#
# Uses the repo's venv (~/.venv) per project convention.

PY := $(HOME)/.venv/bin/python
REPO := $(shell cd .. && pwd)
COMPOSE := $(REPO)/infra/docker/docker-compose.local-test.yaml

# Load local/.env if present so creds/overrides reach the child processes.
ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: help env erpnext erpnext-down up seed ui clean

help:
	@echo "aria-p2p-agent local harness targets:"
	@echo "  make -C local erpnext       start local ERPNext (docker compose)"
	@echo "  make -C local up            emulators + shims + agents + backend (foreground)"
	@echo "  make -C local ui            run the SPA (Vite dev server) with local config"
	@echo "  make -C local seed          seed local ERPNext with demo data"
	@echo "  make -C local erpnext-down  stop + remove ERPNext containers/volumes"
	@echo "  make -C local clean         remove generated local artifacts"

env:
	@test -f .env || (echo "no local/.env — run: cp local/env.example local/.env" && exit 1)

erpnext:
	docker compose -f $(COMPOSE) up -d
	@echo "ERPNext starting on http://localhost:8080 — complete the Frappe setup wizard once."

erpnext-down:
	docker compose -f $(COMPOSE) down -v

up: env
	$(PY) supervisor.py

seed: env
	$(PY) scripts/seed_local.py

# Serve the SPA with the local runtime config injected (guest mode + local agent
# proxy). Copies local-config.js into the Vite public dir (gitignored there).
ui:
	cp config/local-config.js $(REPO)/frontend/public/local-config.js
	cd $(REPO)/frontend && ARIA_LOCAL_PROXY=1 npm run dev

clean:
	rm -f $(REPO)/frontend/public/local-config.js
	@echo "removed injected local-config.js"
