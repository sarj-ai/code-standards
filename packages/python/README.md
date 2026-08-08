# sarj-python-lint

Deterministic Python rules built on the standard-library AST. The rules cover
correctness, test quality, framework contracts, performance, and maintainable
code patterns that Ruff does not already enforce.

Install and inspect the live rule catalog:

```bash
uv tool install sarj-python-lint
sarj-python-lint list-rules
```

Run all rules through Sarj Standards:

```bash
sarj-standards check src tests
```

Diagnostics use `path:line:column: CODE message`. Where a finding is genuinely
intentional, use the exact code-scoped suppression described by the diagnostic;
avoid file-wide or blanket ignores.

Each registry entry points to a rule class under `src/sarj_python_lint/rules/`.
Its implementation and paired test module are the complete behavior
specification. The generated catalog exposed by `sarj-standards show rules`
contains the current identifiers and lifecycle state.

New rules must first confirm that Ruff has no equivalent, include precise
positive and negative fixtures, and pass the corpus evaluation workflow in the
root contribution guide.
