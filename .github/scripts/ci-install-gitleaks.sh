#!/usr/bin/env bash
set -e

if ! curl --fail --location --silent --show-error \
  --output "$RUNNER_TEMP/gitleaks.tar.gz" \
  https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz; then
  timeout --kill-after=5s 60s gh release download v8.30.1 \
    --repo gitleaks/gitleaks --pattern gitleaks_8.30.1_linux_x64.tar.gz \
    --output "$RUNNER_TEMP/gitleaks.tar.gz" --clobber
fi
echo '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb  '"$RUNNER_TEMP/gitleaks.tar.gz" | sha256sum --check --strict
tar -xzf "$RUNNER_TEMP/gitleaks.tar.gz" -C "$RUNNER_TEMP" gitleaks
