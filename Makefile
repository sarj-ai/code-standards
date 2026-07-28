SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
MAKEFLAGS += --warn-undefined-variables --no-builtin-rules

CONFIG_SRC := packages/lint-configs/src/sarj_lint_configs/configs

.PHONY: help build test lint typecheck sync-configs check-configs-synced \
        publish publish-typescript publish-python publish-sql publish-iac \
        publish-lint-configs publish-tsconfig

help:
	@echo "Targets: build | test | lint | typecheck | sync-configs | check-configs-synced | promote-strict"
	@echo "         publish-{typescript,python,sql,iac,lint-configs,tsconfig} | publish (all)"
	@echo "Releases trigger via tag push: typescript-v* python-v* sql-v* iac-v* lint-configs-v* tsconfig-v*"

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

test: check-configs-synced
	cd packages/typescript     && npm test
	cd packages/python         && uv run pytest -q
	cd packages/sql            && uv run pytest -q
	cd packages/iac            && uv run pytest -q
	cd packages/lint-configs   && uv build --wheel >/dev/null && uv pip install --quiet --reinstall ./dist/*.whl && uv run --no-project pytest -q tests/
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

# Root .ruff-strict.toml / .pyright-strict.json are the synced consumer artifacts the
# packages extend; they must stay byte-identical to the published source of truth.
sync-configs:
	cp $(CONFIG_SRC)/ruff.strict.toml    .ruff-strict.toml
	cp $(CONFIG_SRC)/pyright.strict.json .pyright-strict.json

check-configs-synced:
	@cmp -s $(CONFIG_SRC)/ruff.strict.toml    .ruff-strict.toml    || { echo "error: .ruff-strict.toml out of sync — run 'make sync-configs'"; exit 1; }
	@cmp -s $(CONFIG_SRC)/pyright.strict.json .pyright-strict.json || { echo "error: .pyright-strict.json out of sync — run 'make sync-configs'"; exit 1; }
	@root=$$(grep -m1 '^version' pyproject.toml) && pkg=$$(grep -m1 '^version' packages/python/pyproject.toml) && [ "$$root" = "$$pkg" ] || { echo "error: root pyproject.toml version out of sync with packages/python (pre-commit consumers install the root package)"; exit 1; }
	@echo "root configs in sync with source ✓"

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
