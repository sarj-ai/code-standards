#!/usr/bin/env bash
set -euo pipefail
version="${STANDARDS_TAG#standards-v}"
if [[ -z "$version" || "$version" == "$STANDARDS_TAG" ]]; then
  echo "::error::invalid immutable Standards tag: $STANDARDS_TAG"
  exit 2
fi
# Preserve active controllers; scheduled reconciliation selects the new release later.
if ! active="$(
  for state in in_progress waiting pending requested queued; do
    timeout --kill-after=5s 30s gh run list --repo "$GITHUB_REPOSITORY" --workflow standards-rollout.yml \
      --status "$state" --limit 20 --json databaseId,status,attempt || exit "$?"
  done | jq -sc 'if any(.[]; type != "array" or length >= 20) then error("incomplete active-rollout inventory") else add | unique_by([.databaseId, .attempt, .status]) end'
)"; then
  echo "::error::could not inspect active rollouts; leaving them unchanged"
  exit 1
fi
run_rows="$(jq -r 'if all(.[]; (.databaseId | type) == "number" and (.attempt | type) == "number" and (.status | type) == "string") then .[] | [.databaseId, .status, .attempt] | @tsv else error("invalid rollout metadata") end' <<<"$active")"
while IFS=$'\t' read -r run_id state attempt; do
  [[ -n "$run_id" ]] || continue
  if [[ ! "$run_id" =~ ^[0-9]+$ || ! "$attempt" =~ ^[1-9][0-9]*$ || ! "$state" =~ ^(in_progress|waiting|pending|requested|queued|completed)$ ]]; then
    echo "::error::invalid rollout metadata; leaving existing runs unchanged"
    exit 1
  fi
  [[ "$state" != completed ]] || continue
  if [[ "$state" == in_progress ]]; then
    jobs="$(timeout --kill-after=5s 30s gh api "repos/$GITHUB_REPOSITORY/actions/runs/$run_id/attempts/$attempt/jobs?per_page=100")"
    if jq -e '.total_count == (.jobs | length) and any(.jobs[]; .name == "report" and .status == "completed") and all(.jobs[]; .status == "completed")' >/dev/null <<<"$jobs"; then
      continue
    fi
  fi
  echo "Rollout $run_id is active; scheduled reconciliation will pick up $version"
  exit 0
done <<<"$run_rows"
gh workflow run standards-rollout.yml \
  --repo "$GITHUB_REPOSITORY" \
  --ref "$STANDARDS_TAG" \
  -f version="$version" \
  -f preserve_baselines=true
