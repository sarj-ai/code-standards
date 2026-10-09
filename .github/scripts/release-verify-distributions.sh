#!/usr/bin/env bash
set -euo pipefail

kind=${1:-python}
case "$kind" in
python) artifact=verified-dist/SHA256SUMS ;;
npm) artifact="$RUNNER_TEMP/npm-artifacts/package.tgz" ;;
*) exit 64 ;;
esac
printf '%s  %s\n' "$EXPECTED_SHA256" "$artifact" | sha256sum --check --strict
if [[ "$kind" == python ]]; then
  (cd verified-dist && sha256sum --check --strict SHA256SUMS)
fi
