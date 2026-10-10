#!/usr/bin/env bash
set -euo pipefail

encoded_tag="$(jq -rn --arg value "$STANDARDS_TAG" '$value | @uri')"
release_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --retry 2 --retry-all-errors --connect-timeout 5 --max-time 20 \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/releases/tags/$encoded_tag")"
case "$release_status" in
  200) ;;
  404)
    gh release create "$STANDARDS_TAG" --verify-tag --generate-notes \
      --title "Standards ${STANDARDS_TAG#standards-v}"
    ;;
  *)
    echo "::error::GitHub Release lookup returned HTTP $release_status for $STANDARDS_TAG"
    exit 1
    ;;
esac
