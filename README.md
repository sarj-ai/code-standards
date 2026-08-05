# sarj-ai/standards

The single home for Sarj code standards, in two layers:

- **Machine-enforced floor** — lint rules + maximally-strict configs for TypeScript + Python + SQL + Terraform (`@sarj/eslint-plugin`, `sarj-python-lint`, `sarj-sql-lint`, `sarj-iac-lint`, `sarj-lint-configs`). Run in CI.
- **Judgment layer** — the `sarj-audit` Claude Code plugin: on-demand audit commands for the things that can't be reliably linted. Each audit cites the deterministic rule that backs it where one exists. (Merged here from a retired first-party repo.)

## Contributor setup

Run `make setup` once after cloning. It installs Lefthook 2.1.10 before package
dependencies, so commits receive the same lint, typecheck, and test
feedback as CI. Coding agents must repair reported failures rather than bypassing
hooks. Run `make verify` before requesting review.

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

Then run any audit, e.g. `/sarj-audit:data-contracts` or `/sarj-audit:concurrency-and-performance`. The plugin lives in [`plugins/sarj-audit/`](plugins/sarj-audit/); [`commands/stack-detection.md`](plugins/sarj-audit/commands/stack-detection.md) is the shared stack-aware Phase-0 the audits gate on, and [`skills/`](plugins/sarj-audit/skills/) ships the lint-rule authoring and ratcheting skills alongside it — they used to sit in a top-level `skills/` directory that nothing loaded them from.

## Adopt

```bash
uvx --from sarj-lint-configs sarj-standards init
```

`init` detects whether the repo is Python, TypeScript or both; installs the
toolchain and hooks; syncs only the
configs that ecosystem uses; wires them into `pyproject.toml`,
`pyrightconfig.json` and `eslint.config.mjs`; writes a pre-commit block; records
the adopted version in `.sarj-standards.toml`; and prints the CI snippet plus, for
TypeScript, the exact peer set whose versions resolve together. `--dry-run`
shows the plan first, `--no-install` only writes the wiring, and nothing existing
is overwritten without `--force`.

Deliberately no version literal above. Pinning a version in prose is how the
previous instructions came to pin `sarj-lint-configs` at 0.10.0 five minor
versions after 0.10.0, and to name a peer floor of `@sarj/eslint-plugin` 2.16.0
for a config that needed 2.17.0 or newer — anyone who followed them got a stale
toolchain or a broken config. `uv add` resolves the current version; `.sarj-standards.toml` records it;
`doctor` proves everything else agrees. Both READMEs are now asserted against the
shipping versions by a test, so this section cannot rot silently again.

## Daily use

Use the launcher printed by `init`; it reflects where the bundle was installed:

| Repository shape | Launcher prefix |
|---|---|
| Python project at the root | `uv run --frozen` |
| Python project in `backend/` | `uv run --project backend --frozen` |
| TypeScript-only repository | `uvx --from sarj-lint-configs==<manifest version>` |

The examples below show the root-Python form. Keep the command after the prefix
the same for other layouts.

| Command | Answers |
|---|---|
| `uv run --frozen sarj-standards check` | Run version, config, custom-rule, Ruff, BasedPyright, and ESLint gates. |
| `uv run --frozen sarj-standards fix` | Format Python and apply safe Ruff and ESLint fixes. |
| `uv run --frozen sarj-standards doctor` | Diagnose drift and print exact remediation. |
| `uv run --frozen sarj-standards update --check` | Preview a coherent toolchain update. |
| `uv run --frozen sarj-standards show state` | Show the detected adoption as JSON. |

For TypeScript, `sarj-standards show peers` (with the init-generated launcher) prints every npm package
`eslint.strict.mjs` needs at versions that install together — there is no
`@latest` combination that does.

See [`packages/lint-configs/README.md`](packages/lint-configs/README.md) for how
to extend the configs without forking them, polyglot destination routing, and the
generated pre-commit block.

## Where things live

| Source | Published as |
|---|---|
| [`packages/typescript/`](packages/typescript/) | `@sarj/eslint-plugin` on [npm](https://www.npmjs.com/package/@sarj/eslint-plugin) |
| [`packages/python/`](packages/python/) | `sarj-python-lint` on [PyPI](https://pypi.org/project/sarj-python-lint/) |
| [`packages/sql/`](packages/sql/) | `sarj-sql-lint` on [PyPI](https://pypi.org/project/sarj-sql-lint/) |
| [`packages/iac/`](packages/iac/) | `sarj-iac-lint` on [PyPI](https://pypi.org/project/sarj-iac-lint/) |
| [`packages/lint-configs/`](packages/lint-configs/) | `sarj-lint-configs` on [PyPI](https://pypi.org/project/sarj-lint-configs/) |
| [`packages/tsconfig/`](packages/tsconfig/) | `@sarj/tsconfig` on [npm](https://www.npmjs.com/package/@sarj/tsconfig) |
| [`plugins/sarj-audit/`](plugins/sarj-audit/) | `sarj-audit` Claude Code plugin (install via `/plugin marketplace add sarj-ai/standards`) |

## Release

Normal releases are triggered by merging a manifest version bump to `main`;
`release.yml` publishes via OIDC, then creates the matching version tag.
Manual tagging is an exceptional recovery workflow.

| Tag pattern | Publishes |
|---|---|
| `typescript-vX.Y.Z` | `@sarj/eslint-plugin` to npm |
| `python-vX.Y.Z` | `sarj-python-lint` to PyPI |
| `sql-vX.Y.Z` | `sarj-sql-lint` to PyPI |
| `iac-vX.Y.Z` | `sarj-iac-lint` to PyPI |
| `lint-configs-vX.Y.Z` | `sarj-lint-configs` to PyPI |
| `tsconfig-vX.Y.Z` | `@sarj/tsconfig` to npm |

For a rule release, keep the change atomic: update the implementation, registry,
strict config and tests; bump the owning package manifest; update its generated
lockfile; and, for Python/SQL/IaC rules, bump the exact dependency and version of
`sarj-lint-configs`. Run `make verify`. The release workflow
then publishes and tags every changed package. Consumer repositories run
`sarj-standards doctor` and `update --configs-only --check` in CI, so a new release cannot
silently leave them stale.

Adding an npm import to `eslint.strict.mjs` also means adding its pin to
`eslint.peers.json` and to `packages/typescript`'s devDependencies — a test fails
otherwise, and `packages/typescript` installing that exact set is what proves the
set resolves and that ESLint can load the config.

Local fallback: `NPM_TOKEN=... make publish`.

Each rule is self-documenting via its source file. MIT.
