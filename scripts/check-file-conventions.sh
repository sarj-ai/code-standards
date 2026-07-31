#!/usr/bin/env bash
# Repo layout gate: filename casing, rule<->test pairing, and one-copy-per-config.
#
# Conventions are cheap to state and expensive to remember. This states them once,
# because the repo already had two of them broken and neither was visible to review:
#   - packages/sql/tests/rules/test_new_sql_rules.py covered three rules under a
#     name that named none of them, so `add-constraint-not-valid` looked untested.
#   - the one-copy-per-config rule held, but only by convention: the root
#     `.ruff-strict.toml` and `.pyright-strict.json` are symlinks and nothing said
#     so, so a `cp` over either -- the obvious "fix" for a broken link -- would
#     have restored the drift CLAUDE.md forbids without failing anything.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

CANONICAL_CONFIG_DIR="packages/lint-configs/src/sarj_lint_configs/configs"

fail=0
report() { echo "error: $1"; fail=1; }

# Tracked AND present in the working tree. `git ls-files` reads the index, so a
# half-finished `git mv` would otherwise be reported as a misnamed file that
# cannot be opened — an error about the rename you are in the middle of doing.
tracked() {
  local path
  while read -r path; do
    [ -e "$path" ] && echo "$path"
  done < <(git ls-files "$@")
}

# --- 1. Filename casing -----------------------------------------------------
# One convention per ecosystem, chosen to match the ecosystem rather than to be
# uniform across them: Python modules are imported by name so they are
# snake_case, TypeScript modules are imported by path so they are kebab-case.

while read -r path; do
  [ -n "$path" ] || continue
  name=$(basename "$path")
  [[ "$name" =~ ^[a-z_][a-z0-9_]*\.py$ ]] ||
    report "python module is not snake_case: $path"
done < <(tracked 'packages/*/src/**/*.py' 'packages/*/tests/**/*.py' 'packages/*/*.py')

while read -r path; do
  [ -n "$path" ] || continue
  name=$(basename "$path")
  # Leading `_` marks a shared non-rule helper; the rest must be kebab-case, with
  # an optional `.test`/`.config` qualifier before the extension.
  [[ "$name" =~ ^_?[a-z0-9]+(-[a-z0-9]+)*(\.(test|config|d))?\.(ts|tsx|mts|cts)$ ]] ||
    report "typescript module is not kebab-case: $path"
done < <(tracked 'packages/typescript/src/**/*.ts' 'packages/typescript/tests/**/*.ts' 'packages/typescript/*.ts')

while read -r path; do
  [ -n "$path" ] || continue
  name=$(basename "$path")
  # `.py` as well as `.sh`: a script that has to import a registry or emit JSON
  # is Python, and forcing it into bash to satisfy a filename rule would trade a
  # convention for a worse script. The naming rule is what matters here -- a
  # script is invoked by path, so it is kebab-case like everything else invoked
  # by path, whatever it is written in.
  [[ "$name" =~ ^[a-z0-9]+(-[a-z0-9]+)*\.(sh|py)$ ]] ||
    report "script is not kebab-case .sh or .py: $path"
  [ -x "$path" ] || report "script is not executable: $path"
  head -1 "$path" | grep -q '^#!' || report "script has no shebang: $path"
done < <(tracked 'scripts/*')

# `.yml` or `.yaml`, but not both in one directory -- mixing them is how a
# workflow ends up edited in the copy GitHub does not read.
if [ -n "$(tracked '.github/workflows/*.yaml')" ]; then
  report ".github/workflows uses both .yml and .yaml; standardise on .yml"
fi
while read -r path; do
  [ -n "$path" ] || continue
  name=$(basename "$path")
  [[ "$name" =~ ^[a-z0-9]+(-[a-z0-9]+)*\.yml$ ]] ||
    report "workflow is not kebab-case .yml: $path"
done < <(tracked '.github/workflows/*')

# --- 2. Markdown lives in a closed set of places ----------------------------
# Prose is a defect here: a rule's claim belongs in its docstring, its examples
# in its tests, and its measurements in docs/rules/<name>.md. Anything else is a
# file nobody updates. Adding a location is a deliberate act, so it edits this list.
while read -r path; do
  [ -n "$path" ] || continue
  case "$path" in
    README.md | CLAUDE.md) ;;
    docs/rules/*.md | docs/rules/retired/*.md) ;;
    packages/*/README.md) ;;
    plugins/*/commands/*.md | plugins/*/skills/*/SKILL.md | plugins/*/README.md) ;;
    *) report "markdown outside the allowed locations: $path" ;;
  esac
done < <(tracked '*.md')

