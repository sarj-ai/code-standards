# sarj-iac-lint

Deterministic Terraform and IaC safety rules. They require effective deletion
protection for stateful or irreplaceable resources and reject commented-out
configuration and section-banner noise.

```bash
uv tool install sarj-iac-lint
sarj-iac-lint list-rules
sarj-iac-lint check --rule require-deletion-protection infrastructure/
```

Sarj repositories normally run the package through `sarj-standards check`.
Diagnostics use `path:line:column: CODE message`. Suppress an intentional
finding on the relevant line with an exact code and reason, for example
`# sarj-noqa: SARJ201 -- temporary sandbox resource`.

Protection expressions are not accepted as proof when static analysis cannot
establish that they evaluate to a safe value. Each registry entry under
`src/sarj_iac_lint/rules/` and its paired test are the authoritative rule
specification. Run `sarj-standards show rules` for the current catalog.
