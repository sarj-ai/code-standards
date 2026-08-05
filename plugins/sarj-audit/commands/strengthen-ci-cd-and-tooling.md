# CI/CD and tooling

Audit delivery and toolchain reliability using the shared [audit protocol](../README.md#audit-protocol). General lint-rule coverage belongs in `lint-rule-generator`; dead code belongs in `dead-and-duplicate-code`.

## Judgment checks

- Required format, lint, type, test, migration, security, or build gates missing from protected CI paths.
- Mutable action/image references, missing lockfiles, non-reproducible installs, or unverified generated artifacts.
- Overprivileged workflow tokens, untrusted input interpolation, unsafe artifact handling, and secrets exposed to forked code.
- Brittle deployment ordering, absent concurrency controls, missing rollback/health checks, or environments that can drift from reviewed configuration.
- Unsupported runtimes and tools with a demonstrably safer maintained migration path.

Do not prescribe a package manager or tool solely because it is newer. Tie modernization to support status, reproducibility, security, speed, or meaningful simplification.
