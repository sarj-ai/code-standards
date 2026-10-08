#!/usr/bin/env bash
set -euo pipefail
version="${STANDARDS_TAG#standards-v}"
if [[ -z "$version" || "$version" == "$STANDARDS_TAG" ]]; then
  echo "::error::invalid immutable Standards tag: $STANDARDS_TAG"
  exit 2
fi
# Keep mutation serialized, but let a published release replace work
# from an older scheduled controller instead of waiting behind it.
if [[ "$PUBLISHED_SHA" =~ ^[0-9a-f]{40}$ ]] && scheduled="$(
  for state in in_progress pending queued; do
    gh run list --repo "$GITHUB_REPOSITORY" --workflow standards-rollout.yml \
      --event schedule --status "$state" --limit 20 \
      --json databaseId,event,headSha,status
  done | jq -sc 'add | unique_by(.databaseId)'
)"; then
  while IFS=$'\t' read -r run_id source_sha; do
    if [[ "$run_id" =~ ^[0-9]+$ && "$source_sha" =~ ^[0-9a-f]{40}$ && "$source_sha" != "$PUBLISHED_SHA" ]] &&
      [[ "$(gh api "repos/$GITHUB_REPOSITORY/compare/$source_sha...$PUBLISHED_SHA" --jq .status)" == ahead ]]; then
      gh run cancel "$run_id" --repo "$GITHUB_REPOSITORY" ||
        echo "::warning::could not cancel superseded scheduled rollout $run_id"
    fi
  done < <(jq -r '.[] | select(.event == "schedule" and (.status == "in_progress" or .status == "pending" or .status == "queued")) | [.databaseId, .headSha] | @tsv' <<< "$scheduled")
else
  echo "::warning::could not inspect scheduled rollouts; dispatching normally"
fi
gh workflow run standards-rollout.yml \
  --repo "$GITHUB_REPOSITORY" \
  --ref "$STANDARDS_TAG" \
  -f version="$version"
