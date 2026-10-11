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

Before adding tests, inspect existing coverage, identify the changed contract,
and choose the cheapest faithful boundary. Reuse maintained fakes and fixtures
before introducing support abstractions.

Prefer the smallest suite that distinguishes the required contracts. Each new
case must add a concrete regression, boundary, interaction, or lifecycle check;
delete an identical case or strengthen an existing oracle before adding another
test. A passing test of a library default, trivial accessor, or unchanged
forwarder needs a demonstrated compatibility or application contract to earn
ongoing maintenance. Coverage targets alone do not supply that contract.

Trace actual CI test selections and their effective pytest roots/configuration,
coverage collection, skips and prerequisites, retries, and optional lanes before
assessing which contracts execute. Establish the intended lane and available
prerequisites; do not infer execution from a test's presence or require every
lane to run every test.

For fixture-liveness evidence, use `pytest-unused-fixtures==0.3.1` in the test
environment and add `--unused-fixtures -v` to the already owned complete pytest
command for each supported profile. Bound `--unused-fixtures-context` to authored
test support; retain the ordinary test exit status and do not use
`--unused-fixtures-fail-when-present`. Record supported profiles and prerequisites
from existing CI configuration, rather than adding a second suite runner.
Collection-only, focused, deselected, sharded, interrupted, or skipped execution
cannot establish fixture inactivity across the complete suite.

Treat an inactive fixture as review evidence, never deletion proof. Check fixture
dependencies, autouse behavior, indirect parameters, `usefixtures`, dynamic
`getfixturevalue` requests, plugin registration, shadowing, and optional profiles
before removal. Preserve intentional autouse overrides and exported fixture
libraries. An unexecuted dynamic path or unavailable profile is inconclusive;
absence from one run does not justify a suppression, replacement, or deletion.
The upstream report hides private fixture names without verbosity; it cannot
establish liveness for fixtures omitted by collection or the selected context.

For unused Python helper evidence, enable native BasedPyright
`"reportUnusedFunction": "warning"` only in the existing execution environments
that own authored tests, preserving their import paths and interpreter settings.
The source adapter bounds this diagnostic to private, undecorated, module-level
helpers in conventional test paths and keeps it advisory. The shared production
setting stays disabled; adopting the bundle does not activate or rewrite
consumer test environments. Decorated fixtures, methods, generated support,
public helpers, and production callbacks are outside this finding.

## Judgment checks

Report only a concrete test whose code and nearby production behavior establish
the weakness:

1. **Name/oracle alignment** — Every behavior promised by the test name has an
   observation that distinguishes success from a plausible wrong result.
   Existence, type, call count, truthiness, or 2xx status proves only that narrow
   fact; do not infer that such assertions are weak when that fact is the actual
   contract. Distinguish a missing prerequisite from an observed failure of the
   promised outcome converted into a skip: an authentication failure in a
   successful-access test or a language mismatch in a language-correctness test
   still needs an oracle unless the test explicitly measures availability.
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
    line or branch execution as proof of test value. Keep generated artifacts
    and static fixture/demo data outside the application-logic denominator;
    verify their actual callers and ownership before changing coverage scope,
    and never exclude maintained runtime behavior to silence a failing gate.
14. **Resource lifecycle** — Establish ownership and release behavior from the
    concrete API or helper contract. After a successful acquisition, cleanup must
    cover setup failures before a fixture yields; independent cleanup must still
    run if an earlier teardown action fails. Identify the exact acquisition and
    failing operation rather than inferring a leak from a resource's name or a
    timeout whose API already closes it.
15. **Distinct coverage and necessary support** — Identify the contract,
    interaction, regression, or lifecycle need each additional case or support
    abstraction serves. Prefer sparse scenarios when dimensions do not interact;
    after paths rejoin, cover common behavior once unless a distinct failure
    requires another combination. Retain safety, race, cryptographic,
    compatibility, and lifecycle cases when their boundaries differ.

Do not use assertion-to-code ratio, raw coverage percentage, test length, or the
mere presence of mocks/private calls as evidence of low value. Prefer the
cheapest test level that exercises the real contract, and justify containers or
integration dependencies by the fidelity they add.

## Writing pytest tests

Keep setup compact while leaving the action and the observations visible in the
test. These defaults complement the judgment checks above:

- Construct the subject through its real constructor or production factory.
  Inject collaborators there; do not graft replacement methods onto the subject
  or a real collaborator. `no-test-method-grafting` targets those replacements,
  not ordinary domain-state assignments or configuration of a test double.
- Build real Pydantic value objects. A mock with a model's spec still skips its
  validation and defaults; `no-mocked-pydantic-value-object` targets that gap.
  Boundary mocks remain useful when their interface and assertions are precise.
- Use ordinary typed factories for data that varies by case. Use fixtures for
  dependency reuse and lifecycle ownership; use a factory fixture when it needs
  pytest-managed resources or must create several instances in one test.
- Give mutable fakes function scope. Configure their documented result/error
  hooks before invoking the subject, and fail clearly on unsupported calls.
- Keep closely coupled collaborators in a small typed harness with named fields.
  Share one session/state object across them; separate session copies can make a
  language-switch test pass while the live state remains wrong.
- Keep factories local until reused, and keep behavior-relevant overrides in the
  test. Helpers construct valid inputs and wire dependencies; they do not run
  the tested action, duplicate its decision logic, or hide its assertions.
- Parameterize cases sharing the same action and assertion contract. Separate
  behaviors whose setup or assertions need branches; name table rows when their
  distinction is not obvious from the values.
