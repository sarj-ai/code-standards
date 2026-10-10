#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=rollout-common.sh
source "${BASH_SOURCE[0]%/*}/rollout-common.sh"

plan_status=0
consumers='[]'
if [[ -z "$REGISTRY_TOML" ]]; then
  echo "rollout consumer registry is not configured" | tee -a "$log"
  plan_status=1
elif [[ -z "$GH_TOKEN" ]]; then
  echo "rollout App token was not minted" | tee -a "$log"
  plan_status=1
else
  matrix_output="$RUNNER_TEMP/rollout-plan.outputs"
  run_and_log uv run --project packages/standards --frozen python -m sarj_standards.libs.release.rollout --registry "$registry" --jobs 4 --github-output "$matrix_output" plan --version "$VERSION" "${repository_rule_args[@]}" || plan_status=$?
  if ((plan_status == 0)); then
    consumers="$(sed -n 's/^consumers=//p' "$matrix_output")"
    if [[ -z "$consumers" ]]; then
      consumers='[]'
      plan_status=2
    fi
  fi
fi
{
  echo "plan_status=$plan_status"
  echo "consumers=$consumers"
} >>"$GITHUB_OUTPUT"
