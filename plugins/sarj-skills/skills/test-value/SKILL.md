---
name: test-value
description: Write or review pytest and Vitest tests for distinct regression coverage and safe redundancy removal.
---

Run `code-standards observe --test-value --base BASE` for changes; omit `--base`
for the suite. Executable Oxlint config needs `--trust-repository-code`.
Check changed fixtures/consumers with `code-standards check`.

Name the contract, plausible wrong outcome, recurring consumer and cheapest faithful
oracle. Charge probes, fixtures, wrappers and cleanup the same review cost as
production code. Reuse sufficient coverage; line counts, coverage percentages and
helper self-tests alone justify no addition. Retain required gates.

Delete/merge only when retained cases reject the same wrong outcomes with
compatible inputs, actions, fixtures, marks, runtime, order and effects.
Preserve ordered scenarios and smoke/compatibility/representation contracts.
Read [oracles](references/oracles.md) for integration and fixture-liveness decisions.

Rerun affected consumers. Report keep/strengthen/merge/delete with location,
wrong outcome, covering check and evidence. Advisory/incomplete results never
prove redundancy.
