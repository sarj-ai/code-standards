# sarj-lint-configs

Ships the maximally-strict ruff / pyright / ESLint configs from `sarj-ai/standards`
as a pip-installable package, plus the commands that adopt them and keep them current.

## Adopt

```bash
uv add --dev sarj-lint-configs
uv run --frozen sarj-lint-configs init
```

`init` detects Python and/or TypeScript, writes only the configs that ecosystem
uses, wires them up (`[tool.ruff] extend`, `pyrightconfig.json`,
`eslint.config.mjs`), writes a pre-commit block, records the adopted version in
`.sarj-standards.toml`, and prints the CI snippet and — for TypeScript — the one
`npm install` command that gets the ESLint peers right.

`init --dry-run` prints the whole plan without touching anything. `init` never
overwrites a file that already exists unless you pass `--force`, so it is safe to
re-run and safe on a repo that is already half-adopted.

### Your TypeScript does not have to be at the repo root

`init` writes each ecosystem's configs into the directory that owns it, not into
the repo root: the ESLint config goes beside the npm lockfile, the ruff and
pyright configs beside the `pyproject.toml`. That is not cosmetic. A repo whose
TypeScript lives in `frontend/` has no `node_modules` and no `tsconfig.json` at
its root, and ESLint does not search upward for a flat config — a root-level
`eslint.config.mjs` is a file that can never load, written by a tool that reports
success.

The project root is found by **lockfile**, not by `package.json`: a repo can carry
a root `package.json` declaring nothing but `packageManager` while the real
project is a directory down.

The detected destinations are recorded in `.sarj-standards.toml`, so plain `sync`
and `sync --check` find them again without CI having to restate them. Override
detection with `init --python-dest` / `--typescript-dest`.

### npm, pnpm, Yarn and Bun

The peer set below does not install without an override block, and every client
spells that block differently: npm and Bun nest it under `overrides`, pnpm wants
`pnpm.overrides` with a `parent>child` selector, Yarn wants `resolutions` with a
`parent/child` path and no `$dep` indirection. `init` detects the client from the
lockfile (or a `packageManager` field, which Corepack enforces), writes the right
one, and prints the matching install command. Writing npm's spelling everywhere
was worse than writing nothing: pnpm and Yarn ignore a stray `overrides` key, so
the install failed identically while `package.json` looked fixed.

## Keep current

```bash
uv run --frozen sarj-standards doctor       # every version pin agrees?
uv run --frozen sarj-standards sync --check # the synced configs are unmodified?
uv run --frozen sarj-standards check .      # every custom code/config/text rule passes?
uv run --frozen sarj-standards check --noise-only .  # comment/artifact ratchet only
```

Run all three in CI. `init` prints them as a ready-made job.
`check --noise-only` covers Python and text/config inputs; TypeScript comment
noise is enforced by the generated strict ESLint config.

`sarj-standards` is the preferred entrypoint. `sarj-lint-configs` remains an
alias for compatibility. `check` routes Python, SQL, Terraform, YAML/TFTPL,
TOML, JSONC, Markdown, INI-style config, environment files, shell scripts,
Dockerfile variants, Makefiles, and Justfiles in one pass. It rejects
commented-out config (`SARJ301`), dense config narration (`SARJ300`), and AI
execution diaries or briefs that should have been reduced to durable
README/docs/ADR facts (`SARJ302`).

Generated or intentionally instructional config can be excluded explicitly;
there is no blanket directory exemption:

```toml
[text]
exclude = ["examples/generated-values/**"]
```

In source code, use names, types, small functions, and data structures to carry
the explanation. One sentence of nearby rationale is clean; exactly two
sentences is a non-blocking warning; three or more is an error and should be
reduced to the local constraint or moved to an ADR/doc. Fully typed functions
must not repeat parameters or returns in docstring/JSDoc tables, while external
contracts, invariants, failures, examples, generated docs, directives,
licenses, and runtime-consumed prompt/tool/route documentation remain valid.

### `doctor` — one version, not three

A consumer repo used to state a Sarj version in three independent places: the
`pyproject.toml` pin, the pre-commit `rev:`, and whatever a CI job typed on its
own command line. Nothing compared them, so they drifted apart and stayed
drifted — a repo could run one linter version at commit time, a second in CI, and
a third locally, and pass its own build.

