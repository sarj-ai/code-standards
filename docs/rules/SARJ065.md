# SARJ065 `conditional-assertion-in-test` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_conditional_assertion_in_test.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

```python
def test_results():
    rows = fetch()
    for row in rows:      # rows == [] -> zero assertions, green test
        assert row.id > 0
```

The loop body is the whole test. If `fetch()` regresses to returning nothing —
the most likely way for it to break — the test does not fail; it passes,
having checked nothing at all. The same hole opens under a one-armed `if`:
`if should_match: condition.evaluate(...)` verifies nothing on the branch that
was supposed to be the happy path. These are the tests that go green for years
and then turn out never to have run their assertion.

The rule is a structural reachability check over the test body. `always
asserts` is computed bottom-up:

* an `assert`, a `raise`, a call named like an assertion (`self.assertEqual`,
  `mock.assert_called_once_with`, `_assert_row`, `check_response`,
  `pytest.fail`) or a call to a same-module helper that itself asserts,
* `with pytest.raises(...)` / `with self.assertRaisesMessage(...)`,
* an `if` only when it has an `else`/`elif` chain in which **every** branch
  either asserts or bails out (`return`, `raise`, `pytest.skip(...)`), or when
  its single arm fails the test outright — `if failures: pytest.fail(...)` is
  `assert not failures` spelled long-hand,
* a `for`/`while` **never**, unless the iterable is proven non-empty (below) or
  a `for ... else:` clause asserts,
* a `try` when any limb asserts, and a `match` only with a `case _`.

It fires when the test contains at least one assertion but no path through it
is guaranteed to reach one. A test with *no* assertion anywhere is SARJ043's
finding, not this one, and is left alone.

**The guards are the rule.** The naive version reported 148 findings across the
five corpora, 73 of them in django, and almost every django hit was a loop over
a fixture table the suite has always populated. Successive guards took the
population to 29 without losing a single first-party finding:

| corpus | naive | shipped |
|---|---|---|
| repo A | 32 | 6 |
| repo B | 13 | 6 |
| django | 73 | 5 |
| fastapi | 1 | 1 |
| celery | 29 | 11 |

(repo labels are stable within this docstring only.)

Every one of the 29 was read. One is a clear false positive (fastapi's
`tests/test_operations_signatures.py:8`, whose inner loop walks
`inspect.signature(...).parameters` — a signature always has parameters, and
nothing in the source says so). Roughly five celery hits in
`t/unit/tasks/test_canvas.py` are true by the letter — `g = group(Mock(),
Mock())` then `for task in g.tasks: task.set_immutable.assert_called_with(...)`
does pass vacuously if `group` drops its children, which is the very thing the
test claims to check — but few teams would act on them. The repo A and
repo B findings are all worth reading.

A later sweep over 19 corpora (the five above plus airflow, dagster, litellm,
saleor, mlflow, langchain, superset, zulip, prefect, warehouse, sentry-python
and three more first-party repos) reported 751, and the failure-aggregator
guard below took that to 669. All 82 removals were the same shape and none of
them was first-party: repo A 6, repo B 6, django 5, celery 11 and fastapi 1
are unchanged by it.

Deliberately NOT flagged:

* **a failure aggregator.** `failures = []`, a loop that appends, then `if
  failures: pytest.fail("; ".join(failures))` *is* `assert not failures` — the
  arm that is not taken is the passing outcome, so nothing about the check is
  conditional. Any one-armed `if` whose body always raises, asserts a falsy
  literal, or calls `fail` reads this way, as does an `if X: ... elif not X:
  ...` chain, which leaves no third case. 82 hits: 68 in litellm's
  `tests/e2e/claude_code/**` model harness, the rest in airflow
  (`always/test_project_structure.py:360`), dagster, mlflow
  (`tests/sagemaker/test_sagemaker_deployment_client.py:373`), langchain and
  sentry-python (`integrations/threading/test_threading.py:224`, the `elif`),
* **a loop whose collection was sized first.** `assert len(rows) == 3` (or
  `assert rows`, `assert len(rows) > 0`, `self.assertEqual(len(rows), 2)`,
  `assertTrue(rows)`, `assertIn(x, rows)`, `if not rows: pytest.skip(...)`)
  anywhere in the test makes the following loop guaranteed. This is the fix the
  message asks for, so the rule must recognise it. Module-level tables get the
  claim pooled across the file, because it is routinely a *sibling* test that
  states the size: one first-party test module asserts `len(TEST_CASES) == 4`
  near the top and three later tests loop over it,
