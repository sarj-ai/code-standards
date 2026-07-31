#!/usr/bin/env bash
# Fails if a private org repo name, client name, or conflict marker reaches the
# tree -- or the message of a commit being pushed.
#
# This has regressed four times. Three were file contents: a rebase onto the
# scrub commit silently restores scrubbed prose, and a merge of a branch that
# predates the scrub does the same. The fourth was still in the tree when this
# rewrite was written -- `packages/python/tests/rules/test_no_tautological_expect.py`
# had carried a private repo name and a private file path since #124, straight
# through the #173 scrub AND through the first version of this guard, because
# that version scanned six hand-listed directories and matched nineteen
# hand-listed names. Review caught none of the four. A grep catches all four,
# but only if it looks everywhere.
#
# So: scan the WHOLE tracked tree with explicit, justified exclusions, rather
# than an allowlist of directories that silently omitted `docs/` (72 files),
# `plugins/` (28), `scripts/`, `.claude/` and every root config.
#
# ---------------------------------------------------------------------------
# WHY THE NAME LIST IS IN PLAINTEXT, HERE, IN THE PUBLIC TREE
# ---------------------------------------------------------------------------
# A checked-in list of private client names is itself an inventory, and the
# reflex is to move it somewhere unreadable. Three options were weighed:
#
#   1. An out-of-tree source (env var, Actions secret, untracked file).
#      REJECTED, and not narrowly. This repo is public, so pull requests from
#      forks receive no secrets, and an unset variable makes the guard a no-op.
#      That turns the gate into one that passes hardest on exactly the path all
#      four regressions took. A guard that silently disables itself is worse
#      than no guard, because it also reports success.
#
#   2. Salted hashes of the names, compared against hashed tokens of the tree.
#      REJECTED. The salt must ship with the guard for the guard to run
#      anywhere, so a ~40-word list falls to a dictionary attack: obscurity, not
#      secrecy. It also costs real detection, because hashing requires
#      tokenising, and the leak found above (a name and a path fused into one
#      docstring) is exactly the shape tokenising splits wrong. Paying coverage
#      for obscurity is a bad trade when the thing being obscured is already
#      public: every name below appears in this repo's git history -- in 53 of
#      156 commit messages and in the pre-#173 contents of ~60 files. History is
#      immutable and public. This list reveals nothing `git log` does not.
#
#   3. Plaintext, here, in one file that ships to nobody. CHOSEN. `scripts/` is
#      in no wheel, no sdist and no npm package, so no consumer ever receives
#      it. It runs identically for maintainers, for fork PRs and in CI, with
#      zero configuration -- the only property that actually matters here.
#
# The mitigation is not hiding this list; it is that nothing in it may appear
# anywhere else. That is what this script enforces.
# ---------------------------------------------------------------------------
set -uo pipefail

usage() {
  cat <<'USAGE'
usage: check-no-private-refs.sh [--commits <range>]

  (no args)          scan the tracked working tree
  --commits <range>  ALSO scan the messages of commits in <range>,
                     e.g. origin/main..HEAD. May instead be supplied via
                     the PRIVATE_REFS_COMMIT_RANGE environment variable.
USAGE
}

COMMIT_RANGE="${PRIVATE_REFS_COMMIT_RANGE:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --commits) COMMIT_RANGE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

# --------------------------------------------------------------------------- #
# TIER A -- names distinctive enough to match anywhere a word boundary allows.
#
# Recovered from the diff of the #173 scrub commit (32a89b6), not from memory.
# The previous list held 19 of these and missed 14, including four names that
# #173 demonstrably scrubbed and one (`falltime`) that it missed entirely and
# that is still in the tree at the moment this list is being written.
# --------------------------------------------------------------------------- #
TIER_A=$(cat <<'EOF'
bulbul
noura
vision[ _-]?bank
digital[ _-]?bank
banking-(be|ai|demo|api)
kpi[ _-]?hub
demos?-gateway
sarj-demos
ai-canvas-health
money2020
name-healer
precedent-(node|iso)
internal-automations
zoho-canary
voice-cluster
vb-landing
hala
najm
kashta
tamr
farwa
pericles
mojaz
faris
falltime
tahded
sifi
aljazira
alinma
momah
absher
mngha
lucidya
EOF
)

# --------------------------------------------------------------------------- #
# TIER B -- private repo names that are also ordinary English words.
#
# `summer`, `portal`, `automations`, `bell`, `wiki`, `demos`, `submissions` and
# `talent` are all real private repos and all appear in the #173 scrub diff.
# Matched bare they are unusable: on today's clean tree `portal` alone fires on
# pnpm's `portal:` specifier and on FastAPI's `portal-gun` tutorial fixture, and
# `wiki` fires on `wiki.python.org`. So they are matched only in the three
# shapes a repo reference actually takes in this repo's evidence prose. All
# three are lifted from real scrubbed lines:
#
#   summer/typescript/packages/credit/...   path prefix
#   summer's `ReceiptService`               possessive
#   automations' `MainRouter`               plural possessive (bare apostrophe)
#   | summer | 18 | 1 | 94% |               per-repo evidence table row
#
# The plural-possessive arm is why `'` alone must be followed by whitespace: a
# name at the end of a single-quoted string is not a possessive.
#
# Two scrubbed repo names are deliberately absent: `docs` and `ai`. `docs/` is a
# real directory here, matching 167 files, and `ai` is a substring of half the
# vocabulary. No context filter separates either from ordinary use at a
# tolerable false-positive rate, and a guard that cries wolf gets switched off.
# They are accepted misses -- recorded here rather than pretended away.
# --------------------------------------------------------------------------- #
TIER_B=$(cat <<'EOF'
summer
portal
automations
bell
wiki
demos
submissions
talent
EOF
)

