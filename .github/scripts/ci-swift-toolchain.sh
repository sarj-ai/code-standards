#!/usr/bin/env bash
set -eo pipefail

digest=$(xcodebuild -version | shasum -a 256 | cut -d ' ' -f 1)
echo "digest=$digest" >>"$GITHUB_OUTPUT"
