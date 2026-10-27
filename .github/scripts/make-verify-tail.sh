#!/usr/bin/env bash
set -euo pipefail

"$@" --no-print-directory --assume-old=typescript-build test
exec "$@" --no-print-directory repo-check check-no-private-refs shell-check
