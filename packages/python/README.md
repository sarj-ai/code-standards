# sarj-python-lint

Custom Python lint rules via stdlib `ast`. Designed for pre-commit. For SQL rules see [`sarj-sql-lint`](../sql/).

```bash
uv tool install sarj-python-lint
```

## Pre-commit

```yaml
- repo: https://github.com/sarj-ai/standards
  rev: python-v0.2.0
  hooks:
    - id: sarj-no-sequential-await
    - id: sarj-inefficient-string-concat-in-loop
    - id: sarj-prefer-str-enum
    - id: sarj-no-fat-try-blocks
    - id: sarj-pydantic-at-boundaries
    - id: sarj-prefer-class-row
    - id: sarj-prefer-timedelta-for-durations
    - id: sarj-prefer-struct-over-namedtuple
    - id: sarj-no-comment-cruft
    - id: sarj-no-fstring-in-log
```

### Test-quality rules (0.15.0)

Mined from an AST audit of ~7,500 test functions across two production repos.
Every one is scoped to test files and carries the false-positive guard that made
it shippable; the module docstring for each records the population it was
measured against.

```yaml
    - id: sarj-mock-without-spec                   # SARJ040
    - id: sarj-test-loops-over-literal-cases       # SARJ041
    - id: sarj-parametrize-case-needs-id           # SARJ042
    - id: sarj-zero-assertion-test                 # SARJ043
    - id: sarj-fixture-returns-bare-tuple          # SARJ044
    - id: sarj-kwarg-heavy-construction-in-test    # SARJ045
    - id: sarj-xfail-requires-strict               # SARJ046
    - id: sarj-sleep-with-computed-arg-in-test     # SARJ047
```

### Private access, first-party only (0.19.0)

```yaml
    - id: sarj-no-first-party-private-import       # SARJ048
```

Reaching past a module's public surface is a design finding when the module is
ours and an unavoidable fact of life when it is not: a dependency that moves an
API private in a minor release leaves no edit that satisfies the lint.

`SARJ048` fires only when the module declaring the private name resolves to a
package inside your own project. Third-party privates are never flagged.

**It replaces ruff's `PLC2701 import-private-name`,** whose only exemption is
*same top-level package* — a different question, and one that cannot separate
`from bulbul.stores.task_store import _row_to_task` (real; export it) from
`from livekit.agents.inference_runner import _InferenceRunner` (no fix exists).
`sarj-lint-configs` ≥ 0.8.0 ships `PLC2701` in its ignore list for exactly this
reason; if you take that config, turn this hook on, or you lose the check
entirely.

Attribute access (`session._stt`) is out of scope and stays with ruff's
`SLF001`, which cannot make the distinction either — see the rationale in
`ruff.strict.toml`.

### Comment-hygiene rules (0.20.0)

From a 37,918-comment, nine-repo measurement study. All three are
deletion-class, so each was validated against pydantic / trio / attrs as well as
the maintained repos before shipping — the counts and the false-positive classes
each guard was built from are recorded in the rule module docstrings.

```yaml
    - id: sarj-no-restated-comment                 # SARJ049
    - id: sarj-redundant-docstring                 # SARJ050
    - id: sarj-trailing-value-narration            # SARJ051
```

`redundant-docstring` finds real volume on a codebase that has never had it
(105 in noura-be), so the same baseline ratchet applies.

### House conventions moved out of consumer repos (0.21.0)

```yaml
    - id: sarj-no-stdlib-logging                   # SARJ052
    - id: sarj-no-gen-random-uuid-in-sql           # SARJ053
    - id: sarj-no-file-level-escape-hatch-noqa     # SARJ054
    - id: sarj-no-report-call-issue-ignore         # SARJ055
```

`SARJ055` bans `# type: ignore[reportCallIssue]`. It is intentionally narrower
than a blanket `pyright: ignore[reportCallIssue]` ban after corpus validation:
Django/Pydantic/Flask had 0 hits for the narrowed rule, while the broader shape
was too noisy in dynamic library code. In Sarj repos it surfaces call-contract
debt that should either be fixed or moved to a documented, narrow
`pyright: ignore[reportCallIssue]` boundary.

`SARJ052` bans importing stdlib `logging` in application code, because the
house logger is loguru and two logger hierarchies mean two handler chains: the
records written to the one nobody configured skip the JSON formatter, the
redaction patcher and the error reporter, and — since the stdlib root defaults
to WARNING — usually vanish in production while looking fine locally.