* **a loop over a literal collection** — `[1, 2, 3]`, `("a", "b")`, a non-empty
  dict, `range(6)`, `range(len(rows))`, `range(n + 1)`, a comprehension with no
  `if` over a non-empty iterable, `zip(...)` where either leg is non-empty,
  `dict.fromkeys(whitelist, 0).items()`, `"a,b".split(",")` — resolved through
  local, module-level and default-argument bindings. A name is followed to its
  binding at most once per path, which is what makes `a = b` beside `b = a`
  terminate rather than chase itself. celery writes its fixtures as defaults
  (`def test_merge(self, p, data=["foo", "bar", "baz"])`,
  `t/unit/worker/test_state.py:119`),
* **a loop over a `@pytest.mark.parametrize` column whose every row is a
  non-empty literal.** `parametrize("present", [["a"], ["b", "c"]])` then
  `for fragment in present:` is a literal loop written one indirection away.
  Found against three first-party sites — two in repo A, one in repo B,
* **a loop over a fixed table rather than a computed result** — a capitalised
  name (`for role in UserRole:` walks an enum's members; PEP 8 reserves
  CapWords and SCREAMING_CASE for things declared once), a call-free attribute
  chain rooted at `self`/`cls` (django's `self.geometries.wkt_out`, 16 hits in
  `tests/gis_tests/gdal_tests/test_geom.py` alone) or at a class
  (`ContentType._meta.default_permissions`), a chain rooted at a class through
  calls (`Country.objects.annotate(...)`, `FormSet(form_kwargs={...})`,
  `CommonPasswordValidator().passwords` — 15 further django hits), and a bare
  imported name (`for s in srlist:`). This is the rule's known blind spot: a
  loop over `MyService().compute()` reads the same way and is exempted too. An
  imported *function* called here is not covered — `for tool_class in
  get_all_tool_classes():` still fires, which is one first-party site,
* **an inner loop reached through an outer loop that is proven to run.**
  `for c in countries: for ring in c.mpoly: assertAlmostEqual(...)` — once the
  outer collection is known non-empty, each element's own sub-collections are
  the item's structure, and "assert `c.mpoly` is non-empty first" is not a
  request anyone would act on. The largest residual class in the sweep: django's
  `test_functions.py:827`, `servers/test_basehttp.py:29`,
  `validation/test_unique.py:51` and one first-party site, all false positives,
* **a branch that bails out.** In `if cond: pytest.skip(...) else: assert ...`
  the skipping arm owes no assertion — the arm that falls through is the one
  that has to check. `return`, `raise`, `continue`, `break`, `pytest.xfail(...)`,
  `pytest.exit(...)`, `self.skipTest(...)` and `pytest.importorskip(...)` all
  count as bailing out. Note where this stops, because the shape reads as if it
  did more: a bail-out on an *emptiness* test is also read as sizing the
  collection (`if not rows: pytest.skip(...)` clears a following `for row in
  rows:`), but a bail-out on anything else proves nothing about a later loop,
  so `if not has_gpu: pytest.skip(...)` above `for row in fetch(): assert row`
  still fires — the skip says the machine has a GPU, not that `fetch()`
  returned anything,
