#!/usr/bin/env bash
set -e

routing_event="$EVENT_NAME"
if [[ "$EVENT_NAME" == push || "$EVENT_NAME" == pull_request ]]; then
  if ! bash .github/scripts/ci-base-certified.sh "$GITHUB_REPOSITORY" "$BASE_SHA"; then
    routing_event=uncertified-base
    echo "Full validation: comparison base has no successful exact-main CI certificate."
  fi
fi
bash .github/scripts/ci-scope.sh "$routing_event" "$BASE_SHA" "$HEAD_SHA" "$GITHUB_OUTPUT"
echo "test-event=$routing_event" >>"$GITHUB_OUTPUT"
