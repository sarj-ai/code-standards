#!/usr/bin/env bash
set -euo pipefail

# Recursive Make recipes run even during planning. GNU Make emits boolean flags
# before option operands; stop before operands so paths cannot become flag clusters.
read -r -a make_flags <<<"${MAKEFLAGS-} --"
for flags in "${make_flags[@]}"; do
  case "$flags" in
    --warn-undefined-variables | --no-builtin-rules | --no-builtin-variables | --no-print-directory | -) continue ;;
    --*) break ;;
  esac
  flags=${flags#-}
  while [[ -n "$flags" ]]; do
    case "${flags:0:1}" in
      n | t | q) exec "$@" ;;
      b | B | d | e | E | i | k | L | m | p | r | R | s | S | v | w) ;;
      *) break 2 ;;
    esac
    flags=${flags:1}
  done
done

if command -v sarj-local-check >/dev/null 2>&1; then
  exec sarj-local-check "$@"
fi
exec "$@"
