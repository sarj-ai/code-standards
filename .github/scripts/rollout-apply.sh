#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=rollout-common.sh
source "${BASH_SOURCE[0]%/*}/rollout-common.sh"

operation_status=0
if [[ -z "$GH_TOKEN" ]]; then
  echo "rollout App token was not minted" | tee -a "$log"
  operation_status=1
else
  gh auth setup-git
  git config --global user.name "sarj-standards-rollout[bot]"
  git config --global user.email "sarj-standards-rollout[bot]@users.noreply.github.com"
  if [[ "$EVENT_NAME" == schedule ]]; then
    run_and_log uv run --project packages/standards --frozen python -m sarj_standards.libs.release.rollout --registry "$registry" reconcile --version "$VERSION" --consumer "$CONSUMER" || operation_status=$?
  else
    run_and_log uv run --project packages/standards --frozen python -m sarj_standards.libs.release.rollout --registry "$registry" apply --version "$VERSION" --consumer "$CONSUMER" "${repository_rule_args[@]}" || operation_status=$?
  fi
fi
echo "$operation_status" >"$RUNNER_TEMP/standards-rollout.status"
exit "$operation_status"
