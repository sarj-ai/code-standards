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
* a call to anything named like an assertion helper — any snake_case name
  *carrying* the token `assert`, `expect`, `verify` or `validate`, whether it
  leads (`assert_matches`, `self.assertEqual`, `_assert_default`) or not
  (`invoke_and_assert`, `run_and_verify`) — or any attribute chain passing
  through `.expect` (the fluent style used by the LiveKit test harness,
  `result.expect.contains_function_call(...)`),
* a **verifier handed to a runner** — a bare reference to an imported or
  module-level callable, in the callable slot of a call, whose name reads as an
  assertion helper: `run_sync_in_worker_thread(invoke_and_assert, "...",
  expected_code=1)`,
* a `raise AssertionError(...)`, the `match`-statement spelling of a failed
  expectation (`case _: raise AssertionError(...)`),
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
another module, and that is its stated, accepted residual. A test whose only
verification is a project-specific assertion helper imported from elsewhere, or
inherited from a base test case, will be flagged: saleor's
`get_graphql_content(...)`, which raises on a GraphQL error (37 occurrences),
django's inherited `self.check_html(...)` (144), an AWS-CDK-style
`assertions.Template.has_resource_properties(...)`. Each was examined during the
audit and every candidate predicate for it — "any call to an imported name", "any
call on `self`" — is far broader than the shape and would take the rule's
population with it. `# sarj-noqa: SARJ043` is the intended escape, and this
residual is the reason the message asks rather than asserts. A
screenshot/visual-regression test, whose verification happens outside Python
altogether, is the same case and too rare to be worth a predicate.

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

## 2026-07 false-positive audit

Over a 12-repo corpus: **2,113 findings**, 66 of them first-party. A seeded
random sample of 50 read against source put the false-positive rate at **34%**.
The three guards below removed **460 findings (21.8%)** and 5 of the 66
first-party ones, taking the rule to **1,653**.

The sample contained **no MISSED weak test** — `pytest.raises`/`warns`,
`self.assert*`, `assert_called_*` and same-module helpers were all already
handled. 23 of the 50 were "this call does not raise" tests, correctly counted
arguable rather than wrong: the `# sarj-noqa` escape the message already offers
is the answer for those.

* **An assertion helper whose name carries the token but does not lead with it.**
  The largest false-positive class, **8 of the 50 read**. The name pattern used to
  be anchored, so a project's primary CLI-test verifier — prefect's
  `invoke_and_assert(...)`, which takes `expected_code=` and
  `expected_output_contains=` — was invisible to a rule that recognised
  `assert_invoke` perfectly well. Searching for the token anywhere in the
  snake_case name (326 findings), and reading the callable slot of a call as well
  as its callee (a further 113), removed **439 of 2,113 (20.8%)** and only **1 of
  the 66 first-party** ones. `invoke_and_assert` accounts for 423 of the 439 by
  itself (`prefect/tests/cli/test_sdk.py:134` and `:487`,
  `prefect/tests/cli/test_work_pool.py:157`,
  `prefect/tests/cli/test_flow_run.py:1096`).
* **Verification by `raise`, not by `assert`.** `match result: case Ok(): pass;
  case _: raise AssertionError(...)` states an expectation as precisely as an
  `assert` does. Only **3 findings**, but ALL THREE are first-party — 4.5% of the
  entire first-party population, and unambiguously wrong before.
* **An unconditional `pytest.skip(...)` body.** The rule exempted the declarative
  `@pytest.mark.skip` but not the imperative form, although a body of
  `pytest.skip("CANCEL responses is not supported...")` asserts nothing for
  exactly the reason the decorator does (four such methods in
  `litellm/tests/llm_responses_api_testing/test_google_ai_studio_responses_api.py`).
  31 flagged tests corpus-wide call `pytest.skip`; requiring the call to stand
  ALONE as a statement of the body exempts **18** of them (1 first-party) and
  leaves the other 13 — a conditional skip is a precondition, and everything after
  it runs and verifies nothing.

## Implementation notes

### `_collectible_tests`

Only module-level functions and methods of a class qualify. A `test_*`
nested inside another function is a callback, not a test — pytest never
collects it — so descending into function bodies would invent findings.

### `_verifying_local_names`

Transitive because assertion helpers stack: black's `compare_results` calls
`check_ast_equivalence`, and only the latter holds the `assert`.

## Library assertion helpers (2026-07-31 sweep)

The name heuristic — a snake_case token search for `assert`, `expect`, `verify`
or `validate` — is a good default with one blind spot: a widely used assertion
API is free to spell itself without any of those words.

Measured over **39,893 content-deduplicated `.py` files** from four first-party
repos and 33 OSS Python repos: **4,386 of this rule's 7,352 findings (59.7%)**
were on test functions whose body calls such a helper. They assert perfectly
well; the rule simply could not see it.

| helper family | findings | why the token search misses it |
| --- | --- | --- |
| `_pytest.pytester.LineMatcher` — `fnmatch_lines`, `no_fnmatch_line`, `re_match_lines`, … | 438 | the name describes the MATCH, not the assertion; `fnmatch_lines` raises `Failed` on a mismatch |
| `sqlalchemy.testing.assertions` — `eq_`, `ne_`, `is_`, `is_true`, `is_false`, `in_`, `eq_regex`, `eq_ignore_whitespace` | 3,948 | the trailing underscore exists to dodge a Python keyword |

Three read at source, all assertion-complete and all wrongly flagged:

- `pytest/testing/test_stepwise.py:99` `test_run_without_stepwise` — three
  consecutive `result.stdout.fnmatch_lines([...])` calls.
- `pytest/testing/test_cacheprovider.py:501` `test_terminal_report_failedfirst`.
- `sqlalchemy/test/engine/test_logging.py:138` `test_repr_params_unknown_list` —
  `eq_(repr(...), "[[1, 2, 3], 5]")`.

`_LIBRARY_ASSERTION_NAMES` is a **closed set of exact names**, not a pattern. A
wildcard for "ends in an underscore" or "starts with `eq`" would swallow
unrelated user functions, and a test that really asserts nothing must stay
flagged — that is the whole rule. The closed-set choice is pinned by
`test_a_similarly_named_local_function_still_does_not_rescue_a_bare_test`.

Corpus effect, same 39,893 files: **7,352 -> 2,613 (-64.5%)**. The extra 353
beyond the 4,386 counted directly come from `_verifying_local_names`, whose
transitive promotion now reaches a local helper that asserts through one of
these. No other rule in the registry moved.

Concentration note: 3,944 of the 4,386 are in one repo (SQLAlchemy's own test
suite) and 438 in another (pytest's). First-party impact today is nil. The class
is fixed anyway because `fnmatch_lines` is what any repo testing a console
script through the `pytester` fixture uses, and that repo would see the rule
fire on every one of its CLI tests.
