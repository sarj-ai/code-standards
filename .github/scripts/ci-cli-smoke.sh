#!/usr/bin/env bash
set -e

uv run --no-project code-standards show configs
uv run --no-project code-standards show config ruff
uv run --no-project code-standards show peers
fresh="$(mktemp -d)"
printf 'VALUE = 1\n' >"$fresh/example.py"
(cd "$fresh" && "$GITHUB_WORKSPACE/packages/standards/.venv/bin/code-standards" check example.py)
cli="$GITHUB_WORKSPACE/packages/standards/.venv/bin/code-standards"
"$cli" --root "$fresh" check --format json --output "$fresh/report.json" example.py
jq --exit-status '.exitCode == 0 and .completion == "complete"' "$fresh/report.json" >/dev/null
