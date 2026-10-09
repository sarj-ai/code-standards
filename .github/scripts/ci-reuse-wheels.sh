#!/usr/bin/env bash
set -e

mkdir -p dist
cp -R "$RUNNER_TEMP/reviewed-analysis/wheels/". dist/
mv dist/proof.json dist/REVIEWED_SOURCE.json
echo "Exact reviewed wheel bytes from CI $REVIEWED_RUN; checked tree and comparison base match." >>"$GITHUB_STEP_SUMMARY"
