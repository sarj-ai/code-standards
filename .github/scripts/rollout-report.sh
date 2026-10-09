#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=rollout-common.sh
source "${BASH_SOURCE[0]%/*}/rollout-common.sh"

parts=("$RUNNER_TEMP/rollout-logs/standards-rollout-log-plan")
consumer_count="$(jq length <<<"$CONSUMERS")" || exit $?
for ((index = 0; index < consumer_count; index++)); do
  parts+=("$RUNNER_TEMP/rollout-logs/standards-rollout-log-consumer-$index")
done
operation_status="$PLAN_STATUS"
for part in "${parts[@]}"; do
  if [[ -f "$part/standards-rollout.log" ]]; then
    cat "$part/standards-rollout.log" >>"$log"
  fi
  if [[ -f "$part/standards-rollout.status" ]] && (($(<"$part/standards-rollout.status") > operation_status)); then
    operation_status="$(<"$part/standards-rollout.status")"
  fi
done
# A leg that failed before recording its status still fails the rollout.
if ((operation_status == 0)) && [[ "$ROLLOUT_RESULT" != success ]] && [[ "$CONSUMERS" != '[]' ]]; then
  operation_status=1
fi
status_status=0
run_and_log uv run --project packages/standards --frozen python -m sarj_standards.libs.release.rollout --registry "$registry" --jobs 4 status --version "$VERSION" || status_status=$?
if ((operation_status != 0 || status_status > 1)); then
  result=failure
elif ((status_status == 1)); then
  result=pending
else
  result=success
fi
{
  echo "result=$result"
  echo "operation_status=$operation_status"
  echo "status_status=$status_status"
} >>"$GITHUB_OUTPUT"
