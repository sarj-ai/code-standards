#!/usr/bin/env bash
set -e

uv venv --clear --python "${STANDARDS_PYTHON:-3.15}" --seed
uv pip install ./dist/deps/*.whl ./dist/code_standards-*.whl pytest==9.1.1 jsonschema==4.25.1 ruff pytest-xdist==3.8.0 pytest-unused-fixtures==0.3.1
uv run --no-project pytest -q -n 4 --dist worksteal tests/
