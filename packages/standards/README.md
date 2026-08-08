# sarj-standards

The Python package and command-line entry point for Sarj Standards. It detects
repository structure, installs the supported toolchain, generates shared
configuration, runs checks and fixes, and diagnoses drift.

## Use

```bash
uv tool install sarj-standards
sarj-standards setup
sarj-standards doctor
sarj-standards check --trust-repository-code
```

Use `sarj-standards fix` for supported safe fixes and formatting. Use
`sarj-standards update` to update the complete Standards toolchain as one
reviewable change. Every command is repository-root aware and `setup` and
`update` are idempotent.

The generated `.sarj-standards.toml` is the repository's concise policy:
applicable rules are on by default, while exceptional paths or rules are
excluded explicitly. Do not edit generated tool configuration.

Use one denylist command instead of editing generated analyzer configs:

```bash
sarj-standards exclude add path 'generated/**'
sarj-standards exclude add rule 'eslint:@typescript-eslint/no-explicit-any'
sarj-standards exclude list
sarj-standards exclude remove path 'generated/**'
```

Paths are repository-relative globs and rules use an exact `engine:rule`
selector. The operations are atomic and idempotent. Repository-wide path
patterns are rejected so an exclusion cannot silently turn Standards off.

## Tool ownership

Standards orchestrates these native analyzers:

- Ruff for Python lint and formatting.
- BasedPyright for Python types.
- ESLint for JavaScript and TypeScript semantics.
- Sarj analyzers for Python, SQL, IaC, and text policy.

Existing formatters, generators, tests, and custom gates remain repository
owned unless setup can prove that Standards owns an equivalent integration.

## CI

Run `sarj-standards check --trust-repository-code` as the quality gate. The
trust flag explicitly permits the repository's executable ESLint configuration;
generated hooks and CI use it automatically. Keep the package version pinned by
the repository lock file, and run `sarj-standards doctor` when diagnosing a
failed upgrade or unexpected drift. Machine-readable diagnostics are available
through the formats shown by `sarj-standards check --help`.

## Maintainers

Business logic lives under `sarj_standards.libs`; the CLI is a presentation
adapter. Repository maintenance commands live under `sarj-standards maintain`.
Generated documentation must be synchronized with:

```bash
sarj-standards maintain docs sync
sarj-standards maintain docs check
```

The repository's contribution guide defines verification and release
requirements.
