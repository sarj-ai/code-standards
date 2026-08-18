# Test quality and strategy

Audit tests for whether they would fail on a meaningful regression using the
shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). Run
the repository's deterministic test-quality rules first and do not repeat their
findings here.

## Discover

Map source and test roots, test frameworks, fakes/fixtures, generated artifacts,
and the native focused/full test commands. Exclude generated, vendored,
snapshot, fixture-data, LLM-evaluation, and end-to-end trees unless the finding
specifically concerns one of them. In pull-request audits, separate executable
test changes from support-only fixtures, fakes, and expected-data maintenance;
classify individual tests rather than whole files or pull requests.

## Judgment checks

Report only a concrete test whose code and nearby production behavior establish
the weakness:

1. **Name/oracle alignment** — Every behavior promised by the test name has an
   observation that distinguishes success from a plausible wrong result.
   Existence, type, call count, truthiness, or 2xx status proves only that narrow
   fact; do not infer that such assertions are weak when that fact is the actual
   contract.
2. **Kill condition** — Name the smallest production deletion, constant change,
   or branch inversion that should make the test fail. If no repository-owned
   mutation exists, classify the test explicitly as compatibility, smoke,
   availability, or repository-invariant coverage.
3. **Independent oracle** — Expected cases and values do not come from the same
   production collection, mapping, parser, or helper whose behavior they claim
   to verify. Enum/registry exhaustiveness sweeps are valid when adding a member
   is meant to add a case.
4. **State and access** — A mutation test reads back the changed/cleared state; a
   successful access test identifies the returned resource and tenant; a filter,
   pagination, ordering, or distinctness test seeds both qualifying and
   disqualifying records and asserts exact identities/order/boundaries.
5. **Negative cases** — Build a known-valid baseline, introduce one defect, and
   assert the intended stable diagnostic or domain error. A fixture with several
   faults cannot prove which validator branch fired.
6. **Classifier tables** — Each row uniquely exercises the branch named by the
   case; an input accepted by a sibling branch cannot prove the intended branch
   still exists.
7. **Determinism** — Inject/freeze clocks and RNGs. Do not encode wall-clock or
   probabilistic ambiguity as multiple acceptable core outcomes. Property tests
   with recorded seeds and true set-valued contracts are valid.
8. **Generated parity** — A test claiming that generated output matches a source
   executes the renderer/generator and compares its complete output. Tests of a
   committed artifact's schema, marker, or repository presence need not run the
   generator.
9. **Dependency fidelity** — Prefer real stores/services or maintained fakes.
   Interaction assertions are appropriate at true adapter boundaries, but an
   observable returned value, persisted row, emitted event, or rendered payload
   is the stronger oracle elsewhere.
10. **Delegation contracts** — A forwarding test uses non-default sentinels and
    proves the exact arguments and returned/yielded value that distinguish the
    delegate. `None`, an empty iterator, or a no-throw loop is not evidence of
    forwarding unless that empty/default behavior is the named contract.
11. **Structured results** — A decoder, response, or error test observes the
    domain fields or stable diagnostic it promises. Container type, non-null,
    key presence, or success status alone is sufficient only when that narrow
    shape is explicitly the contract.
12. **Pagination and competing cases** — A cursor is consumed, both traversal
    directions are checked when supported, and seeded controls distinguish
    tenant, filter, ordering, and boundary behavior. Merely producing a cursor
    or a non-empty page does not prove those contracts.
13. **Coverage incentives** — Review changed-line and per-component coverage
    gates alongside the tests they induce. Coverage is useful discovery evidence,
    but a test added only to execute a forwarding line still needs an independent
    contract oracle. Recommend mutation review for new logic instead of treating
    line or branch execution as proof of test value.

Do not use assertion-to-code ratio, raw coverage percentage, test length, or the
mere presence of mocks/private calls as evidence of low value. Prefer the
cheapest test level that exercises the real contract, and justify containers or
integration dependencies by the fidelity they add.

## Report

For every finding include the test location, the behavior it claims, the
specific mutation that survives, the impact, and the smallest stronger oracle.
Also name nearby strong counterexamples when they establish an important
false-positive boundary. Separate confirmed weak tests from suggestions, and
record whether an active deterministic rule supports the finding or whether it
remains `judgment-only`.
