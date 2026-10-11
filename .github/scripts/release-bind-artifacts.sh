#!/usr/bin/env bash
set -euo pipefail

case "$1" in
  python)
    (cd dist && sha256sum ./*.whl ./*.tar.gz >SHA256SUMS)
    artifact=dist/SHA256SUMS
    ;;
  npm) artifact="$RUNNER_TEMP/npm-artifacts/package.tgz" ;;
  *) exit 64 ;;
esac
digest=$(sha256sum "$artifact" | cut -d ' ' -f1)
echo "sha256=$digest" >>"$GITHUB_OUTPUT"
