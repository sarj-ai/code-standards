---
name: test-value
description: Write or review pytest and Vitest tests when reducing redundancy or strengthening regression coverage.
---

# Test value

Review changed tests or the requested suite.

1. Run applicable deterministic checks; verify findings in source.
2. Name the contract and a plausible wrong outcome the test rejects. Reuse existing coverage when it already rejects that outcome.
3. Observe returned content, state, access, or emitted effects. Exact interaction assertions belong at real boundaries.
4. Parameterize independent cases sharing one action and oracle. Keep ordered scenarios intact.
5. Add tests for uncovered behavior changes. Mechanical edits and review comments alone do not require new tests.
6. Treat smoke, no-throw, compatibility, nullable results, enum sweeps, and property tests as possible contracts. Broad advisories require review.
7. Use real construction and maintained fakes. Add production abstractions only when production needs them.

Preserve mandatory repository coverage rules, including store line/branch coverage. Preserve assertion helpers and explicit representation contracts.

Report keep, strengthen, merge, or delete with the contract, evidence, and focused command. Automated findings never authorize deletion.

Read [references/oracles.md](references/oracles.md) only for uncertain cases.
