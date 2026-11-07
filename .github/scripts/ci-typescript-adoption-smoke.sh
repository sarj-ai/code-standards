#!/usr/bin/env bash
set -euo pipefail

temporary="$(mktemp -d)"
repo="$(cd "$temporary" && pwd -P)"
printf '{ "name": "smoke", "private": true }\n' >"$repo/package.json"
cli="$GITHUB_WORKSPACE/packages/standards/.venv/bin/code-standards"
"$cli" --root "$repo" setup --no-install
for managed in oxlint.config.mts oxlint.strict.mts oxfmt.config.mts oxfmt.strict.mts doctor.config.json syncpack.strict.mts; do
  test -f "$repo/$managed"
done
if compgen -G "$repo/eslint*" >/dev/null; then
  echo "setup wrote ESLint configuration for the typescript capability" >&2
  exit 1
fi
jq --exit-status '.overrides == {}' "$repo/package.json" >/dev/null
jq --exit-status '.devDependencies | has("eslint") | not' "$repo/package.json" >/dev/null
jq --exit-status '.devDependencies | has("oxlint") and has("oxfmt") and has("tsrs")' "$repo/package.json" >/dev/null

# Resolution only, and without the unpublished @sarj/eslint-plugin pin:
# this asserts the peer set + overrides setup wrote produce a tree npm accepts.
resolution="$(mktemp -d)"
cp "$repo/package.json" "$resolution/package.json"
npm --prefix "$resolution" pkg delete 'devDependencies.@sarj/eslint-plugin'
(cd "$resolution" && npm install --package-lock-only --no-audit --no-fund)

# Run the gate end to end (Oxlint with tsrs type checking, oxfmt) against the
# plugin built from this checkout, which may not be published yet.
plugin="$GITHUB_WORKSPACE/packages/typescript"
npm --prefix "$plugin" ci --ignore-scripts --no-audit --no-fund
npm --prefix "$plugin" run build
tarball=$(npm pack "$plugin" --ignore-scripts --silent --pack-destination "$repo")
version="$(jq -r '.version' "$plugin/package.json")"
(
  cd "$repo"
  npm pkg set "devDependencies.@sarj/eslint-plugin=file:./$tarball"
  npm install --ignore-scripts --no-audit --no-fund
  # Keep the tested pin doctor expects; node_modules holds the same version from the tarball.
  npm pkg set "devDependencies.@sarj/eslint-plugin=$version"
)
mkdir "$repo/src"
printf '{ "compilerOptions": { "strict": true, "noEmit": true, "module": "nodenext" }, "include": ["src"] }\n' \
  >"$repo/tsconfig.json"
printf 'export const greeting = "hello";\n' >"$repo/src/greeting.ts"
(cd "$repo" && node_modules/.bin/oxfmt --write package.json tsconfig.json oxfmt.config.mts oxlint.config.mts src)
"$cli" --root "$repo" check --trust-repository-code --format json --output "$repo/report.json" || {
  cat "$repo/report.json"
  exit 1
}
jq --exit-status '.exitCode == 0 and .completion == "complete"' "$repo/report.json" >/dev/null
