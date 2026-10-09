#!/usr/bin/env bash
set -euo pipefail

# Run release analysis with only the source-owned bootstrap pins.
# Lint engines and test tools are installed by the lanes that actually use them.
root="$(git rev-parse --show-toplevel)"
requirements="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/release-python.XXXXXX")"
trap 'rm -f "$requirements"' EXIT
uv run --no-config --no-project --python "${STANDARDS_PYTHON:-3.15}" python "$root/.github/scripts/release-metadata.py" \
  runtime-requirements "$root/packages/standards/pyproject.toml" >"$requirements"
PYTHONPATH="$root/packages/standards/src" uv run --no-config --no-project --python "${STANDARDS_PYTHON:-3.15}" \
  --with-requirements "$requirements" python "$@"
