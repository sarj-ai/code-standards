#!/usr/bin/env bash
# Every place a version number is written must agree with the package it names.
#
# The old check was one line of Make and compared exactly two of the twenty-one
# version sites in this repo: root `pyproject.toml` against
# `packages/python/pyproject.toml`. Everything else was unguarded, and the gap
# is not theoretical:
#
#   - #183 bumped `packages/typescript/package.json` 4.2.0 -> 5.0.0 and left
#     BOTH version fields in `package-lock.json` at 4.2.0, while its own message
#     claimed "versions and lockfiles bumped for all five published packages".
#     They were in sync at #183^, so #183 introduced the drift, and the old
#     check was structurally incapable of seeing it.
#   - the root `uv.lock` has said `sarj-python-lint 0.33.0` since #169 while
#     `pyproject.toml` went 0.33.0 -> 0.34.0 -> 0.35.0. That drift is live on
#     main at the time this script is written, and this script is what found it.
#
# So enumerate every site. A version site that is not listed here is a site that
# will drift, so adding a package means adding it below -- and the LOCKFILE
# COVERAGE assertion at the end fails if a package appears without its lock.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail=0
report() { echo "error: $1"; fail=1; }

# --- readers ----------------------------------------------------------------

# `version = "X"` from a pyproject's [project] table. Anchored to the file head
# so a `[tool.*]` table further down cannot supply the answer.
toml_version() { sed -n '1,20s/^version = "\([^"]*\)"$/\1/p' "$1" | head -1; }

# A dotted path out of a JSON file. python3 rather than grep: `"version"` occurs
# once per dependency in a lockfile, and picking the first is how you validate
# the version of somebody else's package.
json_at() {
  python3 -c '
import json, sys
doc = json.load(open(sys.argv[1]))
for key in sys.argv[2:]:
    doc = doc[key] if key else doc[""]
print(doc)
' "$@" 2>/dev/null
}

