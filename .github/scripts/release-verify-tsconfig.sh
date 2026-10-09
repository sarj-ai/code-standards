#!/usr/bin/env bash
set -euo pipefail

manifest=$(tar -xOf "$RUNNER_TEMP/npm-artifacts/package.tgz" package/package.json)
actual_name=$(jq -er '.name | select(type == "string")' <<<"$manifest")
actual_version=$(jq -er '.version | select(type == "string")' <<<"$manifest")
expected_version=$(jq -er '.version | select(type == "string")' package.json)
test "$actual_name" = '@sarj/tsconfig'
test "$actual_version" = "$expected_version"
bash ../../.github/scripts/release-bind-artifacts.sh npm
