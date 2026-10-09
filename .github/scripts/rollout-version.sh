#!/usr/bin/env bash
set -euo pipefail
export UV_PYTHON_DOWNLOADS_JSON_URL="${UV_PYTHON_DOWNLOADS_JSON_URL:-https://raw.githubusercontent.com/astral-sh/uv/f69fb50c8b28997af9c6b0e5c700a34470d86005/crates/uv-python-managed/download-metadata.json}"
version="$REQUESTED_VERSION"
if [[ -z "$version" && "$EVENT_NAME" == schedule ]]; then
  version="$(uvx --no-config --isolated --python "${STANDARDS_PYTHON:-3.15.0}" --refresh --from code-standards code-standards --version | sed -E 's/.* ([0-9][^ ]*)$/\1/')"
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
