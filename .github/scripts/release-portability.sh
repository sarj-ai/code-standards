#!/usr/bin/env bash
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
export GITHUB_WORKSPACE="$root"
export GITHUB_SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
source_commit=$(git rev-parse HEAD)
test "$source_commit" = "$GITHUB_SHA"
work="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/release-portability.XXXXXX")"
trap 'rm -rf "$work"' EXIT
export PRE_COMMIT_HOME="${PRE_COMMIT_HOME:-$work/hooks}"
export PYTHONUNBUFFERED=1
reports="${PORTABILITY_REPORT_DIR:-$work/reports}"
mkdir -p "$reports"
run_check() {
  label="$1"
  shift
  started=$SECONDS
  printf '%s: started\n' "$label"
  if "$@" 2>&1 | tee "$reports/$label.log"; then
    result=0
  else
    result=$?
  fi
  printf '%s: %ss (exit %s)\n' "$label" "$((SECONDS - started))" "$result" | tee "$reports/$label-timing.txt"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    cat "$reports/$label-timing.txt" >>"$GITHUB_STEP_SUMMARY"
  fi
  return "$result"
}
cd "$root/packages/standards"
uv sync --locked --dev
run_check consumer-cli uv run --no-sync pytest -vv --durations=10 tests/test_cli_startup.py tests/test_consumer_cli.py &
smoke_pid=$!
run_check lifecycle-cli uv run --no-sync pytest -vv --durations=10 tests/test_lifecycle.py tests/test_package_managers.py &
lifecycle_pid=$!
run_check pre-commit bash "$root/.github/scripts/release-precommit.sh" "$work" &
hook_pid=$!
result=0
wait "$smoke_pid" || result=1
wait "$lifecycle_pid" || result=1
wait "$hook_pid" || result=1
exit "$result"
