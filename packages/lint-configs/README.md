# sarj-lint-configs

Ships the maximally-strict ruff / pyright / ESLint configs from `sarj-ai/standards`
as a pip-installable package, plus the commands that adopt them and keep them current.

## Adopt

```bash
uvx --from sarj-lint-configs sarj-standards init
```

`init` detects Python and/or TypeScript, installs the toolchain and hooks, and writes only the configs that ecosystem
uses, wires them up (`[tool.ruff] extend`, `pyrightconfig.json`,
`eslint.config.mjs`), writes a pre-commit block, records the adopted version in
`.sarj-standards.toml`, and prints the CI snippet and — for TypeScript — the one
ESLint peer set that resolves together. Pass `--no-install` to write only the wiring.

`init --dry-run` prints the whole plan without touching anything. Existing Ruff,
Pyright, ESLint flat-config, package-manager, and pre-commit files are merged
only when their structure is unambiguous; user-owned settings are preserved. If
a file cannot be wired safely, `init` explains the exact manual change and makes
no changes. A failed sync or dependency install restores every tracked file.

The command consolidates orchestration, not analyzer implementation. Ruff,
BasedPyright, ESLint, Prettier, Biome, and their native configurations remain
authoritative for behavior Standards does not exactly model. Adoption never
removes a direct formatter, generator, suppression workflow, or custom lint
stage based on name alone; ambiguous migrations stop with a concrete manual
step instead of guessing.

Application repositories can opt into the preferred-library policy at adoption
time:

```bash
uvx sarj-lint-configs init --profile application
```

The selected `standard` or `application` profile is recorded in
`.sarj-standards.toml`, so later `update --configs-only`, `update
--configs-only --check`, and `check` select the
same standalone Ruff and ESLint artifacts automatically. Existing manifests
without a `profile` field remain on `standard`. The application profile is an
intentional stack policy: it treats cataloged imports such as `argparse` and
`pandas` as errors even when the old library remains maintained.

It also checks direct dependencies in `pyproject.toml`, PEP 735 groups,
Poetry/PDM/uv tables, authored requirements files, and every npm dependency
field. Run that manifest gate independently—or measure an unadopted repository—
with:

```bash
uvx sarj-lint-configs check --dependencies --profile application
```

Findings carry stable `LIB###` IDs and migration cautions. Architectural
replacements such as Flask to FastAPI, pandas to Polars, and Axios to Ky are
deliberately errors, but are never broadly autofixed because their APIs and
runtime semantics differ.

The Standards CLI itself remains on `argparse` deliberately. It is a low-level
`uvx`/pre-commit bootstrap tool using the `standard` library profile, where a
dependency-free parser keeps installation and `--help` available before the
consumer stack is installed. The Typer preference applies to application
profiles; it is not a claim that maintained standard-library APIs are obsolete.

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

The detected destinations are recorded in `.sarj-standards.toml`, so plain
`update --configs-only` and `update --configs-only --check` find them again
without CI having to restate them. Override
detection with `init --python-dest` / `--typescript-dest`.

### npm, pnpm, Yarn and Bun

The peer set below does not install without an override block, and every client
spells that block differently: npm and Bun use `package.json#overrides`, pnpm 11
wants `overrides` in `pnpm-workspace.yaml` (older standalone pnpm projects use
`package.json#pnpm.overrides`) with a `parent>child` selector, Yarn wants `resolutions` with a
`parent/child` path and no `$dep` indirection. `init` detects the client from the
lockfile (or a `packageManager` field, which Corepack enforces), writes the right
one, and prints the matching install command. Writing npm's spelling everywhere
was worse than writing nothing: pnpm and Yarn ignore a stray `overrides` key, so
the install failed identically while `package.json` looked fixed.

## Keep current

Use the exact isolated launcher that `init` writes to pre-commit and `show ci`
emits for CI. It is identical for root Python, nested Python, mixed, and
TypeScript-only repositories:

`uvx --isolated --python 3.14 --from sarj-lint-configs==VERSION sarj-standards`

