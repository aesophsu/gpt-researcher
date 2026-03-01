SHELL := /bin/bash

MAIN_BRANCH ?= main
UPSTREAM_NAME ?= upstream
UPSTREAM_URL ?= https://github.com/assafelovic/gpt-researcher.git

.PHONY: help upstream-init sync sync-rebase deps deps-upgrade nix-update update-all safety-branch verify nix-shell bootstrap backend-dev frontend-dev dev local-health zotero-import zotero-reindex zotero-import-fast p0-guardrails

help:
	@echo "Available targets:"
	@echo "  make upstream-init   # Add/verify upstream remote"
	@echo "  make sync            # Fetch upstream, merge to main, push origin"
	@echo "  make sync-rebase     # Fetch upstream, rebase main, force-with-lease push"
	@echo "  make deps            # Sync Python deps via uv"
	@echo "  make deps-upgrade    # Upgrade lock + sync via uv"
	@echo "  make nix-update      # Update Nix env if flake.nix/shell.nix exists"
	@echo "  make nix-shell       # Enter nix develop shell"
	@echo "  make bootstrap       # Install backend/frontend dependencies"
	@echo "  make backend-dev     # Run FastAPI backend on 127.0.0.1:8000"
	@echo "  make frontend-dev    # Run NextJS frontend on 127.0.0.1:3000"
	@echo "  make dev             # Print two-terminal dev workflow"
	@echo "  make local-health    # Check Ollama/Qdrant/Zotero local pipeline health"
	@echo "  make zotero-import   # Import Zotero PDFs -> Ollama embeddings -> Qdrant"
	@echo "  make zotero-reindex  # Rebuild fixed Zotero Qdrant collection from scratch"
	@echo "  make zotero-import-fast # Import with larger batch size (BATCH_SIZE=128)"
	@echo "  make p0-guardrails   # Run P0 static guardrails checks"
	@echo "  make safety-branch   # Create chore/sync-YYYYMMDD branch"
	@echo "  make verify          # Verify remotes and recent commits"
	@echo "  make update-all      # sync + nix-update + deps"

upstream-init:
	@if git remote get-url "$(UPSTREAM_NAME)" >/dev/null 2>&1; then \
		echo "$(UPSTREAM_NAME) already exists:"; \
		git remote get-url "$(UPSTREAM_NAME)"; \
	else \
		echo "Adding $(UPSTREAM_NAME) => $(UPSTREAM_URL)"; \
		git remote add "$(UPSTREAM_NAME)" "$(UPSTREAM_URL)"; \
	fi
	@git remote -v

sync:
	@git fetch "$(UPSTREAM_NAME)" --prune
	@git checkout "$(MAIN_BRANCH)"
	@git merge "$(UPSTREAM_NAME)/$(MAIN_BRANCH)"
	@git push origin "$(MAIN_BRANCH)"

sync-rebase:
	@git fetch "$(UPSTREAM_NAME)" --prune
	@git checkout "$(MAIN_BRANCH)"
	@git rebase "$(UPSTREAM_NAME)/$(MAIN_BRANCH)"
	@git push --force-with-lease origin "$(MAIN_BRANCH)"

deps:
	@if uv sync; then \
		echo "uv sync succeeded"; \
	else \
		echo "uv sync failed; fallback to requirements.txt via uv pip"; \
		uv pip install -r requirements.txt; \
	fi

deps-upgrade:
	@if uv lock --upgrade && uv sync; then \
		echo "uv lock+sync succeeded"; \
	else \
		echo "uv lock/sync failed; fallback to upgrading requirements.txt via uv pip"; \
		uv pip install -U -r requirements.txt; \
	fi

nix-update:
	@if [ -f flake.nix ]; then \
		echo "Detected flake.nix; running flake update + nix develop"; \
		nix flake update; \
		nix develop --command echo "nix env ready"; \
	elif [ -f shell.nix ]; then \
		echo "Detected shell.nix; running nix-shell"; \
		nix-shell --run "echo nix env ready"; \
	else \
		echo "No flake.nix or shell.nix found; skip nix-update"; \
	fi

nix-shell:
	@nix develop

bootstrap:
	@command -v uv >/dev/null 2>&1 || (echo "uv not found. Enter nix shell first: make nix-shell" && exit 1)
	@command -v npm >/dev/null 2>&1 || (echo "npm not found. Enter nix shell first: make nix-shell" && exit 1)
	@echo "Syncing Python deps..."
	@$(MAKE) deps
	@echo "Installing frontend deps..."
	@cd frontend/nextjs && npm install

safety-branch:
	@git checkout -b "chore/sync-$$(date +%Y%m%d)"

backend-dev:
	@env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
		uv run uvicorn main:app --host 127.0.0.1 --port 8000 --reload

frontend-dev:
	@cd frontend/nextjs && NEXT_PUBLIC_GPTR_API_URL="$${NEXT_PUBLIC_GPTR_API_URL:-http://127.0.0.1:8000}" npm run dev -- --hostname 127.0.0.1 --port 3000

dev:
	@echo "Run in terminal A: make backend-dev"
	@echo "Run in terminal B: make frontend-dev"

local-health:
	@env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
		bash scripts/health_local.sh

zotero-import:
	@env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
		bash scripts/import_zotero_local.sh

zotero-reindex:
	@env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
		bash scripts/import_zotero_local.sh --recreate

zotero-import-fast:
	@env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy \
		BATCH_SIZE=128 bash scripts/import_zotero_local.sh

p0-guardrails:
	@python scripts/check_p0_guardrails.py

verify:
	@git remote -v
	@git log --oneline --decorate -n 5
	@git status --short --branch

update-all: sync nix-update deps
