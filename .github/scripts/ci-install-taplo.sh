#!/usr/bin/env bash
set -e

npm --prefix "$RUNNER_TEMP/taplo" install --ignore-scripts --no-audit --no-fund --no-save @taplo/cli@0.7.0
test -x "$RUNNER_TEMP/taplo/node_modules/.bin/taplo"
echo "$RUNNER_TEMP/taplo/node_modules/.bin" >>"$GITHUB_PATH"
