#!/usr/bin/env bash
set -euo pipefail

temporary="$(mktemp -d)"
tool_paths="$temporary/paths"
trap 'rm -rf "$temporary"' EXIT
GITHUB_PATH="$tool_paths" uv run --project packages/standards --frozen python -m sarj_standards.libs.release.native_test_setup --root .
while IFS= read -r directory; do
  export PATH="$directory:$PATH"
done <"$tool_paths"
rm -rf "$temporary"
trap - EXIT
exec "$@"
