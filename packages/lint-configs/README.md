# sarj-lint-configs

Ships the maximally-strict ruff / pyright / ESLint configs from `sarj-ai/standards` as a pip-installable package.

```bash
uv add --dev sarj-lint-configs
uv run sarj-lint-configs sync --only ruff      # writes .ruff-strict.toml
uv run sarj-lint-configs sync --only pyright   # writes .pyright-strict.json
uv run sarj-lint-configs sync --only eslint    # writes eslint.strict.mjs
uv run sarj-lint-configs check .                # runs every Python/SQL/IaC custom registry
```

Polyglot repositories can route the Python and TypeScript configs to their
respective tool roots in one canonical sync:

```bash
uv run sarj-lint-configs sync \
  --python-dest python \
  --typescript-dest typescript \
  --force
```

Use the same command with `--check` in CI or a Git hook to detect drift without
writing to the worktree.

The `check` command discovers every rule from the exact registry versions
installed with this package: `sarj-python-lint==0.26.0`,
`sarj-sql-lint==0.5.0`, and `sarj-iac-lint==0.3.0`. Files and recursively
discovered directory contents are routed to the applicable registry by suffix.
The command is deliberately zero-tolerance: it does not accept suppression
baselines that a change could inflate to conceal new findings.

For commit-time feedback, pin Lefthook and install the hook during setup:

```bash
uv add --dev lefthook==2.1.10 sarj-lint-configs==0.10.0
uv run lefthook install
```

```yaml
# lefthook.yml
min_version: 2.1.10
assert_lefthook_installed: true
pre-commit:
  jobs:
    - name: strict config drift
      run: uv run --frozen sarj-lint-configs sync --check
      fail_text: "Strict configs drifted. Re-run sync --force, stage the result, and retry."
    - name: sarj standards
      run: uv run --frozen sarj-lint-configs check -- {staged_files}
      fail_text: "Standards checks failed. Fix the issue, stage the result, and retry."
```

Do not copy the runner into consumer repositories. Keeping it inside the wheel
ensures the CLI implementation and its exact registry dependencies upgrade as
one tested unit.

### Peer version floors for the bundled ESLint config

| Peer | Floor | Why |
| --- | --- | --- |
| `@sarj/eslint-plugin` | `4.3.0` | Contains every custom TypeScript rule referenced by the config. |
| `eslint-plugin-unicorn` | `>= 65` *only* if you pass `checkDirectories` | The option does not exist before 65, and on 64 an unknown option is a **hard config error**, not a soft degrade. |
| `eslint-plugin-perfectionist` | `>= 4.0.0` | `sort-modules` does not exist before 4. On 3.x this is a **hard config error**, not a soft degrade. |

`@sarj/eslint-plugin@3.0.0` is a **breaking** release: it removes
`no-unsafe-cast`, `prefer-shadcn`, `no-sequential-await`,
`require-schema-validate-search` and `single-public-export`. An
`eslint-disable` naming any of them reports "Definition for rule was not found"
until the comment is dropped. Do not pin below `4.3.0` — the config references
`@sarj/no-type-member-comment-wall`, added in `4.3.0`,
`@sarj/prefer-zod-infer`, added in `4.1.0`, and `@sarj/prefer-zod-enum`, which
does not exist before `2.17.0`. A missing rule is a hard config error on the
first `eslint` run, not a soft degrade.

`unicorn/filename-case` in this config deliberately does **not** pass
`checkDirectories`, so the config itself imposes no unicorn floor above what
the rest of the rule set already needs. The floor is recorded here because it
is the reason the option is absent, and because it is invisible at the call
site: a consumer that adds `checkDirectories` locally will break on any unicorn
older than 65. Installed versions across first-party consumers currently span
`^62.0.0` through `^72.0.0`, with one consumer pinned to an exact `64.0.0`
— i.e. two consumers sit below the floor today.

Then reference the synced file:

```toml
# pyproject.toml
[tool.ruff]
extend = ".ruff-strict.toml"
```

```json
// pyrightconfig.json
{ "extends": ".pyright-strict.json" }
```

```js
// eslint.config.mjs
import strict from "./eslint.strict.mjs";
export default [...strict];
```

Re-run sync with `--force` after upgrading. Programmatic access via `from sarj_lint_configs import RUFF_STRICT, PYRIGHT_STRICT, ESLINT_STRICT` (returns `pathlib.Path` into the wheel).

## 0.8.0 — `PLC2701` moved out of ruff

`PLC2701 import-private-name` is now in the ignore list. It cannot tell a
private name of *ours* from a private name of a *dependency's*: its exemption
is "same top-level package", so `from livekit.agents.inference_runner import
_InferenceRunner` — an API livekit made private in 1.6.6, with no public
replacement — is flagged identically to a first-party helper someone forgot to
export. Ruff has no configuration surface that separates them.

The check is replaced by `SARJ048` in
[`sarj-python-lint`](https://pypi.org/project/sarj-python-lint/) ≥ 0.19.0,
which resolves the imported module against your project tree and fires only on
first-party modules:

```yaml
- repo: https://github.com/sarj-ai/standards
  rev: python-v0.19.0
  hooks:
    - id: sarj-no-first-party-private-import
```

**If you are not running the sarj-python-lint hooks, re-enable `PLC2701` in
your own `[tool.ruff.lint] extend-select`** — an over-firing check beats no
check.

Attribute access (`session._stt`) is unchanged: ruff's `SLF001` and pyright's
`reportPrivateUsage` both still fire, and neither can make the first/third-party
distinction. Both configs carry the rationale and the escape hatches inline.
