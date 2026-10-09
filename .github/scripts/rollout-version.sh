#!/usr/bin/env bash
set -euo pipefail
version="$REQUESTED_VERSION"
if [[ -z "$version" && "$EVENT_NAME" == schedule ]]; then
  version="$(uvx --no-config --isolated --python 3.14 --refresh --from code-standards code-standards --version | sed -E 's/.* ([0-9][^ ]*)$/\1/')"
fi
if [[ -z "$version" ]]; then
  echo "::error::an exact published Standards version is required"
  exit 2
fi
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([a-zA-Z0-9.-]+)?$ ]]; then
  echo "::error::invalid Standards bundle version: $version"
  exit 2
fi
echo "version=$version" >>"$GITHUB_OUTPUT"
