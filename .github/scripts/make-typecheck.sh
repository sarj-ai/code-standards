#!/usr/bin/env bash
set -euo pipefail

# Replace the wrapper so Make receives signals and owns the checker children.
exec "$@" --file - checks <<'MAKE'
SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.PHONY: checks python standards sql iac contracts bootstrap
checks: python standards sql iac contracts bootstrap
python:
	uv --directory packages/python run basedpyright
standards:
	uv run --project packages/standards --frozen basedpyright --project packages/standards/pyrightconfig.json packages/standards/src packages/standards/tests .github/scripts/*.py
sql:
	uv --directory packages/sql run basedpyright
iac:
	uv --directory packages/iac run basedpyright
contracts:
	uv --directory packages/contracts run basedpyright
bootstrap:
	uv --directory packages/bootstrap run basedpyright
MAKE
