#!/usr/bin/env bash
set -e

repo="$(mktemp -d)"
printf '{ "name": "smoke", "private": true }\n' >"$repo/package.json"
cli="$GITHUB_WORKSPACE/packages/standards/.venv/bin/code-standards"
"$cli" --root "$repo" setup --no-install
jq --exit-status '.overrides | has("eslint-plugin-react")' "$repo/package.json" >/dev/null
npm --prefix "$repo" pkg delete 'devDependencies.@sarj/eslint-plugin'
# Resolution only, and without the unpublished @sarj/eslint-plugin pin:
# this asserts the peer set + overrides produce a tree npm accepts.
peer_commands=$("$cli" --root "$repo" show peers)
peer_lines=$(sed -n 's/^npm install -D --save-exact //p' <<<"$peer_commands")
peer_lines=$(tr ' ' '\n' <<<"$peer_lines")
peer_lines=$(grep -v '^@sarj/' <<<"$peer_lines")
mapfile -t peer_specs <<<"$peer_lines"
(cd "$repo" && npm install --package-lock-only --no-audit --no-fund "${peer_specs[@]}")
