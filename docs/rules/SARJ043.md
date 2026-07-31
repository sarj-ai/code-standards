# SARJ043 `zero-assertion-test` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_zero_assertion_test.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A `test_*` function with no assertion of any kind only proves the code under test
did not throw. That is occasionally the intent, but far more often it is a test
someone stopped writing halfway: the return value is computed and dropped on the
floor, so the test goes green no matter what the function returns. One real
example from the audited corpora calls `evaluate_conditions(...)`, discards the
result, and is named `test_equality_matches_name_in_jsonobject` — it asserts
nothing about equality, or about anything else.

Fires when a `test_*` function contains **none** of the following, anywhere in
its subtree:

* an `assert` statement,
* a `with pytest.raises(...)` / `pytest.warns(...)` block, or a bare call to
  either — including anything whose name merely *carries* the `raises`/`warns`
  token, which covers `pytest.deprecated_call(...)`, pytest 8.4's
  `pytest.RaisesGroup(pytest.RaisesExc(...))`, and project-local wrappers such
  as pydantic's `pytest_raises_user_error_for_undefined_type(...)`,
* a call to anything named like an assertion helper — `assert*`, `_assert*`,
  `self.assertEqual`, `expect*`, `verify*`, `validate*` — or any attribute chain
  passing through `.expect` (the fluent style used by the LiveKit test harness,
  `result.expect.contains_function_call(...)`),
* a call to `pytest.fail(...)`,
* a call to a **function defined in the same module that itself verifies**,
  directly or through another local helper,
* a call to some *other* `test_*` callable that this module does not define —
  the tutorial-runner shape, where the assertions live in the delegate.

**The guards are the rule.** A naive version of this check is overwhelmingly
wrong: of 264 assertion-free tests found across the two repos, **223 verify
through `pytest.raises`** and would have been false positives — an 84% error
rate. Of the remainder, a further tranche delegates to a local `_assert_default`
helper or a fluent `.expect` DSL. Only ~41 are genuinely bare. The rule
deliberately searches the whole subtree rather than the top level, because the
`async def _run(): ...; asyncio.run(_run())` wrapper puts the real assertions
inside a nested function that a top-level-only scan would miss.

Even so, this rule cannot see across a call boundary into a helper defined in
another module. A test whose only verification is a project-specific assertion
helper imported from elsewhere will be flagged; `# sarj-noqa: SARJ043` is the
intended escape, and the residual false-positive rate is the reason the message
asks rather than asserts.

Deliberately NOT flagged:

* a test marked `@pytest.mark.skip`/`skipif`/`xfail` — it is not expected to
  verify anything right now,
* **a file pytest would never collect.** `is_test_path` is deliberately broad —
  it accepts anything under a `tests/` directory — but pytest only collects
  modules matching `test_*.py` / `*_test.py`. `black/tests/data/cases/` holds
  formatter fixtures such as `class_blank_parentheses.py` and `fmtonoff5.py`
  whose *content* is arbitrary Python containing `def test_func(self)`; a
  third-party sweep produced 10 hits there (`black/tests/data/cases/
  fmtskip8.py:43`, `.../line_ranges_basic.py:37`, `.../comments4.py:52`), every
  one a false positive, because those functions are input data for a formatter,
  not tests,
* **a pytest-benchmark test** — one that declares a `benchmark` parameter and
  uses it, whether called (`benchmark(model_eq, m1, m2)`) or applied as a
  decorator (`@benchmark`). A benchmark measures wall time; asserting is not its
  job. This is the single largest cluster in the third-party sweep: 94 of 291
  hits, all of `pydantic/tests/benchmarks/` and
  `pydantic/pydantic-core/tests/benchmarks/` (e.g.
  `pydantic/tests/benchmarks/test_north_star.py:86`,
  `pydantic/pydantic-core/tests/benchmarks/test_micro_benchmarks.py`, 45 hits in
  that file alone),
* **a test that delegates to a verifying helper defined in the same module.**
  Resolving called names against the module's own `def`s — transitively, so a
  helper that delegates to another helper still counts — cleared 50 sweep hits:
  black's `self.invokeBlack(...)` / `self.check_features_used(...)` /
  `self.compare_results(...)` (`black/tests/test_black.py:1156`), flask's
  `common_object_test(app)` (`flask/tests/test_config.py:19`), pydantic's
  `inspect_type_hints(...)` (`pydantic/tests/test_type_hints.py:133`) and
  `url_test_case_helper(...)`
  (`pydantic/pydantic-core/tests/validators/test_url.py`), and sqlmodel's
  `check_calls(...)`,
* **a test that calls another `test_*` function this module does not define.**
  The fastapi/sqlmodel tutorial suites re-run a documented test module's own
  tests: `from docs_src.app_testing.tutorial002_py310 import test_read_main` and
  then `def test_main(): test_read_main()`
  (`fastapi/tests/test_tutorial/test_testing/test_tutorial002.py:4`), or
  `modules.test.test_create_hero()`
  (`sqlmodel/tests/test_tutorial/test_fastapi/test_app_testing/
  test_tutorial001_tests001.py:39`). The assertions are one import away. 17
  sweep hits,
* **a `test_*` function nested inside another function.** pytest only collects
  module-level functions and methods of `Test*` classes, so a nested one is not
  a test at all — it is a callback that happens to be named for what it does.
  Flask route handlers are the canonical case: `def test_index()` registered
  with `@app.route("/", subdomain="test")` inside a test that asserts on the
  response afterwards. A third-party sweep found 36 such hits, every one a false
  positive. Only functions whose parent is the module or a class are considered.
* **a `@pytest.fixture`**, whatever it is named — a `test_*`-named fixture in a
  collected module sets state up and yields, and asserting nothing is exactly
  right for it. (The original example, `test_apps` in `flask/tests/conftest.py`,
  no longer reaches this rule at all: `conftest.py` is not a collected module.)
* a helper, or any function not named `test_*`,
* an abstract or stub body (`...`, `pass`, docstring only) — an intentionally
  empty placeholder is a different problem from a half-written test,
* anything under a `scripts/` directory. One first-party service's
  `chat/scripts/` directory
  holds four `test_*.py` files that are manual CLI probes run as
  `uv run python chat/scripts/test_llm_providers.py`, not pytest modules — they
  sit outside every `testpaths` and are never collected. A file that is not
  collected cannot have a weak assertion, so flagging it is noise; this is the
  one rule where the distinction matters, because "no assertions" is definitional
  for a CLI script.

## Implementation notes

### `_collectible_tests`

Only module-level functions and methods of a class qualify. A `test_*`
nested inside another function is a callback, not a test — pytest never
collects it — so descending into function bodies would invent findings.

### `_verifying_local_names`

Transitive because assertion helpers stack: black's `compare_results` calls
`check_ast_equivalence`, and only the latter holds the `assert`.