`doctor` finds every pin site under a repo root and checks each against the
installed wheel:

```
ok     .sarj-standards.toml  --  version 0.32.0
drift  .github/workflows/ci.yml: sarj-python-lint==0.12.2  --  installed sarj-python-lint is 0.37.0
drift  pyproject.toml: sarj-python-lint==0.25.0  --  installed sarj-python-lint is 0.37.0
ok     pyproject.toml: sarj-lint-configs==0.32.0  --  matches the installed wheel
drift  package.json: @sarj/eslint-plugin@2.16.0  --  the bundled eslint.strict.mjs is tested against 9.0.0
```

It reports; it never rewrites. Exit 1 on drift.

The sibling linter versions are not yours to pick. `sarj-lint-configs` pins
`sarj-python-lint`, `sarj-sql-lint` and `sarj-iac-lint` exactly, so `doctor`
reads them out of the wheel you already installed and derives what every other
site should say — including the pre-commit tag, which lives in a different
namespace (`python-v0.37.0` for `sarj-lint-configs` 0.32.0) that nobody should
have to translate by hand.

The block `init` writes has no `rev:` at all. A `repo: local` hook runs the CLI
from the environment your `pyproject.toml` pin already fixed, which deletes the
second pin site rather than checking it:

```yaml
repos:
  - repo: local
    hooks:
      - id: sarj-standards-drift
        name: sarj standards -- config + version drift
        entry: uv run --frozen sarj-lint-configs doctor
        language: system
        pass_filenames: false
      - id: sarj-standards-check
        name: sarj standards -- custom rules
        entry: uv run --frozen sarj-lint-configs check
        language: system
        types_or: [python, sql, yaml]
```

That is the block a **Python** repo gets. A TypeScript-only repo gets the same
hook with `uvx --from sarj-lint-configs==<version>` instead of `uv run --frozen`
— `uv run` in a repo with no `pyproject.toml` is `error: Failed to spawn:
sarj-lint-configs`, exit 2, on every commit — and no `check` hook, because
`check` runs the Python/SQL/IaC registries and a TypeScript repo has nothing to
feed them.

### Removed and renamed rules — the upgrade that crashes

Deleting a rule is not a lint-level change for the repo that uses it. A flat
config still naming it makes ESLint exit **2** before it reads a single file:

```
TypeError: Key "rules": Key "@sarj/prefer-setup-file-mocks": Could not find
"prefer-setup-file-mocks" in plugin "@sarj".
```

The whole repo stops linting. A pre-commit hook id that no longer exists fails
the same way, and because the strict config sets
`reportUnusedDisableDirectives: "error"`, every orphaned
`// eslint-disable-next-line @sarj/<removed-rule>` is an error of its own.

`rule-ledger.json` ships inside the wheel and records every rule identifier this
toolchain has ever shipped, along with what became of it. `doctor` reads it and
names every stale reference — in configs, in suppression baselines, in
pre-commit, and in ordinary source — **before** the upgrade that would break
them:

```
drift  eslint.config.mjs: @sarj/prefer-setup-file-mocks x1  --  no longer exists -- Delete the config entry and suppressions; there is no replacement.
drift  src/legacy.ts: @sarj/no-implicit-attribute-access x1  --  no longer exists -- ...
drift  .pre-commit-config.yaml: no-implicit-attribute-access x1  --  no longer exists -- removed in sarj-python-lint 0.37.0 ...
drift  .sarj-python-baseline.json: SARJ083 x1  --  no longer exists -- removed in sarj-python-lint 0.37.0 ...
drift  eslint.config.mjs: @sarj/strict-test-assertions x1  --  renamed to @sarj/prefer-whole-object-assertion -- the old name no longer resolves: @sarj/eslint-plugin 9.0.0 deleted the deprecated aliases 7.0.0 shipped ...
```

There is nothing to fall back on in any of these cases. A deleted rule, a
`SARJnnn` code that was renumbered and a rule renamed without an alias all fail
identically at load time, and the failure names the identifier but never says it
went deliberately or what replaced it. The ledger is where that is written down.

