#!/usr/bin/env bash
set -euo pipefail
version="${STANDARDS_TAG#standards-v}"
if [[ -z "$version" || "$version" == "$STANDARDS_TAG" ]]; then
  echo "::error::invalid immutable Standards tag: $STANDARDS_TAG"
  exit 2
fi
# Keep mutation serialized, but let a published release replace work
# from an older automatic controller instead of waiting behind it.
if [[ "$PUBLISHED_SHA" =~ ^[0-9a-f]{40}$ ]] && active="$(
  for state in in_progress pending queued; do
    gh run list --repo "$GITHUB_REPOSITORY" --workflow standards-rollout.yml \
      --status "$state" --limit 20 \
      --json databaseId,event,headSha,status
  done | jq -sc 'add | unique_by(.databaseId)'
)"; then
  run_rows=$(jq -r '.[] | select((.event == "schedule" or .event == "workflow_dispatch") and (.status == "in_progress" or .status == "pending" or .status == "queued")) | [.databaseId, .headSha, .event] | @tsv' <<<"$active") || run_rows=''
  while IFS=$'\t' read -r run_id source_sha event; do
    [[ "$run_id" =~ ^[0-9]+$ && "$source_sha" =~ ^[0-9a-f]{40}$ && "$source_sha" != "$PUBLISHED_SHA" ]] || continue
    if [[ "$event" == workflow_dispatch ]]; then
      automatic="$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$run_id" |
        jq -r --arg sha "$source_sha" '.event == "workflow_dispatch" and .head_sha == $sha and (.head_branch | test("^standards-v[0-9]+\\.[0-9]+\\.[0-9]+")) and .actor.login == "github-actions[bot]" and .triggering_actor.login == "github-actions[bot]" and .run_attempt == 1')" || automatic=false
      [[ "$automatic" == true ]] || continue
    fi
    comparison=$(gh api "repos/$GITHUB_REPOSITORY/compare/$source_sha...$PUBLISHED_SHA" --jq .status) || comparison=''
    if [[ "$comparison" == ahead ]]; then
      gh run cancel "$run_id" --repo "$GITHUB_REPOSITORY" ||
        echo "::warning::could not cancel superseded automatic rollout $run_id"
    fi
  done <<<"$run_rows"
else
  echo "::warning::could not inspect automatic rollouts; dispatching normally"
fi
gh workflow run standards-rollout.yml \
  --repo "$GITHUB_REPOSITORY" \
  --ref "$STANDARDS_TAG" \
  -f version="$version"
