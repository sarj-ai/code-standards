SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules

CONFIG_SRC := packages/lint-configs/src/sarj_lint_configs/configs
STANDARDS := uv run --project packages/lint-configs --frozen sarj-standards

.PHONY: help setup build verify test lint format-check typecheck repo-check check-no-private-refs check-file-conventions promote-strict check-versions-synced publish publish-typescript publish-python publish-sql \
        publish-iac publish-lint-configs publish-tsconfig sync-rule-ledger

help:
	@echo "Targets: setup | verify | build | test | lint | typecheck | promote-strict"
	@echo "         check-{versions-synced,no-private-refs,file-conventions}"
	@echo "         publish-{typescript,python,sql,iac,lint-configs,tsconfig} | publish (all)"
	@echo "Releases trigger via tag push: typescript-v* python-v* sql-v* iac-v* lint-configs-v* tsconfig-v*"

# Lefthook must be installed before the first commit, so hooks come first.
setup:
	uv sync --project packages/lint-configs --frozen
	packages/lint-configs/.venv/bin/sarj-standards repo hooks install --dest .
	cd packages/python       && uv sync --frozen
	cd packages/sql          && uv sync --frozen
	cd packages/iac          && uv sync --frozen
	cd packages/lint-configs && uv sync --frozen
	cd packages/typescript   && npm install --no-audit --no-fund

# The gate CONTRIBUTING/CLAUDE.md tells contributors to run before review. It did
# not exist, so `make verify` failed with "No rule to make target" and the
# documented workflow could not be followed as written.
verify: format-check lint typecheck test repo-check

format-check:
	uv run --project packages/lint-configs --frozen ruff format --check \
	  packages/python/src packages/python/tests \
	  packages/sql/src packages/sql/tests \
	  packages/iac/src packages/iac/tests \
	  packages/lint-configs/src packages/lint-configs/tests

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
	cd packages/typescript     && npm run lint
	cd packages/python         && uv run ruff check src/ tests/
	cd packages/sql            && uv run ruff check src/ tests/
	cd packages/iac            && uv run ruff check src/ tests/
	cd packages/lint-configs   && uv run ruff check src/ tests/
	# `lint-configs-ci.yml` runs the custom SARJ rules over this package and
	# `make lint` did not, so a change could pass `make verify` locally and fail
	# CI on rules this repo wrote. Dogfooding that stops at ruff is not dogfooding.
	cd packages/lint-configs   && uv run sarj-lint-configs check src/ tests/

typecheck:
	cd packages/python         && uv run basedpyright
	cd packages/sql            && uv run basedpyright
	cd packages/iac            && uv run basedpyright
	cd packages/lint-configs   && uv run basedpyright
	cd packages/typescript     && npm run typecheck

check-no-private-refs:
	@$(STANDARDS) repo check --only private-refs --only ci-history

# Filename casing, rule<->test pairing, markdown placement, and the ONE-copy rule
# for the strict configs in $(CONFIG_SRC). The root `.ruff-strict.toml` /
# `.pyright-strict.json` are SYMLINKS into that directory and must stay symlinks:
# ruff anchors `per-file-ignores` globs at the directory of the config that
# declares them, so pointing a package at the canonical path directly silently
# drops the whole `"**/tests/**"` exemption -- 239 new findings in packages/python
# alone. A `cp` in place of either link does the same job and then drifts.
# Regenerate the shipped record of every rule identifier and what became of it.
# It never deletes: a rule that leaves a registry is moved to `retired`, because
# a consumer config naming a removed rule makes ESLint exit 2 on the whole repo
# and `doctor` needs the record to warn before the upgrade rather than after.
sync-rule-ledger:
	@$(STANDARDS) repo sync-ledger

check-file-conventions:
	@$(STANDARDS) repo check --only file-conventions

# Every one of the 21 places a version is written, not just the two this target
# used to compare. Pre-commit consumers install the ROOT package, so a root
# version lagging packages/python ships a stale linter under a fresh number --
# but that was the only case covered, which is why #183 could bump
# `packages/typescript/package.json` and leave `package-lock.json` two minor
# versions behind, and why the root `uv.lock` sat two versions stale on main.
check-versions-synced:
	@$(STANDARDS) repo check --only versions

repo-check:
	@$(STANDARDS) repo check

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
