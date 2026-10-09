#!/usr/bin/env bash
set -e

destination="$RUNNER_TEMP/reviewed-codeql-$LANGUAGE"
mkdir -p "$destination"
cp "$SARIF_OUTPUT"/*.sarif "$destination/"
bash .github/scripts/ci-record-analysis.sh "codeql-$LANGUAGE" "$destination"
