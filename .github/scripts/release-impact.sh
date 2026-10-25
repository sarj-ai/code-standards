#!/usr/bin/env bash
set -e

if [[ "$EVENT_NAME" == push ]] && ! bash .github/scripts/ci-base-certified.sh "$GITHUB_REPOSITORY" "$BEFORE"; then
  EVENT_NAME=uncertified-base
fi
bash .github/scripts/release-python.sh -m sarj_standards.libs.release.test_selection \
  --root . --base "$BEFORE" --head "$AFTER" --event "$EVENT_NAME" --report "$RUNNER_TEMP/impact.json"
# Test-only changes must requalify the cross-platform checks they exercise.
portability="$(jq -r '
  .full or any(.changed_files[]; IN(
    "packages/standards/tests/test_cli_startup.py",
    "packages/standards/tests/test_consumer_cli.py",
    "packages/standards/tests/test_lifecycle.py",
    "packages/standards/tests/test_package_managers.py"
  ))' "$RUNNER_TEMP/impact.json")"
echo "portability=$portability" >>"$GITHUB_OUTPUT"
