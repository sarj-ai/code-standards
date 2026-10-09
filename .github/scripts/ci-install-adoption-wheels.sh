#!/usr/bin/env bash
set -e

uv venv --clear --python 3.14 --seed
uv pip install ./dist/deps/*.whl ./dist/code_standards-*.whl
