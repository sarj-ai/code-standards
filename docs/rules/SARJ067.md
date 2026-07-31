# SARJ067 `unused-mock-setup` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_unused_mock_setup.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

An arrange block that configures a collaborator the test never reaches misleads
every later reader — it says "this test depends on `refund` returning a receipt"
when the assertion has nothing to do with `refund`. It is also what a refactor
leaves behind: the call is deleted from the code under test, the `return_value`
line stays, and the test still passes while covering strictly less than its name
claims.

The rule only fires where deadness is **provable from the test itself**:

* **overwritten before use** — the same `<mock>.<attr>.return_value` /
  `.side_effect` target is assigned twice in one block with nothing in between
  that can execute code (other mock configuration, literal assignments, `pass`,
  imports). Nothing can have observed the first value, so it is dead,
* **asserted never called** — the test configures `<mock>.<attr>` and then
  asserts `<mock>.<attr>.assert_not_called()` (or `assert_not_awaited()`) on
  that path or a dotted prefix of it, with no further code afterwards that could
  invoke it. If the assertion passes, the configured return was never observed
  — the two statements contradict each other.

**Why the obvious version of this rule is not here.** The tempting formulation
is "a configured path that the function never mentions again": `gateway.refund.
return_value = X` where nothing else says `refund`. That was implemented and
measured first, and it is unusable. A mock reaches the code under test in ways
the test body does not spell out — it is handed over whole (`billing.charge(
gateway, 100)` and the SUT picks `.refund` off it), or it is installed by
`patch`, where the test never passes it anywhere at all. On the five audited
corpora that formulation produced 493 hits (repo A 70, django 37, celery 386,
repo B 0, fastapi 0; repo labels are stable within this docstring only), of
which 17 were read line by line across all three
corpora that produced any: **17 false positives, 0 true**. The census explains
why — 196 of the 493 configured bases are `@patch`-decorator parameters, 29 are
`with patch(...) as m` bindings and 38 are fixture parameters, all wired into
the SUT where the test cannot see it, and the 126 locally constructed mocks are
handed to the SUT whole. Named examples, all false:
`django/tests/queries/test_sqlcompiler.py:31` (`cursor.execute.side_effect`, and
the cursor is patched onto the connection two lines later),
`django/tests/decorators/test_cache.py:147` (`mocked_time.return_value` — the
view calls `time.time()`), `celery/t/unit/app/test_app.py:1328`
(`router.route.return_value`, and `router` is passed to `send_task`),
`celery/t/unit/fixups/test_django.py:408`, and three sites in repo A — an
agent-tool test (`mock_datetime.now.return_value`), a generation-service test
(`llm_provider` is the injected fixture mock) and a
public-API test. The narrower salvage (fire only when the base
mock is a locally constructed `Mock()`/`MagicMock()` that escapes nowhere) is
sound but empty: of 966 locally constructed mocks and 982 configuration
statements across the same corpora, **0** were configured without the mock being
used elsewhere. A mock nobody hands to anything is a mock nobody writes.

The two shapes that survived are rare and always right: 5 hits across five
corpora, 1 in repo A (an audit-middleware test), 4 in
celery (`t/unit/utils/test_platforms.py:952` and `:981`, literally duplicated
`grp_module.getgrgid.return_value = [group_name]` lines;
`t/unit/backends/test_elasticsearch.py:340` and `:375`,
`x._server.update.return_value = {...}` under an `x._server.update.
assert_not_called()`), 0 in django, fastapi and repo B, 0 false positives.

**Not duplicated from ruff.** `select = ["ALL"]` already covers the whole
"never used at all" family: `F841` flags `gateway = MagicMock()` with no later
use *and* `with patch(...) as m` with no use of `m`, `ARG001` flags an unused
`@patch`-injected parameter, and `PGH005` flags `mock.assert_called_once`
without parentheses. What none of them see is a mock that *is* used — used only
to configure something the test then throws away. That gap is this rule.

Deliberately NOT flagged:

* **a configured path the test simply never mentions again.** The dominant
  shape, and unknowable: see above,
* **a mid-test `assert_not_called()` checkpoint.** `pool_close.side_effect =
  ...` / `pool_close.assert_not_awaited()` / `await shutdown()` /
  `pool_close.assert_awaited_once()` asserts the collaborator has not fired
  *yet* — the setup is exercised two lines later
  (one first-party settings test). Any positive call
  assertion or call introspection (`assert_called*`, `assert_awaited*`,
  `assert_has_calls`, `.called`, `.call_count`, `.call_args`, `reset_mock`) on
  the same path, its prefix or its extension, anywhere in the function,
  suppresses the diagnostic. Two of the six raw shape-B hits were this:
  `celery/t/unit/tasks/test_result.py:150` (`assert_not_called()` then
  `assert_called()` after a second act) and
  `celery/t/unit/worker/test_consumer.py:313`,
* **anything after the `assert_not_called()` that can run code.** A second act
  makes the configuration live again, so the rule requires no effectful call
  after the assertion line — only further `assert*` calls whose arguments do not
  themselves call anything,
* **a conditional or looped overwrite.** `m.get.return_value = A` followed by
  `if x: m.get.return_value = B` configures two different runs; only
  reassignments in the *same* block pair up,
* **a reassignment separated by anything that executes** — a call, an `await`,
  an attribute load, a subscript, a nested `def`. Celery's
  `t/unit/utils/test_platforms.py:230` sets `setuid.side_effect` inside a nested
  `raise_on_second_call` closure and again at module scope below it; the closure
  runs later, so the pair is not dead,
* **`side_effect = None` followed by `return_value = ...`.** Clearing
  `side_effect` re-enables `return_value`, so the two are not competing
  configurations of the same thing (`celery/t/unit/backends/test_gcs.py:414`).
  Only assignments to the *identical* target pair up,
* **anything paired across a scope boundary.** A nested `def` or `class` inside a
  test is its own scope, and the rule never pairs a configuration in one with an
  assertion in the other — in *either* direction. It cannot know when the helper
  runs relative to the act, and guessing is how the unusable first formulation
  went wrong. The cost is symmetric and real: a helper that only calls
  `assert_not_called()` does not condemn the outer arrange block, and a helper
  that only configures a mock is not condemned by the outer test's
  `assert_not_called()`,
* **a configuration on the same physical line as the assertion.** Ordering is by
  line number, so `m.get.assert_not_called(); m.get.return_value = X` and its
  reverse both stay silent. The comparison is strict on purpose: the reverse
  spelling is the far commoner one and there the configuration genuinely is for
  whatever the test does next,
* **`configure_mock(...)` / `attach_mock(...)` / `Mock(**{"a.return_value": …})`
  key strings.** Measured across the five corpora: 15 `configure_mock` /
  `attach_mock` calls and 116 `**{...}` call sites, none of which the two sound
  shapes above could be extended to reach without re-introducing the
  unknowable-reachability problem,
* non-test files.

## Implementation notes

### `_last_effectful_line`

Assertion calls are excluded — `m.assert_called_with(3)` inspects the mock
rather than driving it — but only when their own arguments call nothing.

### `_introspected_paths`

Searches the whole subtree, nested helpers included: a positive call
assertion anywhere means the test does expect the call, so an
`assert_not_called` on the same path is a mid-test checkpoint.

### `_is_inert`

An inert statement between two configurations cannot have read the first
one. Anything that calls, awaits, subscripts or reads an attribute is not
inert: a property getter or a `__getitem__` can reach the mock.
