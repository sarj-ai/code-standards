#!/usr/bin/env bash
set -euo pipefail

repository=$1
base=$2
[[ "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ && "$base" =~ ^[0-9a-f]{40}$ ]] || exit 1
[[ "$base" != 0000000000000000000000000000000000000000 ]] || exit 1

# Never inherit skipped checks from an unsuccessful or still-running baseline.
# The caller falls back to all checks if this read fails or finds no certificate.
response=$(gh api --method GET "repos/$repository/actions/workflows/ci.yml/runs" \
  -f head_sha="$base" -f event=push -f per_page=100)
jq -e --arg sha "$base" --arg repo "$repository" '
  [.workflow_runs[] | select(.head_sha == $sha and .event == "push" and
    .head_branch == "main" and .head_repository.full_name == $repo and
    .path == ".github/workflows/ci.yml")]
  | max_by(.id) | .conclusion == "success"
' <<< "$response" >/dev/null
