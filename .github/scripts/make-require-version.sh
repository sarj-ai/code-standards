#!/usr/bin/env bash
set -euo pipefail

if [[ -n "$2" ]]; then
  exit 0
fi
if [[ "$1" == rollout-check ]]; then
  printf 'usage: make %s VERSION=<published-version>\n' "$1"
else
  printf 'usage: make %s VERSION=<published-version>\n' "$1" >&2
fi
exit 2
