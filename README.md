# Sarj Standards

Sarj Standards is the single code-quality entry point for Sarj repositories. It
combines strict native-tool configuration with deterministic Python,
TypeScript, SQL, Terraform, and documentation rules.

Standards orchestrates Ruff, BasedPyright, and ESLint; it does not pretend to
reimplement them. Repository-specific formatters, generators, tests, and policy
checks remain owned by their repositories.

## Adopt a repository

Install [`uv`](https://docs.astral.sh/uv/), then run:

```bash
uv tool install sarj-standards
sarj-standards setup
sarj-standards doctor
sarj-standards check --trust-repository-code
```

`setup` detects the repository, writes the minimum required integration, and is
safe to run again. `doctor` reports configuration drift and exact repairs.
`check` is the complete local and CI gate. The trust flag explicitly permits
the repository's executable ESLint configuration; generated hooks and CI use
the same flag. Run `sarj-standards --help` for the current command reference.

All applicable rules are enabled by default. Put narrow, reasoned rule or path
exclusions in `.sarj-standards.toml`; generated and vendored code should be
excluded there rather than by weakening the shared policy.

Standards executes repository-owned ESLint configuration only after the
repository is explicitly trusted. Use reviewable, pinned dependencies in CI.

## Packages

<!-- generated:packages:start -->
| Package | Registry | Purpose |
| --- | --- | --- |
| [`sarj-standards`](packages/standards/) | PyPI | Python orchestration and shared configuration |
| [`sarj-python-lint`](packages/python/) | PyPI | Python AST rules |
| [`sarj-sql-lint`](packages/sql/) | PyPI | PostgreSQL migration rules |
| [`sarj-iac-lint`](packages/iac/) | PyPI | Terraform and IaC rules |
| [`@sarj/eslint-plugin`](packages/typescript/) | npm | ESLint rules and presets |
| [`@sarj/tsconfig`](packages/tsconfig/) | npm | Strict TypeScript configurations |
<!-- generated:packages:end -->

## Rules

<!-- generated:rules:start -->
| Family | Active rules |
| --- | ---: |
| TypeScript | 65 |
| Python | 79 |
| SQL | 12 |
| IaC | 3 |
| Text | 4 |

Rule identifiers and lifecycle data are available through `sarj-standards show rules`.
<!-- generated:rules:end -->

Rule source and its paired tests are the authoritative specification. New rules
must prove precision against real repositories before they are enabled.

Run `make setup` after cloning and `make verify` before requesting review.
Security issues belong in the private process described in
[`SECURITY.md`](.github/SECURITY.md), not a public issue.

The project is Beta software, licensed under the [MIT License](LICENSE).