The one legitimate reason to touch stdlib logging in a loguru house is to
*bridge* it, and the bridge cannot be written without naming both loggers, so a
module importing loguru is exempt. Measured across two production repos that
exemption is exact: all four sites that import stdlib logging
(`bulbul/__init__.py`, `bulbul/configure_logging.py`, `agent/main.py`,
noura-be's `common/logging.py`) are bridges, all four import loguru, and no
other module in either repo imports stdlib logging at all. Tests, `scripts/`,
`notebooks/`, generated files and `if TYPE_CHECKING:` imports are also exempt.

**This is a house-convention rule, not a universal one.** A *library* should log
through stdlib `logging` precisely so it does not impose a sink on its callers —
trio's three sites are correct for trio. Enable it in applications only.

`SARJ053` flags `gen_random_uuid()` in SQL embedded in a Python string literal:
UUIDv4 keys scatter B-tree inserts across every leaf page, where `uuidv7()`
(Postgres 18) is time-ordered and appends. It is the embedded-SQL third of a
policy the stack already states twice — `ruff.strict.toml` bans `uuid.uuid4`,
and `sarj-sql-lint`'s SARJ109 `prefer-uuidv7-default` covers `.sql` migration
files (41 sites in bulbul, 14 in noura-be, all of them a primary-key `DEFAULT`).
A literal only counts when it is SQL-shaped, so prose naming the function is not
a finding.

`SARJ054` is SARJ038's scoped sibling. SARJ038 bans the unscoped blanket
(`# ruff: noqa`); this bans a *scoped* file-level exemption that names an
escape-hatch code — a code whose remediation `ruff.strict.toml` spells as an
inline `# noqa: CODE — <reason>`, which today is `TID251` alone, ruff's only
banned-API code. Hoisting that to the top of a file turns N reviewed per-site
decisions into one unreviewable one and pre-authorizes every mock added later.
Scoped exemptions for mechanical codes (`E501`, `F401`, `UP035`) are never
flagged — measured across five repos those are the entire population.

### Suppression ratchet (`sarj-ratchet`, 0.21.0)

```yaml
    - id: sarj-suppression-ratchet
```

One tool replacing the per-repo ratchet scripts. It counts every escape hatch in
the tree and enforces three ceilings that may only shrink:

* **per code** — `noqa:TID251` going 40 → 41 is a regression even if the total falls
* **per package** — one package's headroom must not finance another's debt
* **per file** — a global cap so new suppressions cannot pile into one hot spot;
  pre-existing hot spots are grandfathered at their then-current counts

All four dialects are counted under distinct key prefixes, so moving a
suppression between spellings can never hide it: `noqa:CODE`,
`sarj-noqa:CODE`, `pyright:CODE`, `type-ignore:CODE` / bare `type-ignore`, plus
the file-level `file-noqa:CODE` / `file-noqa:<blanket>` and `file-pyright:RULE`.

```bash
sarj-ratchet --update python/          # seed (or lock in a drop)
sarj-ratchet python/                   # gate
sarj-ratchet --update --allow-increase python/   # a reviewed ceiling raise
```

`--update` **refuses** to raise a ceiling unless `--allow-increase` says the
raise was reviewed, and it drops a per-file grandfather clause as soon as the
file falls back under the global cap, so an allowance cannot outlive its debt.

### Two conventions that stayed pygrep

`sarj-fakes-in-shared-location` and `sarj-no-raw-connection-in-tests` ship as
pygrep hooks, not SARJ rules, and both need a `files:`/`exclude:` from the
consumer. An AST port of each was built and measured, and the boundary each
encodes turned out to be repo-specific rather than shared: "shared fake" flagged
9/9 single-use test doubles in noura-be that are idiomatic where they sit, and
"raw connection in a test" flagged 46 sites in bulbul of which every one is
already an intentional exemption (store tests asserting DB state, pool-lifecycle
tests, retention tests where physical deletion is the subject). SARJ036
`no-raw-sql-in-tests` remains the corpus-validated shared rule for raw SQL in
tests.

Adopting these against an existing suite is easier through the baseline ratchet
than as a big-bang fix — snapshot the current counts, then let them only shrink:

```bash
sarj-python-lint check --rule mock-without-spec --update-baseline test-quality-baseline.json python/
sarj-python-lint check --rule mock-without-spec --baseline test-quality-baseline.json python/
```

## CLI

```bash
sarj-python-lint check --rule no-sequential-await path/to/file.py
sarj-python-lint list-rules
```

Diagnostic format is `path:line:col: CODE message` — Ruff-compatible.

## Suppression

Inline `# sarj-noqa: SARJ00X — <reason>` on the offending line.

Each rule's source under `src/sarj_python_lint/rules/` carries its own `description` and diagnostic message.
