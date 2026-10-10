#!/usr/bin/env bash
set -euo pipefail

kind="${1:?analysis kind required}"
destination="${2:?certificate destination required}"
case "$kind" in
  static | docs | wheels | ci | codeql-python | codeql-javascript-typescript) ;;
  *)
    echo "unknown reviewed analysis kind" >&2
    exit 2
    ;;
esac
mkdir -p "$destination"
source_commit=$(git rev-parse HEAD)
source_tree=$(git rev-parse 'HEAD^{tree}')
comparison_base=$(jq --raw-output '.pull_request.base.sha' "$GITHUB_EVENT_PATH")
jq --null-input \
  --arg repository "$GITHUB_REPOSITORY" \
  --arg source_commit "$source_commit" \
  --arg tree "$source_tree" \
  --arg comparison_base "$comparison_base" \
  --arg kind "$kind" \
  --argjson run_id "$GITHUB_RUN_ID" \
  --argjson run_attempt "$GITHUB_RUN_ATTEMPT" \
  '{schema_version: 1, repository: $repository, source_commit: $source_commit, tree: $tree, comparison_base: $comparison_base, kind: $kind, run_id: $run_id, run_attempt: $run_attempt}' \
  >"$destination/proof.json"
