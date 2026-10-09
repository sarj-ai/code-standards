#!/usr/bin/env bash
set -e

repo="$(mktemp -d)"
wheelhouse="$(mktemp -d)"
cp dist/*.whl dist/deps/*.whl "$wheelhouse/"
printf '[project]\nname = "smoke"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n' >"$repo/pyproject.toml"
cli="$GITHUB_WORKSPACE/packages/standards/.venv/bin/code-standards"
UV_FIND_LINKS="$wheelhouse" "$cli" --root "$repo" setup
"$cli" --root "$repo" doctor
UV_FIND_LINKS="$wheelhouse" "$cli" --root "$repo" setup
"$cli" --root "$repo" doctor
