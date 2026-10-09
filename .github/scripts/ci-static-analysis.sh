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
run_check 'Ruff release helpers' uv run ruff check ../../.github/scripts/ci-precommit-config.py ../../.github/scripts/release-*.py &
ruff_helpers_pid=$!
run_check Typecheck uv run basedpyright src/ tests/ ../../.github/scripts/ci-precommit-config.py ../../.github/scripts/release-*.py &
types_pid=$!
run_check ShellCheck env MISE_OFFLINE=true mise --no-config --no-env --no-hooks exec aqua:koalaman/shellcheck@0.11.0 -- \
  shellcheck --norc --extended-analysis=true --enable=check-extra-masked-returns --severity=info \
  --source-path=SCRIPTDIR -- ../../.github/scripts/*.sh &
shellcheck_pid=$!
run_check ShellFormat env MISE_OFFLINE=true mise --no-config --no-env --no-hooks exec aqua:mvdan/sh@3.14.1 -- \
  shfmt -d -i 2 ../../.github/scripts/*.sh &
shellformat_pid=$!
result=0
wait "$ruff_pid" || result=1
wait "$ruff_helpers_pid" || result=1
wait "$types_pid" || result=1
wait "$shellcheck_pid" || result=1
wait "$shellformat_pid" || result=1
exit "$result"
