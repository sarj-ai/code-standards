#!/usr/bin/env bash
set -euo pipefail
destination="$RUNNER_TEMP/mise-bin"
mkdir -p "$destination"
curl --fail --location --retry 3 --silent --show-error \
  "https://github.com/jdx/mise/releases/download/v${MISE_VERSION}/mise-v${MISE_VERSION}-linux-x64" \
  --output "$destination/mise"
printf '%s  %s\n' "$MISE_SHA256" "$destination/mise" | sha256sum --check --strict
chmod 0755 "$destination/mise"
printf '%s\n' "$destination" >>"$GITHUB_PATH"
