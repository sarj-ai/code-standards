#!/usr/bin/env bash
set -e

echo "Source validation passed on the identical tree in CI $REVIEWED_RUN." >>"$GITHUB_STEP_SUMMARY"
npm --prefix apps/docs ci --ignore-scripts --no-audit --no-fund
# Source/formatter/lint/type gates passed on this exact tree. Build
# the main revision afresh and verify the deployed catalog contents.
npm --prefix apps/docs --ignore-scripts run build
node apps/docs/scripts/verify-third-party-catalog.mjs --dist
