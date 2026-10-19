# CI/CD and tooling

Audit delivery and toolchain reliability using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). General lint-rule coverage belongs in `lint-rule-generator`; dead code belongs in `dead-and-duplicate-code`.

## Judgment checks

- Required format, lint, type, test, migration, security, or build gates missing from protected CI paths.
- Mutable image references, missing lockfiles, non-reproducible installs, or unverified generated artifacts.
- Overprivileged workflow tokens, untrusted input interpolation, unsafe artifact handling, and secrets exposed to forked code.
- Brittle deployment ordering, absent concurrency controls, missing rollback/health checks, or environments that can drift from reviewed configuration.
- Unsupported runtimes and tools with a demonstrably safer maintained migration path.

Do not prescribe a package manager or tool solely because it is newer. Tie modernization to support status, reproducibility, security, speed, or meaningful simplification.

For a coding-session optimization, reproduce the observed bottleneck with a
bounded representative task before proposing more infrastructure. Reuse existing
fixtures and runners. Pin the baseline and candidate revisions; keep task inputs,
harness, cache state, and concurrency comparable. Record the required task outcome and final
qualification gates. Separate queue wait from check execution, and measure the
relevant cost: task-ready time, first actionable error, repeated gates, output
bytes, unnecessary installs, or escaped defects. Report median and p95 only
when repeated measurements support them. Add a regression case for a demonstrated
failure; a larger case count or a scoped green check alone does not prove value.
