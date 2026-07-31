#!/usr/bin/env bash
# Fails if a private org repo name, client name, or conflict marker reaches the tree.
#
# This has regressed three times: a rebase onto the scrub commit silently restores
# scrubbed prose, and a merge of a branch that predates the scrub does the same.
# Review did not catch any of the three. A grep does.
set -uo pipefail

PATHS=(packages/ Makefile CLAUDE.md lefthook.yml .github/ README.md)
PRIVATE='bulbul|noura[-_]?be|noura|vision[ _-]?bank|visionbank|digital-bank|kpi-hub|demo-gateway|sarj-demos|\bhala\b|\bnajm\b|\bkashta\b|\btamr\b|\bfarwa\b|\bpericles\b|\bmojaz\b|aljazira|alinma|momah|absher|mngha|lucidya'
MARKERS='^<<<<<<< |^>>>>>>> |^\|\|\|\|\|\|\| '

fail=0

hits=$(git grep -inE "$PRIVATE" -- "${PATHS[@]}" ':!*package-lock.json' ':!*uv.lock' 2>/dev/null \
       | grep -viE 'comprehension|comprehensive' || true)
if [ -n "$hits" ]; then
  echo "error: private repo/client name in tracked files:"; echo "$hits"; fail=1
fi

marks=$(git grep -nE "$MARKERS" -- "${PATHS[@]}" 2>/dev/null || true)
if [ -n "$marks" ]; then
  echo "error: unresolved conflict markers:"; echo "$marks"; fail=1
fi

[ "$fail" = 0 ] && echo "no private references or conflict markers ✓"
exit "$fail"
