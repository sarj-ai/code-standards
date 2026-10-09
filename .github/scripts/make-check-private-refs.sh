#!/usr/bin/env bash
set -euo pipefail

if [[ -f .sarj-private-refs.toml ]]; then
  "$@" --root . maintain check --only private-refs --only ci-history
else
  printf '%s\n' 'private-reference scan delegated to trusted CI'
fi