VERSION comes from `.sarj-standards.toml`. The tool's Python 3.14 runtime stays
outside the consumer environment, so projects targeting older Python versions
remain installable. The stable verbs after `sarj-standards` are:

```bash
doctor                 # read-only diagnosis with exact fixes
update --check          # preview whether an upgrade is needed
update                  # resolve latest, migrate, install, postflight
check                   # run every adoption and lint gate
fix                     # apply formatter and safe lint fixes
show state              # print detected adoption state
check --noise-only .    # comment/artifact ratchet only
```

Run `check` in CI. `init` prints the exact install and check steps for the
detected project layout. With no paths, `check`
runs the complete repository verification. With paths, it runs the applicable
custom rules for those paths, which keeps pre-commit fast.
`check --noise-only` covers Python and text/config inputs; TypeScript comment
noise is enforced by the generated strict ESLint config.

`check` checks the whole repository by default. A tool repository whose rule
fixtures intentionally contain rejected code can narrow only the custom-rule
pass, without weakening Ruff, BasedPyright, or ESLint:

```toml
[verify]
paths = ["src", "tests", "README.md"]
```

Paths are repository-relative and cannot escape the repository root.

Maintainers can declare repository policy in `.sarj-standards.toml` and replace
ad hoc scripts with `sarj-standards maintain check`. The same command checks private
references, CI history, filenames, rule/test/registry pairing, canonical config
references, and version coverage; `maintain sync-ledger`, `maintain
comment-corpus`, `maintain hooks install`, and `show rules` provide the related maintenance
operations.

The package also owns repository setup and release policy; workflows and the
Makefile are intentionally thin adapters rather than a second implementation:

```bash
sarj-standards maintain setup --check
sarj-standards maintain release check-tag typescript-v10.0.0
sarj-standards maintain release lock-age packages/typescript/package-lock.json --exclude-file .github/release-age-exclusions.txt
sarj-standards maintain release typescript check
sarj-standards maintain release publish typescript
```

The former `sync`, `list`, `path`, `peers`, `upgrade`, `verify`, `format`,
`inspect`, `library-policy`, and `repo` commands remain exact compatibility
aliases. Existing CI and hooks keep working while new usage stays within the
consumer verbs shown by `sarj-standards --help`.

Programmatic consumers should import `sarj_lint_configs.api`. Business logic is
grouped under `sarj_lint_configs.libs` by adoption, linting, repository, setup,
and release domains; `__main__` is only an entrypoint and `cli/` owns argument
parsing and presentation. The former top-level modules remain identity-preserving
compatibility aliases for existing imports and monkeypatches.

The Python facade mirrors the consumer vocabulary without parsing CLI output:

```python
from pathlib import Path

from sarj_lint_configs.api import Standards

standards = Standards(Path.cwd())
health = standards.doctor()
preview = standards.init(dry_run=True)
result = standards.init(install=False)
status = standards.check(("src", "tests"))
analysis = standards.analyze(("src", "tests"))

# Installed Ruff and BasedPyright are opt-in. ESLint configuration is executable
# JavaScript, so it additionally requires an explicit trusted-repository choice.
from sarj_lint_configs.api import TrustMode

full_analysis = standards.analyze(("src", "tests"), external=True)
trusted_analysis = standards.analyze(("src", "tests"), external=True, trust=TrustMode.TRUSTED)

# Stable schema-v1 JSON for internal automation, and SARIF 2.1.0 for CI/editors.
from sarj_lint_configs.api import to_json, to_sarif

json_report = to_json(analysis)
sarif_report = to_sarif(analysis)
```

The same normalized native diagnostics are available directly in CI without a
Python wrapper:

```bash
# Human output, schema-v1 JSON, GitHub workflow annotations, or SARIF 2.1.0.
sarj-standards analyze
sarj-standards analyze --format json
sarj-standards analyze --format github
sarj-standards analyze --format sarif --output sarj.sarif
sarj-standards analyze --mode raw  # ignore adopted scope/baselines for calibration
# In CI for your own trusted mixed Python/TypeScript checkout:
sarj-standards analyze --external --trust trusted --format github
```

