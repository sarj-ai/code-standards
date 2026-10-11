#!/usr/bin/env bash
set -euo pipefail

standards_tag="$(python3 .github/scripts/release-metadata.py standards-tag packages/standards/pyproject.toml)"

set +e
uv run --project packages/standards --frozen code-standards --root . \
  maintain release verify-tags --commit "$TARGET_SHA"
tag_status=$?
set -e
case "$tag_status" in
  0) recovery=false ;;
  1) recovery=true ;;
  *)
    echo "::error::failed to validate immutable release tags"
    exit "$tag_status"
    ;;
esac
encoded_tag="$(jq -rn --arg value "$standards_tag" '$value | @uri')"
release_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --retry 2 --retry-all-errors --connect-timeout 5 --max-time 20 \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "$GITHUB_API_URL/repos/$GITHUB_REPOSITORY/releases/tags/$encoded_tag")"
case "$release_status" in
  200) ;;
  404)
    recovery=true
    echo "missing GitHub Release for $standards_tag"
    ;;
  *)
    echo "::error::GitHub Release lookup returned HTTP $release_status for $standards_tag"
    exit 1
    ;;
esac
echo "recovery=$recovery" >>"$GITHUB_OUTPUT"
echo "standards_tag=$standards_tag" >>"$GITHUB_OUTPUT"
