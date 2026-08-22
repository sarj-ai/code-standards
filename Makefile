SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules

CONFIG_SRC := packages/standards/src/sarj_standards/configs
STANDARDS := uv run --project packages/standards --frozen code-standards
ROLLOUT := uv run --project packages/standards --frozen python -m sarj_standards.libs.release.rollout
VERSION ?=
CHANNEL ?= stable
REGISTRY ?= .sarj-standards-rollout.toml

.PHONY: help setup build verify doctor docs-artifacts-check docs-code-sync docs-check test lint dogfood dogfood-python dogfood-typescript format-check typecheck repo-check check-no-private-refs check-file-conventions check-versions-synced release-check release-check-lock-age release-check-tags release-check-typescript sync-rule-ledger rollout

help:
	@echo "Targets: setup | verify | doctor | build | test | lint | dogfood | typecheck"
	@echo "         check-{versions-synced,no-private-refs,file-conventions} | release-check"
	@echo "         rollout VERSION=<published-version>"
	@echo "Releases are published only after a version-changing merge to main."

rollout:
	@test -n "$(VERSION)" || { echo "usage: make rollout VERSION=<published-version>" >&2; exit 2; }
	$(ROLLOUT) --registry "$(REGISTRY)" plan --version "$(VERSION)" --channel "$(CHANNEL)"
	$(ROLLOUT) --registry "$(REGISTRY)" apply --version "$(VERSION)" --channel "$(CHANNEL)"
	$(ROLLOUT) --registry "$(REGISTRY)" status --version "$(VERSION)" --channel "$(CHANNEL)"

setup:
	$(STANDARDS) --root . maintain setup

# Canonical local gate; CI runs the same checks.
verify: doctor docs-check format-check lint dogfood typecheck test repo-check check-no-private-refs

doctor:
	@$(STANDARDS) doctor

docs-artifacts-check:
	@$(STANDARDS) --root . maintain rules check
	@$(STANDARDS) --root . maintain catalog check
	@$(STANDARDS) --root . maintain cli-reference check
	@$(STANDARDS) --root . maintain docs check

docs-code-sync:
	cd apps/docs && npm run code-examples:sync

docs-check: docs-artifacts-check
	cd packages/typescript && npm run build
	cd apps/docs && npm run code-examples:check
	cd apps/docs && npm run lint && npm run check && npm run build

format-check:
	uv run --project packages/standards --frozen ruff format --check \
	  packages/bootstrap/src packages/bootstrap/tests \
	  packages/python/src packages/python/tests \
	  packages/sql/src packages/sql/tests \
	  packages/iac/src packages/iac/tests \
	  packages/standards/src packages/standards/tests

build:
	cd packages/typescript     && npm run build
	cd apps/docs               && npm run build
	cd packages/bootstrap      && uv build
	cd packages/python         && uv build
	cd packages/sql            && uv build
	cd packages/iac            && uv build
	cd packages/standards   && uv build
	cd packages/standards-compat && uv build