The ledger is generated by `make sync-rule-ledger`, which never deletes: a rule
that leaves a registry is *retired*, and tests in both this package and the
plugin fail until the ledger matches the live registries again. So the next
removal is recorded whether or not its author thought about consumers.

### `sync --check` — the synced configs are unmodified

Ruff cannot `extend` a config out of an installed package's path portably, which
is why `sync` writes a copy into your repo instead of you referencing one. A copy
can be edited, so `sync --check` compares each one byte-for-byte and fails CI when
it differs. One consumer's copy of the ESLint config had quietly drifted to 120
rules against a canonical 145 — missing 30, carrying 5 that no longer exist
upstream — and nothing caught it.

`sync` and `sync --check` operate on the config set in `.sarj-standards.toml`,
so a Python repo is not asked to carry an ESLint config it never wanted. That
matters: `sync --check` used to insist on all six files, report permanent drift
on the two a repo had no use for, and so never made it into anyone's CI.

**Your own settings are not clobbered, and you do not need to fork anything.**

- **Ruff.** `[tool.ruff.lint] ignore` in your `pyproject.toml` is *additive* over
  the extended file's list — verified, not assumed. Adding `ignore = ["ANN001"]`
  silences ANN001 and leaves all 43 canonical ignores in force. Put every local
  ruff decision in `pyproject.toml` and leave `.ruff-strict.toml` alone.
- **ESLint.** Your `eslint.config.mjs` spreads the synced array and appends. Flat
  config is last-wins, so an override block after `...strict` relaxes a rule,
  scopes one to a directory, or adds a framework exemption — and still receives
  every rule added upstream. `init` writes that block for you, commented, with a
  `unicorn/filename-case` example, because "the canonical config does not know
  about my framework's filenames" is the most common reason people forked it.

## ESLint peers

`eslint.strict.mjs` imports eleven npm packages, and the set does not resolve on its
own. The unicorn floor (72) pulls `eslint >= 10.4`, while `eslint-plugin-react@7.37.5`
— the newest published release — peers `eslint <= ^9.7`. **`npm install` exits
ERESOLVE**, so the config is unreachable until you add an `overrides` entry:

```json
{ "overrides": { "eslint-plugin-react": { "eslint": "$eslint" } } }
```

Following the README used to mean hitting `Cannot find package` nine times and
then that dead end, with nothing naming the escape. That is most of why
TypeScript repos vendored the file. `init` writes the block; `peers` prints it.

```bash
uv run --frozen sarj-lint-configs peers   # prints the set and one install command
```

The set is pinned in `eslint.peers.json` inside the wheel, `packages/typescript`
installs exactly it, and tests there both load the shipped config through a real
ESLint and lint real files with it — so "these versions resolve and this config
works" is a CI claim, not a sentence in a README.

Three of the pins are load-bearing floors rather than just "current":

| Peer | Why the pin is a floor |
| --- | --- |
| `@sarj/eslint-plugin` | Every custom rule the config names has to exist. `no-declaration-comment-wall` arrived in 7.1.0, four rules were renamed in 7.0.0 and their aliases deleted in 9.0.0, `prefer-module-level-schema` arrived in 6.1.0, `no-type-member-comment-wall` in 5.1.0, `prefer-zod-infer` in 4.1.0 and `prefer-zod-enum` in 2.17.0; naming a rule the installed plugin lacks is "Definition for rule was not found", once per file. |
| `eslint-plugin-unicorn` | The config enables 213 unicorn rules; most do not exist below 72. |
| `eslint-plugin-zod` | The config **imports** it, so a missing or older install is a hard config error rather than a skipped rule. `zod/prefer-nullish` and `zod/no-any-schema` both land in 4.9.0. |
| `eslint-plugin-perfectionist` | `sort-modules` does not exist before 4. On 3.x an unknown rule is a **hard config error**, not a soft degrade. |

`eslint-plugin-zod` returns to the config after being dropped in #155, when the
one rule taken from it (`zod/prefer-enum-over-literal-union`) was replaced by
`@sarj/prefer-zod-enum` and the import went with it. Two of its rules are worth
the dependency on their own measured evidence — `zod/prefer-nullish` (691 hits
across 12 of 17 audited repos, autofixable) and `zod/no-any-schema` (159 hits
across 10) — and enabling a maintained upstream rule beats keeping a local copy
of it. The rest of the plugin stays off: most of it is Zod v3 → v4 migration
advice (`no-number-schema-with-int`, `prefer-top-level-string-formats`, the
`no-schema-with-is-*` deprecations) that would misfire on a v3 consumer.

