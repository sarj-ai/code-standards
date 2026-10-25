#!/usr/bin/env bash
set -euo pipefail

if [[ ! "${CONSUMER:-}" =~ ^([^/]+)/([A-Za-z0-9_.-]+)@.+$ ]]; then
  echo "::error::Expected a rollout consumer in owner/repository@branch form" >&2
  exit 1
fi
owner="${BASH_REMATCH[1]}"
repository="${BASH_REMATCH[2]}"
if [[ "$owner" != "$GITHUB_REPOSITORY_OWNER" ]]; then
  echo "::error::Rollout consumer must belong to the token installation owner" >&2
  exit 1
fi
printf 'repository=%s\n' "$repository" >>"$GITHUB_OUTPUT"