test: check-versions-synced
	cd packages/typescript     && npm test
	cd packages/bootstrap      && uv run pytest -q
	cd packages/python         && uv run pytest -q
	cd packages/sql            && uv run pytest -q
	cd packages/iac            && uv run pytest -q
	# Sibling wheels are built and installed alongside, mirroring standards-ci.yml.
	# `code-standards` pins its siblings exactly, so resolving them from PyPI fails
	# for the whole window between bumping a pin and publishing that version -- which
	# is exactly when this target most needs to run. Building them locally keeps
	# `make test` usable on a version-bump branch.
	cd packages/standards   && rm -rf dist \
	  && uv build --wheel >/dev/null \
	  && uv build --wheel --project ../python --out-dir dist/deps >/dev/null \
	  && uv build --wheel --project ../sql    --out-dir dist/deps >/dev/null \
	  && uv build --wheel --project ../iac    --out-dir dist/deps >/dev/null \
	  && uv venv --quiet --clear dist/test-venv \
	  && uv pip install --quiet --python dist/test-venv/bin/python pytest==9.1.1 'jsonschema>=4.26,<5' ./dist/deps/*.whl ./dist/code_standards-*.whl \
	  && dist/test-venv/bin/python -m pytest -q tests/
	cd packages/tsconfig       && node -e "JSON.parse(require('fs').readFileSync('base.json','utf8'))" && node -e "JSON.parse(require('fs').readFileSync('strict.json','utf8'))"

# Each package runs its native type-aware lint gate.
lint:
	cd packages/typescript     && npm run lint
	cd packages/bootstrap      && uv run ruff check src/ tests/
	cd packages/python         && uv run ruff check src/ tests/
	cd packages/sql            && uv run ruff check src/ tests/
	cd packages/iac            && uv run ruff check src/ tests/
	cd packages/standards   && uv run ruff check src/ tests/
	# `standards-ci.yml` runs the custom SARJ rules over this package and
	# `make lint` did not, so a change could pass `make verify` locally and fail
	# CI on rules this repo wrote. Dogfooding that stops at ruff is not dogfooding.
	uv run --project packages/standards --frozen code-standards --root . check \
	  packages/standards/src packages/standards/tests

# Run every shipped custom rule over maintained implementation and test source.
# Only dedicated fixture directories are excluded from the TypeScript scan.
# The registries are read at execution time, so adding a rule automatically adds
# it to this gate without another hand-maintained list.
dogfood: dogfood-python dogfood-typescript

dogfood-python:
	@python_files=(); \
	while IFS= read -r -d '' file; do python_files+=("$$file"); done < <(git ls-files -z --cached --others --exclude-standard -- 'packages/*/src/*.py' 'packages/*/src/**/*.py' 'packages/*/tests/*.py' 'packages/*/tests/**/*.py'); \
	python_rules=(); \
	while IFS= read -r rule; do python_rules+=("$$rule"); done < <(uv run --quiet --project packages/python --frozen sarj-python-lint list-rules | awk '{print $$2}'); \
	if (( $${#python_files[@]} == 0 || $${#python_rules[@]} == 0 )); then echo 'dogfood: Python source or registry is unexpectedly empty' >&2; exit 2; fi; \
	rule_args=(); \
	for rule in "$${python_rules[@]}"; do rule_args+=(--rule "$$rule"); done; \
	set +e; \
	output="$$(uv run --quiet --project packages/python --frozen sarj-python-lint check "$${rule_args[@]}" -- "$${python_files[@]}" 2>&1)"; \
	status=$$?; \
	set -e; \
	if (( status > 1 )); then printf '%s\n' "$$output"; exit $$status; fi; \
	if [[ -n "$$output" ]]; then printf '%s\n' "$$output"; exit 1; fi; \
	if (( status != 0 )); then exit $$status; fi; \
	printf 'dogfood: %d Python rules, %d source files, 0 diagnostics\n' "$${#python_rules[@]}" "$${#python_files[@]}"

dogfood-typescript:
	cd packages/typescript && npm run dogfood

typecheck:
	cd packages/bootstrap      && uv run basedpyright
	cd packages/python         && uv run basedpyright
	cd packages/sql            && uv run basedpyright
	cd packages/iac            && uv run basedpyright
	cd packages/standards   && uv run basedpyright
	cd packages/typescript     && npm run typecheck

check-no-private-refs:
	@if test -f .sarj-private-refs.toml; then \
	  $(STANDARDS) --root . maintain check --only private-refs --only ci-history; \
	else \
	  echo "private-reference scan delegated to trusted CI"; \
	fi

# Filename casing, rule<->test pairing, markdown placement, and strict-config
# ownership. Setup synchronizes the root `.ruff-strict.toml` and
# `.pyright-strict.json` from $(CONFIG_SRC); packages extend the root copies so
# Ruff anchors `per-file-ignores` at the repository root. The gate rejects drift
# and additional copies.
# Regenerate the shipped record of every rule identifier and what became of it.
# It never deletes: a rule that leaves a registry is moved to `retired`, because
# a consumer config naming a removed rule makes ESLint exit 2 on the whole repo
# and `doctor` needs the record to warn before the upgrade rather than after.
sync-rule-ledger:
	@$(STANDARDS) --root . maintain sync-ledger

check-file-conventions:
	@$(STANDARDS) --root . maintain check --only file-conventions

# Every one of the 21 places a version is written, not just the two this target
# used to compare. Pre-commit consumers install the ROOT package, so a root
# version lagging packages/python ships a stale linter under a fresh number --
# but that was the only case covered, which is why #183 could bump
# `packages/typescript/package.json` and leave `package-lock.json` two minor
# versions behind, and why the root `uv.lock` sat two versions stale on main.
check-versions-synced:
	@$(STANDARDS) --root . maintain check --only versions

repo-check:
	@$(STANDARDS) --root . maintain check

# Exercise the immutable artifact that a release would publish. This deliberately
# installs from the lockfile and packs to a temporary directory: local release
# checks cannot accidentally bless a stale ignored `dist/` tree or leave a
# publishable tarball behind in the repository.
release-check: check-versions-synced release-check-lock-age release-check-tags release-check-typescript

release-check-lock-age:
	$(STANDARDS) --root . maintain release lock-age packages/typescript/package-lock.json --minimum-days 0 --exclude-file .github/release-age-exclusions.txt

release-check-tags:
	$(STANDARDS) --root . maintain release check-tag typescript-v$$(node -p "require('./packages/typescript/package.json').version")
	! $(STANDARDS) --root . maintain release check-tag typescript-v0.0.0

release-check-typescript:
	$(STANDARDS) --root . maintain release typescript check
