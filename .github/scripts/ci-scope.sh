#!/usr/bin/env bash
set -euo pipefail

# This runs on the Linux routing runner without installing a package toolchain.
event=$1
base=$2
head=$3
output=$4
scopes=(bootstrap python sql iac typescript tsconfig standards docs mobile codeql-python codeql-javascript docs-audit)
selected=" "

select_scopes() {
  selected+="$* "
}

if [[ "$event" != pull_request ]]; then
  # Releases wait for complete validation of their exact main revision.
  select_scopes "${scopes[@]}"
else
  [[ "$base" =~ ^[0-9a-f]{40}$ && "$head" =~ ^[0-9a-f]{40}$ ]] || {
    echo 'PR routing requires base and head commit SHAs' >&2
    exit 1
  }
  changed=$(mktemp)
  trap 'rm -f "$changed"' EXIT
  # Disable rename detection so BOTH the old and new package owners run.
  # A failed diff must abort before any false outputs can be published.
  git diff --no-renames --name-only -z "$base...$head" -- > "$changed"
  while IFS= read -r -d '' path; do
    case "$path" in
      *.py|*.pyi) select_scopes codeql-python ;;
      *.js|*.jsx|*.mjs|*.cjs|*.ts|*.tsx|*.mts|*.cts|*.astro) select_scopes codeql-javascript ;;
    esac
    case "$path" in
      packages/*/README.md) select_scopes docs standards ;;
      .github/*)
        select_scopes "${scopes[@]}" ;;
      .sarj-standards.toml)
        select_scopes standards docs ;;
      pyproject.toml|uv.lock)
        select_scopes python standards docs ;;
      packages/standards/src/sarj_standards/configs/eslint*)
        select_scopes typescript standards docs ;;
      packages/standards/src/sarj_standards/configs/rule-*|packages/standards/src/sarj_standards/configs/cli-reference.v1.json)
        select_scopes standards docs ;;
      packages/standards/src/sarj_standards/configs/*)
        select_scopes "${scopes[@]}" ;;
      packages/bootstrap/*)
        select_scopes bootstrap standards docs ;;
      packages/python/*)
        select_scopes python standards docs ;;
      packages/sql/*)
        select_scopes sql standards docs ;;
      packages/iac/*)
        select_scopes iac standards docs ;;
      packages/typescript/*)
        select_scopes typescript standards docs ;;
      packages/tsconfig/*)
        select_scopes tsconfig standards docs ;;
      packages/standards/tests/*)
        select_scopes standards ;;
      packages/standards/src/*)
        select_scopes standards docs mobile ;;
      packages/standards/*)
        # These dependencies belong to the runner, not the independent packages.
        select_scopes standards docs mobile ;;
      packages/standards-compat/*)
        select_scopes standards docs ;;
      apps/docs/src/generated/*)
        select_scopes docs standards ;;
      apps/docs/package.json|apps/docs/package-lock.json)
        select_scopes docs standards docs-audit ;;
      apps/docs/*.md|apps/docs/*.mdx)
        select_scopes docs ;;
      apps/docs/*)
        select_scopes docs standards ;;
      README.md|CLAUDE.md|AGENTS.md|LICENSE|plugins/*)
        select_scopes docs standards ;;
      *)
        # New directories and repository-wide configuration fail open to work,
        # never to a green result that omitted an unknown dependency.
        select_scopes "${scopes[@]}" ;;
    esac
  done < "$changed"
fi

for scope in "${scopes[@]}"; do
  value=false
  if [[ "$selected" == *" $scope "* ]]; then value=true; fi
  printf '%s=%s\n' "$scope" "$value" | tee -a "$output"
done
