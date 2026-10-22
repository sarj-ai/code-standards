---
name: test-value
description: Write or review pytest and Vitest tests for distinct regression coverage and safe redundancy removal.
---

# Test value

Run `code-standards observe --test-value --base BASE` for changed tests; omit
`--base` for the suite. Executable ESLint configuration requires
`--trust-repository-code`. Verify advisory candidates in source; incomplete
analysis is not clean evidence. Check changed fixture support and its consumers
with `code-standards check` too.

Name each contract, plausible wrong outcome and cheapest faithful observation.
Reuse sufficient coverage; an edit, review comment or coverage percentage alone
does not justify another test. Preserve required coverage gates.

Merge or remove only when retained cases reject the same wrong outcomes under
compatible inputs, actions, fixtures, marks, runtime, ordering and effects.
Parameterize independent cases when clearer; preserve ordered scenarios and
meaningful smoke, compatibility, representation and boundary contracts.

Reuse compatible providers and maintained fakes; keep actions and independent
oracles visible. Read [oracles.md](references/oracles.md) for integration,
fixture-liveness and ambiguous cases. Rerun affected consumers after changes.

Report keep, strengthen, merge or delete with location, wrong outcome, covering
check, evidence and focused command. Advisory findings never authorize deletion;
an inconclusive comparison does not justify pruning.
