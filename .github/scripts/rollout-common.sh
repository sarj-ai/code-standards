#!/usr/bin/env bash
# Shared controller logging and private registry setup for the rollout entrypoints.
log="$RUNNER_TEMP/standards-rollout.log"
registry="$RUNNER_TEMP/standards-rollout.toml"
: >"$log"
install -m 600 /dev/null "$registry"
printf '%s' "$REGISTRY_TOML" >"$registry"
repository_rule_args=()
if [[ "${EVENT_NAME:-}" == workflow_dispatch && -n "${REQUESTED_REPOSITORY_RULE:-}" ]]; then
  # Sourced callers read this array when invoking the controller.
  # shellcheck disable=SC2034
  repository_rule_args=("--enable-repository-rule=$REQUESTED_REPOSITORY_RULE")
fi

run_and_log() {
  # The controller status is captured from PIPESTATUS immediately after tee.
  # shellcheck disable=SC2312
  "$@" 2>&1 | tee -a "$log"
  return "${PIPESTATUS[0]}"
}
