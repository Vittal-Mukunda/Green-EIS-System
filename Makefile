# Targets mirror tasks.py (use `python tasks.py <target>` where `make` is unavailable, e.g. this Windows setup).
PY ?= python

.PHONY: test lint format all-dry ddl check

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check src tests scripts tasks.py dashboard

format:
	$(PY) -m ruff format src tests scripts tasks.py dashboard

# Whole pipeline on 2 synthetic sectors x 3 synthetic companies with the MockRunner. Never calls Cursor.
all-dry:
	$(PY) -m gauge.cli all-dry

ddl:
	$(PY) -m gauge.cli init-db --ddl-only

check: lint test all-dry
