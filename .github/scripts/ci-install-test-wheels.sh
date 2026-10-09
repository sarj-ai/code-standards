#!/usr/bin/env bash
set -e

uv venv --clear --python 3.14 --seed
uv pip install ./dist/deps/*.whl ./dist/code_standards-*.whl pytest==9.1.1 pytest-xdist==3.8.0 jsonschema==4.25.1 ruff
