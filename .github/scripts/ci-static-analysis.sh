#!/usr/bin/env bash
set -e

run_check() {
  label="$1"
  shift
  started=$SECONDS
  "$@" && result=0 || result=$?
  printf '%s: %ss (exit %s)\n' "$label" "$((SECONDS - started))" "$result" >>"$GITHUB_STEP_SUMMARY"
  return "$result"
}
run_check Ruff uv run ruff check src/ tests/ &
ruff_pid=$!
run_check 'Ruff release helpers' uv run ruff check ../../.github/scripts/*.py &
ruff_helpers_pid=$!
run_check Typecheck uv run basedpyright src/ tests/ ../../.github/scripts/*.py &
types_pid=$!
run_check ShellCheck uv run python -m sarj_standards.libs.repository.shell_checks --root ../.. --tool shellcheck &
shellcheck_pid=$!
run_check ShellFormat uv run python -m sarj_standards.libs.repository.shell_checks --root ../.. --tool shfmt &
shellformat_pid=$!
result=0
wait "$ruff_pid" || result=1
wait "$ruff_helpers_pid" || result=1
wait "$types_pid" || result=1
wait "$shellcheck_pid" || result=1
wait "$shellformat_pid" || result=1
exit "$result"
