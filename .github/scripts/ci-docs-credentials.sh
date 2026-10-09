#!/usr/bin/env bash
set -e

test -n "$CLOUDFLARE_ACCOUNT_ID" || {
  echo "CLOUDFLARE_ACCOUNT_ID is not configured in code-standards-production"
  exit 1
}
test -n "$CLOUDFLARE_API_TOKEN" || {
  echo "CLOUDFLARE_API_TOKEN is not configured in code-standards-production"
  exit 1
}
