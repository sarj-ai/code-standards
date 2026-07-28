# sarj-ai/standards

The single home for Sarj code standards, in two complementary layers:

- **Machine-enforced floor** — deterministic AST lint rules + maximally-strict configs for TypeScript + Python + SQL (`@sarj/eslint-plugin`, `sarj-python-lint`, `sarj-sql-lint`, `sarj-iac-lint`, `sarj-lint-configs`). Run automatically in CI.
- **Judgment & Audit layer** — the `sarj-audit` Claude Code plugin: on-demand audit commands for standards, architectural, security, atomicity, and test strategy evaluation that complement or extend deterministic linters.

## Claude Code plugin (`sarj-audit`)

This repo is a Claude Code plugin marketplace. To roll the audit commands out to a whole repo's team, commit this to the repo's `.claude/settings.json` — Claude Code then prompts each engineer once (on folder trust) to install the marketplace and enables the plugin:

```json
{
  "extraKnownMarketplaces": {
    "sarj": {
      "source": { "source": "github", "repo": "sarj-ai/standards" }
    }
  },
  "enabledPlugins": {
    "sarj-audit@sarj": true
  }
}
```

For a one-off personal install instead:

```
/plugin marketplace add sarj-ai/standards
/plugin install sarj-audit@sarj
```

### Audit Commands

- **`/sarj-audit:stepdown`** — Audits codebase for violations of the Stepdown Rule (newspaper metaphor: public API at top, helpers below callers).
- **`/sarj-audit:system-architecture`** — High-density audit of service layer boundaries, layer directionality, DI / inversion of control, client→server & app→database logic pushdown, DTO entity leakage, sync-to-async queue offloading, and data contract tiers.
- **`/sarj-audit:security-and-atomicity`** — High-density audit of multi-tenant isolation & IDOR prevention, RBAC role enforcement, server-derived session identity, TOCTOU race conditions, multi-write transaction boundaries, external network calls inside DB transactions, and idempotent retry keys.
- **`/sarj-audit:testing-and-modernization`** — High-density audit of test fidelity & mock architecture (4-tier hierarchy promoting `AsyncMock` over-mocking to fakes/DB container fixtures) and identifies complex hand-rolled code candidates for replacement with mature third-party libraries or modern stdlib features.
- **`/sarj-audit:stack-detection`** — Shared stack-aware Phase-0 detection pass (detects framework, database, ORM, linter authority, tenancy model, and DI conventions before running audits).
- **Granular Audit Suite**: `/sarj-audit:authn-and-authz`, `/sarj-audit:client-server-boundary`, `/sarj-audit:concurrency-and-performance`, `/sarj-audit:data-contracts`, `/sarj-audit:database-schemas-and-migrations`, `/sarj-audit:dead-and-duplicate-code`, `/sarj-audit:decouple-components-with-di`, `/sarj-audit:error-handling`, `/sarj-audit:externalize-configuration-and-secrets`, `/sarj-audit:idempotency-and-atomicity`, `/sarj-audit:libraries`, `/sarj-audit:linting`, `/sarj-audit:magic-values`, `/sarj-audit:observability`, `/sarj-audit:readability-and-naming`, `/sarj-audit:service-layer`, `/sarj-audit:stack`, `/sarj-audit:strengthen-ci-cd-and-tooling`, `/sarj-audit:test-quality-and-strategy`, `/sarj-audit:zod-types`.

The plugin lives in [`plugins/sarj-audit/`](plugins/sarj-audit/); [`commands/stack-detection.md`](plugins/sarj-audit/commands/stack-detection.md) is the shared stack-aware Phase-0 the audits gate on.

## How to use (lint rules)

| Tool | Add this |
|---|---|
| **ESLint** | `pnpm add -D @sarj/eslint-plugin` → use `packages/lint-configs/src/sarj_lint_configs/configs/eslint.strict.mjs` directly |
| **ruff** | `uv add --dev sarj-lint-configs` → `uv run sarj-lint-configs sync --only ruff` → `[tool.ruff] extend = ".ruff-strict.toml"` |
| **pyright** | `uv run sarj-lint-configs sync --only pyright` → in `pyrightconfig.json`: `{"extends": ".pyright-strict.json"}` |
| **pre-commit (Python)** | `repo: https://github.com/sarj-ai/standards, rev: python-v0.2.0` |
| **pre-commit (SQL)** | `repo: https://github.com/sarj-ai/standards, rev: sql-v0.1.0` |

## Where things live

| Source | Published as |
|---|---|
| [`packages/typescript/`](packages/typescript/) | `@sarj/eslint-plugin` on [npm](https://www.npmjs.com/package/@sarj/eslint-plugin) |
| [`packages/python/`](packages/python/) | `sarj-python-lint` on [PyPI](https://pypi.org/project/sarj-python-lint/) |
| [`packages/sql/`](packages/sql/) | `sarj-sql-lint` on [PyPI](https://pypi.org/project/sarj-sql-lint/) |
| [`packages/iac/`](packages/iac/) | `sarj-iac-lint` on [PyPI](https://pypi.org/project/sarj-iac-lint/) |
| [`packages/lint-configs/`](packages/lint-configs/) | `sarj-lint-configs` on [PyPI](https://pypi.org/project/sarj-lint-configs/) |
| [`plugins/sarj-audit/`](plugins/sarj-audit/) | `sarj-audit` Claude Code plugin (install via `/plugin marketplace add sarj-ai/standards`) |

## Release

Tag and push — the `release.yml` workflow handles publish via OIDC (PyPI) and `NPM_TOKEN` (npm).

| Tag pattern | Publishes |
|---|---|
| `typescript-vX.Y.Z` | `@sarj/eslint-plugin` to npm |
| `python-vX.Y.Z` | `sarj-python-lint` to PyPI |
| `sql-vX.Y.Z` | `sarj-sql-lint` to PyPI |
| `iac-vX.Y.Z` | `sarj-iac-lint` to PyPI |
| `lint-configs-vX.Y.Z` | `sarj-lint-configs` to PyPI |

```bash
git tag python-v0.2.0 && git push --tags
```

Local fallback: `NPM_TOKEN=... make publish`.

Each rule is self-documenting via its source file. MIT.
