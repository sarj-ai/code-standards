#!/usr/bin/env bash
set -euo pipefail

temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT
git ls-files -z --cached --others --exclude-standard -- 'packages/*/src/*.py' 'packages/*/src/**/*.py' 'packages/*/tests/*.py' 'packages/*/tests/**/*.py' >"$temporary/files"
python_files=()
while IFS= read -r -d '' file; do
  if [[ -f "$file" ]]; then
    python_files+=("$file")
  fi
done <"$temporary/files"
uv run --quiet --project packages/python --frozen sarj-python-lint list-rules >"$temporary/registry"
awk '{print $2}' "$temporary/registry" >"$temporary/rules"
python_rules=()
while IFS= read -r rule; do
  python_rules+=("$rule")
done <"$temporary/rules"
if ((${#python_files[@]} == 0 || ${#python_rules[@]} == 0)); then
  echo 'dogfood: Python source or registry is unexpectedly empty' >&2
  exit 2
fi
rule_args=()
for rule in "${python_rules[@]}"; do
  rule_args+=(--rule "$rule")
done
set +e
output="$(uv run --quiet --project packages/python --frozen sarj-python-lint check "${rule_args[@]}" -- "${python_files[@]}" 2>&1)"
status=$?
set -e
if ((status != 0)); then
  printf '%s\n' "$output"
  exit "$status"
fi
if [[ -n "$output" ]]; then
  printf '%s\n' "$output"
fi
printf 'dogfood: %d Python rules, %d source files, 0 blocking diagnostics\n' "${#python_rules[@]}" "${#python_files[@]}"
