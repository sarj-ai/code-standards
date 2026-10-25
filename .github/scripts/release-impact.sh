#!/usr/bin/env bash
set -e

if [[ "$EVENT_NAME" == push ]] && ! bash .github/scripts/ci-base-certified.sh "$GITHUB_REPOSITORY" "$BEFORE"; then
  EVENT_NAME=uncertified-base
fi
bash .github/scripts/release-python.sh -m sarj_standards.libs.release.test_selection \
  --root . --base "$BEFORE" --head "$AFTER" --event "$EVENT_NAME" --report "$RUNNER_TEMP/impact.json"
portability="$(jq -r '
  .full or any(.changed_files[];
    test("^packages/standards/tests/test_(cli_startup|consumer_cli|lifecycle|package_managers)\\.py$")
  )
' "$RUNNER_TEMP/impact.json")"
echo "portability=$portability" >>"$GITHUB_OUTPUT"
