SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules

CONFIG_SRC := packages/lint-configs/src/sarj_lint_configs/configs
STANDARDS := uv run --project packages/lint-configs --frozen sarj-standards

.PHONY: help setup build verify doctor test lint format-check typecheck repo-check check-no-private-refs check-file-conventions check-versions-synced release-check release-check-lock-age release-check-tags release-check-typescript sync-rule-ledger

help:
	@echo "Targets: setup | verify | doctor | build | test | lint | typecheck"
	@echo "         check-{versions-synced,no-private-refs,file-conventions} | release-check"
	@echo "Releases are published only after a version-changing merge to main."

setup:
	$(STANDARDS) repo setup --dest .

# The gate CONTRIBUTING/CLAUDE.md tells contributors to run before review. It did
# not exist, so `make verify` failed with "No rule to make target" and the
# documented workflow could not be followed as written.
verify: doctor format-check lint typecheck test repo-check check-no-private-refs

doctor:
	@$(STANDARDS) doctor

format-check:
	uv run --project packages/lint-configs --frozen ruff format --check \
	  packages/python/src packages/python/tests \
	  packages/sql/src packages/sql/tests \
	  packages/iac/src packages/iac/tests \
	  packages/lint-configs/src packages/lint-configs/tests

build:
	cd packages/typescript     && npm run build
	cd packages/python         && uv build --wheel
	cd packages/sql            && uv build --wheel
	cd packages/iac            && uv build --wheel
	cd packages/lint-configs   && uv build --wheel

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

# Each package runs its native type-aware lint gate.
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
	@if test -f .sarj-private-refs.toml; then \
	  $(STANDARDS) repo check --only private-refs --only ci-history; \
	else \
	  echo "private-reference scan delegated to trusted CI"; \
	fi

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

# Exercise the immutable artifact that a release would publish. This deliberately
# installs from the lockfile and packs to a temporary directory: local release
# checks cannot accidentally bless a stale ignored `dist/` tree or leave a
# publishable tarball behind in the repository.
release-check: check-versions-synced release-check-lock-age release-check-tags release-check-typescript

release-check-lock-age:
	$(STANDARDS) repo release lock-age packages/typescript/package-lock.json --dest . --exclude-file .github/release-age-exclusions.txt

release-check-tags:
	$(STANDARDS) repo release check-tag typescript-v$$(node -p "require('./packages/typescript/package.json').version") --dest .
	! $(STANDARDS) repo release check-tag typescript-v0.0.0 --dest .

release-check-typescript:
	$(STANDARDS) repo release typescript check --dest .