# --- 2b. Evidence is RETAINED when its rule is deleted -----------------------
# `docs/rules/<name>.md` holds the measured corpus evidence a rule was shipped
# on. That evidence is the only thing that makes the decision revisitable, and
# the previous version of the check below actively destroyed it: it reported any
# doc that named no live rule as an orphan, so the mechanical way to satisfy it
# when withdrawing a rule was to delete the evidence too. #183 did exactly that
# -- `docs/rules/SARJ061.md` was deleted with SARJ061, taking with it the
# identity of the 3 findings that commit called true positives, which is now
# unrecoverable from the tree. In the same commit a second rule was withdrawn on
# a stated "0 true positives" that no surviving artifact can support or refute.
#
# So evidence is not deleted, it is MOVED to `docs/rules/retired/`, and this is
# enforced two ways rather than written down and hoped for:
#   - a doc that names no live rule must be under retired/ (not absent);
#   - and the diff gate at the end fails if a doc leaves `docs/rules/` in this
#     branch without arriving under `docs/rules/retired/`.
allocated_codes=$(git grep -hoE '"SARJ[0-9]{3}"' -- 'packages/*/src/*/rules/*.py' |
  tr -d '"' | sort -u)

names_a_live_rule() {
  local stem="$1"
  if [[ "$stem" =~ ^SARJ[0-9]{3}$ ]]; then
    grep -qx "$stem" <<<"$allocated_codes"
    return
  fi
  # A leading `_` marks a shared non-rule helper; it still has to name a module,
  # because the doc-diet convention gives every module under src/rules an
  # evidence file and `rule-docs.test.ts` walks the modules to require them.
  [[ "$stem" =~ ^_?[a-z0-9]+(-[a-z0-9]+)*$ ]] &&
    [ -f "packages/typescript/src/rules/$stem.ts" ]
}

while read -r path; do
  [ -n "$path" ] || continue
  stem=$(basename "$path" .md)
  names_a_live_rule "$stem" ||
    report "docs/rules/$stem.md names no live rule; move it to docs/rules/retired/$stem.md rather than deleting it -- the evidence is what makes the decision revisitable"
done < <(tracked 'docs/rules/*.md' ':!docs/rules/retired/*')

# The mirror: an archived doc whose rule is live again is evidence nobody reads,
# because every link derived by `Rule.evidence_path()` points at docs/rules/.
while read -r path; do
  [ -n "$path" ] || continue
  stem=$(basename "$path" .md)
  if names_a_live_rule "$stem"; then
    report "docs/rules/retired/$stem.md is archived but $stem is a live rule; move it back to docs/rules/$stem.md"
  fi
done < <(tracked 'docs/rules/retired/*.md')

