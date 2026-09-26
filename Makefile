PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
STAMP := $(VENV)/.installed
TOOL := $(BIN)/pybricks-independent

# Hub program to compile/upload, e.g. make download PROGRAM=hub/other.py
PROGRAM ?= hub/worker.py
# Hub Bluetooth name (default: first Pybricks hub found), e.g. make run HUB="Pybricks Hub"
HUB ?=
# Extra tool options, e.g. make debug ARGS="--attempts 5 -v"
ARGS ?=
HUB_ARGS := $(if $(HUB),--hub-name '$(HUB)') $(ARGS)
IMAGE := build/$(basename $(notdir $(PROGRAM))).bin

# `make sync` mirrors this directory to $(REMOTE):$(REMOTE_DIR)/pybricks-independent/.
# The remote .venv and build output are machine-local and left untouched.
REMOTE ?= 192.168.50.178
REMOTE_DIR ?= work/lego/pybricks_projects
RSYNC_EXCLUDES := --exclude=/.venv/ --exclude=/build/ --exclude=__pycache__/ \
	--exclude=.pytest_cache/ --exclude=.ruff_cache/ --exclude=*.egg-info/
RSYNC := rsync -az --delete $(RSYNC_EXCLUDES) ./ $(REMOTE):$(REMOTE_DIR)/$(notdir $(CURDIR))/

.DEFAULT_GOAL := help

.PHONY: help install compile download run debug stop test lint format check sync sync-dry clean distclean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)

$(STAMP): pyproject.toml | $(BIN)/python
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e '.[dev]'
	touch $@

install: $(STAMP) ## Create the venv and install the tool (editable) with dev tools

$(IMAGE): $(PROGRAM) $(STAMP)
	$(TOOL) compile $(PROGRAM) -o $@

compile: $(IMAGE) ## Compile PROGRAM into build/<name>.bin locally (no hub needed)

download: $(STAMP) ## Store PROGRAM on the hub; start it later with the hub button
	$(TOOL) download $(HUB_ARGS) $(PROGRAM)

run: $(STAMP) ## Store and start PROGRAM, then disconnect (it keeps running)
	$(TOOL) run $(HUB_ARGS) $(PROGRAM)

debug: $(STAMP) ## Run PROGRAM with DEBUG = True and stream its output (Ctrl-C stops it)
	$(TOOL) debug $(HUB_ARGS) $(PROGRAM)

stop: $(STAMP) ## Stop the program running on the hub
	$(TOOL) stop $(HUB_ARGS)

test: $(STAMP) ## Run unit tests (incl. simulated hub program)
	$(BIN)/pytest

lint: $(STAMP) ## Lint and check formatting
	$(BIN)/ruff check src hub tests
	$(BIN)/ruff format --check src hub tests

format: $(STAMP) ## Auto-format and fix lint issues
	$(BIN)/ruff format src hub tests
	$(BIN)/ruff check --fix src hub tests

check: lint test compile ## Run all checks

sync: ## Mirror the project (incl. .git) to REMOTE:REMOTE_DIR/pybricks-independent (deletes stale remote files)
	$(RSYNC) --itemize-changes

sync-dry: ## Show what `make sync` would change, without changing anything
	$(RSYNC) --itemize-changes --dry-run

clean: ## Remove build artifacts and caches
	rm -rf build dist .pytest_cache .ruff_cache src/*.egg-info
	find . -path ./$(VENV) -prune -o -name __pycache__ -type d -exec rm -rf {} +

distclean: clean ## Also remove the virtualenv
	rm -rf $(VENV)
