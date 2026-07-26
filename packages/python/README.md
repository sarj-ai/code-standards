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
