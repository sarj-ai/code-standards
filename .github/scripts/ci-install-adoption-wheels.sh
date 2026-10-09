#!/usr/bin/env bash
set -e

uv venv --clear --python "${STANDARDS_PYTHON:-3.15}" --seed
uv pip install ./dist/deps/*.whl ./dist/code_standards-*.whl
