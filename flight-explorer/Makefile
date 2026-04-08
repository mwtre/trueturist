# Flight explorer — local venv (PEP 668–safe) + sibling ../fli scanner.
PYTHON ?= python3
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
FLI_ROOT := ../fli
HOST ?= 127.0.0.1
PORT ?= 8765

.PHONY: setup run dev health

setup:
	@test -d "$(FLI_ROOT)" || (echo "Missing $(FLI_ROOT); clone or place fli next to flight-explorer." && exit 1)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e $(FLI_ROOT)
	@echo "OK — run: make run"

run:
	@test -x "$(PY)" || (echo "No venv. Run: make setup" && exit 1)
	$(PY) -m uvicorn app.main:app --host $(HOST) --port $(PORT)

dev: run

health:
	@curl -sf "http://$(HOST):$(PORT)/api/health" | $(PYTHON) -m json.tool