* **a `try` whose check sits in any limb.** An explicit `try` in a test is
  `assertRaises` written long-hand, reached for when `assertRaises` cannot
  express the check: django's `forms_tests/field_tests/test_datefield.py:212`
  says so in a comment ("assertIsInstance or assertRaises cannot be used
  because UnicodeEncodeError is a subclass of ValueError"), and
  `admin_views/test_related_object_lookups.py:183` spells it
  `except TimeoutException: pass` / `else: self.fail(...)`. Four django hits,
* **an assertion gated on a capability probe.** `if
  connection.features.supports_expression_indexes:` (django
  `migrations/test_operations.py:5307`) and `if hasattr(signal, "setitimer"):`
  (celery `t/unit/utils/test_platforms.py:129`) skip a check the environment
  cannot run, which is an environment gate, not a forgotten assertion. `if
  user.is_admin: assert can_delete(user)` is not a capability probe and still
  fires,
* **`unittest`'s `subTest` and pytest-subtests' `subtests` fixture** — both
  re-enter the loop body as its own sub-test from a table the rule cannot size
  (celery `t/unit/worker/test_consumer.py:690`),
* **hypothesis `@given`/`@example` tests**, where one function expands into many
  generated inputs and a per-input branch is the normal shape,
* **a test whose assertions live in a nested `def`** — `async def _run():
  assert ...` handed to `asyncio.run`, or a callback registered with a runner —
  because whether it is invoked is not visible here,
* a skipped test (`@pytest.mark.skip`/`skipif`/`xfail`) or a `@pytest.fixture`,
* **a module pytest would never collect.** `is_test_path` accepts anything under
  `tests/`; pytest imports only `test_*.py` / `*_test.py`, and `scripts/`
  holds manual CLI probes that are never collected,
* a decorator that happens to be an asserting local helper. django's
  `@test_mutation()` wraps the body in an `assertRaisesMessage`, and reading
  the decorator as part of the body invented five findings in
  `tests/gis_tests/test_gis_tests_utils.py`.

Measured and rejected, so that the next auditor does not re-raise them:

* **exempting a loop over a name bound to a pytest fixture.** Hit density runs
  from django's 0.3 per 1,000 tests to sentry-python's 11.9, and the cause is
  structural: every fixed-table exemption above is keyed to unittest shapes
  (`self.`/`cls.` roots, CapWords, parameter defaults), and django is 100%
  class-method tests, celery 96%. A pytest-fixture suite that loops over a
  lowercase fixture parameter gets no exemption at all. Reading a test's own
  parameters as non-empty removes 93 of the 669 hits — but three of them are
  half of repo B's findings, including one module where three consecutive tests
  loop over a `tools` fixture and all three go green if the tool registry ever
  regresses to empty. That is precisely the failure this rule exists to catch,
  so the exemption costs more than it saves,
* **exempting every test that opens with an early-exit guard**, the literal
  reading of the bail-out bullet above. It removes 3 hits in 19 corpora, and
  would suppress the whole class by construction for that. Not worth it.

## Implementation notes

### `_is_static_table`

Three shapes read as "declared once, somewhere else":

* a capitalised name — PEP 8 reserves CapWords for classes (`for role in
  UserRole:` walks an enum's members) and SCREAMING_CASE for constants,
* an attribute chain, call-free, rooted at `self`/`cls` or at a capitalised
  name — the unittest class fixture (`self.geometries.wkt_out`) and the
  class-level table (`ContentType._meta.default_permissions`),
* a name this module imported — the table lives in another file, so its size
  is not something this test computed.

### `_iterable_is_nonempty`

`seen` holds the names already followed to their bindings on this path.
Every other step of the walk moves to a strictly smaller sub-expression, so
refusing to resolve a name twice is what makes the walk terminate — `a = b`
beside `b = a` would otherwise chase itself forever.

### `_negation_proves`

`if not rows: pytest.skip(...)` leaves `rows` non-empty below.

### `_parametrized_nonempty`

`@pytest.mark.parametrize("present", [["a"], ["b", "c"]])` followed by
`for fragment in present:` is a literal-collection loop written one
indirection away; every row supplies a non-empty list, so the body always
runs.

### `_accumulators_filled`

`for i in range(10): results.append(...)` then `for expected, result in
results:` is a two-phase loop; the second half runs because the first did.

### `_default_bindings`

celery writes its fixtures that way: `def test_merge(self, p,
data=["foo", "bar", "baz"])` loops over `data`, whose only definition is
the default.

### `_asserting_helper_names`

A loop body calling `_assert_row(row)` or `check_response(r)` is asserting
even though the `assert` lives elsewhere; so is one calling a locally
defined `compare_output(...)` whose name says nothing.

### `_complementary_branch`

An `elif` whose test is implied by the negation of the `if`'s test leaves
no third case — sentry-python writes `if propagate_scope or ...: elif not
propagate_scope:` (`tests/integrations/threading/test_threading.py:224`).

### `_collectible_tests`

Only module-level functions and methods of a class qualify — a `test_*`
nested inside another function is a callback, not a test.
