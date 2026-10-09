#!/usr/bin/env bash
set -e

uv venv --python 3.14 "$RUNNER_TEMP/standards-sdist"
uv pip install --python "$RUNNER_TEMP/standards-sdist/bin/python" --find-links dist/deps dist/*.tar.gz
"$RUNNER_TEMP/standards-sdist/bin/code-standards" --help
