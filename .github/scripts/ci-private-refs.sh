#!/usr/bin/env bash
set -euo pipefail

test -n "$PRIVATE_REFS_TOML"
policy_file="$RUNNER_TEMP/private-refs.toml"
trap 'rm -f "$policy_file"' EXIT
install -m 600 /dev/null "$policy_file"
printf '%s' "$PRIVATE_REFS_TOML" > "$policy_file"
trusted/packages/standards/.venv/bin/code-standards --root candidate maintain check \
  --policy-root trusted \
  --private-refs-file "$policy_file" \
  --only private-refs \
  --commits "$BASE_SHA..$HEAD_SHA"
