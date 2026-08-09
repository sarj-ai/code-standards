# Test quality and strategy

Audit brittle, misleading, and missing tests using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Critical behavior, failure modes, authorization boundaries, migrations, and regressions without coverage.
- Tests coupled to private methods, call ordering, incidental SQL, or framework internals rather than public behavior.
- Mocks whose permissive behavior differs materially from the real dependency.
- Shared mutable state, wall-clock sleeps, randomness, network dependence, or ordering assumptions that cause nondeterminism.
- Assertions too weak to detect the failure the test claims to cover.

Do not maximize coverage mechanically. Prefer the cheapest test level that exercises the real contract, and justify containers or integration dependencies by the fidelity they add.
