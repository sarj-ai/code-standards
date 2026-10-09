#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../../apps/docs"

run_check() {
  label="$1"; shift
  started=$SECONDS
  "$@" && result=0 || result=$?
  printf 'Docs %s: %ss (exit %s)\n' "$label" "$((SECONDS - started))" "$result"
  return "$result"
}

# The source artifacts have already passed docs-artifacts-check. Validate the
# shared projections once; standalone npm commands retain their pre/post hooks.
run_check Examples npm run code-examples:check
run_check Catalog npm run third-party-catalog:check
run_check Lint npm --ignore-scripts run lint
run_check Types npm --ignore-scripts run check
run_check Build npm --ignore-scripts run build
run_check Distribution node scripts/verify-third-party-catalog.mjs --dist