**All 18 `eslint-plugin-react` rules remain active on ESLint 10.** Version 7.37.5
calls rule-context APIs removed by ESLint 10, so the config wraps it with
ESLint's official `@eslint/compat` adapter. Runtime tests lint real TSX and fail
if the adapter or any configured React rule becomes inert.

You do not have to install Python to get the ESLint config. If your repo is
TypeScript-only, either run `init` once from `uvx` and commit the result, or skip
`sarj-lint-configs` and use the plugin's own preset:

```js
// eslint.config.mjs
import sarj from "@sarj/eslint-plugin";
export default [sarj.configs.strict];
```

That preset carries the `@sarj` rules only — not the typescript-eslint, unicorn,
react or perfectionist layers the shipped config adds — but it needs one npm
package and no Python. It is flat-config shaped as of `@sarj/eslint-plugin` 6.0.0;
before that both presets declared `plugins` in eslintrc array form and ESLint
threw on sight, which is the other reason people copied the file.

### Rules removed in a breaking release

An `eslint-disable` naming a rule that no longer exists reports "Definition for
rule was not found" until the comment is dropped. `3.0.0` removed
`no-unsafe-cast`, `prefer-shadcn`, `no-sequential-await`,
`require-schema-validate-search` and `single-public-export`; `5.1.0` removed
`ban-loose-type-guards-in-tests`, `no-implicit-attribute-access` and
`prefer-setup-file-mocks`.

## What each config lands as

| Config | Written to | Referenced from |
| --- | --- | --- |
| ruff | `.ruff-strict.toml` | `pyproject.toml` → `[tool.ruff] extend` |
| pyright | `.pyright-strict.json` | `pyrightconfig.json` → `extends` |
| eslint | `eslint.strict.mjs` | `eslint.config.mjs` → `import` |
| markdownlint | `.markdownlint.yaml` | picked up by name |
| taplo | `.taplo.toml` | picked up by name |
| yamllint | `.yamllint.yaml` | picked up by name |

Polyglot repos can route the two ecosystems to their own roots:

```bash
uv run --frozen sarj-lint-configs sync --python-dest python --typescript-dest web --force
```

## `check` — the custom rules

`check` discovers every rule from the exact registry versions installed with this
package. Files and recursively discovered directory contents are routed to the
applicable registry by suffix. It is deliberately zero-tolerance: it does not
accept suppression baselines that a change could inflate to conceal new findings.

Do not copy the runner into consumer repositories. Keeping it inside the wheel
ensures the CLI implementation and its exact registry dependencies upgrade as one
tested unit.

Programmatic access: `from sarj_lint_configs import RUFF_STRICT, PYRIGHT_STRICT,
ESLINT_STRICT, ESLINT_PEERS` (each a `pathlib.Path` into the wheel).

## 0.8.0 — `PLC2701` moved out of ruff

`PLC2701 import-private-name` is in the ignore list. It cannot tell a private name
of *ours* from a private name of a *dependency's*: its exemption is "same
top-level package", so `from livekit.agents.inference_runner import
_InferenceRunner` — an API livekit made private in 1.6.6, with no public
replacement — is flagged identically to a first-party helper someone forgot to
export. Ruff has no configuration surface that separates them.

The check is replaced by `SARJ048` in
[`sarj-python-lint`](https://pypi.org/project/sarj-python-lint/), which resolves
the imported module against your project tree and fires only on first-party
modules. It runs as part of `sarj-lint-configs check`.

**If you are not running `sarj-lint-configs check`, re-enable `PLC2701` in your
own `[tool.ruff.lint] extend-select`** — an over-firing check beats no check.

Attribute access (`session._stt`) is unchanged: ruff's `SLF001` and pyright's
`reportPrivateUsage` both still fire, and neither can make the first/third-party
distinction. Both configs carry the rationale and the escape hatches inline.
