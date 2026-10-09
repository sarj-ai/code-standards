#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
consumer="$1/consumer"
mkdir -p "$consumer"
git -C "$consumer" init -q
git -C "$consumer" config user.name "Standards Release"
git -C "$consumer" config user.email "standards-release@example.invalid"
printf 'VALUE: int = 1\n' >"$consumer/smoke.py"
printf 'SELECT 1;\n' >"$consumer/smoke.sql"
: >"$consumer/smoke.tf"
python "$root/.github/scripts/ci-precommit-config.py" "$consumer/.pre-commit-config.yaml" "$GITHUB_WORKSPACE" "$GITHUB_SHA"
git -C "$consumer" add .
git -C "$consumer" commit -qm fixture
pc=(uv run --project "$root/packages/standards" --no-sync pre-commit)
(cd "$consumer" && "${pc[@]}" run sarj-standards --color never --files smoke.py smoke.sql smoke.tf)
(cd "$consumer" && "${pc[@]}" run sarj-standards --color never --files smoke.py smoke.sql smoke.tf) 2>&1 | tee "$1/pre-commit-warm.log"
if grep -q 'Installing environment' "$1/pre-commit-warm.log"; then
  echo "warm pre-commit execution rebuilt its environment" >&2
  exit 1
fi
