#!/usr/bin/env bash
set -e

install -d -m 700 "$RUNNER_TEMP/npm-artifacts"
npm pack --pack-destination "$RUNNER_TEMP/npm-artifacts" --ignore-scripts