- Keep tables sparse: stack parameter dimensions only when their interaction is
  the contract. Put independent dimensions in separate tables, construct fresh
  mutable inputs per case, and preserve case-specific marks and regression IDs.
- Assert one coherent result directly, using ordinary pytest assertion diffs.
  Remove setup defaults, explanatory prose, and intermediate aliases that merely
  repeat visible code. Retain comments explaining a surprising boundary or bug;
  concision must leave the action and independent oracle readable.
- Use scoped monkeypatching for process boundaries such as environment, clocks,
  or unavoidable third-party globals. Prefer constructor injection for service
  dependencies. A scoped patch may replace an existing constructor-injected
  collaborator on a test-owned instance with an interface-conforming fake when
  rebuilding the fixture would add wiring without improving the boundary. Keep
  attribute-existence checks enabled, preserve the tested implementation, and
  explain ownership and the injection seam in an exact local `SARJ445` suppression.
  Replacing `subject.method` still bypasses the behavior being tested. Do not
  convert scoped patches to bare assignment just to silence the rule; restoration
  alone also does not justify a patch.

## Writing TypeScript tests

- Use `it.each` or `test.each` for one action and oracle with varying inputs.
  Prefer short tuples for scalar cases and typed named records for structured
  cases; use an informative case title and avoid branches in the test callback.
- Use a local typed factory for varying data and a shared factory when multiple
  suites need it. Use `satisfies` or the real constructor/schema instead of
  assertions that cast an incomplete fixture into the collaborator type.
- Create mutable collaborators, query clients, and request handlers per test.
  Keep immutable case data shared; restore timers, spies, globals, and handlers
  through the framework's cleanup hooks. Avoid hidden setup in a distant global
  hook when only one suite needs it.
- Assert the complete relevant value with `toEqual` or `toStrictEqual`, or a
  deliberate `toMatchObject` for a partial contract. Keep identity, ordering,
  negative controls, and adapter interactions when those are the behavior.
- For UI contracts, query by role and accessible name and await observable state
  with the existing Testing Library helpers. Reuse provider/render helpers;
  avoid fixed sleeps, implementation snapshots, and duplicate rendering layers.
- Apply the same case-admission and sparse-table rules as pytest. Do not replace
  a clear two-line test with a generic runner, assertion helper, or new framework
  that hides which production operation and regression the case exercises.

### A small language switch harness

This illustrative application exposes a real Pydantic `SwitchParameters` model,
a dispatcher interface with `switch_to(language)`, and a tool with
`switch_language()`. Adapt those names to the production interfaces. The session
contract queues speech synchronously and returns an awaitable handle: queueing
and waiting for speech are separate observations.

```python
from collections.abc import Generator
from dataclasses import dataclass, field

import pytest

from app.language_switch import Dispatcher, LanguageSwitchTool, SwitchParameters


@dataclass
class RecordedSpeech:
    text: str
    awaited: list[str]

    def __await__(self) -> Generator[None, None, None]:
        self.awaited.append(self.text)
        yield from ()


@dataclass
class RecordingSession:
    current_language: str = "en"
    queued: list[str] = field(default_factory=list)
    awaited: list[str] = field(default_factory=list)

    def say(self, text: str) -> RecordedSpeech:
        self.queued.append(text)
        return RecordedSpeech(text, self.awaited)


class RecordingDispatcher(Dispatcher):
    def __init__(self, session: RecordingSession) -> None:
        self.session = session
        self.switches: list[str] = []

    async def switch_to(self, language: str) -> None:
        self.switches.append(language)
        self.session.current_language = language


@dataclass
class SwitchHarness:
    tool: LanguageSwitchTool
    session: RecordingSession
    dispatcher: RecordingDispatcher


def make_switch_harness(parameters: SwitchParameters) -> SwitchHarness:
    session = RecordingSession()
    dispatcher = RecordingDispatcher(session)
    tool = LanguageSwitchTool(
        parameters=parameters, session=session, dispatcher=dispatcher
    )
    return SwitchHarness(tool, session, dispatcher)


@pytest.mark.asyncio
async def test_switch_waits_for_the_transition_phrase() -> None:
    harness = make_switch_harness(
        SwitchParameters(target_language="ar", transition_phrase="Next language")
    )

    await harness.tool.switch_language()

    assert harness.dispatcher.switches == ["ar"]
    assert harness.session.current_language == "ar"
    assert harness.session.queued == ["Next language"]
    assert harness.session.awaited == ["Next language"]
```

The fake dispatcher records the requested switch and applies a configured state
change; it does not implement target selection. This unit test covers the tool's
request and speech behavior. A separate regression test must construct the real
dispatcher, invoke its assignment operation, and assert the actual target/profile
and shared session state. The fake's assignment cannot prove the real assignment
works. Keep `say` synchronous here: an `AsyncMock` would change when speech is
queued and test a different contract. If relative ordering is the contract, add
one shared event log rather than inferring ordering from separate lists.

## Report

For every finding include the test location, the behavior it claims, the
specific mutation that survives, the impact, and the smallest stronger oracle.
For redundancy findings instead, name the proposed removal, the existing
covering tests, the preserved regressions, and the demonstrated maintenance or
execution cost. Identical outcomes alone do not establish equivalent contracts.
Also name nearby strong counterexamples when they establish an important
false-positive boundary. Separate confirmed weak tests from suggestions, and
record whether an active deterministic rule supports the finding or whether it
remains `judgment-only`.