# Conflict markers. `=======` is deliberately NOT matched: it is valid Markdown
# setext underlining and valid reStructuredText, and all three real incidents
# carried the `<<<<<<< ` / `>>>>>>> ` pair anyway.
MARKERS='^<<<<<<< |^>>>>>>> |^\|\|\|\|\|\|\| '

A_ALT=$(printf '%s\n' "$TIER_A" | paste -sd'|' -)
B_ALT=$(printf '%s\n' "$TIER_B" | paste -sd'|' -)

# An empty tier makes `(...)` match the empty string, so the guard would report
# every line of every file rather than nothing. That is the safe direction, but
# it is an unreadable way to say "this script is broken" -- and it is reachable:
# a full disk makes the heredocs above produce nothing at all, which is how this
# assert came to be written. Say what actually happened instead.
[ -n "$A_ALT" ] && [ -n "$B_ALT" ] || {
  echo "error: the name list is empty; this script did not load correctly (disk full?)" >&2
  exit 2
}

# POSIX ERE has no \b, and BSD grep and GNU grep disagree about \< and \>, so
# the word boundaries are spelled out as character classes.
A_RE="(^|[^A-Za-z0-9])($A_ALT)([^A-Za-z0-9]|$)"
B_RE="(^|[^A-Za-z0-9])($B_ALT)(/[A-Za-z0-9_.]|'s[^A-Za-z0-9]|'[[:space:]])|^[[:space:]]*\|[[:space:]]*($B_ALT)[[:space:]]*\|"

# --------------------------------------------------------------------------- #
# Path exclusions. Every one is justified; there is no catch-all.
# --------------------------------------------------------------------------- #
EXCLUDES=(
  # This file. It is the one place the names are allowed to appear.
  ':!scripts/check-no-private-refs.sh'
  # Machine-generated dependency graphs: they enumerate every transitive package
  # the toolchain resolves, so they collide with third-party names by accident,
  # they are never hand-edited, and a leak cannot originate in them.
  ':!uv.lock'
  ':!*package-lock.json'
)

fail=0

# --------------------------------------------------------------------------- #
# 1. Tracked tree contents. `git grep` with no tree-ish reads the working tree
#    for tracked paths, so staged and unstaged edits are both covered.
# --------------------------------------------------------------------------- #
hits=$(git grep -IinE "$A_RE" -- . "${EXCLUDES[@]}" 2>/dev/null || true)
if [ -n "$hits" ]; then
  echo "error: private repo/client name in tracked files:"
  echo "$hits"
  fail=1
fi

hits_b=$(git grep -IinE "$B_RE" -- . "${EXCLUDES[@]}" 2>/dev/null || true)
if [ -n "$hits_b" ]; then
  echo "error: private repo name as a path, possessive or evidence-table row:"
  echo "$hits_b"
  fail=1
fi

marks=$(git grep -InE "$MARKERS" -- . "${EXCLUDES[@]}" 2>/dev/null || true)
if [ -n "$marks" ]; then
  echo "error: unresolved conflict markers:"
  echo "$marks"
  fail=1
fi

# --------------------------------------------------------------------------- #
# 2. Commit messages.
#
# 53 of this repo's 156 historical commit messages name a private repo or a
# client. History is immutable, so those stay; what this stops is adding more.
# The tree scan above is structurally blind to them -- a message is not a file.
# --------------------------------------------------------------------------- #
if [ -n "$COMMIT_RANGE" ]; then
  if ! git rev-list --quiet "$COMMIT_RANGE" -- >/dev/null 2>&1; then
    echo "error: cannot resolve commit range '$COMMIT_RANGE'"
    echo "hint: CI needs actions/checkout with fetch-depth: 0 to see the base."
    fail=1
  else
    # Markers are in scope here too: two of the three content regressions were
    # conflict markers committed during a rebase, and a rebase that leaves one
    # in a file leaves one in the message resolving it just as easily.
    msg_hits=$(git log --format='%h %s%n%b' "$COMMIT_RANGE" 2>/dev/null \
               | grep -IinE "$A_RE|$B_RE|$MARKERS" || true)
    if [ -n "$msg_hits" ]; then
      echo "error: private name or conflict marker in a commit message in $COMMIT_RANGE:"
      echo "$msg_hits"
      echo "hint: reword the message (git rebase -i, or squash) and re-push."
      fail=1
    fi
  fi
fi

if [ "$fail" = 0 ]; then
  scope="tracked tree"
  [ -n "$COMMIT_RANGE" ] && scope="$scope + commit messages in $COMMIT_RANGE"
  echo "no private references or conflict markers ($scope) ✓"
fi
exit "$fail"
