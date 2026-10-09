#!/usr/bin/env bash
set -e

uv venv --python "${STANDARDS_PYTHON:-3.15}" "$RUNNER_TEMP/standards-sdist"
uv pip install --python "$RUNNER_TEMP/standards-sdist/bin/python" --find-links dist/deps dist/*.tar.gz
"$RUNNER_TEMP/standards-sdist/bin/code-standards" --help
