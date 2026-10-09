#!/usr/bin/env bash
set -e

printf '%s\n' "$GITHUB_SHA" >dist/SOURCE_COMMIT
git rev-parse 'HEAD^{tree}' >dist/SOURCE_TREE
(cd dist && sha256sum ./*.whl ./*.tar.gz >SHA256SUMS)
