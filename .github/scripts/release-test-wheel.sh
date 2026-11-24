#!/usr/bin/env bash
set -e

uv venv --clear --python "${STANDARDS_PYTHON:-3.15}" --seed
uv pip install ./dist/deps/*.whl ./dist/code_standards-*.whl pytest==9.2.0 jsonschema==4.26.0 yamllint==1.38.0 ruff pytest-xdist==3.8.0 pytest-unused-fixtures==0.3.2
uv run --no-project pytest -q -n 4 --dist worksteal tests/
