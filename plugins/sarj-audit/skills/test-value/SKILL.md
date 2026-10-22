---
name: test-value
description: Write or review pytest and Vitest tests when reducing redundancy or strengthening regression coverage.
---

# Test value

Run `code-standards observe --test-value --base BASE` for changed tests; omit
`--base` for the suite. Authorize repository ESLint execution with
`--trust-repository-code`. Verify candidates in source.

For fixture changes, also run `code-standards check` over shared setup and its
affected consumers. The observer's candidate list does not establish fixture
visibility or liveness.

- Name the contract and wrong outcome. Reuse adequate coverage; a changed file, script, or review comment does not by itself require a new test. Record sufficient existing checks when no case is needed.
- For script, CI, configuration, and infrastructure cases, apply [operational test admission](references/oracles.md#operational-tests): identify the distinct wrong outcome, covering native checks, and any necessary representation contract before adding or pruning coverage.
- Compare inputs, actions, fixtures/marks, runtime, and assertion order/effects before removing duplicated or subsumed oracles. Combine complementary assertions sharing those conditions.
- Cover inherited behavior at its owner; retain override and composition contracts.
- Choose reusable setup by provider visibility, configuration, state isolation, and cleanup ownership. Compose fixture dependencies or typed factories while keeping the tested action and oracle visible; see [fixture design and reuse](references/oracles.md#fixture-design-and-reuse).
- Reduce repeated setup with existing bulk APIs, compatible fixtures, or a data loop only when the result is clearer; preserve ordering, hoisting, and cleanup. See [repeated setup](references/oracles.md#repeated-setup).
- Parameterize independent cases when shorter; preserve ordered scenarios.
- Observe content, state, access, or effects. Exact interactions belong at real boundaries. Preserve smoke, no-throw, compatibility, enum/property, representation, and assertion-helper contracts.
- An integration claim must exercise the real boundary it names and observe its externally visible result. Review negative side effects and failure atomicity when those contracts are affected. See [oracles.md](references/oracles.md#integration-boundaries).
- Await or return asynchronous assertions and their promise chains. Ensure expected-error tests fail when the operation succeeds; a catch-only assertion leaves the success path unchecked.
- Verify retained cases and coverage; use targeted regression probes when an oracle could be lost. Equal coverage does not prove equivalence.
- Rerun checks and inspect affected helpers/fixtures until no confirmed improvement remains within scope.

Preserve mandatory coverage, including store lines/branches. Reuse maintained
fakes; production abstractions need a production reason. Findings never
authorize deletion.

Report keep, strengthen, merge, or delete with the wrong outcome, retained or
covering check, evidence, and a focused command. An inconclusive comparison is
not evidence to prune a test.
Read [references/oracles.md](references/oracles.md) for uncertain cases.
