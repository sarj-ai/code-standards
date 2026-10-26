#!/usr/bin/env bash
set -euo pipefail

if [[ -f apps/docs/dist/projects/code-standards/index.html ]]; then
  exit 0
fi
printf '%s\n' 'build the documentation before checking deployment'
exit 2
