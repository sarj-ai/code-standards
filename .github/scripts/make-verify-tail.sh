#!/usr/bin/env bash
set -euo pipefail

mode="$1"
shift
case "$mode" in
  final)
    target="$1"
    shift
    "$@" --no-print-directory --assume-old=typescript-build "$target"
    exec "$@" --no-print-directory repo-check check-no-private-refs shell-check
    ;;
  grouped)
    bash .github/scripts/make-local-check.sh "$@" --no-print-directory --assume-old=typescript-build verify-test-typescript
    bash .github/scripts/make-local-check.sh "$@" --no-print-directory --assume-old=typescript-build verify-test-python
    target=verify-test-standards
    ;;
  aggregate) target='test' ;;
  *)
    printf 'Unknown verification mode: %s\n' "$mode" >&2
    exit 2
    ;;
esac
exec bash .github/scripts/make-local-check.sh bash "$0" final "$target" "$@"