`analyze` is intentionally read-only and native-only. In its default `policy`
mode it applies the manifest's verification scope, gradual Python baseline,
bundled Python/SQL/IaC/text rules, and application dependency policy. `--mode
raw` scans the requested native corpus without those adoption filters. Neither
mode discovers executables, installs tools, or executes repository JavaScript.
Exit 0 means every selected file was covered and findings were warning-only or
absent; 1 means at least one error diagnostic; 2 means invalid or incomplete
analysis. Native-only TypeScript or unsupported explicit files therefore return
2 with a coverage notice instead of masquerading as clean. JSON and SARIF
written to stdout contain only their payload; `--output` writes either format
atomically.

Keep `sarj-standards check` as the canonical merge gate. It additionally checks
adoption/config drift, Ruff, BasedPyright, application dependency policy, and
ESLint; TypeScript is therefore enforced by `check`, not native-only `analyze`.
Use the GitHub format only when a separate native annotation lane is useful.
For a root Python project, this is a complete minimal job; nested projects use
the launcher and lock path printed by `init`:

```yaml
permissions:
  contents: read
steps:
  - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
  - uses: astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9 # v9.0.0
    with:
      enable-cache: true
      cache-dependency-glob: uv.lock
  - run: uv sync --frozen
  - run: uvx --isolated --python 3.14 --from sarj-lint-configs==VERSION sarj-standards analyze --format github
```

GitHub output is deterministically capped at ten annotations per severity;
JSON and SARIF retain the complete result. Pass
`--max-annotations-per-level 0..10` to lower that log budget.

The preferred API is deliberately small: `Standards`, `Result`, `Finding`,
`AnalysisReport`, `Diagnostic`, `Change`, `Inspection`, `Status`, and
`__version__`. `check()` retains its existing exit-oriented `Result`; `analyze()`
returns normalized findings without parsing console output. Its completion and
conclusion are separate, so a crashed tool cannot masquerade as clean code.
Locations retain byte offsets internally and serialize as zero-based UTF-16
positions; ranges are emitted only when an analyzer supplied a real end point.
Existing `sarj_lint_configs.api` exports remain as compatibility aliases.
Maintainer plan/apply, rule evaluation, corpus, and release APIs live in the
public `sarj_lint_configs.libs` namespace.

Release-age exception files contain one exact `package@version` per line, with
optional `#` comments. Name-wide exceptions are rejected in files, so a future
lockfile upgrade cannot silently inherit a temporary whitelist.

`sarj-standards` is the preferred entrypoint. `sarj-lint-configs` remains an
alias for compatibility. `check` routes Python, SQL, Terraform, YAML/TFTPL,
TOML, JSONC, Markdown, INI-style config, environment files, shell scripts,
Dockerfile variants, Makefiles, and Justfiles in one pass. It rejects
commented-out config (`SARJ301`), dense config narration (`SARJ300`), and AI
execution diaries, bug-hunt dumps, or large point-in-time audits that should
have been reduced to durable README/docs/ADR facts (`SARJ302`). Large documents
need at least two independent artifact signals, so size alone never reports.
`SARJ302` is visible but non-blocking for its first minor release; promotion is
an explicit per-rule metadata change after corpus calibration, never a global
warning-to-error rewrite. The new constructor and shadcn checks are likewise
warnings, and shadcn guidance exists only in the application profile, outside
tests, fixtures, and design-system implementation directories.

`SARJ303` warns when a remote `uses:` entry under `.github/workflows` is pinned
to a tag, branch, expression, or container tag. Pin Marketplace actions and
reusable workflows to a full 40-character commit SHA, and container actions to
a full `sha256` digest. Local `./` actions remain valid. The rule is warning-only
for its first release and supports a local preceding `# sarj-noqa: SARJ303`.

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

Run it without preparation:

```bash
sarj-standards doctor
sarj-standards doctor --format json  # stable schema and finding IDs for automation
```