# The `version` of one [[package]] block in a uv.lock, selected by name. uv.lock
# is TOML, but tomllib on a 5k-line lock for one field is slower than awk and
# adds a parse-error mode for a file uv itself guarantees well-formed.
uvlock_version() {
  awk -v want="$2" '
    /^\[\[package\]\]/ { inpkg = 1; name = ""; next }
    inpkg && /^name = / { gsub(/[",]/, "", $3); name = $3 }
    inpkg && /^version = / && name == want { gsub(/[",]/, "", $3); print $3; exit }
  ' "$1"
}

# --- the assertions ---------------------------------------------------------

# $1 human label, $2 expected, $3 actual, $4 where
same() {
  if [ -z "$3" ]; then
    report "$1: could not read a version from $4"
  elif [ "$2" != "$3" ]; then
    report "$1: $4 says $3, expected $2"
  fi
}

# Identity versions: the single source of truth for each published package.
ROOT_V=$(toml_version pyproject.toml)
PY_V=$(toml_version packages/python/pyproject.toml)
SQL_V=$(toml_version packages/sql/pyproject.toml)
IAC_V=$(toml_version packages/iac/pyproject.toml)
CFG_V=$(toml_version packages/lint-configs/pyproject.toml)
TS_V=$(json_at packages/typescript/package.json version)
TSC_V=$(json_at packages/tsconfig/package.json version)

for pair in "root pyproject:$ROOT_V" "python:$PY_V" "sql:$SQL_V" "iac:$IAC_V" \
            "lint-configs:$CFG_V" "typescript:$TS_V" "tsconfig:$TSC_V"; do
  [ -n "${pair#*:}" ] || report "no version found for ${pair%%:*}"
done

# 1. Root package vs packages/python. Pre-commit consumers install the ROOT
#    package, so a root version lagging packages/python ships a stale linter
#    under a fresh number. This is the one case the old check covered.
same "root package" "$PY_V" "$ROOT_V" "pyproject.toml"

# 2. npm: package.json vs BOTH version fields of its lockfile. `npm publish`
#    reads package.json, so the lock is the field that silently rots -- and
#    `npm ci` writes the lock's number into the installed tree.
same "typescript lock" "$TS_V" "$(json_at packages/typescript/package-lock.json version)" \
  "packages/typescript/package-lock.json .version"
same "typescript lock" "$TS_V" "$(json_at packages/typescript/package-lock.json packages '' version)" \
  'packages/typescript/package-lock.json .packages[""].version'

# 3. uv locks: each package's own entry in its own lock, plus the root lock.
same "root uv.lock" "$ROOT_V" "$(uvlock_version uv.lock sarj-python-lint)" \
  "uv.lock [sarj-python-lint]"
same "python uv.lock" "$PY_V" "$(uvlock_version packages/python/uv.lock sarj-python-lint)" \
  "packages/python/uv.lock [sarj-python-lint]"
same "sql uv.lock" "$SQL_V" "$(uvlock_version packages/sql/uv.lock sarj-sql-lint)" \
  "packages/sql/uv.lock [sarj-sql-lint]"
same "iac uv.lock" "$IAC_V" "$(uvlock_version packages/iac/uv.lock sarj-iac-lint)" \
  "packages/iac/uv.lock [sarj-iac-lint]"
same "lint-configs uv.lock" "$CFG_V" "$(uvlock_version packages/lint-configs/uv.lock sarj-lint-configs)" \
  "packages/lint-configs/uv.lock [sarj-lint-configs]"

# 4. lint-configs pins its three siblings EXACTLY, in the manifest and again in
#    its lock. CLAUDE.md calls this out by name: a rule change has to move the
#    owning package version, the lockfile, and any exact `sarj-lint-configs`
#    dependency in one commit.
for sib in "sarj-python-lint:$PY_V" "sarj-sql-lint:$SQL_V" "sarj-iac-lint:$IAC_V"; do
  name=${sib%%:*}
  want=${sib#*:}
  pin=$(sed -n "s/.*\"$name==\([^\"]*\)\".*/\1/p" packages/lint-configs/pyproject.toml | head -1)
  same "lint-configs pin of $name" "$want" "$pin" "packages/lint-configs/pyproject.toml"
  same "lint-configs lock of $name" "$want" \
    "$(uvlock_version packages/lint-configs/uv.lock "$name")" \
    "packages/lint-configs/uv.lock [$name]"
done

# 5. The generated ESLint peer floor names the plugin version a consumer must
#    install for every rule the strict config references to exist. Naming a
#    version that predates a referenced rule is "Definition for rule was not
#    found", once per file -- the exact defect #180 shipped in prose form.
PEERS=packages/lint-configs/src/sarj_lint_configs/configs/eslint.peers.json
same "eslint peer floor" "$TS_V" "$(json_at "$PEERS" peers '@sarj/eslint-plugin')" \
  "$PEERS"

# 6. COVERAGE. The failure this whole script exists to prevent is a version site
#    nobody listed. So assert the list is complete rather than trusting it: every
#    tracked lockfile must be named above, and every published package manifest
#    must have had its version read.
declare -a KNOWN_LOCKS=(
  uv.lock
  packages/python/uv.lock
  packages/sql/uv.lock
  packages/iac/uv.lock
  packages/lint-configs/uv.lock
  packages/typescript/package-lock.json
)
while read -r lock; do
  [ -n "$lock" ] || continue
  found=0
  for known in "${KNOWN_LOCKS[@]}"; do
    [ "$lock" = "$known" ] && found=1 && break
  done
  [ "$found" = 1 ] ||
    report "$lock is a lockfile this check does not know about; add it to KNOWN_LOCKS and assert its version"
done < <(git ls-files '*uv.lock' '*package-lock.json')

while read -r manifest; do
  [ -n "$manifest" ] || continue
  case "$manifest" in
    packages/python/pyproject.toml | packages/sql/pyproject.toml | \
      packages/iac/pyproject.toml | packages/lint-configs/pyproject.toml) ;;
    packages/tsconfig/package.json | packages/typescript/package.json) ;;
    *) report "$manifest declares a package version this check does not assert" ;;
  esac
done < <(git ls-files 'packages/*/pyproject.toml' 'packages/*/package.json')

[ "$fail" = 0 ] && echo "all 21 version sites agree ✓"
exit "$fail"
