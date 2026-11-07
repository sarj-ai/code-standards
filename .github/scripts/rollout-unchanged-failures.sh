#!/usr/bin/env bash
# Skip a consumer leg whose last automated failure had identical rollout inputs.
# Any lookup failure keeps the consumer, so uncertainty always retries the apply.
set -uo pipefail

log="$RUNNER_TEMP/standards-rollout.log"
window="$(date -u +%Y-%m-%d)/$((10#$(date -u +%H) / 6))"
registry_digest="$(printf '%s' "$REGISTRY_TOML" | sha256sum | cut -c1-64)"
# Only scheduled and release-dispatched runs reuse a failure; a person dispatching
# the workflow always retries every pending consumer.
reuse=false
if [[ "$EVENT_NAME" == schedule || "$TRIGGERING_ACTOR" == "github-actions[bot]" ]]; then
  reuse=true
fi

kept='[]'
skipped='[]'
if ! count="$(jq -e 'if type == "array" then length else error("consumers must be an array") end' <<<"$CONSUMERS")"; then
  printf 'consumers=%s\nskipped=[]\n' "$CONSUMERS" >>"$GITHUB_OUTPUT"
  exit 0
fi
for ((index = 0; index < count; index++)); do
  entry="$(jq -c ".[$index]" <<<"$CONSUMERS")" || exit 1
  identity="$(jq -r '.identity // ""' <<<"$entry")" || exit 1
  name="$(jq -r '.name // .identity // ""' <<<"$entry")" || exit 1
  key=''
  if [[ "$identity" =~ ^([^/@]+/[A-Za-z0-9_.-]+)@(.+)$ ]]; then
    repository="${BASH_REMATCH[1]}"
    branch="${BASH_REMATCH[2]}"
    if base="$(GH_TOKEN="$CONSUMER_TOKEN" gh api "repos/$repository/git/ref/heads/$branch" --jq '.object.sha')" &&
      [[ "$base" =~ ^[0-9a-f]{40}$ ]] &&
      rollout="$(GH_TOKEN="$CONSUMER_TOKEN" gh api "repos/$repository/git/matching-refs/heads/standards-rollout/current" \
        --jq '[.[] | select(.ref == "refs/heads/standards-rollout/current") | .object.sha][0] // "none"')" &&
      [[ "$rollout" =~ ^([0-9a-f]{40}|none)$ ]]; then
      digest="$(printf '%s\n' v1 "$VERSION" "$CONTROLLER_SHA" "$registry_digest" "$PRESERVE_BASELINES" \
        "$REQUESTED_REPOSITORY_RULE" "$identity" "$base" "$rollout" "$window" | sha256sum | cut -c1-64)"
      [[ "$digest" =~ ^[0-9a-f]{64}$ ]] && key="standards-rollout-failure-$digest"
    fi
  fi
  failed_run=''
  if [[ "$reuse" == true && -n "$key" ]]; then
    failed_run="$(GH_TOKEN="$ACTIONS_TOKEN" gh api "repos/$GITHUB_REPOSITORY/actions/artifacts?name=$key&per_page=1" \
      --jq '[.artifacts[] | select(.expired == false) | .workflow_run.id][0] // ""')" || failed_run=''
  fi
  if [[ "$failed_run" =~ ^[0-9]+$ ]]; then
    skipped="$(jq -c --arg name "$name" '. + [$name]' <<<"$skipped")" || exit 1
    echo "standards-rollout: $identity: skipped; identical inputs failed in $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$failed_run and retry when the release, controller, consumer base or rollout branch changes, or within six hours" |
      tee -a "$log"
  else
    kept="$(jq -c --argjson entry "$entry" --arg key "$key" \
      '. + [if $key == "" then $entry else $entry + {failure_key: $key} end]' <<<"$kept")" || exit 1
  fi
done
printf 'consumers=%s\nskipped=%s\n' "$kept" "$skipped" >>"$GITHUB_OUTPUT"
