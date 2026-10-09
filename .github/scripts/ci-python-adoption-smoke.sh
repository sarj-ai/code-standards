#!/usr/bin/env bash
set -e

wheelhouse="$(mktemp -d)"
cp dist/*.whl dist/deps/*.whl "$wheelhouse/"
cli="$GITHUB_WORKSPACE/packages/standards/.venv/bin/code-standards"
for python_version in 3.14 3.15; do
  repo="$(mktemp -d)"
  printf '[project]\nname = "smoke"\nversion = "0.1.0"\nrequires-python = ">=%s"\n' "$python_version" >"$repo/pyproject.toml"
  UV_FIND_LINKS="$wheelhouse" "$cli" --root "$repo" setup
  "$cli" --root "$repo" doctor
  UV_FIND_LINKS="$wheelhouse" "$cli" --root "$repo" setup
  "$cli" --root "$repo" doctor
done
