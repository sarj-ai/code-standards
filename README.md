# sarj-ai/standards

The single home for Sarj code standards, in two layers:

- **Machine-enforced floor** — lint rules + maximally-strict configs for TypeScript + Python + SQL (`@sarj/eslint-plugin`, `sarj-python-lint`, `sarj-sql-lint`, `sarj-lint-configs`). Run in CI.
- **Judgment layer** — the `sarj-audit` Claude Code plugin: on-demand audit commands for the things that can't be reliably linted. Each audit cites the deterministic rule that backs it where one exists. (Merged here from the retired `sarj-ai/agentic` repo.)

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

Then run any audit, e.g. `/sarj-audit:data-contracts` or `/sarj-audit:concurrency-and-performance`. The plugin lives in [`plugins/sarj-audit/`](plugins/sarj-audit/); [`commands/stack-detection.md`](plugins/sarj-audit/commands/stack-detection.md) is the shared stack-aware Phase-0 the audits gate on.

## How to use (lint rules)

| Tool | Add this |
|---|---|
| **All strict configs** | `uv add --dev sarj-lint-configs==0.9.0` → `uv run --frozen sarj-lint-configs sync --force` |
| **Python / SQL / IaC rules** | `uv run --frozen sarj-lint-configs check .` |
| **ESLint rules** | `pnpm add -D --save-exact @sarj/eslint-plugin@2.16.0` → import the synced `eslint.strict.mjs` |
| **Config drift in CI** | `uv run --frozen sarj-lint-configs sync --check` |

See [`packages/lint-configs/README.md`](packages/lint-configs/README.md) for
polyglot destination routing and the recommended Lefthook jobs.

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

Normal releases are triggered by merging a manifest version bump to `main`;
the workflow publishes the changed package and creates its matching version tag.

Local fallback: `NPM_TOKEN=... make publish`.

Each rule is self-documenting via its source file. MIT.
