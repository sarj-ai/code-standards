#!/usr/bin/env bash
set -euo pipefail

# Run release analysis with only the source-owned bootstrap pins.
# Lint engines and test tools are installed by the lanes that actually use them.
root="$(git rev-parse --show-toplevel)"
requirements="$(mktemp "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/release-python.XXXXXX")"
trap 'rm -f "$requirements"' EXIT
uv run --no-config --no-project --python 3.14 python - "$root/packages/standards/pyproject.toml" > "$requirements" <<'PY'
import sys
import tomllib
from pathlib import Path

dependencies = tomllib.loads(Path(sys.argv[1]).read_text())["project"]["dependencies"]
selected = [spec for spec in dependencies if spec.startswith(("pydantic==", "typer==", "packaging=="))]
if len(selected) != 3:
    raise SystemExit("release analysis requires exact Pydantic, Typer and Packaging pins")
print("\n".join(selected))
PY
PYTHONPATH="$root/packages/standards/src" uv run --no-config --no-project --python 3.14 \
  --with-requirements "$requirements" python "$@"
