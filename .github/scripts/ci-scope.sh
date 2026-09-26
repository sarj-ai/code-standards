#!/usr/bin/env bash
set -euo pipefail

# This runs on the Linux routing runner without installing a package toolchain.
event=$1
base=$2
head=$3
output=$4
scopes=(bootstrap python sql iac typescript tsconfig standards docs mobile codeql-python codeql-javascript-typescript docs-audit)
selected=" "

select_scopes() {
  selected+="$* "
}

# Runner images provide Python 3.11+; no package installation is needed.
# Local linter releases cannot affect mobile; retain their dependency/toolchain changes.
release_metadata_only() {
  python3 - "$1" "$2" "$3" <<'PY'
import re
import subprocess
import sys
import tomllib

base, head, path = sys.argv[1:]
local_sources = {
    "code-standards": ".",
    "sarj-python-lint": "../python",
    "sarj-sql-lint": "../sql",
    "sarj-iac-lint": "../iac",
    "sarj-rule-contracts": "../contracts",
}
documents = []
for revision in (base, head):
    source = subprocess.check_output(["git", "show", f"{revision}:{path}"], text=True, timeout=30)
    document = tomllib.loads(source)
    if path.endswith("pyproject.toml"):
        del document["project"]["version"]
        document["project"]["dependencies"] = [
            re.sub(r"^(sarj-(?:python|sql|iac)-lint|sarj-rule-contracts)==[0-9]+(?:\.[0-9]+)*$", r"\1", dependency)
            for dependency in document["project"].get("dependencies", [])
        ]
    else:
        for package in document["package"]:
            name = package["name"]
            if name in local_sources and package.get("source") == {"editable": local_sources[name]}:
                del package["version"]
    documents.append(document)
sys.exit(0 if documents[0] == documents[1] else 1)
PY
}

if [[ "$event" == schedule ]]; then
  # Weekly security coverage does not rebuild packages or deploy documentation.
  select_scopes codeql-python codeql-javascript-typescript docs-audit
elif [[ "$event" != pull_request ]]; then
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
  comparison_base=$(git merge-base "$base" "$head")
  git diff --no-renames --name-only -z "$comparison_base" "$head" -- > "$changed"
  while IFS= read -r -d '' path; do
    case "$path" in
      *.py|*.pyi) select_scopes codeql-python ;;
      *.js|*.jsx|*.mjs|*.cjs|*.ts|*.tsx|*.mts|*.cts|*.astro) select_scopes codeql-javascript-typescript ;;
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
      packages/contracts/*)
        select_scopes python sql iac standards docs ;;
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
      packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json|packages/standards/src/sarj_standards/libs/linting/textlint.py)
        select_scopes standards docs ;;
      packages/standards/pyproject.toml|packages/standards/uv.lock)
        select_scopes standards docs
        # Missing/malformed files and comparison failures conservatively run mobile.
        if ! release_metadata_only "$comparison_base" "$head" "$path"; then select_scopes mobile; fi ;;
      packages/standards/*)
        # Shared runner code and configuration can affect mobile execution.
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
      README.md|AGENTS.md|LICENSE|plugins/*)
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
