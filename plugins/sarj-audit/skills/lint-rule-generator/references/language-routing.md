# Language and engine routing

Choose the owning ecosystem first; do not duplicate a rule for symmetry.

| Input | Prefer first | Custom implementation when |
|---|---|---|
| Python | Ruff, BasedPyright | the pattern needs project-specific AST relationships not exposed upstream |
| TypeScript/JavaScript | ESLint core and typescript-eslint | the typed or syntax relationship is absent upstream |
| Markdown/prose | markdownlint, deterministic line/block scanner | the concern is a durable repository artifact pattern, not subjective writing style |
| SQL | parser/token-aware SQL rule | dialect syntax, comments, dollar strings, or statement boundaries matter |
| Terraform/HCL | HCL block/token parser | block ownership or lifecycle semantics matter |
| YAML/TOML/JSON/config | format parser or textlint config scanner | commented-out configuration or cross-format artifacts need one shared rule |

Use regex only when the match is lexical, line-local, and independently testable
against comments and strings. Use AST/token structure for scopes, calls, imports,
types, or nesting. Use project-aware analysis only when the extra I/O is needed;
cache immutable parse products by content or stable file identity.

Before custom code, record:

- upstream rule/documentation searched;
- closest existing Sarj rule and overlap;
- whether preset configuration can solve it;
- why an autofix is safe, unsafe, or intentionally absent;
- which generated/vendor/fixture paths are excluded and why.

Diagnostic messages name the observed construct and a concrete remediation.
They do not claim AI authorship, speculate about intent, or shame the author.
Suppressions must be exact-code, local, and auditable.
