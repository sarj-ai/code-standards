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
