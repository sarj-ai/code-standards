#!/usr/bin/env bash
# Every CI job that runs a package test suite must check out FULL history.
#
# The retired-identifier gates derive the withdrawn rule set from
# `git log --diff-filter=D` instead of trusting a hand-kept list, and they fail
# loudly on a shallow clone rather than skipping — a gate that goes quiet when
# its input is missing is the class of defect they were written to remove.
#
# `actions/checkout` defaults to `fetch-depth: 1`, so "runs the tests" and "can
# read history" are two independent facts about a job, and nothing tied them
# together. release.yml's publish-typescript ran `npm test` on a depth-1
# checkout and failed the plugin's publish. Deriving the pairing here is the fix:
# a new workflow that runs a suite cannot forget, because this check reads the
# workflows rather than a list of them.
set -euo pipefail

cd "$(dirname "$0")/.."

status=0
report() {
  echo "error: $1" >&2
  status=1
}

for workflow in .github/workflows/*.yml; do
  # Split the file into jobs, then ask each job the two questions. `awk` keeps
  # this to one pass and no temp files; a job starts at two-space indentation
  # under `jobs:`.
  awk -v file="$workflow" '
    /^jobs:/ { in_jobs = 1; next }
    in_jobs && /^  [A-Za-z0-9_-]+:/ {
      if (job != "") print job "\t" tests "\t" depth "\t" file
      job = $1; sub(/:$/, "", job); tests = 0; depth = 0; next
    }
    in_jobs && (/npm test/ || /pytest/ || /make (verify|test)\b/) { tests = 1 }
    in_jobs && /fetch-depth:[[:space:]]*0/ { depth = 1 }
    END { if (job != "") print job "\t" tests "\t" depth "\t" file }
  ' "$workflow"
done | while IFS=$'\t' read -r job tests depth file; do
  if [ "$tests" = "1" ] && [ "$depth" != "1" ]; then
    echo "error: $file job '$job' runs a test suite on a shallow checkout; add 'fetch-depth: 0'" >&2
    exit 1
  fi
done || status=1

[ "$status" -eq 0 ] && echo "CI history depth ✓"
exit "$status"
