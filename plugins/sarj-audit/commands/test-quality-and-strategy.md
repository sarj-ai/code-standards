# Test quality and strategy

Audit tests for whether they would fail on a meaningful regression using the
shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). Run
the repository's deterministic test-quality rules first and do not repeat their
findings here.

## Discover

Map source and test roots, test frameworks, fakes/fixtures, generated artifacts,
and the native focused/full test commands. Exclude generated, vendored,
snapshot, fixture-data, LLM-evaluation, and end-to-end trees unless the finding
specifically concerns one of them.

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

Do not use assertion-to-code ratio, raw coverage percentage, test length, or the
mere presence of mocks/private calls as evidence of low value. Prefer the
cheapest test level that exercises the real contract, and justify containers or
integration dependencies by the fidelity they add.

## Report

For every finding include the test location, the behavior it claims, the
specific mutation that survives, the impact, and the smallest stronger oracle.
Also name nearby strong counterexamples when they establish an important
false-positive boundary. Separate confirmed weak tests from suggestions.
