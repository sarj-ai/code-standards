SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules

CONFIG_SRC := packages/lint-configs/src/sarj_lint_configs/configs

.PHONY: help setup build verify test lint typecheck promote-strict check-versions-synced publish publish-typescript publish-python publish-sql \
        publish-iac publish-lint-configs publish-tsconfig

help:
	@echo "Targets: setup | verify | build | test | lint | typecheck | promote-strict"
	@echo "         publish-{typescript,python,sql,iac,lint-configs,tsconfig} | publish (all)"
	@echo "Releases trigger via tag push: typescript-v* python-v* sql-v* iac-v* lint-configs-v* tsconfig-v*"

# Lefthook must be installed before the first commit, so hooks come first.
setup:
	./scripts/install-lefthook.sh
	cd packages/python       && uv sync --frozen
	cd packages/sql          && uv sync --frozen
	cd packages/iac          && uv sync --frozen
	cd packages/lint-configs && uv sync --frozen
	cd packages/typescript   && npm install --no-audit --no-fund

# The gate CONTRIBUTING/CLAUDE.md tells contributors to run before review. It did
# not exist, so `make verify` failed with "No rule to make target" and the
# documented workflow could not be followed as written.
verify: lint typecheck test

promote-strict:
	@echo "Promoting all warning-level standards to errors globally..."
	@sed -i '' 's/: "warn"/: "error"/g' $(CONFIG_SRC)/eslint.strict.mjs
	@echo "Done."

build:
	cd packages/typescript     && npm run build
	cd packages/python         && uv build --wheel --sdist
	cd packages/sql            && uv build --wheel --sdist
	cd packages/iac            && uv build --wheel --sdist
	cd packages/lint-configs   && uv build --wheel --sdist

test: check-versions-synced
	cd packages/typescript     && npm test
	cd packages/python         && uv run pytest -q
	cd packages/sql            && uv run pytest -q
	cd packages/iac            && uv run pytest -q
	# Sibling wheels are built and installed alongside, mirroring lint-configs-ci.yml.
	# `sarj-lint-configs` pins its siblings exactly, so resolving them from PyPI fails
	# for the whole window between bumping a pin and publishing that version -- which
	# is exactly when this target most needs to run. Building them locally keeps
	# `make test` usable on a version-bump branch.
	cd packages/lint-configs   && rm -rf dist \
	  && uv build --wheel >/dev/null \
	  && uv build --wheel --project ../python --out-dir dist/deps >/dev/null \
	  && uv build --wheel --project ../sql    --out-dir dist/deps >/dev/null \
	  && uv build --wheel --project ../iac    --out-dir dist/deps >/dev/null \
	  && uv pip install --quiet --reinstall ./dist/deps/*.whl ./dist/sarj_lint_configs-*.whl \
	  && uv run --no-project pytest -q tests/
	cd packages/tsconfig       && node -e "JSON.parse(require('fs').readFileSync('base.json','utf8'))" && node -e "JSON.parse(require('fs').readFileSync('strict.json','utf8'))"

# Dogfooding: every package is linted/formatted by this repo's own strict config.
lint:
	cd packages/python         && uv run ruff check src/ tests/
	cd packages/sql            && uv run ruff check src/ tests/
	cd packages/iac            && uv run ruff check src/ tests/
	cd packages/lint-configs   && uv run ruff check src/ tests/

typecheck:
	cd packages/python         && uv run basedpyright
	cd packages/sql            && uv run basedpyright
	cd packages/iac            && uv run basedpyright
	cd packages/lint-configs   && uv run basedpyright
	cd packages/typescript     && npm run typecheck

# There is exactly ONE copy of each strict config, in $(CONFIG_SRC); every package
# extends it by relative path. The repo used to keep a second, `cp`-synced copy at
# the root for packages to extend, which bought nothing (the two were identical by
# construction) and cost a sync target, a check target, a CI workflow and a class
# of "out of sync" failure that fired whenever the two drifted by a single edit.
#
# What remains here is the version check that lived alongside them, which is a
# genuinely different invariant: pre-commit consumers install the ROOT package, so
# a root version lagging packages/python ships a stale linter under a fresh number.
check-versions-synced:
	@root=$$(grep -m1 '^version' pyproject.toml) && pkg=$$(grep -m1 '^version' packages/python/pyproject.toml) && [ "$$root" = "$$pkg" ] || { echo "error: root pyproject.toml version out of sync with packages/python (pre-commit consumers install the root package)"; exit 1; }
	@echo "root and package versions agree ✓"

publish-typescript:
	@test -n "$$NPM_TOKEN" || (echo "error: NPM_TOKEN unset"; exit 1)
	cd packages/typescript && npm publish --access public

publish-python:
	cd packages/python && uv build --wheel --sdist && uv publish

publish-sql:
	cd packages/sql && uv build --wheel --sdist && uv publish

publish-iac:
	cd packages/iac && uv build --wheel --sdist && uv publish

publish-lint-configs:
	cd packages/lint-configs && uv build --wheel --sdist && uv publish

publish-tsconfig:
	@test -n "$$NPM_TOKEN" || (echo "error: NPM_TOKEN unset"; exit 1)
	cd packages/tsconfig && npm publish --access public

publish: publish-typescript publish-python publish-sql publish-iac publish-lint-configs publish-tsconfig
