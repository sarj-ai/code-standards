---
name: test-value
description: Write or review pytest and Vitest tests when reducing redundancy or strengthening regression coverage.
---

# Test value

Run `code-standards observe --test-value --base BASE` for changed tests; omit
`--base` for the suite. Authorize repository ESLint execution with
`--trust-repository-code`. Verify candidates in source.

- Name the contract and wrong outcome. Reuse adequate coverage; mechanical edits and review comments do not require tests.
- Compare inputs, actions, fixtures/marks, runtime, and assertion order/effects before removing duplicated or subsumed oracles. Combine complementary assertions sharing those conditions.
- Cover inherited behavior at its owner; retain override and composition contracts.
- Parameterize independent cases when shorter; preserve ordered scenarios.
- Observe content, state, access, or effects. Exact interactions belong at real boundaries. Preserve smoke, no-throw, compatibility, enum/property, representation, and assertion-helper contracts.
- Verify retained cases and coverage; use targeted regression probes when an oracle could be lost. Equal coverage does not prove equivalence.
- Rerun checks and inspect affected helpers/fixtures until no confirmed improvement remains within scope.

Preserve mandatory coverage, including store lines/branches. Reuse maintained
fakes; production abstractions need a production reason. Findings never
authorize deletion.

Report keep, strengthen, merge, or delete with evidence and a focused command.
Read [references/oracles.md](references/oracles.md) for uncertain cases.