# --- 3. Every rule module has a test module named after it ------------------
# The pairing is what makes `Rule.examples_path()` resolvable and what makes an
# untested rule visible. A catch-all test file hides both.
#
# A rule module missing from the registry is the other half of the same defect: it
# is tested, it typechecks, and it never runs. `require-parameterized-tests.ts` sat
# in the TypeScript tree in exactly that state, referenced by nothing.
pair_python() {
  local pkg="$1" dist="$2" src tests base
  src="packages/$pkg/src/$dist/rules"
  tests="packages/$pkg/tests/rules"
  for file in "$src"/*.py; do
    base=$(basename "$file" .py)
    case "$base" in _* | __*) continue ;; esac
    [ -f "$tests/test_$base.py" ] ||
      report "$pkg rule $base.py has no $tests/test_$base.py"
    grep -q "rules\.$base import" "$src/_registry.py" ||
      report "$pkg rule $base.py is in no registry, so it never runs"
  done
  for file in "$tests"/test_*.py; do
    base=$(basename "$file" .py)
    base=${base#test_}
    [ -f "$src/$base.py" ] || [ -f "$src/_$base.py" ] ||
      report "$tests/test_$base.py names no rule or helper in $src"
  done
}
pair_python python sarj_python_lint
pair_python sql sarj_sql_lint
pair_python iac sarj_iac_lint

for file in packages/typescript/src/rules/*.ts; do
  base=$(basename "$file" .ts)
  case "$base" in _*) continue ;; esac
  [ -f "packages/typescript/tests/rules/$base.test.ts" ] ||
    report "typescript rule $base.ts has no tests/rules/$base.test.ts"
  grep -q "\"$base\"" packages/typescript/src/index.ts ||
    report "typescript rule $base.ts is not exported from src/index.ts, so it never runs"
done
for file in packages/typescript/tests/rules/*.test.ts; do
  base=$(basename "$file" .test.ts)
  [ -f "packages/typescript/src/rules/$base.ts" ] ||
    report "tests/rules/$base.test.ts names no rule in src/rules"
done

# --- 4. Exactly one copy of each strict config ------------------------------
# CLAUDE.md's hard constraint. A second copy is always byte-identical on the day
# it lands and always drifts later, and the drift is invisible because both files
# look canonical. Hashing is the only check that cannot be fooled by a rename.
#
# The root `.ruff-strict.toml` / `.pyright-strict.json` are SYMLINKS into the
# canonical directory, and the indirection is load-bearing rather than cosmetic:
# ruff resolves `per-file-ignores` globs against the directory of the config that
# declares them, so pointing a package at the canonical path directly loses the
# whole `"**/tests/**"` exemption block -- measured at 239 new findings in
# packages/python alone. The symlink keeps the anchor at the repo root while
# keeping one copy of the bytes. A `cp` in its place looks identical on the day
# it lands and drifts silently after.
#
# One `git hash-object --stdin-paths` for the whole tree: the naive
# hash-per-pair loop is 3.5k subprocesses and takes minutes, which is the same
# as not having the check at all once someone notices it in their pre-commit.
regular_files() {
  local path
  while read -r path; do
    [ -L "$path" ] || echo "$path"
  done < <(tracked)
}
duplicates=$(regular_files | git hash-object --stdin-paths | paste -d' ' - <(regular_files) |
  awk -v dir="$CANONICAL_CONFIG_DIR/" '
    { hash = $1; path = $2 }
    index(path, dir) == 1 { canonical[hash] = path; next }
    { seen[hash] = seen[hash] " " path }
    END {
      for (hash in canonical)
        if (hash in seen)
          print canonical[hash] "|" seen[hash]
    }')
while IFS='|' read -r canonical copies; do
  [ -n "$canonical" ] || continue
  report "$copies duplicates $canonical byte for byte; make it a symlink into that directory instead of a copy"
done <<<"$duplicates"

# Packages must extend the canonical file, not a copy of it. `realpath -m` would
# say this in one line but BSD realpath has no -m, so normalise by hand.
normalize() {
  local combined="$1/$2" part
  local -a parts out=()
  IFS='/' read -ra parts <<<"$combined"
  for part in "${parts[@]}"; do
    case "$part" in
      '' | '.') ;;
      '..') out=("${out[@]:0:$((${#out[@]} - 1))}") ;;
      *) out+=("$part") ;;
    esac
  done
  (
    IFS=/
    echo "${out[*]}"
  )
}

check_extends() {
  local manifest="$1" extend="$2" resolved link
  [ -n "$extend" ] || return 0
  resolved=$(normalize "$(dirname "$manifest")" "$extend")
  if [ ! -e "$resolved" ]; then
    report "$manifest extends $extend, which does not exist"
    return 0
  fi
  if [ -L "$resolved" ]; then
    link=$(readlink "$resolved")
    resolved=$(normalize "$(dirname "$resolved")" "$link")
  fi
  case "$resolved" in
    "$CANONICAL_CONFIG_DIR"/*) ;;
    *) report "$manifest extends $extend, which is a real file outside $CANONICAL_CONFIG_DIR; make it a symlink into that directory" ;;
  esac
}

while read -r manifest; do
  [ -n "$manifest" ] || continue
  check_extends "$manifest" "$(sed -n 's/^extend = "\(.*\)"$/\1/p' "$manifest" | head -1)"
done < <(tracked 'packages/*/pyproject.toml')

while read -r manifest; do
  [ -n "$manifest" ] || continue
  check_extends "$manifest" "$(sed -n 's/.*"extends": "\([^"]*\)".*/\1/p' "$manifest" | head -1)"
done < <(tracked 'packages/*/pyrightconfig.json')

# --- 5. No evidence document leaves the tree --------------------------------
# The half of retention that section 2b cannot see. 2b answers "is every doc in
# the right directory"; a doc that was deleted outright is in no directory, so
# only a diff against the merge base can catch it.
#
# It FAILS rather than skips when it cannot resolve the base. A gate that
# silently no-ops without its input is the defect this whole file exists to
# stop -- see `check-no-private-refs.sh`, which for three regressions ran only
# in a hook and reported success everywhere else.
EVIDENCE_RETENTION_BASE="${EVIDENCE_RETENTION_BASE:-}"
if [ -z "$EVIDENCE_RETENTION_BASE" ] && git rev-parse --verify --quiet origin/main >/dev/null 2>&1; then
  EVIDENCE_RETENTION_BASE=$(git merge-base origin/main HEAD 2>/dev/null || true)
fi
if [ -n "$EVIDENCE_RETENTION_BASE" ]; then
  if ! git rev-parse --verify --quiet "$EVIDENCE_RETENTION_BASE^{commit}" >/dev/null 2>&1; then
    report "evidence-retention base '$EVIDENCE_RETENTION_BASE' does not resolve; CI needs actions/checkout with fetch-depth: 0"
  else
    # `-M` is what separates a withdrawal from a rename. #186 renamed four
    # TypeScript rules and their evidence files with them; that is content
    # moving, not evidence being destroyed, and git reports it as R rather than
    # D. Comparing directory listings instead would fail every rename, which is
    # how a gate earns a `|| true` from the next person in a hurry.
    while read -r path; do
      [ -n "$path" ] || continue
      stem=$(basename "$path" .md)
      [ -f "docs/rules/retired/$stem.md" ] && continue
      report "docs/rules/$stem.md was deleted, not archived; restore it as docs/rules/retired/$stem.md (git show $EVIDENCE_RETENTION_BASE:docs/rules/$stem.md) -- a rule's evidence is what makes its withdrawal revisitable"
    done < <(git diff -M --diff-filter=D --name-only "$EVIDENCE_RETENTION_BASE" HEAD -- 'docs/rules/*.md' |
      grep -E '^docs/rules/[^/]+\.md$')
  fi
fi

[ "$fail" = 0 ] && echo "file conventions ✓"
exit "$fail"