It is read-only, exits 0 for a healthy adopted repository, 1 for actionable
drift (including a repository that has not adopted Standards yet), and 2 for
invalid input such as malformed TOML/JSON. Every
drift finding includes a concrete remediation. Intentional compatibility
fixtures can be excluded narrowly with `[doctor] exclude = ["tests/fixtures/**"]`.

Upgrading is one command from an installed environment:

```bash
sarj-standards update
```

The command bootstraps the newest published compatibility bundle with `uvx
--refresh`, previews each changed path, blocks on retired rule references,
updates the single manifest version, syncs configs, safely repairs wiring and
peer pins, installs dependencies, rolls generated/config files back, and
removes a newly created `.venv` if installation or the doctor postflight
fails. An existing environment is not snapshotted; after a failed update, run
your package manager's frozen sync to reconcile it with the restored lockfile.
Use `update --check` in automation. The legacy
`upgrade --offline --no-install` spelling remains available for maintainers
testing the already-installed bundle.

For an offline or review-first update, run `sarj-standards update --offline
--no-install`. This uses the executing/cached bundle, updates only tracked
configuration, and prints the exact pending install commands. `doctor` and full
`check` intentionally remain nonzero until those dependencies are installed.
The bundle and `uvx` environment must already exist in the local cache; this
mode never claims to download them offline.

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
site should say. It still diagnoses legacy pre-commit tag pins so an old
adoption cannot drift silently, but new adoption does not create that second
version site.

Do not use generic `pre-commit autoupdate` for a legacy remote Standards block:
the repository publishes separate aggregate, Python, SQL, and IaC tag families,
so a lexically newest tag is not necessarily the hook's package. Run
`sarj-standards update`; it derives the compatible revision from the hook IDs
and migrates supported consumers to the single local orchestrator.

The block `init` writes has no `rev:` at all. One `repo: local` hook runs the
manifest-pinned CLI in an isolated environment and starts the toolchain only
once per commit:

```yaml
repos:
  - repo: local
    hooks:
      - id: sarj-standards-check
        name: sarj standards -- staged checks
        entry: uvx --isolated --python 3.14 --from sarj-lint-configs==VERSION sarj-standards check --staged --
        language: system
        verbose: true
        pass_filenames: true
        # `init` supplies the generated matcher for every supported source/config file.
```

Every repository shape gets the same launcher form. `check --staged` routes
only staged paths to their applicable linters in either ecosystem.

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

### `update --configs-only --check` — synced configs are unmodified

Ruff cannot `extend` a config out of an installed package's path portably, which
is why config refresh writes a copy into your repo instead of you referencing one. A copy
can be edited, so `update --configs-only --check` compares each one byte-for-byte and fails CI when
it differs. One consumer's copy of the ESLint config had quietly drifted to 120
rules against a canonical 145 — missing 30, carrying 5 that no longer exist
upstream — and nothing caught it.

`update --configs-only` and its `--check` mode operate on the config set in `.sarj-standards.toml`,
so a Python repo is not asked to carry an ESLint config it never wanted. That
matters: `sync --check` used to insist on all six files, report permanent drift
on the two a repo had no use for, and so never made it into anyone's CI.
Without `--force`, an edited config is preserved and reported as skipped. Use
`update --configs-only --force` to restore the canonical bytes after reviewing
the diff.

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
sarj-standards update --configs-only --python-dest python --typescript-dest web --force
```

## `check` — the custom rules

`check` discovers every rule from the exact registry versions installed with this
package. Files and recursively discovered directory contents are routed to the
applicable registry by suffix. Normal suppressions are exact-code and local.
Python additionally supports a shrink-only `--baseline` / `--create-baseline`:
the recorded ceiling may decrease, but a change cannot inflate it to conceal
new findings.

Do not copy the runner into consumer repositories. Keeping it inside the wheel
ensures the CLI implementation and its exact registry dependencies upgrade as one
tested unit.

Legacy config-path exports remain importable for compatibility. New automation
should use `sarj-standards show config NAME` or the typed adoption libraries.

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
